"""The console API reference page lists every route the console serves (Step 10, P9): it cannot fall behind."""
from pathlib import Path

from voicecore_console.app import create_app

PAGE = Path(__file__).resolve().parents[3] / "apps/docs/docs/reference/console-api.md"


def test_api_reference_lists_every_route(tmp_path):
    app = create_app(tmp_path / "c", tmp_path / "a")
    page = PAGE.read_text()
    missing = [f"{m} {r.path}" for r in app.routes if hasattr(r, "methods") and r.path.startswith(("/api/", "/preview/"))
               and r.path not in ("/api/docs", "/api/openapi.json", "/api/docs/oauth2-redirect")
               for m in sorted(r.methods - {"HEAD"}) if f"| {m} | `{r.path}` |" not in page]
    assert missing == []
