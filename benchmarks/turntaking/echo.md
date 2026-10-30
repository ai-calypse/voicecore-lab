# Echo and false-wake control (S02-T03)

## Fixture results (measured offline, 2026-10-30)

Echo fixtures play an agent clip back into the mic at −15 dB with a 40 ms delay; interrupt fixtures add a user at a labelled onset (both at −23 dBFS). Silero VAD v6.2.3 + `Floor` echo gate (`voicecore/turntaking/floor.py`), per-frame played power from the clip's `playout_ref`. Commands: `uv run pytest services/agent-core/tests/test_echo.py` and `uv run python harness/turn_sweep.py`.

| Clips | Result |
|---|---|
| echo only, dev 2 + holdout 2 | 0 speech starts, 0 barge-ins |
| interrupt, dev 3 | barge-in 180, 440, 160 ms after the labelled onset |
| interrupt, holdout 2 | barge-in 180, 200 ms |
| echo only, gate off (no playout info) | Silero marks the echo as speech: speech start on 2 of 2 dev clips |

The gate parameters (threshold +0.2, 160 ms minimum speech, mic ≥ played − 6 dB over 100 ms, 200 ms tail) are in `Policy` and in [ADR 0002](../../docs/adr/0002-turn-policy.md).

## Manual check (label `manual`) — not run yet

This needs a person, laptop speakers and the demo page (Step 08), so it is open. Procedure:

1. Open the demo with `?lab=1`, laptop speakers at 70 % volume, no headphones.
2. With Chrome `echoCancellation: true` (SDK default): ask 10 questions and stay silent while the agent answers; count spurious barge-ins. Then interrupt 10 answers mid-sentence; count misses and note the barge-in time from the lab panel.
3. Repeat with `echoCancellation: false` (`VoiceClient` capture constraint).
4. Record the 4 counts, device, browser version and room here.
