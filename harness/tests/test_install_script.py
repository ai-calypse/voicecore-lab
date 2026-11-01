"""install.sh, the one-line server setup: it runs create-voicecore on the server's own address unless given a domain,
and says what to do when it can't run. Docker, Node.js and npx are stand-ins here; the docker-marked test installs
the real Node.js on a clean Ubuntu."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "install.sh"


def run(tmp_path, *args, uname="Linux", uid="0"):
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    stubs = {"uname": f'[ "$1" = -m ] && echo x86_64 || echo {uname}', "id": f"echo {uid}", "docker": "exit 0",
             "node": "echo 22", "npx": f'echo "$@" > {tmp_path}/npx-args; pwd > {tmp_path}/npx-dir', "curl": "exit 0"}
    for name, body in stubs.items():
        (bin_ / name).write_text(f"#!/bin/sh\n{body}\n")
        (bin_ / name).chmod(0o755)
    env = {"PATH": f"{bin_}:/usr/bin:/bin", "HOME": str(tmp_path)}
    return subprocess.run(["sh", str(SCRIPT), *args], env=env, capture_output=True, text=True)


def test_the_servers_own_address_by_default(tmp_path):
    r = run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "npx-args").read_text().split() == ["--yes", "create-voicecore@latest", "--yes", "--domain", "auto"]
    assert (tmp_path / "npx-dir").read_text().strip() == str(tmp_path)  # the install goes to ~/voicecore


def test_a_domain_of_your_own(tmp_path):
    assert run(tmp_path, "--domain", "voice.example.com").returncode == 0
    assert (tmp_path / "npx-args").read_text().split() == ["--yes", "create-voicecore@latest", "--yes", "--domain", "voice.example.com"]


def test_says_why_it_cannot_run(tmp_path):
    r = run(tmp_path, uid="1000")
    assert (r.returncode, r.stderr.strip()) == (1, "VoiceCore: run it as root: curl -fsSL "
                                                   "https://raw.githubusercontent.com/ai-calypse/voicecore-lab/main/install.sh | sudo sh")
    r = run(tmp_path, uname="Darwin")
    assert r.returncode == 1 and "On your own computer, install Docker Desktop and Node.js" in r.stderr


@pytest.mark.docker
@pytest.mark.skipif(shutil.which("docker") is None, reason="needs Docker")
def test_installs_node_on_a_clean_ubuntu(tmp_path):
    """The real script on ubuntu:24.04 (Docker and npx stood in): it downloads Node.js, checks its checksum, installs it."""
    stub = tmp_path / "stub"
    stub.mkdir()
    (stub / "docker").write_text("#!/bin/sh\nexit 0\n")
    (stub / "npx").write_text('#!/bin/sh\necho "npx $@"\nnode --version\n')
    for f in stub.iterdir():
        f.chmod(0o755)
    cmd = ("apt-get update -qq >/dev/null && apt-get install -y -qq curl ca-certificates >/dev/null && "
           "PATH=/stub:$PATH sh /install.sh")
    r = subprocess.run(["docker", "run", "--rm", "-v", f"{SCRIPT}:/install.sh:ro", "-v", f"{stub}:/stub:ro", "ubuntu:24.04",
                        "sh", "-c", cmd], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.strip().splitlines()
    assert lines[-2] == "npx --yes create-voicecore@latest --yes --domain auto"
    assert lines[-1].startswith("v22.")
