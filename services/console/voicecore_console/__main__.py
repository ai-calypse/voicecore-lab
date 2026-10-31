"""python -m voicecore_console serve | reset-admin

serve: the console on --host/--port (the installer runs it in Docker). The first-run setup token comes from the
environment (CONSOLE_SETUP_TOKEN), never a flag, so it does not show up in ps.
reset-admin: forget the admin password and print a new setup link (for a lost password).
"""
import argparse
import os
import secrets
from pathlib import Path

from . import auth
from .store import Store


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m voicecore_console")
    sub = ap.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="run the console")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    for p in (serve, sub.add_parser("reset-admin", help="forget the admin password and print a new setup link")):
        p.add_argument("--data-dir", type=Path, default=Path(os.environ.get("CONSOLE_DATA_DIR", "/data/console")))
    serve.add_argument("--agents-dir", type=Path, default=Path(os.environ.get("VOICECORE_AGENTS_DIR", "/data/agents")))
    sub.choices["reset-admin"].add_argument("--url", default="http://localhost:8000", help="the console's address")
    args = ap.parse_args(argv)

    if args.cmd == "reset-admin":
        token = secrets.token_urlsafe(24)
        Store(args.data_dir / "console.db").reset_admin(auth.digest(token))
        print(f"Open {args.url.rstrip('/')}/#/setup?token={token} to set a new admin password.")
        return

    import uvicorn

    from .app import create_app

    ledger = os.environ.get("VOICECORE_LEDGER")
    static = os.environ.get("CONSOLE_STATIC")
    app = create_app(args.data_dir, args.agents_dir, setup_token=os.environ.get("CONSOLE_SETUP_TOKEN"),
                     ledger=Path(ledger) if ledger and not ledger.startswith("redis") else None,
                     providers=os.environ.get("VOICECORE_PROVIDERS", "free"),
                     voice_url=os.environ.get("PUBLIC_VOICE_URL", "http://localhost:8080"),
                     static_dir=Path(static) if static else None)
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"))


if __name__ == "__main__":
    main()
