# Benchmarks

Every number here names its command, machine and label (`fake-provider`, `live-provider`, `simulated`, `manual`, `target`). Raw outputs live in `raw/`; spend is in `spend_ledger.json`.

| File | Step | What |
|---|---|---|
| `baseline_results.json` | S00-T02 | Deepgram Voice Agent hosted baseline (live) |
| `transport.md` | S01-T05 | gateway round trip, cadence, codec cost |

## Shaped network (dummynet)

Kernel shaping on macOS loopback, for real delay and packet loss on both TCP (WebSocket) and UDP (Step 07 RTP). Needs `sudo`; the agent cannot run it, so these commands have not been run yet. They shape traffic to and from the gateway port 8080 on `lo0`.

```bash
# enable a dummynet anchor alongside the system rules
(cat /etc/pf.conf; echo 'dummynet-anchor "voicecore"'; echo 'anchor "voicecore"') | sudo pfctl -f -
printf 'dummynet in quick on lo0 proto tcp from any to any port 8080 pipe 1\ndummynet out quick on lo0 proto tcp from any port 8080 to any pipe 1\n' | sudo pfctl -a voicecore -f -
sudo pfctl -E

sudo dnctl pipe 1 config delay 50ms               # profile "50 ms"
sudo dnctl pipe 1 config delay 150ms plr 0.01     # profile "150 ms + 1% loss"
(cd services/realtime-gateway && go run ./cmd/wsload -n 1 -duration 30s -label dummynet-150ms-1pct)

# undo
sudo pfctl -a voicecore -F all && sudo dnctl -q flush && sudo pfctl -f /etc/pf.conf
```

dummynet has no jitter setting; the `simulated` proxy in `cmd/wsload -delay -jitter` covers jitter without loss.
