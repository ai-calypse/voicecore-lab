---
title: Measure latency
description: How to run the WSS runner and the fake-time benchmark, read each latency column, run the CI regression gate and inspect one session in the lab timeline.
---

VoiceCore measures a voice turn in two ways: through the real stack in real time, or inside one process on fake time. Both use the metric definitions in `harness/timeline.py`, so a number from one tool means the same thing as a number from another. This page shows how to run each tool, what each column means, and how to look at one session on a timeline.

## Two ways to measure a voice turn

VoiceCore has two latency harnesses, and they answer different questions. Pick the one that matches yours.

| | WSS runner | In-process runner |
|---|---|---|
| Script | `harness/runner/wss.py` | `harness/runner/inprocess.py`, used by `bench.py` and `gate.py` |
| What runs | headless SDK client, Go gateway, Python orchestrator, real network sockets | one real `Session` in one event loop, with a fake client |
| Clock | real time | fake time (`looptime`): a 10 s clip takes milliseconds |
| Providers | mock or live | mock only |
| Repeatable | no, so it is for benchmarks, not CI gates | yes, every run is identical |

Use the WSS runner when you want the real end-to-end number, including transport and live provider delays. Use the in-process runner when you want a deterministic number that changes only when the code changes. The CI regression gate uses the in-process runner for that reason.

## What the total latency number measures

The headline number for a voice turn is `total_ms`. It runs from the labelled end of the user's speech to the first agent sample rendered by the client.

- **Start:** every speech fixture in the manifest has a label, `turn_end_ms`, for where the user stops speaking. The headless client logs `mic.start` with the time of its first mic frame, so the speech end on the client clock is that time plus `turn_end_ms`.
- **End:** the client's `playout.started` event for the agent's generation, which the playout emits when it renders the first sample.
- **Clock:** both ends are on the client's clock, so no clock offset is involved.

When one user turn produced more than one generation (for example, an early cutoff that was merged), the total is measured to the generation that actually played. Percentiles are nearest-rank: the p50 is the smallest value with at least half of the values at or below it. Small samples rank configurations; they are not production rates.

## Run the WSS runner with mock providers

The WSS runner starts the whole stack, runs one headless client per clip, then stops the stack. With mock providers it spends nothing.

```bash
uv run python harness/runner/wss.py --clips dev_single_01 dev_single_02
```

What the runner does, in order:

1. Builds the gateway with `go build` into `.cache/bin/gateway`. The binary never goes into the run folder, because that folder is committed evidence.
2. Starts the orchestrator (`python -m voicecore.server`) with `--trace-dir` pointing into the run folder.
3. Starts the gateway on `127.0.0.1:8080` with a trace file, and with `-max-sessions-per-ip 0 -tokens-per-minute 0`, because every benchmark client shares one IP.
4. Waits for `GET /debug/counters` to answer, plus one second for the orchestrator to load the VAD model.
5. Runs `packages/web-sdk/bin/headless-client.ts` under Node once per clip, each with `--fixture`, `--out` and `--tail`.
6. Saves the gateway counters, then stops both processes with SIGINT.

If the gateway or orchestrator exits during startup, the runner stops with an error that points at `gateway.log` and `orchestrator.log`. One cause is a `docker compose` stack that already holds port 8080 and would answer instead. Before that check existed, one smoke run silently measured the leftover Docker stack instead.

## WSS runner flags

The WSS runner, `harness/runner/wss.py`, takes the flags below. The defaults run one mock-provider client on clip `dev_single_01` with a 12 s tail. Clips run in parallel unless you pass `--sequential`, and each copy from `--parallel` is a separate headless client and session. The run folder name records the providers, the policy and your label, so runs stay comparable later. Unknown clip ids stop the runner with an error.

