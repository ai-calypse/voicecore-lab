"""Every reported metric is defined once here (seam 12)."""
import math


def percentile(xs, p):
    """Nearest-rank percentile: the smallest value with at least p% of values at or below it."""
    s = sorted(xs)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]


def endpoint_scores(cases):
    """cases: (labelled turn end ms, endpoint times ms) per utterance.

    The first endpoint decides: before the labelled end it is an early cutoff, none is a miss,
    otherwise its distance to the labelled end is the endpoint delay.
    """
    delays, early, missed = [], 0, 0
    for end, endpoints in cases:
        if not endpoints:
            missed += 1
        elif endpoints[0] < end:
            early += 1
        else:
            delays.append(endpoints[0] - end)
    n = len(cases)
    return {"n": n, "delays_ms": delays, "early_cutoffs": early, "missed": missed,
            "early_cutoff_rate": early / n, "missed_rate": missed / n,
            "median_ms": percentile(delays, 50) if delays else None,
            "p95_ms": percentile(delays, 95) if delays else None}


def turn_breakdown(client, trace, turn_end_ms):
    """Latency of one voice turn, from a headless-client log and the orchestrator trace of the same session.

    total_ms (client clock): labelled end of the user's speech -> first agent sample rendered by the client.
    endpoint_delay_ms (client clock): speech end -> end of the mic frame on which the floor decided.
    stt_settle_ms, llm_first_token_ms, tts_first_audio_ms (orchestrator clock): endpoint -> transcript ready,
    LLM request -> first token, first token -> first TTS audio.
    residual_ms (derived): total minus the above: uplink + downlink transport and playout start.
    """
    t0 = next(e["t0_us"] for e in client if e["type"] == "mic.start")
    speech_end = t0 + turn_end_ms * 1000
    gen = next(e["gen"] for e in client if e["type"] == "agent.generation_started")
    started = next(e["t_us"] for e in client if e["type"] == "playout.started" and e.get("dir") == "out" and e["gen"] == gen)

    def at(span, event, g=None):
        return next(e for e in trace if e["span"] == span and e["event"] == event and (g is None or e.get("generation_id") == g))

    def last_before(span, event, t):  # the endpoint and transcript that led to this generation, not an earlier one
        return [e for e in trace if e["span"] == span and e["event"] == event and e["t_mono_us"] <= t][-1]

    req, ft, fa = at("llm", "request", gen), at("llm", "first_token", gen), at("tts", "first_audio", gen)
    ep, tt = last_before("turn", "endpoint", req["t_mono_us"]), last_before("stt", "turn_text", req["t_mono_us"])
    ms = lambda a, b: (b - a) / 1000  # noqa: E731
    b = {"endpoint_delay_ms": ms(speech_end, ep["attrs"]["capture_end_us"]), "stt_settle_ms": ms(ep["t_mono_us"], tt["t_mono_us"]),
         "llm_first_token_ms": ms(req["t_mono_us"], ft["t_mono_us"]), "tts_first_audio_ms": ms(ft["t_mono_us"], fa["t_mono_us"]),
         "total_ms": ms(speech_end, started)}
    b["residual_ms"] = b["total_ms"] - b["endpoint_delay_ms"] - ms(ep["t_mono_us"], fa["t_mono_us"])
    return b
