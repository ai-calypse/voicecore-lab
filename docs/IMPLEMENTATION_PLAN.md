# VoiceCore Lab — build plan to finish the project (v3, final)

## Context

Step 00 is half done: S00-T01 (requirements matrix) and S00-T02 (Deepgram hosted baseline, $0.525 spent). Steps 01–08 exist only as one-line task outcomes in `docs/step_0X_*.md`. The user asked for one plain, very specific, test-first plan for the whole project. It was built in stages: draft v1 → review 1 → improve-codebase-architecture pass → v2 → independent review 2 (19 findings) → this v3. The review log is at the end.

User decisions (2026-10-29):
- **Architecture** (all adopted): one generation runtime + fencing; one turn-taking module inside the orchestrator; client playout module + one harness runner/timeline; no reorder buffer on the WebSocket path (the real jitter buffer moves to the RTP lab).
- **TDD seams:** all 13 in section C (9 agreed first; seams 10–13 signed off after review 2).
- **Providers:** Deepgram STT; an OpenAI model through **OpenRouter** (low-cost); Cartesia TTS (user has **20K credits**). Embeddings run locally.
- **Money cap:** **$5 total for the whole project, including the $0.525 already spent.** Cartesia credits are a separate pool.
- **Fixtures:** LibriSpeech (CC BY 4.0) + Deepgram Aura TTS for docs questions + 10 questions recorded by the user (holdout).
- **UI:** `frontend-design` skill + the `uizze` skill (install at user scope).

On approval, step 0.2 saves this plan in the repo as `docs/IMPLEMENTATION_PLAN.md`. Task IDs below are the stable IDs from the step docs; new tasks get new IDs, which are registered in the step docs in step 0.4.

---

## A. How every slice is done (TDD loop)

Each table row is one **slice** = one red → green cycle.
1. **RED:** write only the test named in the row. Run it. It must fail for the expected reason (not an import error).
2. **GREEN:** write the least code to pass. Run it: green.
3. **COMMIT** (`test(scope)`/`feat(scope)` or one commit). Push at least once per task. No refactor inside the loop; refactor at the step gate.

Always:
- Tests only at agreed seams (section C).
- Expected values are literals from the spec or a worked example, never recomputed the way the code computes them.
- Mock only system edges (provider network APIs, clock, randomness). Never our own modules.
- One clock per process, injected (Python: `loop.time` through a `Clock` object; Go: `time` under `synctest`; TS: an injected `now()`), so traces are reproducible.
- Live tests carry `@pytest.mark.live`, run serially (`-p no:randomly`, no xdist), skip without keys, and get a budget reservation first (section E).
- Every number is labelled `fake-provider`, `live-provider`, `simulated`, `manual` or `target`.

## B. Module map

```
pyproject.toml               root uv workspace: members services/agent-core, harness
packages/protocol/           ONE spec for both hops
  SPEC.md                    frame header, control events, fencing rule, trace event schema
  vectors/frames.json        golden frames (hex + fields; capture_us stored as a STRING, it can exceed 2^53)
  vectors/events.json        golden control events
  ts/frame.ts, ts/events.ts
packages/web-sdk/            browser SDK (TypeScript)
  src/capture/               resample.ts, framer.ts, pcm.ts, capture-worklet.ts (thin adapter)
  src/playout/               playout.ts (deep module), worklet-adapter.ts, offline-adapter.ts
  src/client.ts              WS session: hello, frames out, events in, clock ping
  bin/headless-client.ts     Node client using client.ts + offline playout; reads a fixture, paces 20 ms, writes JSONL
services/realtime-gateway/   Go (go.mod `go 1.25` minimum): owns the CONNECTION
  protocol/frame.go
  session/                   token, hello, heartbeat, resume window, bounded queues, counters, outbound fence
  internal/memnet/           in-memory net.Pipe listener + dialer for synctest tests
  cmd/gateway, cmd/fakeorch (scripted fake orchestrator), cmd/wsload
services/agent-core/         Python package `voicecore`: owns the CONVERSATION
  protocol.py, server.py (gateway hop), trace.py, clock.py
  budget.py                  pools, ledger, reservations (harness imports it)
  turntaking/                floor module + vad_silero.py, vad_fixture.py
  runtime/                   generation runtime (private helpers: transcript assembler, TTS chunker, recovery rules)
  providers/                 base.py, factory.py (live adapters need a Reservation), mock.py, deepgram_stt.py, openai_compat_llm.py, cartesia_tts.py
  answer/                    ingest, index (FTS5 + fastembed + RRF), docs.search tool, citation validator, speechify
harness/
  runner/                    in-process adapter (fake time, CI) | WSS adapter (launches N headless clients, real time)
  timeline.py                merge JSONL, clock offsets, every metric defined once
  fixtures.py, build_fixtures.py, record_questions.md, baseline_deepgram.py
apps/demo/                   widget + `?lab=1` timeline panel
experiments/rtp_lab/, experiments/webrtc_pion/
fixtures/audio/, fixtures/docs/, docs/adr/, GLOSSARY.md
```

- **Ownership:** Go owns the connection (auth, heartbeat, resume, backpressure, drop counters, outbound fence). Python owns turns and generations. The browser owns capture and playout. One protocol on both hops.
- **Fencing rule:** every agent audio frame carries `generation_id`. On cancel, each queue owner (Python outbound queue, Go send queue, browser playout) sets `fence = cancelled id` and drops every frame with `generation_id <= fence`.

## C. Test seams

Agreed by the user:

