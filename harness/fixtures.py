"""Fixture manifest access (seam 11). Clip paths in the manifest are relative to fixtures/audio/."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "fixtures/audio/manifest.json"


def load_manifest(path=MANIFEST):
    return json.loads(Path(path).read_text())
