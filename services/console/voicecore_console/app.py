"""The console's HTTP API. This module maps HTTP to the store, auth and publishing; it holds no rules of its own.

create_app is the one composition root: folders, the setup token and the edges (clock, git) come in as arguments,
so tests run it on temporary folders with a fake clock.
"""
import time
from collections.abc import Callable
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import auth
from .store import Store

COOKIE = "vc_session"
SAFE = {"GET", "HEAD", "OPTIONS"}


class SetupIn(BaseModel):
    token: str = ""
    password: str = Field(min_length=12, max_length=200)


class LoginIn(BaseModel):
    password: str = Field(max_length=200)


class KeyIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)


def create_app(data_dir: Path, agents_dir: Path, setup_token: str | None = None, now: Callable[[], float] = time.time,
               run_git=None, ledger: Path | None = None) -> FastAPI:
    data_dir, agents_dir = Path(data_dir), Path(agents_dir)
    store = Store(data_dir / "console.db")
    if setup_token:
        store.offer_setup(auth.digest(setup_token))
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
        return await call_next(request)

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

    app.state.admin = admin  # the agents and publishing routes (P5) use the same dependency
    return app