| # | Seam | Tool | Catches | Misses |
|---|---|---|---|---|
| 1 | Protocol golden vectors (TS, Go, Python) | vitest / go test / pytest | byte order, bounds, version, fencing disagreement | timing, load |
| 2 | Gateway session vs fake orchestrator + fake client | go test + `testing/synctest` over `internal/memnet` + goleak | leaks, drops, resume, flush after cancel | conversation logic |
| 3 | Turn-taking on labelled fixtures (time = sample position) | pytest | early cutoff, missed utterance, false barge-in on echo | room acoustics, browser AEC |
| 4 | Generation runtime with mock providers + fake clock | pytest + looptime | stale resumes, chunk order, duplicate text, stalls, deadlocks | real provider quirks |
| 5 | Provider contract suite (mock + live) | pytest, `-m live` | event order, cancel, retry class | latency spread |
| 6 | Answer engine (retrieval + tool + citations) | pytest | invented URLs, parity, refusals, query syntax | answer quality (eval) |
| 7 | Client playout (offline adapter) | vitest | stale audio after cancel, ACK, underruns | device output latency |
| 8 | Browser capture | Playwright, Chrome fake mic | rate, endian, frame size, consent | device quirks |
| 9a | Runner, in-process adapter, fake time | pytest (CI) | integration of turn-taking + runtime + answer, chaos reproducibility | Go/browser hops |
| 9b | Runner, WSS adapter, real time | harness (benchmarks only) | full-stack breaks, real latency | not deterministic |

Added after review 2, **signed off by the user**:

| # | Seam | Why |
|---|---|---|
| 10 | Budget guard (`voicecore/budget.py`) | money path; must refuse over-cap spend |
| 11 | Fixture set validation | proves provenance, splits, labels |
| 12 | Timeline metrics + merge | every reported number comes from here |
| 13 | Demo UI (Playwright on the demo page) | widget embed, mic-denied fallback, lab panel |

## D. Skills and when

| When | Skill |
|---|---|
| Every code slice | `tdd` |
| Before coding against any library/provider API | Context7 (`resolve-library-id` → `query-docs`); record version + date in the step register |
| End of Steps 01, 03, 05 | user runs `/improve-codebase-architecture` (HTML report in `$TMPDIR`) |
| Before each step handoff | `code-review`; user runs `/thermo-nuclear-code-quality-review` |
| Any live failure | `investigate` |
| UI (S06-T02, S08-T01) | `frontend-design` + `uizze`; screenshots with `browse` |
| Demo QA (Step 08) | `qa` (mocks only) |
| Before going public | `security-review` |

## E. Budget

**Pool `usd` (Deepgram + OpenRouter): $5.00 total, $0.525 already spent.**

| Step | Live use | Allowance |
|---|---|---|
| 00 | Aura speaks 40 docs questions (~2.4k chars) + 5 agent sentences | $0.10 |
| 03 | listen repro (10 sockets), STT/LLM contract smoke, 10 live turns, 1 baseline rerun | $0.55 |
| 04 | live text answer eval (holdout + adversarial) | $0.20 |
| 05 | 20 live barge-in scripts | $0.20 |
| 06 | 30 perf turns, quality eval (text), live load | $0.60 |
| 08 | demo smoke | $0.20 |
| Reserve | | $2.625 |

**Pool `cartesia_credits`: 20,000 owned, plan uses ≤ 16,000** (~1 credit per character; verify in Step 03).

| Step | Use | Credits |
|---|---|---|
| 03 | contract texts ≤ 40 chars (~10 runs = 400) + 10 turns × ~150 | 2,000 |
| 05 | 20 barge-in scripts (cut short) | 3,000 |
| 06 | 30 perf turns × ~150 + load (1 and 5 sessions × 1 turn) | 6,000 |
| 08 | demo smoke | 3,000 |
| Reserve | | 2,000 |

Credit savers: LLM `max_tokens=80` and a "answer in at most 2 sentences" instruction; the quality eval is text-only.

**How it is enforced (seam 10):**
- `voicecore/budget.py`: `reserve(pool, amount) -> Reservation` and `settle(reservation, actual)`. It keeps one total per pool in `benchmarks/spend_ledger.json` (entries gain a `pool` field; old entries default to `usd`). An `fcntl.flock` lock makes concurrent writers safe.
- `providers/factory.py::make_live(kind, reservation)`: **live adapters cannot be built without a Reservation.** So `server.py`, Playwright runs, `qa` and a public demo cannot spend outside the guard.
- Per-session caps: STT ≤ 120 s, TTS ≤ 1,500 characters. When a cap is hit, the session ends with `session.ended{reason:'budget'}`.
- The public demo runs on mocks unless the user approves a separate capped pool in Step 08.
- After each live run, read OpenRouter's real usage from `GET https://openrouter.ai/api/v1/key` and compare it with the ledger. Ask the user to also set a credit limit on the OpenRouter key.
- `harness/baseline_deepgram.py` uses the shared `usd` pool. Its own `budget_usd: 2.0` is removed.

---

## Step 0 — Setup (one time, ~5 h)

