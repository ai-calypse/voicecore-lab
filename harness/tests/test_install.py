"""Step 10 (seam 25): create-voicecore on real images, timed to the first cited answer; the image size budget.

The docker CI job builds both images as :ci first (VOICECORE_IMAGE_TAG=ci). Locally: build them with the
commands in deploy/platform/README.md, tagged local.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TAG = os.environ.get("VOICECORE_IMAGE_TAG", "local")
pytestmark = [pytest.mark.docker, pytest.mark.timeout(900)]


def test_install_to_cited_answer_under_10_min(tmp_path):
    deadline = os.environ.get("INSTALL_DEADLINE_S", "600")
    out = subprocess.run([sys.executable, str(ROOT / "harness/install_smoke.py"), "--dir", str(tmp_path / "voicecore"),
                          "--image-tag", TAG, "--deadline", deadline], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout[-3000:] + out.stderr[-3000:]
    report = json.loads(out.stdout)
    assert report["answer"] == report["answer_with_console_stopped"] == "Closest section: Refunds > How refunds work."
    assert report["elapsed_s"] < float(deadline)


def test_image_size_budget():
    """The voicecore image downloads in about a minute and a half at 50 Mbit/s: at most 450 MB compressed."""
    save = subprocess.Popen(["docker", "save", f"ghcr.io/ai-calypse/voicecore:{TAG}"], stdout=subprocess.PIPE)
    size = subprocess.run(["gzip", "-1"], stdin=save.stdout, capture_output=True).stdout
    assert save.wait() == 0
    assert len(size) < 450 * 2**20, f"{len(size) / 2**20:.0f} MB compressed"
