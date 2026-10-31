"""The read-only demo console (Step 10, P9) shows snapshots of the real API, made here through TestClient.

The test fails when the API's shape and the committed snapshots differ. Refresh them with
    UPDATE_DEMO=1 uv run pytest services/console/tests/test_demo_snapshot.py
The demo agent is this project's own docs (apps/docs/docs), published for real: its sections, versions and log
are what the console would show.
"""
import io
import json
import os
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from voicecore_console.app import create_app

ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "apps/console/demo"
DOCS = ROOT / "apps/docs/docs"
NOW = 1793491200.0  # 2026-10-31 UTC: the snapshot's own timestamps


def docs_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(DOCS.rglob("*.md")):
            z.writestr(f"voicecore-docs/{f.relative_to(DOCS).as_posix()}", f.read_text())
    return buf.getvalue()


def snapshots(tmp_path) -> dict:
    app = create_app(tmp_path / "console", tmp_path / "agents", setup_token="demo", now=lambda: NOW, providers="live",
                     voice_url="https://voicecore.fly.dev")
    with TestClient(app, base_url="http://localhost:8000") as c:
        c.post("/api/setup", json={"token": "demo", "password": "a demo password only"})
        agent = c.post("/api/agents", json={"name": "VoiceCore docs"}).json()["id"]
        settings = {**c.get(f"/api/agents/{agent}").json()["config"], "docs_url": "https://voicecore-docs.fly.dev/",
                    "first_message": "Hi. I answer from the VoiceCore docs: ask about latency, turn-taking or the widget.",
                    "instructions": "Keep answers short. Say the section's name when it helps someone find it.",
                    "keyterms": ["VoiceCore", "endpointing", "barge-in", "Silero"]}
        c.put(f"/api/agents/{agent}/settings", json=settings)
        c.put(f"/api/agents/{agent}/sources/upload", params={"name": "voicecore-docs.zip"}, content=docs_zip(),
              headers={"Content-Type": "application/octet-stream"})
        c.post(f"/api/agents/{agent}/sources/text", json={"title": "Support hours", "text": "Questions about VoiceCore go to the GitHub repository's issues."})
        c.post(f"/api/agents/{agent}/publish")
        deadline = time.monotonic() + 240
        while c.get(f"/api/agents/{agent}/builds/latest").json()["status"] not in ("done", "failed") and time.monotonic() < deadline:
            time.sleep(0.2)
        c.put("/api/site", json={"origins": ["voicecore-docs.fly.dev"]})
        c.post("/api/keys", json={"label": "docs CI"})
        paths = ["status", "me", "agents", f"agents/{agent}", f"agents/{agent}/builds/latest", "catalog", "site", "keys", "usage"]
        return {p.replace("/", "__"): c.get(f"/api/{p}").json() for p in paths}


def shape(x):
    if isinstance(x, dict):
        return {k: shape(v) for k, v in sorted(x.items())}
    if isinstance(x, list):
        return [shape(x[0])] if x else []
    return type(x).__name__


@pytest.mark.timeout(300)
def test_demo_snapshot_matches_api(tmp_path):
    fresh = snapshots(tmp_path)
    assert fresh["agents__voicecore-docs__builds__latest"]["status"] == "done"
    if os.environ.get("UPDATE_DEMO"):
        DEMO.mkdir(exist_ok=True)
        for name, data in fresh.items():
            (DEMO / f"{name}.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    committed = {f.stem: json.loads(f.read_text()) for f in DEMO.glob("*.json")}
    assert set(committed) == set(fresh)
    assert {k: shape(v) for k, v in committed.items()} == {k: shape(v) for k, v in fresh.items()}