| Flag | Default | What it does |
|---|---|---|
| `--clips ID ...` | `dev_single_01` | clip ids from the fixture manifest, plus the local-only docs-question clips when `fixtures/audio/local/manifest.json` exists |
| `--parallel N` | 1 | run N copies of each clip, all at once (load tests) |
| `--providers` | `mock` | `mock` or `live`; live spends money |
| `--tail S` | 12 | seconds of silence the client keeps sending after the clip, so the answer can finish |
| `--out DIR` | generated | run folder; the default is `benchmarks/raw/wss_<providers>_<policy>[_<label>]_<UTC time>` |
| `--no-stack` | off | do not start a gateway and orchestrator; use ones that are already running |
| `--sequential` | off | one client at a time, for provider concurrency limits |
| `--policy` | orchestrator default | `fixed`, `adaptive`, `asr_assisted` or `eager`; the default is eager with live providers and fixed with mocks |
| `--server-arg` | none | an extra orchestrator flag, repeatable, for example `--server-arg=--llm-model=openai/gpt-4.1-nano` |
| `--label` | empty | suffix for the run folder name |

## Run a live latency benchmark

A live run uses Deepgram, OpenRouter and Cartesia, so it spends money from the project budget. Each session reserves its caps in `benchmarks/spend_ledger.json` before it starts. Put your keys in `.env` first.

```bash
uv run python harness/runner/wss.py --providers live --sequential --tail 8 \
  --clips dev_docs_question_q01 dev_docs_question_q02
uv run python harness/latency.py benchmarks/raw/<run folder>
```

Use `--sequential` for live runs. Clients then run one after another, so you measure one turn at a time and stay inside provider concurrency limits: 2 concurrent TTS streams is the lowest Cartesia tier (Free plan). The live reports used a `--tail` of 8 or 10 seconds. An answer that is still playing when the tail ends has no `playout.stopped` in the log; that happened to 2 of 10 answers in one 10 s run. It does not affect the total, which ends at `playout.started`.

The live default policy is eager endpointing, so you do not need `--policy`. To compare against the old default, add `--policy fixed`. To try another LLM, pass orchestrator flags through `--server-arg`.

## What a WSS run folder contains

Every WSS run writes one folder, by default under `benchmarks/raw/`. The runner writes the client logs, traces and counters. The two analysis scripts add their output to the same folder later, so one folder holds the raw evidence and the numbers derived from it. Times in the raw logs and traces are on each process's own clock.

| Path | Written by | Content |
|---|---|---|
| `clients/NN_<clip id>.jsonl` | headless client | every event the client sent or received, mic start and playout events, on the client clock |
| `traces/<session id>.jsonl` | orchestrator | trace events for one session, on the orchestrator clock |
| `gateway_trace.jsonl` | gateway | trace events for all sessions, on the gateway clock |
| `gateway_counters.json` | runner | drop, gap and queue counters from `GET /debug/counters` after the run |
| `gateway.log`, `orchestrator.log` | processes | standard output and errors |
| `latency.json` | `harness/latency.py` | per-turn breakdown and p50 and p95 |
| `timelines/<session id>.json` | `harness/session_timeline.py` | one merged timeline per session, for the lab view |

The runner prints each client log's key events (welcome, generation started, playout started and stopped, cancel) and the run folder path when it finishes.

## Break a run down per stage with the latency script

`harness/latency.py` turns a WSS run folder into one row per turn and a p50 and p95 per column.

```bash
uv run python harness/latency.py benchmarks/raw/wss_live_eager_20261030T132949Z
```

For each client log it reads the session id from the `welcome` event, opens `traces/<session id>.jsonl`, and calls `turn_breakdown` with the clip's labelled turn end. It prints a Markdown table you can paste into a report, and writes `latency.json` with the rows, the summary and n.

- A turn whose trace or playout is missing becomes an error row (`incomplete turn`) and is left out of the percentiles.
- Turns with more than one generation are listed under `turns_with_more_than_one_generation` and marked `split` in the table. They still count, measured to the generation that played.
- Percentiles are nearest-rank, from `harness/timeline.py`.

## What each latency column means

Each column comes from `turn_breakdown` in `harness/timeline.py`. Each one is measured on a single clock, so no clocks are subtracted from each other.