| # | Do | Check |
|---|---|---|
| 0.0 | Write the pasted keys to `.env` (mode 600, gitignored): `OPENROUTER_API_KEY`, `CARTESIA_API_KEY`. Never echo them. Make free calls only: OpenRouter `/api/v1/key` (usage + limit) and `/api/v1/models`, to pick the cheapest OpenAI non-reasoning model with streaming + tools (expected `openai/gpt-4.1-nano`). Record the id, price and date. Tell the user to rotate both keys when convenient. | `grep -c "_API_KEY=" .env` = 3; `git check-ignore .env` prints `.env` |
| 0.1 | `npx skills add https://uizze.sh/ -g -a claude-code -y`. List the new skills and read every new `SKILL.md` before use. If it needs a paid login, stop and tell the user. | contents read |
| 0.2 | Save this plan as `docs/IMPLEMENTATION_PLAN.md`; link it from `MASTER_AGENT_GUIDE.md` §4 and `README.md`. | links resolve |
| 0.3 | Fix stale links: `AGENTS.md` → `CLAUDE.md`. Mark MASTER guide §9 `archive/` as "removed from working tree 2026-10-29". | grep shows only intended mentions |
| 0.4 | Doc sync (owning docs first):<br>• master plan: architecture diagram, provider table (LLM via OpenRouter)<br>• steps 01–08: Expected-artifact paths<br>• S01-T03 acceptance becomes: bounded queue, drop/gap/depth counters, resume gaps, no reorder<br>• S07-T01 gains the jitter buffer<br>• register new tasks S01-T06, S01-T07, S03-T07<br>• note the in-step order change (S01: T02 protocol slices before T01 slice 5; S03: T07 before T05)<br>Mark nothing done. | `grep -rn "turn-detector\|services/telemetry\|apps/lab-ui\|services/knowledge" docs/ --exclude=IMPLEMENTATION_PLAN.md` → nothing |
| 0.5 | `GLOSSARY.md`: session, stream, frame, turn, utterance, endpoint, floor, generation, fence, barge-in, playout, underrun, interrupt-to-silence, trace span, scenario, fixture, holdout, mock provider, live provider, reservation, pool. | file exists |
| 0.6 | Workspaces:<br>• root `pyproject.toml` uv workspace with `services/agent-core` (Python 3.12; deps websockets, numpy, onnxruntime, fastembed, openai; dev pytest, pytest-asyncio, looptime, hypothesis) and `harness` (dev jiwer, matplotlib)<br>• `pnpm-workspace.yaml`<br>• `services/realtime-gateway/go.mod` (`go 1.25`, coder/websocket, goleak)<br>Verify looptime with Context7/PyPI. | `uv sync`, `pnpm install`, `go build ./...` succeed |
| 0.7 | Root `Makefile`: `test` (non-live, all languages), `test-live`, `e2e`, `bench`, `fixtures`. | `make test` runs |
| 0.8 | `.github/workflows/ci.yml`:<br>• `go`: `go test -race ./...` in `services/realtime-gateway`<br>• `python`: `uv run pytest -m "not live"` from the root<br>• `ts`: `pnpm -r test`<br>• `e2e`: Playwright with Chromium, 0 tests for now<br>Cache uv, pnpm and the fastembed model. | first run green |
| 0.9 | Budget (seam 10). RED: `test_budget.py`:<br>• "4.95 spent + reserve 0.10 usd → refused"<br>• "15,900 + reserve 200 credits → refused"<br>• "credit entries do not change the usd total"<br>• "old ledger entries without `pool` count as usd: total 0.525"<br>GREEN: `voicecore/budget.py` (moved from baseline). Then point the baseline at it; its `--self-test` still passes. | tests green |

---

## Step 00 — finish (~7 h)

### S00-T03 Fixtures (seam 11)

Build notes:
- **Licence first:** confirm the LibriSpeech CC BY 4.0 licence (openslr.org/12) and write `fixtures/audio/ATTRIBUTION.md`. Check Deepgram's terms for redistributing Aura output. If unclear, Aura-made files are built by script into gitignored `.cache/` and marked `redistributable: false` in the manifest.
- **Download:** the dev-clean and test-clean tarballs (~340 MB each, full download) go to `.cache/librispeech/`. Extract only the chosen files, then delete the tarballs.
- **Trim:** remove each utterance's own leading and trailing silence (first/last 20 ms window with peak ≥ 500, the same rule as `last_voiced` in the baseline). Store the trimmed bounds. Labels = added padding + trimmed bounds, so they are exact.
- **Noise:** seeded synthetic noise from ffmpeg `anoisesrc` (pink and brown) with `seed=42`. No external noise set.
- **Agent voice:** 5 Aura sentences, voice `aura-2-thalia-en`, stored as `agent_*.wav` (the playout reference track for echo and interrupt fixtures).
- **Different voices per split:** docs-question TTS uses a different Aura voice for dev and for holdout (verify the voice names), plus the user's own 10 recordings in holdout.

| # | RED test (`harness/tests/test_fixtures.py`) | GREEN |
|---|---|---|
| 1 | `test_manifest_files_exist_with_matching_sha256` | manifest schema + `harness/fixtures.py::load_manifest()` |
| 2 | `test_every_clip_is_mono_pcm16_16khz` | `harness/build_fixtures.py` (ffmpeg; fixed seeds) |
| 3 | `test_dev_and_holdout_share_no_speaker_voice_or_question` | dev = LibriSpeech dev-clean + Aura voice A; holdout = test-clean + Aura voice B + user recordings |
| 4 | `test_labels_match_trimmed_bounds_plus_padding` (literal check on one known clip: pad 1000 ms, so speech starts at 1000 ms) | trim + `[pad 1.0 s][utterance][pad 1.5 s]` |
| 5 | `test_every_category_exists_in_both_splits` | categories below |
| 6 | `test_echo_and_interrupt_clips_reference_an_agent_track` | manifest field `playout_ref` |
| 7 | `test_answer_key_cites_passages_that_exist_in_snapshot` | `fixtures/docs/uv/` (astral-sh/uv docs at a pinned tag, MIT/Apache-2.0) + `answer_key.json`: 40 questions (30 answerable with `must_cite` + `must_contain`, 10 unanswerable), dev 25 / holdout 15 |
| 8 | `test_every_docs_question_has_audio` | Aura TTS (budget-reserved); the user records 10 using `harness/record_questions.md` (`ffmpeg -f avfoundation -i ":0" -ac 1 -ar 16000 -sample_fmt s16 fixtures/audio/holdout/user_qNN.wav`) |

