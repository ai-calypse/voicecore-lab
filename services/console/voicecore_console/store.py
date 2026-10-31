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

    # --- agents (Step 10 P5) ------------------------------------------------------------

    def agent(self, agent_id: str) -> dict | None:
        with self.db() as db:
            row = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        return row and {**dict(row), "config": json.loads(row["config"]), "enabled": bool(row["enabled"])}
