"""Seam 16: metrics are computed from trace events. Latency has one definition, in voicecore/stages.py."""
import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from voicecore import budget
from voicecore.metrics import MetricsSink, loop_lag_ms
from voicecore.stages import for_generation


def ev(span, event, t_us, gen=None, trace="s-1", **attrs):
    e = {"trace_id": trace, "span": span, "event": event, "t_mono_us": t_us, "attrs": attrs}
    if gen is not None:
        e["generation_id"] = gen
    return e


VOICE_TURN = [ev("turn", "endpoint", 1_000_000, turn_id="t1"), ev("stt", "turn_text", 1_001_000, turn_id="t1"),
              ev("llm", "request", 1_002_000, gen=1, turn_id="t1"), ev("llm", "first_token", 1_262_000, gen=1),
              ev("tts", "first_audio", 1_412_000, gen=1)]


@pytest.fixture
def m():
    reader = InMemoryMetricReader()
    sink = MetricsSink(MeterProvider(metric_readers=[reader]).get_meter("test"))
    sink.reader = reader
    return sink


def points(sink, name) -> dict:
    """{frozenset of attribute items: data point} for one metric."""
    for rm in sink.reader.get_metrics_data().resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if metric.name == name:
                    return {frozenset(p.attributes.items()): p for p in metric.data.data_points}
    return {}


def stages(sink) -> dict:
    return {dict(k)["stage"]: (p.count, p.sum) for k, p in points(sink, "voicecore_stage_ms").items()}


def feed(sink, events):
    for e in events:
        sink(e)


def test_stages_pair_endpoint_request_first_token_first_audio():
    got = {k: p.ms for k, p in for_generation(VOICE_TURN, 1).items()}
    assert got == {"stt_settle": 1.0, "endpoint_to_request": 2.0, "llm_first_token": 260.0, "tts_first_audio": 150.0,
                   "endpoint_to_first_audio": 412.0}


def test_stage_histogram_from_trace_events(m):
    feed(m, VOICE_TURN)
    s = stages(m)
    assert s["endpoint_to_first_audio"] == (1, 412.0) and s["llm_first_token"] == (1, 260.0)


def test_typed_turn_records_only_llm_and_tts_stages(m):
    feed(m, [ev("llm", "request", 0, gen=1, turn_id="t1"), ev("llm", "first_token", 300_000, gen=1),
             ev("tts", "first_audio", 450_000, gen=1)])
    assert stages(m) == {"llm_first_token": (1, 300.0), "tts_first_audio": (1, 150.0)}


def test_typed_turn_after_voice_turn_has_no_endpoint_stage(m):
    feed(m, [*VOICE_TURN, ev("llm", "request", 5_000_000, gen=2, turn_id="t2"), ev("llm", "first_token", 5_100_000, gen=2),
             ev("tts", "first_audio", 5_200_000, gen=2)])
    s = stages(m)
    assert s["endpoint_to_request"] == (1, 2.0) and s["endpoint_to_first_audio"] == (1, 412.0)  # t1 only


def test_first_token_measured_from_the_attempt_that_produced_it(m):
    feed(m, [ev("llm", "request", 1_000_000, gen=1, turn_id="t1"), ev("llm", "request", 3_000_000, gen=1, turn_id="t1"),
             ev("llm", "first_token", 3_250_000, gen=1)])
    assert stages(m) == {"llm_first_token": (1, 250.0)}


def test_cancelled_generation_records_nothing_after_the_cancel(m):
    feed(m, [ev("llm", "request", 0, gen=1, turn_id="t1"), ev("runtime", "cancel", 100_000, gen=1, reason="barge_in"),
             ev("llm", "first_token", 200_000, gen=1), ev("tts", "first_audio", 300_000, gen=1)])
    assert stages(m) == {}


def test_session_ended_drops_its_state(m):
    feed(m, [*VOICE_TURN[:3], ev("session", "ended", 2_000_000, reason="client")])
    assert len(m.stages) == 0


def test_provider_errors_counted_by_kind(m):
    feed(m, [ev("llm", "error", 0, gen=1, kind="rate_limited")] * 3)
    assert points(m, "voicecore_provider_errors")[frozenset({("provider", "llm"), ("kind", "rate_limited")})].value == 3


def test_provider_calls_counted(m):
    feed(m, [ev("llm", "request", t, gen=1, turn_id="t1") for t in range(4)] + [ev("llm", "error", 9, gen=1, kind="retryable"),
             ev("stt", "connect", 10), ev("tts", "request", 11, gen=1)])
    calls = {dict(k)["provider"]: p.value for k, p in points(m, "voicecore_provider_calls").items()}
    assert calls == {"llm": 4, "stt": 1, "tts": 1}


def test_sessions_and_turns_counted_by_outcome(m):
    feed(m, [ev("session", "ended", 0, reason="budget"), ev("turn", "result", 1, gen=1, turn_id="t1", kind="voice", result="answer")])
    assert points(m, "voicecore_sessions")[frozenset({("outcome", "budget")})].value == 1
    assert points(m, "voicecore_turns")[frozenset({("kind", "voice"), ("result", "answer")})].value == 1


def test_loop_lag_from_timestamps():
    assert loop_lag_ms(expected_s=10.000, actual_s=10.180) == pytest.approx(180.0)
    assert loop_lag_ms(expected_s=10.000, actual_s=9.999) == 0.0


def test_spend_gauge_reads_ledger(m):
    budget.settle(budget.reserve("usd", 2.0, "test"), 1.25)
    assert points(m, "voicecore_spend_usd")[frozenset({("pool", "usd")})].value == 1.25