| Column | Clock | From → to |
|---|---|---|
| `total_ms` | client | labelled end of the user's speech → first agent sample rendered (`playout.started`) |
| `endpoint_delay_ms` | client | speech end → end of the mic frame on which the floor decided the turn was over |
| `stt_settle_ms` | orchestrator | endpoint → final transcript ready (`stt.turn_text`) |
| `llm_first_token_ms` | orchestrator | LLM request → first answer token |
| `tts_first_audio_ms` | orchestrator | first token → first TTS audio frame, including the wait for the first full sentence |
| `residual_ms` | derived | total minus endpoint delay minus endpoint → first audio: uplink and downlink transport plus playout start |

A small residual (p50 13 to 26 ms in the live runs, n = 10 to 15 each) means almost all of the turn is spent in endpointing and the providers, not in transport. The stage columns use the endpoint and transcript that led to the generation that played, not an earlier one.

## Why the client and orchestrator clocks are never subtracted

The client, the gateway and the orchestrator each have their own monotonic clock. Subtracting a time on one clock from a time on another gives a meaningless number unless you know the offset between them. `turn_breakdown` avoids that:

- The orchestrator's `turn.endpoint` trace event carries `capture_end_us`: the end of the mic frame that triggered the endpoint. That value comes from the frame's `capture_us` header field, which the client stamped on its own clock. So the endpoint delay is client clock minus client clock.
- STT settle, LLM first token and TTS first audio are differences of two orchestrator events.
- The total is two client events.

Only the residual is derived, as the total minus the measured stages. The merged timeline for the lab view does need offsets, and those are explained in the section on clock offsets.

## Run the fake-time benchmark

`harness/bench.py` measures the turn in process on fake time, with mock providers that have fixed delays. Everything else is real: Silero VAD, the floor and the generation runtime.

```bash
uv run python harness/bench.py
```

- **Mocks:** the STT returns its final on Finalize, the LLM's first token comes after 200 ms, the TTS's first audio after 150 ms.
- **Grid:** every dev speech clip × one-way network delay of 0, 20 or 50 ms × clean or 15 dB pink noise × 3 seeds. With 12 dev speech clips, that is 216 turns.
- **Output:** `reports/perf_fake.json`, with every row and a summary: answered turns, total and endpoint p50, p95 and p99, early cutoffs, STT queue drops and the median total per network delay.

The last recorded run gave total p50 1,320 ms and p95 1,440 ms (fake-provider, n = 216), with 216 of 216 answered and 0 early cutoffs. With mocks the fixed 800 ms endpoint is about two thirds of the total, so this benchmark catches runtime and turn-taking regressions, not provider ones.

## The CI regression gate and its thresholds

`harness/gate.py` runs a fixed scenario set in process on fake time and compares the result with `harness/thresholds.json`. It exits 1 on any regression. The `evals` workflow (`.github/workflows/evals.yml`) runs it on every push and pull request.

The scenarios are 12 dev speech turns, 3 interrupt clips and 2 echo-only clips, with real Silero VAD, runtime and echo gate and mock providers.

| Metric | Limit | Measured 2026-10-30 |
|---|---:|---:|
| `answered` | at least 12 | 12 |
| `interrupts_silenced` | at least 3 | 3 |
| `early_cutoffs` | at most 0 | 0 |
| `false_barge_ins` | at most 0 | 0 |
| `total_ms_p50` | at most 1,360 ms | 1,260 ms |
| `total_ms_p95` | at most 1,480 ms | 1,380 ms |
| `interrupt_to_silence_ms_max` | at most 540 ms | 440 ms |

The rule in the file: latencies may grow by at most 100 ms over the measurement, and counts may not get worse. An empty result counts as a very large latency, so it fails the gate instead of crashing it.

## How to prove and update the gate

