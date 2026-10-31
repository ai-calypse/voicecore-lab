# Platform images (Step 10)

`create-voicecore` installs two images, released together with the installer's version:

| Image | Dockerfile | Runs |
|---|---|---|
| `ghcr.io/ai-calypse/voicecore` | [voicecore.Dockerfile](voicecore.Dockerfile) | the orchestrator, or the console (`python -m voicecore_console serve`), chosen by the command |
| `ghcr.io/ai-calypse/voicecore-gateway` | [gateway.Dockerfile](gateway.Dockerfile) | the Go gateway, serving the widget at `/widget.js` |

Build them locally from the repository root:

```sh
docker build -t ghcr.io/ai-calypse/voicecore:local -f deploy/platform/voicecore.Dockerfile --build-arg VERSION=local .
docker build -t ghcr.io/ai-calypse/voicecore-gateway:local -f deploy/platform/gateway.Dockerfile --build-arg VERSION=local .
node packages/create-voicecore/index.mjs --yes --image-tag local      # install from them
uv run python harness/install_smoke.py --dir /tmp/vc --image-tag local  # the timed path, then uninstall
```

The release workflow (`.github/workflows/release.yml`) builds both for amd64 and arm64 on a `v*` tag and pushes
them to GHCR, then publishes the installer to npm.
