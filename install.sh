#!/bin/sh
# VoiceCore on a new Linux server, in one line (as root, or with sudo):
#
#   curl -fsSL https://raw.githubusercontent.com/ai-calypse/voicecore-lab/main/install.sh | sudo sh
#
# It installs Docker and Node.js when they are missing, then runs `npx create-voicecore --domain auto`: the dashboard
# opens at https://<this server's IP address>, with no domain or DNS needed. With a domain of your own, whose DNS
# points at this server:
#
#   curl -fsSL https://raw.githubusercontent.com/ai-calypse/voicecore-lab/main/install.sh | sudo sh -s -- --domain voice.example.com
#
# The install lives in ~/voicecore. Running this again keeps its settings, password and data.
set -eu

NODE_MAJOR=22
fail() { printf 'VoiceCore: %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = Linux ] || fail "this script sets up a Linux server. On your own computer, install Docker Desktop and Node.js, then run: npx create-voicecore"
[ "$(id -u)" = 0 ] || fail "run it as root: curl -fsSL https://raw.githubusercontent.com/ai-calypse/voicecore-lab/main/install.sh | sudo sh"
command -v curl >/dev/null 2>&1 || fail "curl is missing: install it and run this again"

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker…"
  curl -fsSL https://get.docker.com | sh  # Docker's own install script
fi
docker info >/dev/null 2>&1 || systemctl enable --now docker >/dev/null 2>&1 || service docker start >/dev/null 2>&1 || true

node_major() { node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0; }
if [ "$(node_major)" -lt 20 ]; then
  echo "Installing Node.js $NODE_MAJOR…"
  case "$(uname -m)" in
    x86_64 | amd64) arch=x64 ;;
    aarch64 | arm64) arch=arm64 ;;
    *) fail "no Node.js build for $(uname -m): install Node.js 20 or newer, then run: npx create-voicecore --domain auto" ;;
  esac
  base="https://nodejs.org/dist/latest-v$NODE_MAJOR.x"
  tmp=$(mktemp -d)
  curl -fsSL "$base/SHASUMS256.txt" -o "$tmp/SHASUMS256.txt"
  file=$(grep -o "node-v[0-9.]*-linux-$arch\.tar\.gz" "$tmp/SHASUMS256.txt" | head -n 1)
  curl -fsSL "$base/$file" -o "$tmp/$file"
  (cd "$tmp" && grep "  $file\$" SHASUMS256.txt | sha256sum -c - >/dev/null) || fail "the Node.js download didn't match its checksum"
  tar -xzf "$tmp/$file" -C /usr/local --strip-components=1 --no-same-owner "${file%.tar.gz}/bin" "${file%.tar.gz}/lib" "${file%.tar.gz}/include" "${file%.tar.gz}/share"
  rm -rf "$tmp"
fi

case " $* " in
  *" --domain "* | *" --domain="*) ;;
  *) set -- --domain auto "$@" ;;
esac
cd "$HOME"
exec npx --yes create-voicecore@latest --yes "$@"