The gate was proven to catch a regression. Branch `ci-gate-proof` adds 200 ms to the mock LLM's first token. Locally the gate then reports total p50 1,460 > 1,360 and p95 1,580 > 1,480 (mock, fake time, n = 12), and the `evals` workflow failed on that branch. On main it passes.

When a change makes the turn legitimately faster or slower, measure again and edit the thresholds by hand:

```bash
uv run python harness/gate.py --write-baseline
```

`--write-baseline` prints the measured metrics and exits without checking them. Copy the numbers into the `measured` line of `harness/thresholds.json`, then set each latency limit to the new value plus 100 ms and each count limit to the new count. Run `uv run python harness/gate.py` without the flag to check a change before you push it.

## Build a session timeline from a WSS run

To see one session as a timeline, merge its three logs into one file:

```bash
uv run python harness/session_timeline.py benchmarks/raw/<run folder>
```

For every client log with a `welcome` event, the script reads the client log, the gateway trace events for that session and the orchestrator trace, and writes `timelines/<session id>.json` in the run folder. It prints each session's event count and clock offsets.

The output has `session_id`, `reference_clock` (always `client`), `offsets_us` per process, `offset_notes` explaining how each offset was found, and `events`, sorted by aligned time `t_us`. Client log events are renamed into trace spans: playout events become `playout`, `mic.start` and `user.onset` become `capture`. Pongs and the client's start and end markers are left out. Transcript and answer text are dropped from the merged timeline, as the trace privacy rule requires.

## How clock offsets for the timeline are derived

The merged timeline uses the client's clock as the reference. Each other process gets an offset that is added to its own times.

- **Gateway:** NTP style, from the client's ping and pong. The client sends `ping` with its time every 2 s, and the gateway answers with `pong` carrying its own time. Each pong gives a sample of client send time, gateway time and client receive time. `ntp_offset` picks the sample with the smallest round trip and assumes the gateway time was read at the midpoint.
- **Orchestrator:** derived from mic frames. For every frame, the orchestrator computes its arrival time minus the frame's capture end (`capture_us` + 20 ms) and keeps the minimum. It writes that minimum as a `clock.client_offset` trace event every 250 frames (5 s) and once more when the session closes.

The orchestrator offset includes the smallest one-way uplink delay, so the timeline labels it derived. With every process on one laptop, a comparison through this offset was reported as accurate to about 1 ms (`reports/perf.md`).

## Open the lab timeline view

The demo app has a timeline panel for one session. Add `?lab=1` to the demo page URL: with `docker compose up` that is `http://localhost:5173/?lab=1`.

- By default it loads `/lab/sample-timeline.json`, a mock-provider session made by `harness/lab_sample.py`. In that session the client asks by text, hears its own playback mixed into its mic at −15 dB, and a user clip interrupts 1.2 s into the answer. So the sample has one interrupted and one completed generation.
- To show another session, add `&trace=<url>` with the URL of a timeline JSON file, or use the **Load trace…** file picker on the page to open a `timelines/<session id>.json` from your run folder. A file that is not a timeline shows an error and leaves the current one in place.

The page shows a row of summary numbers, a chart and a table of every event. Chips above the table show or hide each process.

## What the lab timeline chart shows

The lab chart has two speaking lanes and five stage rows, all on the merged client clock.

- **User speaking:** from the orchestrator's `speech_started` or `barge_in` to the speech end of the following endpoint.
- **Agent speaking:** from the client's `playout.started` to `playout.stopped` for each generation. A generation stopped by a cancel is marked interrupted.
- **Endpoint wait:** the trailing silence before the turn ended, ending at the endpoint frame's capture end.
- **STT:** endpoint to final transcript.
- **LLM first token:** request to first token.
- **TTS first audio:** first token to first audio.
- **Playout start:** first audio to the first sample rendered by the client.

The summary row shows speech end to first audio for the last complete voice turn, endpoint wait, LLM first token and TTS first audio for the last generation, interrupt to silence, and gateway drops and gaps when the file includes gateway counters. Timelines from `session_timeline.py` have no counters, so that cell shows a dash.
