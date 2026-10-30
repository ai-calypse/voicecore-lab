# Load and scale

**Step 09 Phase 10, 2026-10-30.** Every number here is `fake-provider`: real audio through the real gateway, the real Silero VAD and the real runtime, with mock STT, LLM and TTS (the scale profile's billed mocks). Live rows will be added after the approved live load test.

## How it was measured

- **Stack:** `docker compose --profile scale`: nginx on 127.0.0.1:8090 in front of two gateways (`gw1`, `gw2`) and two orchestrators, one Redis ledger. Per-address limits and the session cap are off in this profile only, because every test client shares one address.
- **Load:** `uv run python harness/load.py --parallel N --copies C`. N headless SDK clients start at once, each streaming the labelled clip `dev_single_01` in real time through the load balancer, then 12 s of silence.
- **One copy:** orch-2 is stopped for the run; both gateways stay up, because nginx does not retry a POST that reached a dead one.
- **Metrics:** each row's latency and lag come from the orchestrators' own `/metrics`, as the change during that run.
  - `endpoint_to_first_audio` is the server-side stage defined in `voicecore/stages.py`.
  - Event-loop lag is sampled once a second; its p99 is close to the run's worst sample.
- **Machine:** one laptop runs everything: 100 Node clients, Docker's VM and both orchestrators. The 100-session rows partly measure that contention, not only VoiceCore.

## Results

| Orchestrators | Sessions at once | Answered | Server endpoint to first audio, p95 | Event-loop lag, p99 |
|---:|---:|---:|---:|---:|
| 1 | 20 | 20 | 737.5 ms | 4.8 ms |
| 1 | 50 | 50 | 737.5 ms | 4.8 ms |
| 1 | 100 | 100 | 1,473 ms | 445 ms |
| 2 | 20 | 20 | 737.5 ms | 4.9 ms |
| 2 | 50 | 50 | 737.5 ms | 4.8 ms |
| 2 | 100 | 100 | 1,160 ms | 885 ms |

The 737.5 ms p95 at low load is a histogram bucket edge (the 500–750 ms bucket), not a precise value: the mock providers' fixed delays put every turn in that bucket.

**Memory** after the runs: orchestrator about 222–226 MiB each, gateway about 19–23 MiB, independent of N within this range.

## What it means

- **One orchestrator holds 50 concurrent voice sessions** with no measurable loop lag (p99 under 5 ms) and latency unchanged from 20.
- **At 100 on one orchestrator**, the loop falls behind (p99 445 ms) and p95 passes the 1,200 ms target in [slos.md](../docs/ops/slos.md).
- **Two copies.** At 100 they keep every session answered, and p95 drops to 1,160 ms. Their lag p99 is worse than with one copy because the laptop itself is saturated: 100 client processes plus two orchestrators share its cores.
- **The plan's rule** was to move voice activity detection off the event loop (a thread pool) if the loop lag p99 passed 50 ms at 50 sessions on one copy. It measured 4.8 ms, so VAD stays where it is; the code note in `server.py` stays as the upgrade path.
- **Dropped sessions.** Earlier attempts lost sessions for two reasons, both fixed before the rows above. The scale gateways still had the default `-max-sessions 50`, now lifted in that profile. The first "one copy" setup also stopped a gateway, and nginx does not retry a POST to it.

## Soak

`uv run python harness/soak.py --minutes 30` against the scale profile: 10 clients streaming the clip again and again for 30 minutes, 1,390 sessions in total (139 rounds of 10), no failed round.

| Process | Memory at minute 6 | At minute 28 | Growth | Goroutines | Open files |
|---|---:|---:|---:|---|---|
| gateway 1 | 18.2 MiB | 19.1 MiB | +4.9% | 10 → 10 | 11 → 11 |
| gateway 2 | 18.4 MiB | 18.3 MiB | −0.5% | 10 → 11 | 12 → 12 |
| orchestrator 1 | 183.6 MiB | 188.1 MiB | +2.5% | | |
| orchestrator 2 | 186.0 MiB | 186.5 MiB | +0.3% | | |

Every process stays under the 10% rule. The gateways' memory rises from about 14 to 18 MiB in the first 5 minutes and then levels off; the script now measures from minute 5. A first run, which measured from minute 1, reported +20% for the gateways and was set aside for that reason. Its tail output was also cut, so this second run is the one recorded.

Redis memory grows steadily, about 0.5 KiB per session (1.70 to 2.59 MiB): it keeps every ledger entry, as the file ledger does, because the entries are the money record. That is growth by design, not a leak, but it has no bound. A follow-up could expire settled entries after some months, keeping the totals.

## Correctness under scale

From `harness/tests/test_scale.py` (docker; 3 passed locally):

- 40 sessions split over both orchestrators (each within 12–28).
- The Redis ledger moved by exactly 40 × $0.0017.
- A dropped client resumed on the gateway that owns its session (`?resume=s-gwN-...`).
- Stopping one orchestrator mid-run lost no new session.
