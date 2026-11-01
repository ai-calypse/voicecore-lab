"""The console's HTTP API. This module maps HTTP to the store, auth and publishing; it holds no rules of its own.

create_app is the one composition root: folders, the setup token and the edges (clock, git) come in as arguments,
so tests run it on temporary folders with a fake clock.
"""
import html
import json
import os
import re
import secrets
import shutil
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from voicecore import agents, budget
from voicecore.providers import deepgram_tts, openai_compat_llm

from . import auth, publish, sources
from .store import Store

COOKIE = "vc_session"
SAFE = {"GET", "HEAD", "OPTIONS"}
# The console's own pages: nothing from elsewhere, and no other site may frame them.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; frame-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
PREVIEW = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Test: {name}</title>
<style>body {{ margin: 0; padding: 20px; font: 15px/1.5 system-ui, sans-serif; color: #57606a; }}</style>
</head>
<body>
<p>This page holds exactly the snippet from the Embed tab. Open the assistant in the corner and ask it something.</p>
{snippet}
</body>
</html>
"""


class SetupIn(BaseModel):
    token: str = ""
    password: str = Field(min_length=12, max_length=200)


class LoginIn(BaseModel):
    password: str = Field(max_length=200)


class KeyIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class SettingsIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    docs_url: str = Field("", max_length=300)
    instructions: str = Field("", max_length=2000)
    first_message: str | None = Field(None, max_length=300)
    voice: str = deepgram_tts.MODEL
    llm: str = openai_compat_llm.MODEL
    keyterms: list[str] = []


class GitIn(BaseModel):
    url: str = Field(min_length=8, max_length=300)
    folder: str = Field("", max_length=200)
    ref: str = Field("", max_length=100)


class TextIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=200_000)


class SiteIn(BaseModel):
    origins: list[str] = Field(default_factory=list, max_length=50)


WEBSITE = re.compile(r"(https?://)?(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*(:\d{1,5})?")


def publish_site(agents_dir: Path, origins: list[str]) -> None:
    """The gateway reads this file (re-read at most once a second): allowed websites need no restart."""
    d = agents_dir / "_site"
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / ".origins.json.tmp"
    tmp.write_text(json.dumps({"origins": origins}))
    os.replace(tmp, d / "origins.json")


def default_config(name: str) -> dict:
    return SettingsIn(name=name).model_dump()


def create_app(data_dir: Path, agents_dir: Path, setup_token: str | None = None, now: Callable[[], float] = time.time,
               run_git=None, ledger: Path | None = None, max_passages: int = publish.MAX_PASSAGES, providers: str = "free",
               voice_url: str = "http://localhost:8080", static_dir: Path | None = None, turnstile_sitekey: str = "") -> FastAPI:
    """providers: the voice side's mode (free shows the 'voice is off' banner). voice_url: the gateway's public address,
    which the embed snippet loads the widget from. static_dir: the built console UI (apps/console/dist)."""
    data_dir, agents_dir = Path(data_dir), Path(agents_dir)
    store = Store(data_dir / "console.db")
    store.fail_interrupted_builds(now())
    if setup_token:
        store.offer_setup(auth.digest(setup_token))
    builds = ThreadPoolExecutor(max_workers=1, thread_name_prefix="build")  # one at a time: embedding is CPU-bound
    if origins := store.site_origins():  # the gateway's copy always matches the console's record
        publish_site(agents_dir, origins)
    logins = auth.RateLimit()
    app = FastAPI(title="VoiceCore console", docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    app.state.store, app.state.agents_dir, app.state.data_dir, app.state.now = store, agents_dir, data_dir, now
    app.state.run_git, app.state.ledger = run_git, ledger

    @app.middleware("http")
    async def same_origin_only(request: Request, call_next):
        """A changing request from another site's page is refused (the session cookie is also SameSite=Strict)."""
        origin = request.headers.get("origin")
        if request.method not in SAFE and origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            return JSONResponse({"detail": "cross-origin request"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("content-security-policy", CSP)
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("referrer-policy", "same-origin")
        return response

    def admin(request: Request) -> None:
        bearer = request.headers.get("authorization", "")
        if bearer.startswith("Bearer "):
            if store.key_valid(auth.digest(bearer[7:].strip())):
                return
        elif (cookie := request.cookies.get(COOKIE)) and store.session_valid(auth.digest(cookie), now()):
            return
        raise HTTPException(401, "sign in first")

    def sign_in(request: Request, response: Response) -> None:
        token = auth.new_token()
        store.add_session(auth.digest(token), now() + auth.SESSION_S)
        response.set_cookie(COOKIE, token, max_age=auth.SESSION_S, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https")

    voice_url = voice_url.rstrip("/")

    def snippet(agent_id: str) -> str:
        human = f' data-turnstile-sitekey="{html.escape(turnstile_sitekey)}"' if turnstile_sitekey else ""
        return f'<script src="{voice_url}/widget.js" data-agent="{agent_id}"{human} async></script>'

    @app.get("/api/status")
    def status():
        return {"setup_needed": store.admin_password() is None, "providers": providers, "voice_url": voice_url}

    @app.post("/api/setup", status_code=201)
    def setup(body: SetupIn, request: Request, response: Response):
        if store.admin_password():
            raise HTTPException(409, "already set up")
        if not auth.same(body.token, store.setup_hash()):
            raise HTTPException(403, "setup token required: use the link the installer printed")
        if not store.make_admin(auth.hash_password(body.password), now()):
            raise HTTPException(409, "already set up")
        sign_in(request, response)
        return {"admin": True}

    @app.post("/api/login")
    def login(body: LoginIn, request: Request, response: Response):
        if not logins.allow(request.client.host if request.client else "?", now()):
            raise HTTPException(429, "too many attempts: wait a minute")
        if not auth.check_password(body.password, store.admin_password()):
            raise HTTPException(401, "wrong password")
        sign_in(request, response)
        return {"admin": True}

    @app.post("/api/logout", status_code=204)
    def logout(request: Request, response: Response):
        if cookie := request.cookies.get(COOKIE):
            store.end_session(auth.digest(cookie))
        response.delete_cookie(COOKIE)

    @app.get("/api/me", dependencies=[Depends(admin)])
    def me():
        return {"admin": True}

    @app.get("/api/keys", dependencies=[Depends(admin)])
    def keys():
        return store.keys()

    @app.post("/api/keys", status_code=201, dependencies=[Depends(admin)])
    def new_key(body: KeyIn):
        key = auth.KEY_PREFIX + auth.new_token()
        key_id = "key_" + auth.new_token()[:12]
        store.add_key(key_id, body.label, auth.digest(key), now())
        return {"id": key_id, "label": body.label, "key": key}  # shown once; only its hash is kept

    @app.delete("/api/keys/{key_id}", status_code=204, dependencies=[Depends(admin)])
    def revoke_key(key_id: str):
        if not store.revoke_key(key_id, now()):
            raise HTTPException(404, "no such key")

    # --- install-wide settings -------------------------------------------------------------

    @app.get("/api/site", dependencies=[Depends(admin)])
    def get_site():
        return {"origins": store.site_origins()}

    @app.put("/api/site", dependencies=[Depends(admin)])
    def put_site(body: SiteIn):
        origins = [o.strip().lower().rstrip("/") for o in body.origins if o.strip()]
        for o in origins:
            if not WEBSITE.fullmatch(o):
                raise HTTPException(422, f"not a website: {o} (use a host such as docs.example.com)")
        store.set_site_origins(origins)
        publish_site(agents_dir, origins)
        return {"origins": origins}

    @app.get("/api/usage", dependencies=[Depends(admin)])
    def usage():
        if ledger is None:
            return {"spent_usd": None, "cap_usd": None, "today_usd": None, "daily_cap_usd": None}
        return budget.read_totals(ledger)

    # --- agents ---------------------------------------------------------------------------

    def agent_or_404(agent_id: str) -> dict:
        if (a := store.agent(agent_id)) is None:
            raise HTTPException(404, "no such agent")
        return a

    @app.get("/api/catalog", dependencies=[Depends(admin)])
    def catalog():
        return {"voices": deepgram_tts.VOICES, "llms": list(openai_compat_llm.PRICES)}

    @app.get("/api/agents", dependencies=[Depends(admin)])
    def list_agents():
        return [{"id": a["id"], "name": a["config"]["name"], "enabled": a["enabled"],
                 "live_version": agents.current(agents_dir, a["id"]),
                 "build": (b := store.latest_build(a["id"])) and b["status"],
                 "sources": len(store.sources(a["id"])),
                 "summary": (p := store.last_published(a["id"])) and p["log"].split("\n")[0],
                 "published": p and p["finished"]} for a in store.agents()]

    @app.post("/api/agents", status_code=201, dependencies=[Depends(admin)])
    def create_agent(body: AgentIn):
        config = default_config(body.name.strip())
        agent_id = store.add_agent(sources.slug(body.name, 36) or "agent", config, now())
        return {"id": agent_id, "config": config}

    @app.get("/api/agents/{agent_id}", dependencies=[Depends(admin)])
    def get_agent(agent_id: str):
        a = agent_or_404(agent_id)
        return {"id": agent_id, "config": a["config"], "enabled": a["enabled"], "live_version": agents.current(agents_dir, agent_id),
                "sources": store.sources(agent_id), "build": store.latest_build(agent_id), "published": store.last_published(agent_id),
                "snippet": snippet(agent_id)}

    @app.get("/preview/{agent_id}", response_class=HTMLResponse, dependencies=[Depends(admin)])
    def preview(agent_id: str):
        """The Test tab's frame: a page holding exactly the snippet a site would paste."""
        a = agent_or_404(agent_id)
        voice = voice_url.replace("http", "ws", 1)
        csp = (f"default-src 'none'; script-src {voice_url} blob: https://challenges.cloudflare.com; "  # blob: the audio worklets
               f"style-src 'unsafe-inline'; connect-src {voice_url} {voice}; frame-src https://challenges.cloudflare.com; "
               "frame-ancestors 'self'")
        page = PREVIEW.format(name=html.escape(a["config"]["name"]), snippet=snippet(agent_id))
        return HTMLResponse(page, headers={"content-security-policy": csp})

    @app.put("/api/agents/{agent_id}/settings", dependencies=[Depends(admin)])
    def settings(agent_id: str, body: SettingsIn):
        agent_or_404(agent_id)
        config = body.model_dump()
        try:
            agents.validate(config)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        store.set_config(agent_id, config, now())
        return {"config": config}  # takes effect at the next Publish

    @app.delete("/api/agents/{agent_id}", status_code=204, dependencies=[Depends(admin)])
    def delete_agent(agent_id: str):
        agent_or_404(agent_id)
        agents.disable(agents_dir, agent_id)
        shutil.rmtree(agents_dir / agent_id, ignore_errors=True)
        shutil.rmtree(data_dir / "sources" / agent_id, ignore_errors=True)
        store.delete_agent(agent_id)

    def new_source_dir(agent_id: str) -> tuple[str, Path]:
        sid = "src_" + secrets.token_hex(6)
        return sid, data_dir / "sources" / agent_id / sid

    @app.put("/api/agents/{agent_id}/sources/upload", status_code=201, dependencies=[Depends(admin)])
    async def upload(agent_id: str, request: Request, name: str = "upload.zip"):
        agent_or_404(agent_id)
        body = bytearray()
        async for chunk in request.stream():  # counted as it arrives: a huge body is refused before it is all held
            body += chunk
            if len(body) > sources.MAX_BODY:
                raise HTTPException(413, "upload larger than 20 MB")
        sid, dest = new_source_dir(agent_id)
        try:
            result = await run_in_threadpool(sources.save_upload, bytes(body), name, dest)
        except sources.Rejected as e:
            shutil.rmtree(dest, ignore_errors=True)
            raise HTTPException(e.status, e.message) from None
        store.add_source(sid, agent_id, "upload", name[:200], None, result["files"], now())
        return {"id": sid, **result}

    @app.post("/api/agents/{agent_id}/sources/text", status_code=201, dependencies=[Depends(admin)])
    def paste(agent_id: str, body: TextIn):
        agent_or_404(agent_id)
        sid, dest = new_source_dir(agent_id)
        result = sources.save_text(body.title, body.text, dest)
        store.add_source(sid, agent_id, "text", body.title, None, result["files"], now())
        return {"id": sid, **result}

    def git_fetch(body: GitIn, dest: Path) -> dict:
        try:
            return sources.fetch_git(body.url, body.folder, dest, body.ref, **({"run_git": run_git} if run_git else {}))
        except sources.Rejected as e:
            raise HTTPException(e.status, e.message) from None

    @app.post("/api/agents/{agent_id}/sources/git", status_code=201, dependencies=[Depends(admin)])
    def add_git(agent_id: str, body: GitIn):
        agent_or_404(agent_id)
        sid, dest = new_source_dir(agent_id)
        result = git_fetch(body, dest)
        label = body.url + (f" / {body.folder.strip('/')}" if body.folder.strip("/") else "")
        store.add_source(sid, agent_id, "git", label[:200], json.dumps(body.model_dump()), result["files"], now())
        return {"id": sid, **result}

    @app.post("/api/agents/{agent_id}/sources/{source_id}/sync", dependencies=[Depends(admin)])
    def sync_git(agent_id: str, source_id: str):
        """Fetch the repository folder again; the new files replace the old ones (Publish to put them live)."""
        source = next((s for s in store.sources(agent_id) if s["id"] == source_id and s["kind"] == "git"), None)
        if source is None:
            raise HTTPException(404, "no such Git source")
        result = git_fetch(GitIn(**json.loads(source["ref"])), data_dir / "sources" / agent_id / source_id)
        store.set_source_files(source_id, result["files"])
        return result

    @app.delete("/api/agents/{agent_id}/sources/{source_id}", status_code=204, dependencies=[Depends(admin)])
    def delete_source(agent_id: str, source_id: str):
        if not store.delete_source(agent_id, source_id):
            raise HTTPException(404, "no such source")
        shutil.rmtree(data_dir / "sources" / agent_id / source_id, ignore_errors=True)

    @app.post("/api/agents/{agent_id}/publish", status_code=202, dependencies=[Depends(admin)])
    def start_publish(agent_id: str):
        agent_or_404(agent_id)
        if (build_id := store.new_build(agent_id, now())) is None:
            raise HTTPException(409, "a build is already running")
        builds.submit(publish.build, store, data_dir, agents_dir, agent_id, build_id, now, max_passages)
        return {"build": build_id}

    @app.get("/api/agents/{agent_id}/builds/latest", dependencies=[Depends(admin)])
    def latest_build(agent_id: str):
        agent_or_404(agent_id)
        return store.latest_build(agent_id) or {"status": "none"}

    @app.post("/api/agents/{agent_id}/disable", dependencies=[Depends(admin)])
    def disable(agent_id: str):
        agent_or_404(agent_id)
        agents.disable(agents_dir, agent_id)  # new sessions are refused; open ones finish
        store.set_enabled(agent_id, False)
        return {"enabled": False}

    @app.post("/api/agents/{agent_id}/enable", dependencies=[Depends(admin)])
    def enable(agent_id: str):
        agent_or_404(agent_id)
        if not (last := store.last_published(agent_id)):
            raise HTTPException(409, "publish first")
        version = last["version"]
        try:
            agents.activate(agents_dir, agent_id, version)
        except FileNotFoundError:
            raise HTTPException(409, "the last version is gone: publish again") from None
        store.set_enabled(agent_id, True)
        return {"enabled": True, "live_version": version}

    if static_dir:  # last: the API routes above win
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="ui")
    return app