Categories:
- `silence`
- `single`
- `noisy_10db`, `noisy_5db`
- `slow_0_8x` (ffmpeg `atempo=0.8`)
- `mid_pause_600ms` (first part ≥ 1.5 s, then a 600 ms gap, then more speech; one turn)
- `interrupt` (agent clip + user speech at a labelled onset)
- `echo_only` (agent clip at −15 dB, 40 ms delay, no user)
- `docs_question`

Done when: all 8 tests pass, the user has listened to 5 random clips, and the clip set committed to git is under 25 MB.

### S00-T04 ADR

`docs/adr/0001-engine-ownership.md` with five `##` headings:
1. Owned code
2. Purchased inference (Deepgram STT, OpenAI model via OpenRouter, Cartesia TTS, Silero VAD model, fastembed model)
3. Baseline only (Deepgram Voice Agent)
4. Non-goals
5. Architecture decisions 2026-10-29

Done when: `grep -c "^## " docs/adr/0001-engine-ownership.md` = 5 and the user has read it.

**Step 00 gate:** registers, `EXECUTION_STATUS.md` handoff row, `code-review`, commit, push.

---

## Step 01 — Audio transport, SDK, playout (~36 h)

Order inside the step: S01-T02 slices 1–7 (protocol) → S01-T01 → S01-T02 slices 8+ → S01-T03 → S01-T04 → S01-T06 → S01-T07 → S01-T05.

### S01-T02 Protocol + Go transport (seams 1, 2)

Write `packages/protocol/SPEC.md` first. **Frame header:** big-endian, 28 bytes.

| Field | Type | Notes |
|---|---|---|
| `version` | u8 | = 1 |
| `kind` | u8 | 1 = mic_pcm16 at 16 kHz; 2 = agent_pcm16 at 24 kHz |
| `flags` | u16 | bit 0 = end_of_stream |
| `stream_id` | u32 | |
| `sequence` | u32 | |
| `capture_us` | u64 | |
| `generation_id` | u32 | 0 = none |
| `samples` | u16 | |
| `reserved` | u16 | |

Payload: PCM16 little-endian mono.

**Control events** (JSON text frames):
- client → server: `hello{version, token, mic:{rate,frame_ms}, playout:{rate}}`, `ping{t_client_us}`, `text.input`, `mic.revoked`, `client.paused`, `client.resumed_playout`, `playout.started{gen,t}`, `playout.stopped{gen,reason,t}`, `cancel.ack{gen,played_until_seq}`
- server → client: `welcome{session_id,resume_window_ms}`, `pong{t_client_us,t_server_us}`, `user.speech_started`, `transcript.partial`, `transcript.final`, `agent.generation_started{gen}`, `agent.cancel{gen}`, `answer.sources`, `session.ended{reason}`
- gateway → Python only: `client.resumed`

**Trace event:** `{trace_id, span, event, t_mono_us, process, generation_id?, attrs}`. It holds no transcript text unless `include_text`.

| # | RED test | GREEN |
|---|---|---|
| 1 | TS `frame.test.ts` "decodes every golden frame vector" | `vectors/frames.json` (8 vectors: max sequence, gen 0, end_of_stream, max capture_us) + `decodeFrame` |
| 2 | TS "encode(decode(bytes)) === bytes" | `encodeFrame` |
| 3 | TS "rejects short header, version 2, samples ≠ payload/2" | errors |
| 4 | Go `TestGoldenFrames` | `protocol/frame.go` |
| 5 | Py `test_golden_frames` | `voicecore/protocol.py` |
| 6 | TS/Go/Py "every golden event vector round-trips" | `vectors/events.json` + codecs |
| 7 | Go `TestFrameFuzzNeverPanics` (stdlib fuzz, 30 s in CI) | bounds checks |
| 8 | Go `TestHelloWithValidTokenGetsWelcome` (httptest; no fake time needed) | `POST /v1/session` gives an HMAC token (TTL 60 s, dev only); `hello` → `welcome` |
| 9 | `TestInvalidHeaderClosesWith1007`, `TestTruncatedFrameClosesWith1007` | close codes |
| 10 | `TestDuplicateSequenceDroppedAndCounted` | `drops_duplicate` |
| 11 | `TestOlderSequenceDroppedAsStale` | `drops_stale` |
| 12 | `TestForwardsMicFramesInOrderToUpstream` (upstream = `cmd/fakeorch`) | one upstream WS per session to `ws://127.0.0.1:8765/v1/session/{id}` |
| 13 | `TestMissedHeartbeatClosesAfter10s`, using `synctest.Test` + `internal/memnet` (no real sockets: they block fake time) | heartbeat |
| 14 | `TestCleanCloseReleasesSession` (goleak) | close path |

### S01-T01 Browser capture (seam 8)

| # | RED test | GREEN |
|---|---|---|
| 1 | vitest "48 kHz 1 kHz sine → 16 kHz keeps 1 kHz (2000 zero-crossings/s ± 1%)" | `resampleTo16k` |
| 2 | "4800 samples at 48 kHz → 1600; 4410 at 44.1 kHz → 1600" | same |
| 3 | `pcm.test.ts` "rule clamp(−1,1) then round(s<0 ? s·32768 : s·32767): 0.5 → bytes 00 40; 1.5 → FF 7F; −1.5 → 00 80" | `floatToPcm16LE` |
| 4 | `framer.test.ts` "330 samples → one 320-sample frame, 10 kept; sequence 0,1,2…" | `Framer` |
| 5 | Playwright `capture.spec.ts`: `context.grantPermissions(['microphone'])`; Chrome `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<fixture>.wav%noloop`; "test WS server gets 0 binary frames before `start()`, then frames of 20 ms at 16 kHz" | `capture-worklet.ts` + `client.ts` |

### S01-T03 Backpressure (seam 2, revised acceptance)

