# Transport benchmark (S01-T05)

**Date:** 2026-10-30 UTC. **Machine:** Apple M4, macOS 26.5.2, Go 1.27.1 (module minimum 1.25), loopback only.
**Raw output:** [`raw/transport_20261030T003218Z.jsonl`](raw/transport_20261030T003218Z.jsonl). **Label:** `fake-provider` (fakeorch echo), local loopback; the proxy rows are `simulated`.

## What is measured

`cmd/wsload` opens N sessions, sends one 20 ms mic frame (320 samples, 668 bytes) every 20 ms for 10 s, and stamps each frame's `capture_us` with its own monotonic clock. `cmd/fakeorch -echo` upsamples each frame to 24 kHz and sends it back as generation 1 with the same `capture_us`, so:

- **RTT** = wsload receive time − `capture_us` of the echoed frame: client → gateway → orchestrator → gateway → client.
- **Inter-arrival** = time between consecutive echoed frames at the client (cadence; 20 ms is ideal).
- **Gateway overhead** = RTT through the gateway − RTT straight to fakeorch (two gateway passes).

## Results

| Profile | Streams | Frames sent / received | RTT p50 / p95 / p99 (ms) | Inter-arrival p50 / p95 / p99 (ms) | Gateway drops / gaps |
|---|---:|---:|---|---|---|
| direct to fakeorch (no gateway) | 1 | 500 / 500 | 0.24 / 0.37 / 0.43 | 20.00 / 21.60 / 21.82 | — |
| through gateway | 1 | 500 / 500 | 0.43 / 0.60 / 0.69 | 19.96 / 21.49 / 21.79 | 0 / 0 |
| through gateway | 20 | 9,995 / 9,995 | 1.08 / 1.68 / 2.16 | 19.98 / 21.57 / 22.36 | 0 / 0 |
| through gateway + proxy 50 ± 20 ms each way (`simulated`) | 1 | 500 / 500 | 104.71 / 131.03 / 137.18 | 18.28 / 55.51 / 65.58 | 0 / 0 |
| through gateway + proxy 150 ± 50 ms each way (`simulated`) | 1 | 500 / 500 | 326.44 / 377.01 / 385.96 | 0.04 / 86.15 / 118.09 | 0 / 0 |

- **Gateway overhead, 1 stream:** 0.43 − 0.24 = **0.19 ms median for both passes** (≈ 0.1 ms per pass). With 20 streams the RTT median is 1.08 ms.
- **Per-frame codec cost** (`go test -run '^$' -bench . -benchtime 2s ./protocol`): `DecodeFrame` 205.7 ns, 640 B, 1 alloc per 20 ms mic frame; `EncodeFrame` 250.1 ns, 1,024 B, 1 alloc per 20 ms agent frame.
- **Jitter turns into bursts.** The proxy keeps byte order (TCP cannot reorder), so a delayed chunk holds back everything behind it: at 150 ± 50 ms the median inter-arrival is 0.04 ms because frames arrive in clumps. This is why the browser playout counts underruns by time and the RTP jitter buffer belongs to Step 07, not this path.
- 9,995 rather than 10,000 frames in the 20-stream run: the per-stream 10 s timer and 20 ms ticker race at the end, so a few streams sent 499 frames. Every sent frame came back.

## Not measured here

- **Real packet loss.** The proxy adds delay and jitter in user space; it cannot drop TCP segments. Loss on a WebSocket shows up as a retransmission stall, which needs kernel shaping. That needs `sudo`, which the agent does not have. Run the dummynet profile in [README.md](README.md#shaped-network-dummynet) to fill this in. It is not run yet.
- Browser-side capture → send time (the tracer bullet only checks function, not timing).

## Reproduce

```bash
cd services/realtime-gateway
go run ./cmd/fakeorch -addr 127.0.0.1:8765 &
go run ./cmd/gateway -addr 127.0.0.1:8080 -upstream ws://127.0.0.1:8765 &
go run ./cmd/wsload -direct -n 1 -duration 10s -label direct-fakeorch-n1
go run ./cmd/wsload -n 1 -duration 10s -label gateway-n1
go run ./cmd/wsload -n 20 -duration 10s -label gateway-n20
go run ./cmd/wsload -n 1 -duration 10s -delay 50ms -jitter 20ms -label gateway-n1-proxy-50ms+-20ms
go run ./cmd/wsload -n 1 -duration 10s -delay 150ms -jitter 50ms -label gateway-n1-proxy-150ms+-50ms
```
