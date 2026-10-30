"""Metrics computed from trace events, so latency has one definition (voicecore/stages.py). Names: docs/ops/slos.md."""
import asyncio

from opentelemetry.metrics import CallbackOptions, Meter, Observation
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View

from voicecore import budget
from voicecore.stages import Stages

STAGE_BUCKETS_MS = (50, 100, 200, 300, 500, 750, 1000, 1200, 1500, 2000, 3000, 5000, 10000)
LAG_BUCKETS_MS = (1, 5, 10, 25, 50, 100, 250, 500, 1000)
VIEWS = [View(instrument_name="voicecore_stage_ms", aggregation=ExplicitBucketHistogramAggregation(STAGE_BUCKETS_MS)),
         View(instrument_name="voicecore_event_loop_lag_ms", aggregation=ExplicitBucketHistogramAggregation(LAG_BUCKETS_MS))]
CALLS = {("llm", "request"), ("stt", "connect"), ("tts", "request")}  # the denominators of the provider error ratios


class MetricsSink:
    """A trace sink: every session's Tracer sends its events here, and this records the metrics they imply."""

    def __init__(self, meter: Meter):
        self.stages = Stages()
        self.stage_ms = meter.create_histogram("voicecore_stage_ms", description="server-side latency stage (voicecore/stages.py)")
        self.loop_lag = meter.create_histogram("voicecore_event_loop_lag_ms", description="asyncio event loop lag, sampled every 1 s")
        self.turns = meter.create_counter("voicecore_turns", description="finished turns by kind and result")
        self.sessions = meter.create_counter("voicecore_sessions", description="ended sessions by outcome")
        self.calls = meter.create_counter("voicecore_provider_calls", description="provider calls (LLM requests, STT streams, TTS generations)")
        self.errors = meter.create_counter("voicecore_provider_errors", description="provider errors by kind")
        meter.create_observable_gauge("voicecore_spend_usd", [self._spend], description="money spent or reserved, from the ledger")

    def __call__(self, e: dict):
        for p in self.stages.feed(e):
            self.stage_ms.record(p.ms, {"stage": p.stage})
        span, event, attrs = e["span"], e["event"], e.get("attrs", {})
        if (span, event) in CALLS:
            self.calls.add(1, {"provider": span})
        elif event == "error" and span in ("llm", "stt", "tts"):
            self.errors.add(1, {"provider": span, "kind": attrs.get("kind", "unknown")})
        elif (span, event) == ("turn", "result"):
            self.turns.add(1, {"kind": attrs.get("kind", "unknown"), "result": attrs.get("result", "unknown")})
        elif (span, event) == ("session", "ended"):
            self.sessions.add(1, {"outcome": attrs.get("reason", "unknown")})

    def _spend(self, _: CallbackOptions):
        yield Observation(budget.total("usd"), {"pool": "usd"})

    async def sample_loop_lag(self, every_s: float = 1.0):
        """Runs forever: how late the loop wakes a timer is how long every session waits behind other work."""
        loop = asyncio.get_running_loop()
        while True:
            expected = loop.time() + every_s
            await asyncio.sleep(every_s)
            self.loop_lag.record(loop_lag_ms(expected, loop.time()))


def loop_lag_ms(expected_s: float, actual_s: float) -> float:
    return max(0.0, (actual_s - expected_s) * 1000)


def serve_metrics(port: int, host: str = "0.0.0.0") -> MetricsSink:
    """Expose /metrics on its own port (never published in compose) and return the sink to feed."""
    from opentelemetry.exporter.prometheus import PrometheusMetricReader
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from prometheus_client import CollectorRegistry, start_http_server

    registry = CollectorRegistry()  # our own, not the module-global one
    reader = PrometheusMetricReader(registry=registry)
    provider = MeterProvider(resource=Resource.create({SERVICE_NAME: "agent-core"}), metric_readers=[reader], views=VIEWS)
    start_http_server(port, host, registry=registry)
    return MetricsSink(provider.get_meter("voicecore"))