| # | RED test | GREEN |
|---|---|---|
| 1 | `TestFullUpstreamQueueDropsOldestAndCounts` (cap 50 frames = 1 s) | bounded queue, `drops_overload` |
| 2 | `TestQueueDepthAndCountersExposed` (`GET /debug/counters` JSON: depth, drops_*, gaps) | counters |
| 3 | `TestSequenceGapAfterResumeIsCounted` | `gaps` counter |

### S01-T04 Reconnect and lifecycle (seam 2, synctest + memnet)

| # | RED test | GREEN |
|---|---|---|
| 1 | `TestExpiredTokenClosesWith4001` | expiry |
| 2 | `TestResumeWithin10sKeepsSessionAndTellsUpstreamClientResumed` (Python cancels the live generation, so no repeated speech) | resume window |
| 3 | `TestResumeAfter10sStartsNewSession` | window end |
| 4 | `TestMicRevokedEndsMicStreamButKeepsSession` | `mic.revoked` |
| 5 | `TestAgentFramesAtOrBelowFenceAreNotSent` | outbound fence on `agent.cancel` |
| 6 | `TestNoGoroutinesLeftAfterStopExpireOrResume` (goleak, `-race`) | cleanup |

### S01-T06 Playout (new task, seam 7)

Tested through `offline-adapter.ts` with an injected `now()`.

| # | RED test | GREEN |
|---|---|---|
| 1 | "first rendered sample of gen 1 emits `playout.started{gen:1,t}`" | playout queue |
| 2 | "no frame for 100 ms during a generation → silence rendered, `underrun_ms` = 100" | time-based underrun |
| 3 | "after `cancel(1)` no sample of gen ≤ 1 is rendered; emits `playout.stopped{reason:'cancel'}` and `cancel.ack{gen:1,played_until_seq}`" | fence + flush |
| 4 | "gen 2 plays after cancel(1)" | fence blocks only ≤ fence |
| 5 | "`client.paused` stops rendering; resume continues from the next frame" | pause |

### S01-T07 Tracer bullet (new task)

`cmd/fakeorch` echoes mic audio back as gen 1. Playwright test: "fake-mic audio round-trips and the page emits `playout.started`". The CI `e2e` job runs it. Done when: green in CI.

### S01-T05 Transport benchmark

- `cmd/wsload` paces N streams at 20 ms. Go `BenchmarkDecodeFrame` (ns/op, allocs/op).
- Shaping uses macOS dummynet on loopback (user runs the `sudo dnctl`/`pfctl` commands written in `benchmarks/README.md`). Profiles: local; 50 ± 20 ms; 150 ± 50 ms + 1% loss (TCP turns loss into stalls).
- `benchmarks/transport.md`: inter-arrival p50/p95, gateway processing p50/p95, drops, with machine, Go version and the command beside every number.

**Step 01 gate:** `/improve-codebase-architecture`, `/thermo-nuclear-code-quality-review`, `code-review`, registers, push.

---

## Step 02 — Turn-taking (~30 h), `voicecore/turntaking/`

- Time = sample position (frame index × 20 ms).
- Floor and echo tests use `vad_fixture` (1.0 inside labelled speech, else 0.0), so they are frame-exact.
- Silero is only checked by the contract tests.

### S02-T01 VAD adapters (seam 3)

Silero ONNX takes 512 new samples + 64 context samples per call, with state `[2,1,128]` (verify on the repo README; record the model hash). The adapter buffers 20 ms frames into 512-sample windows. Each frame reports the latest window's probability.

| # | RED test | GREEN |
|---|---|---|
| 1 | both adapters: "silence clip: prob < 0.2 on ≥ 95% of frames" | `vad_silero.py` (onnxruntime, windowing above) |
| 2 | "single clip: prob > 0.5 on ≥ 80% of labelled speech frames" (dev only) | same |
| 3 | "reset() between sessions: same clip twice gives identical probs" | state reset |

### S02-T02 Floor module + policies (config, not modules)

Policies:
- **fixed:** end after `silence_ms` of silence.
- **adaptive:** `silence_ms` = 400 if speech so far < 1 s, 700 if 1–3 s, 1,000 if > 3 s.
- **asr_assisted:** end after 300 ms of silence when the latest final transcript ends with `.`, `?` or `!`, otherwise use adaptive.
- **all:** `min_speech_ms` = 60 (3 frames), `max_utterance_ms` = 15,000.

| # | RED test | GREEN |
|---|---|---|
| 1 | "speech_started after 3 voiced frames (60 ms), not 2" | hysteresis |
| 2 | fixed 700: "endpoint at labelled end + 700 ms" (exact with fixture VAD) | fixed |
| 3 | "mid_pause_600ms: fixed 400 ends the turn inside the pause, adaptive does not" | adaptive |
| 4 | "turn force-ends at 15 s with reason `max_length`" | cap |
| 5 | "final 'how do I install it?' + 300 ms silence → endpoint (asr_assisted), 400 ms earlier than adaptive" | asr_assisted |

### S02-T03 Echo control

| # | RED test | GREEN |
|---|---|---|
| 1 | "echo_only during playout → no speech_started" | while playout is active: threshold +0.2, min speech 200 ms, and mic energy must exceed the `playout_ref` energy (delayed 40 ms) by 6 dB |
| 2 | "interrupt during playout → barge_in within 200 ms of labelled onset" | same gate |

Manual (labelled `manual`): laptop speakers, Chrome `echoCancellation` on/off, 10 tries each, counts in `benchmarks/turntaking/echo.md`.

### S02-T04 Evaluator (seam 12, `harness/timeline.py`)

RED tests with literal values:
- "endpoint delays [100, 300, 200] → median 200"
- "endpoint 50 ms before labelled end = early cutoff"
- "labelled utterance with no endpoint = missed"

### S02-T05 Policy sweep + ADR

