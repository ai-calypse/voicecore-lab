"""The console's own records in one SQLite file: the admin, sessions, API keys, agents, sources and builds.

WAL mode and a 5 s busy timeout, one connection per call: FastAPI runs plain endpoints in a thread pool and the
build runs in its own thread. Schema changes are appended to SCHEMA; PRAGMA user_version counts the applied ones.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = [
    """
    CREATE TABLE admin (id INTEGER PRIMARY KEY CHECK (id = 1), password TEXT NOT NULL, created REAL NOT NULL);
    CREATE TABLE setup (id INTEGER PRIMARY KEY CHECK (id = 1), token_hash TEXT NOT NULL);
    CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, expires REAL NOT NULL);
    CREATE TABLE api_keys (id TEXT PRIMARY KEY, label TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE,
                           created REAL NOT NULL, revoked REAL);
    CREATE TABLE agents (id TEXT PRIMARY KEY, config TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                         created REAL NOT NULL, updated REAL NOT NULL);
    CREATE TABLE sources (id TEXT PRIMARY KEY, agent TEXT NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
                          kind TEXT NOT NULL, label TEXT NOT NULL, ref TEXT, files INTEGER NOT NULL DEFAULT 0,
                          created REAL NOT NULL);
    CREATE TABLE builds (id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
                         status TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
                         version TEXT, log TEXT NOT NULL DEFAULT '', created REAL NOT NULL, finished REAL);
    """,
    """
    CREATE TABLE site (id INTEGER PRIMARY KEY CHECK (id = 1), origins TEXT NOT NULL DEFAULT '[]');
    """,
]


def migrate(db: sqlite3.Connection) -> int:
    version = db.execute("PRAGMA user_version").fetchone()[0]
    for n, script in enumerate(SCHEMA[version:], version + 1):
        db.executescript(f"BEGIN; {script}; PRAGMA user_version = {n}; COMMIT;")
    return len(SCHEMA)


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute("PRAGMA journal_mode = WAL")
            migrate(db)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 5000")
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:  # one transaction per call: commits, or rolls back on an exception
                yield db
        finally:
            db.close()

    # --- admin and setup ------------------------------------------------------------

    def admin_password(self) -> str | None:
        with self.db() as db:
            row = db.execute("SELECT password FROM admin").fetchone()
        return row and row["password"]

    def setup_hash(self) -> str | None:
        with self.db() as db:
            row = db.execute("SELECT token_hash FROM setup").fetchone()
        return row and row["token_hash"]

    def offer_setup(self, token_hash: str) -> None:
        """Allow first-run setup with this token, unless an admin exists or a token is already on offer."""
        with self.db() as db:
            if not db.execute("SELECT 1 FROM admin").fetchone():
                db.execute("INSERT OR IGNORE INTO setup (id, token_hash) VALUES (1, ?)", (token_hash,))

    def make_admin(self, password: str, now: float) -> bool:
        """False when an admin already exists (two setups at once: only one wins)."""
        with self.db() as db:
            if db.execute("SELECT 1 FROM admin").fetchone():
                return False
            db.execute("INSERT INTO admin (id, password, created) VALUES (1, ?, ?)", (password, now))
            db.execute("DELETE FROM setup")
            return True

    def set_admin(self, password: str, now: float) -> None:
        """The password from the environment (CONSOLE_ADMIN_PASSWORD): replaces any earlier one and signs everyone out."""
        with self.db() as db:
            db.execute("DELETE FROM sessions")
            db.execute("DELETE FROM setup")
            db.execute("INSERT OR REPLACE INTO admin (id, password, created) VALUES (1, ?, ?)", (password, now))

    def reset_admin(self, token_hash: str) -> None:
        with self.db() as db:
            db.execute("DELETE FROM admin")
            db.execute("DELETE FROM sessions")
            db.execute("INSERT OR REPLACE INTO setup (id, token_hash) VALUES (1, ?)", (token_hash,))

    # --- sessions -------------------------------------------------------------------

    def add_session(self, token_hash: str, expires: float) -> None:
        with self.db() as db:
            db.execute("INSERT INTO sessions (token_hash, expires) VALUES (?, ?)", (token_hash, expires))

    def session_valid(self, token_hash: str, now: float) -> bool:
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE expires <= ?", (now,))
            return db.execute("SELECT 1 FROM sessions WHERE token_hash = ?", (token_hash,)).fetchone() is not None

    def end_session(self, token_hash: str) -> None:
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    # --- API keys ---------------------------------------------------------------------

    def add_key(self, key_id: str, label: str, key_hash: str, now: float) -> None:
        with self.db() as db:
            db.execute("INSERT INTO api_keys (id, label, key_hash, created) VALUES (?, ?, ?, ?)", (key_id, label, key_hash, now))

    def keys(self) -> list[dict]:
        with self.db() as db:
            rows = db.execute("SELECT id, label, created FROM api_keys WHERE revoked IS NULL ORDER BY created").fetchall()
        return [dict(r) for r in rows]

    def revoke_key(self, key_id: str, now: float) -> bool:
        with self.db() as db:
            return db.execute("UPDATE api_keys SET revoked = ? WHERE id = ? AND revoked IS NULL", (now, key_id)).rowcount == 1

    def key_valid(self, key_hash: str) -> bool:
        with self.db() as db:
            return db.execute("SELECT 1 FROM api_keys WHERE key_hash = ? AND revoked IS NULL", (key_hash,)).fetchone() is not None

    # --- install-wide settings --------------------------------------------------------------

    def site_origins(self) -> list[str]:
        with self.db() as db:
            row = db.execute("SELECT origins FROM site").fetchone()
        return json.loads(row["origins"]) if row else []

    def set_site_origins(self, origins: list[str]) -> None:
        with self.db() as db:
            db.execute("INSERT INTO site (id, origins) VALUES (1, ?) ON CONFLICT (id) DO UPDATE SET origins = excluded.origins",
                       (json.dumps(origins),))

    # --- agents ----------------------------------------------------------------------------

    def agent(self, agent_id: str) -> dict | None:
        with self.db() as db:
            row = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        return row and {**dict(row), "config": json.loads(row["config"]), "enabled": bool(row["enabled"])}

    def agents(self) -> list[dict]:
        with self.db() as db:
            rows = db.execute("SELECT * FROM agents ORDER BY created").fetchall()
        return [{**dict(r), "config": json.loads(r["config"]), "enabled": bool(r["enabled"])} for r in rows]

    def add_agent(self, base_id: str, config: dict, now: float) -> str:
        """Stores the agent under base_id, or base_id-2, -3... if taken. Returns the id used."""
        with self.db() as db:
            agent_id, n = base_id, 1
            while db.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone():
                n += 1
                agent_id = f"{base_id}-{n}"
            db.execute("INSERT INTO agents (id, config, created, updated) VALUES (?, ?, ?, ?)",
                       (agent_id, json.dumps(config), now, now))
        return agent_id

    def set_config(self, agent_id: str, config: dict, now: float) -> None:
        with self.db() as db:
            db.execute("UPDATE agents SET config = ?, updated = ? WHERE id = ?", (json.dumps(config), now, agent_id))

    def set_enabled(self, agent_id: str, enabled: bool) -> None:
        with self.db() as db:
            db.execute("UPDATE agents SET enabled = ? WHERE id = ?", (int(enabled), agent_id))

    def delete_agent(self, agent_id: str) -> None:
        with self.db() as db:
            db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))

    # --- sources ---------------------------------------------------------------------------

    def add_source(self, source_id: str, agent_id: str, kind: str, label: str, ref: str | None, files: int, now: float) -> None:
        with self.db() as db:
            db.execute("INSERT INTO sources (id, agent, kind, label, ref, files, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (source_id, agent_id, kind, label, ref, files, now))

    def sources(self, agent_id: str) -> list[dict]:
        with self.db() as db:
            rows = db.execute("SELECT id, kind, label, ref, files, created FROM sources WHERE agent = ? ORDER BY created, id",
                              (agent_id,)).fetchall()
        return [dict(r) for r in rows]

    def set_source_files(self, source_id: str, files: int) -> None:
        with self.db() as db:
            db.execute("UPDATE sources SET files = ? WHERE id = ?", (files, source_id))

    def delete_source(self, agent_id: str, source_id: str) -> bool:
        with self.db() as db:
            return db.execute("DELETE FROM sources WHERE id = ? AND agent = ?", (source_id, agent_id)).rowcount == 1

    # --- builds ----------------------------------------------------------------------------

    def new_build(self, agent_id: str, now: float) -> int | None:
        """None while another build of this agent is queued or running."""
        with self.db() as db:
            if db.execute("SELECT 1 FROM builds WHERE agent = ? AND status IN ('queued', 'running')", (agent_id,)).fetchone():
                return None
            return db.execute("INSERT INTO builds (agent, status, created) VALUES (?, 'queued', ?)", (agent_id, now)).lastrowid

    def build_progress(self, build_id: int, done: int, total: int) -> None:
        with self.db() as db:
            db.execute("UPDATE builds SET status = 'running', done = ?, total = ? WHERE id = ?", (done, total, build_id))

    def finish_build(self, build_id: int, status: str, version: str | None, log: str, now: float) -> None:
        with self.db() as db:
            db.execute("UPDATE builds SET status = ?, version = ?, log = ?, finished = ? WHERE id = ?",
                       (status, version, log, now, build_id))

    def latest_build(self, agent_id: str) -> dict | None:
        with self.db() as db:
            row = db.execute("SELECT * FROM builds WHERE agent = ? ORDER BY id DESC LIMIT 1", (agent_id,)).fetchone()
        return row and dict(row)

    def last_published(self, agent_id: str) -> dict | None:
        """The latest successful build: its version, log and when it finished."""
        with self.db() as db:
            row = db.execute("SELECT version, log, finished FROM builds WHERE agent = ? AND status = 'done' ORDER BY id DESC LIMIT 1",
                             (agent_id,)).fetchone()
        return row and dict(row)

    def fail_interrupted_builds(self, now: float) -> None:
        """At start: a build still queued or running was cut off by a restart."""
        with self.db() as db:
            db.execute("UPDATE builds SET status = 'failed', log = 'interrupted by restart', finished = ? "
                       "WHERE status IN ('queued', 'running')", (now,))