- The runner's in-process adapter feeds dev fixtures through each policy over a grid.
- `asr_assisted` uses a mock STT that emits the transcript at labelled end + 300 ms (labelled `simulated`).
- Plot `reports/turn_policy.png`, pick the default, run it once on holdout, and write `docs/adr/0002-turn-policy.md` with the numbers and failure cases.

---

## Step 03 — Providers + generation runtime (~42 h)

**Before coding:**
- `investigate` the Voice Agent `FAILED_TO_START_LISTENING`:
  - send the 3 failed request IDs to Deepgram support;
  - separately, check whether plain listen sockets also fail (10 back-to-back, ~$0.02). That only tests the STT adapter's risk; it does not explain the Voice Agent error.
- Verify with Context7 and record the model IDs and dates:
  - Deepgram listen;
  - OpenRouter chat completions (streaming + tools, `base_url=https://openrouter.ai/api/v1`, official `openai` SDK with `max_retries=0`);
  - Cartesia WebSocket TTS: the cancel semantics (only not-yet-started requests stop), credits per character, and the plan's concurrency limit (if 5 concurrent sessions are not allowed, live load = 1 and 2).
- Update ADR 0001 + the master plan provider table.

### S03-T01 Provider contracts (seam 5)

`base.py`:
- `STTStream`: send audio; async `Partial`/`Final`; close
- `LLM`: stream → `TextDelta`/`ToolCall`/`Done`
- `TTSStream`: text chunk + gen; async audio; cancel

`ProviderError(kind = retryable | fatal | rate_limited)`. `mock.py` runs a script (delays, tokens, errors, stalls) from config and is also the fault injector. `factory.py::make_live` requires a Reservation.

| # | RED test | Runs on | GREEN |
|---|---|---|---|
| 1 | STT "events come as Partial*, then Final; close() twice is fine" | mock + live | `mock.py`, `deepgram_stt.py` |
| 2 | STT "single clip's Final contains the manifest key words" | live only | same |
| 3 | "bad key → ProviderError(fatal)" | live | adapters |
| 4 | LLM "≥ 1 TextDelta then Done; max_tokens=80 respected" | mock + live | `openai_compat_llm.py` |
| 5 | "HTTP 429 → rate_limited (no SDK retries)" | mock only (scripted 429) | error mapping |
| 6 | TTS "two chunks give audio tagged with their generation_id" (texts ≤ 40 chars) | mock + live | `cartesia_tts.py` |
| 7 | TTS "after cancel(gen), the adapter yields no audio for that gen" | mock + live | adapter-side drop |
| 8 | "make_live without a Reservation raises" | — | factory |

### S03-T02 Session/turn state → generation runtime (seam 4)

| # | RED test | GREEN |
|---|---|---|
| 1 | "a late LLM token for a cancelled generation never reaches the outbound queue" | generation counter + stale check |
| 2 | "a late TTS frame for a cancelled generation is dropped" | same check on audio |
| 3 | "endpoint → gen 1 starts; `text.input` while THINKING cancels 1, starts 2" | transitions |
| 4 | hypothesis: "any random event sequence → at most one active generation; no outbound frame has gen < current" | invariant |
| 5 | "`client.resumed` cancels the live generation" | resume rule |

### S03-T03 Incremental STT and LLM (seam 4)

| # | RED test | GREEN |
|---|---|---|
| 1 | "interims 'what is', 'what is the', final 'what is the sample rate' → LLM prompt text 'what is the sample rate'" | transcript assembler |
| 2 | "LLM silent for 8 s (fake time) → reprompt 'Sorry, could you say that again?'" | stall timeout |
| 3 | "mic frames keep reaching STT while the LLM stalls" | separate tasks |

### S03-T04 Chunked TTS (seam 4)

| # | RED test | GREEN |
|---|---|---|
| 1 | "'First sentence. Second, longer clause here.' → 2 TTS chunks; never split inside 'https://x.y/z' or '[1]'" | chunker |
| 2 | "TTS results arriving 2,1,3 are sent 1,2,3" | outbound sequencer |
| 3 | "first agent frame logs trace span `tts.first_audio`" | `trace.py` |

### S03-T07 Wire-up + runner (new task; before T05)

- `server.py` (gateway hop); the runtime uses `turntaking` for endpoints.
- Runner WSS adapter: launches `bin/headless-client.ts` processes (real SDK + offline playout, real-time 20 ms pacing reused from the baseline), each writing JSONL.
- RED (seam 9a): "in-process run of `single` → endpoint, gen 1, mock audio out".
- 9b check: "WSS run through gateway + Python with mocks: the client log has `playout.started`; the timeline has every span".
- Playwright version in CI e2e.

### S03-T05 Concurrency (seam 9a)

"20 sessions, seed 7, random mock delays and errors: every turn reaches a terminal state, no asyncio task left, every queue ≤ its cap, finished within 30 s fake time."

### S03-T06 Latency breakdown (live)

- 10 live turns: money from the $0.55 allowance, 2,000 Cartesia credits.
- Spans: endpoint, STT final, LLM first token, TTS first audio, client `playout.started`.
- Offsets from `ping/pong` (labelled derived). The OpenRouter hop is noted.
- 1 Deepgram Voice Agent baseline rerun for the master plan's Step 03 comparison gate.
- Output: `reports/latency_breakdown.md`.

**Step 03 gate:** `/improve-codebase-architecture`, `/thermo-nuclear-code-quality-review`, `code-review`, registers, push.

---

## Step 04 — Grounded docs answer engine (~26 h, seam 6)

### S04-T01 Ingest

| # | RED test | GREEN |
|---|---|---|
| 1 | "ingest twice → identical passage IDs + hashes" | split Markdown by heading; canonical URL + `#fragment`; sha256 |
| 2 | "127.0.0.1, 10.0.0.0/8, 169.254.169.254, file:// refused" | SSRF guard + host allowlist |
| 3 | "'ignore previous instructions' passage stored as text, flagged `suspicious`" | flag |

### S04-T02 Retrieval

| # | RED test | GREEN |
|---|---|---|
| 0 | "sqlite3 has FTS5" | (environment check) |
| 1 | "query `uv lock` finds the lockfile passage at rank 1" | FTS5 BM25 |
| 2 | "query `uv.lock --frozen` does not raise and finds its passage" | quote each token for MATCH |
| 3 | "A: lexical 1, dense 3; B: lexical 2, dense 1; k=60 → order [B, A]" | `rrf()` |
| 4 | "paraphrase query finds its passage in the dense top 3" (real fastembed model, cached) | fastembed index |
| 5 | "dev questions: Recall@5 and MRR computed and logged" (offline, no LLM) | eval script → `reports/retrieval_dev.md` |

### S04-T03 Tool + answer schema

| # | RED test | GREEN |
|---|---|---|
| 1 | "citation ID not in the retrieved set → rejected" | validator |
| 2 | "answer contains no URL written by the LLM; URLs come only from passage IDs" | schema `{answerable, text, citations[]}` |
| 3 | "unanswerable → 'I couldn't find that in the docs.'" | refusal |

### S04-T04 Shared text + voice

"Same question as text and as voice (mock STT) → same citations; spoken text has no '[1]'." GREEN: one `answer()` + `speechify()`.

### S04-T05 Adversarial eval (live, text only, $0.20)

- Slice 0 builds `fixtures/docs/adversarial/`:
  - a stale page (older version);
  - two contradictory pages;
  - an injection page;
  - an unauthorized-source page (outside the allowlist);
  - 15 questions over them.
- Measure Recall@5, MRR, refusal accuracy and citation validity on holdout + adversarial. Output: `reports/docs_eval.md`.

---

## Step 05 — Barge-in and recovery (~26 h)

### S05-T01 Barge-in detector

RED (seams 3 + 9a): "interrupt fixture during playout → `barge_in`, runtime cancels gen, `agent.cancel` is sent." GREEN: floor `barge_in` → runtime cancel.

### S05-T02 Generation cancellation

| # | RED test | Seam | GREEN |
|---|---|---|---|
| 1 | "frames of the cancelled gen already in the Go send queue are dropped" | 2 | fence applied to the queue on `agent.cancel` |
| 2 | "client renders no stale samples and acks" (wire S01-T06 #3 to `agent.cancel`) | 7 | client handler |
| 3 | "late Cartesia audio after cancel never reaches the gateway" | 4 | runtime stale check (S03-T02 #2) + adapter drop |

### S05-T03 Recovery paths (seam 4 unless noted, one test each)

| Failure | Expected behaviour |
|---|---|
| STT gives no final 5 s after endpoint | reprompt |
| TTS disconnect | send the text answer + retry TTS once |
| 429 | backoff 1/2/4 s, then "I'm busy, try again in a moment" |
| `client.paused` > 30 s during a generation | cancel it |
| mic revoked | voice stops, text still works |
| network loss | resume via the gateway (seam 2, S01-T04 #2), no repeated speech |

### S05-T05 Chaos controls (seam 9a)

"Fault schedule `harness/scenarios/chaos/stall_and_429.json`, seed 42, in-process with fake time → identical trace twice." Faults come only from mock config. Network faults stay in the 9b/dummynet benchmarks.

### S05-T04 Interruption benchmark

- 20+ staged scripts: fake, plus live ($0.20, 3,000 credits).
- **Interrupt-to-silence** = labelled user onset → client `playout.stopped`.
- Also measure interrupt-to-listening and false barge-ins.
- Plus 5 manual acoustic loopback runs, labelled `manual`.
- Output: `reports/barge_in.md`.
- **Kill gate:** if cancel mid-TTS does not silence the client, stop and fix this before starting Step 06.

**Step 05 gate:** `/improve-codebase-architecture`, `/thermo-nuclear-code-quality-review`, `code-review`, registers, push.

---

## Step 06 — Observability, evals, load (~34 h)

| Task | What exactly | RED test / done when |
|---|---|---|
| T01 Trace + timeline (seam 12) | all processes emit the SPEC trace schema; `timeline.py` merges using ping offsets | "3 logs with a known 12 ms offset merge in the right order"; "no transcript text unless include_text" |
| T02 Lab panel (seam 13) | `apps/demo?lab=1`: stage bars, speaking lanes, drops, interrupted generations. `frontend-design`: write the token plan (4–6 colours, type, layout) and check it against the brief before coding; then `uizze` | Playwright: "fixture trace shows 5 stage bars and marks the interrupted gen" |
| T03 Scenario simulator | add noise, network faults (dummynet profiles), N parallel users to the runner | (seam 9a) "2 users, seed 7 → 2 complete session logs" |
| T04 Performance | `harness/bench.py`: speech end → `playout.started`, endpoint delay, p50/p95/p99, drops, cost per turn | fake n ≥ 200; live n = 30 |
| T05 Quality | WER (jiwer) on holdout audio; answer correctness vs key; refusal accuracy; citation validity; the user audits 20 answers by hand | `reports/quality_eval.md` (text-only LLM, no TTS credits) |
| T06 Load + CI gates | 1/5/20/40 sessions on mocks; live 1 and 5 (or 1 and 2 if Cartesia limits concurrency); `harness/thresholds.json`; `.github/workflows/evals.yml` runs the 9a scenarios and fails on regression | prove it once: a branch that adds 200 ms of mock latency fails CI |

---

## Step 07 — Media lab (hard timebox 35 h; at the box, stop and publish what exists)

| Task | Test-first slice |
|---|---|
| T01 RTP/RTCP + jitter buffer | "seq 65535 then 0 is in order"; "RFC 3550 jitter on a hand-worked 4-packet example = literal"; "reordered packets inside the window come out in order; too-late ones are dropped and counted" |
| T02 Pion spike | browser ↔ Go Pion peer; log ICE/SDP/DTLS steps; Opus RTP feeds the T01 jitter buffer (second adapter = real seam) |
| T03 WS vs WebRTC | same scenario through both, shaped by the same dummynet profiles on loopback (works for TCP and UDP); write down codec and DSP confounds |
| T04 Telephony review | `docs/telephony_extension.md`: SIP call flow + Twilio Media Streams adapter design; no SIP claim |
| T05 Write-up | `docs/media_internals.md` linking code, captures, numbers |

---

## Step 08 — Release (~18 h)

| Task | What exactly | Done when |
|---|---|---|
| T01 Widget (seam 13) | `apps/demo`: launcher pill + orb inspired by `docs/assets/*_reference.png` (no copied branding), voice + text, citations, mic-denied fallback; `frontend-design` + `uizze`; embed `<script src=".../voicecore.js" data-endpoint="…">` | Playwright on a plain HTML page: embed works; voice round-trip (mocks); mic denied → text works |
| T02 Deployment | `docker-compose.yml` (gateway, agent-core, demo), `.env.example`, README run steps; host chosen with the user. Hosting is **not** in the $5. Public demo on mocks unless the user approves a separate capped live pool | a clean clone runs with `docker compose up` + README only |
| T03 Portfolio | `docs/architecture.md`, `docs/portfolio_story.md`, 3 bug/tradeoff write-ups, benchmark chart, video script | every number labelled |
| T04 Requirements check | matrix rows (kept private) move Planned → Implemented/Measured only with evidence; 2 OSS PR ideas | no row claims more than its evidence |
| Go public | `security-review`, secret scan, Aura redistribution check, then the user makes the repo public | user decision |

---

## Verification (whole project)

- `make test` green locally and in CI on every push (all seams except 9b).
- `make test-live` only with keys. Every live run is in `benchmarks/spend_ledger.json`. The `usd` pool total is ≤ $5.00 (incl. $0.525 spent). Cartesia credits ≤ 16,000. OpenRouter `/key` usage matches the ledger.
- Every step gate updates the registers + `EXECUTION_STATUS.md` with commands and raw output paths.
- Master plan kill gates:
  - Step 01: deterministic capture and cleanup.
  - Step 03: compare against the baseline.
  - Step 05: cancel silences the client.
  - Step 06: reproducibility notes.
  - Step 07: timebox.

## Review log

### Review 1 (self, on v1)

Twelve gaps, all fixed in v2:
- no Go↔Python contract
- no setup/CI
- too vague
- no keys/budget
- late first end-to-end run
- echo needs hardware
- open `FAILED_TO_START_LISTENING`
- no docs corpus
- duplicate front ends
- Step 07 has no timebox
- unknown uizze contents
- broken links

### Architecture pass (improve-codebase-architecture method, independent agent)

Six candidates; the user adopted all:

| Change | Rating |
|---|---|
| Generation runtime + fencing | Strong |
| Turn-taking module | Strong |
| Go↔Python contract + client events | Strong |
| Client playout | Strong |
| One runner + one timeline | Strong |
| No WS reorder buffer | Worth exploring |

Contradictions with the master plan are handled by doc sync step 0.4.

### Review 2 (independent agent, on v2): 19 findings, all addressed in v3

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | Critical | renumbered task IDs | stable doc IDs restored; new tasks S01-T06/T07, S03-T07 registered in 0.4 |
| 2 | Critical | live spend outside the guard | `make_live` needs a Reservation; per-session caps; demo on mocks |
| 3 | High | synctest over real sockets | `internal/memnet` + `go 1.25` |
| 4 | High | Silero 512-sample windows | adapter windowing; floor tests use fixture VAD |
| 5 | High | inexact labels | trim at build; seeded synthetic noise; agent clip + `playout_ref` |
| 6 | High | tests at unagreed seams; 9 vs CI | seams 10–13 signed off by the user; seam 9 split into 9a (CI) / 9b (bench) |
| 7 | High | runner had no playout | `bin/headless-client.ts` with offline playout |
| 8 | High | used before built | runner/pacing in S03-T07; simulated STT for the S02-T05 sweep; CI e2e job in 0.8 |
| 9 | High | netem can't shape UDP | dummynet on loopback for both transports |
| 10 | Medium | Cartesia cancel, SDK retries, tautological STT test | contract = no audio for a cancelled gen; `max_retries=0`; 429 mock-only; key-word check live-only |
| 11 | Medium | Cartesia credits too tight | `max_tokens=80`, 2-sentence answers, ≤ 40-char contract texts, text-only quality eval, concurrency check |
| 12 | Medium | budget.py mixed pools, no tests, signatures | per-pool totals, flock, RED tests in 0.9, baseline uses the shared cap |
| 13 | Medium | FTS5 syntax error on `.`/`--` | quoting + RED test |
| 14 | Medium | ambiguous RRF example | explicit ranks → [B, A] |
| 15 | Medium | dropped cases | stale packets, gap/depth counters, client pause, offline Recall/MRR, adversarial doc fixtures |
| 16 | Medium | weak slices | adaptive defined, fixed 400 ms comparison; TCP-impossible playout tests cut; real fastembed for paraphrase; different TTS voices per split |
| 17 | Medium | looptime vs `time.monotonic` | one injected clock; seeded trace IDs |
| 18 | Medium | two uv projects | root uv workspace |
| 19 | Low | small fixes | PCM rounding rule + 44.1 kHz case; `capture_us` as string; Playwright mic permission + `%noloop`; grep excludes the plan; no stale "$25"; Voice Agent error goes to Deepgram support; full tarball download; Aura terms check |
