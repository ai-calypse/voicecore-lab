"""Server-side latency stages, defined once: the metrics and harness/timeline.py both pair trace events here.

Stages of generation g (all on the orchestrator clock, ms):
  stt_settle               turn/endpoint -> stt/turn_text of g's turn
  endpoint_to_request      turn/endpoint -> g's first llm/request
  llm_first_token          g's latest llm/request (the attempt that answered) -> llm/first_token
  tts_first_audio          llm/first_token -> tts/first_audio
  endpoint_to_first_audio  turn/endpoint -> tts/first_audio (the server's share of the user's wait)

Events pair by turn_id and generation, so a typed turn after a voice turn gets no endpoint stages. Traces from
before turn_id existed pair with the latest endpoint and transcript instead (turn_id None), the old rule.
"""
from typing import NamedTuple


class Pair(NamedTuple):
    stage: str
    ms: float
    gen: int
    start: dict  # the event the stage is measured from


class Stages:
    """Feed trace events in order, from one session or many; feed() returns the stages each event completes."""

    def __init__(self):
        self.endpoint: dict[tuple, dict] = {}  # (trace, turn) -> endpoint event
        self.turn_text: dict[tuple, dict] = {}  # (trace, turn) -> stt/turn_text event
        self.turn: dict[tuple, str | None] = {}  # (trace, gen) -> turn_id
        self.request: dict[tuple, dict] = {}  # (trace, gen) -> latest llm/request
        self.first_token: dict[tuple, dict] = {}  # (trace, gen) -> llm/first_token

    def __len__(self):
        return sum(map(len, (self.endpoint, self.turn_text, self.turn, self.request, self.first_token)))

    def feed(self, e: dict) -> list[Pair]:
        tr, g, attrs = e.get("trace_id"), e.get("generation_id"), e.get("attrs", {})
        kind, gk = (e["span"], e["event"]), (tr, g)

        def pair(stage, start):
            return Pair(stage, (e["t_mono_us"] - start["t_mono_us"]) / 1000, g, start)

        out = []
        if kind == ("turn", "endpoint"):
            self.endpoint[(tr, attrs.get("turn_id"))] = e
        elif kind == ("stt", "turn_text"):
            self.turn_text[(tr, attrs.get("turn_id"))] = e
        elif kind == ("llm", "request"):
            tk = (tr, attrs.get("turn_id"))
            if gk not in self.request and (ep := self.endpoint.get(tk)):  # the first attempt: the time until we asked
                out.append(pair("endpoint_to_request", ep))
                if tt := self.turn_text.get(tk):
                    out.append(Pair("stt_settle", (tt["t_mono_us"] - ep["t_mono_us"]) / 1000, g, ep))
            self.request[gk], self.turn[gk] = e, attrs.get("turn_id")
        elif kind == ("llm", "first_token") and gk in self.request and gk not in self.first_token:
            self.first_token[gk] = e
            out.append(pair("llm_first_token", self.request[gk]))
        elif kind == ("tts", "first_audio") and gk in self.request:
            if ft := self.first_token.get(gk):
                out.append(pair("tts_first_audio", ft))
            if ep := self.endpoint.get((tr, self.turn[gk])):
                out.append(pair("endpoint_to_first_audio", ep))
            self._drop(lambda k: k == gk)
        elif kind == ("runtime", "cancel"):
            self._drop(lambda k: k == gk)
        elif kind == ("session", "ended"):
            self._drop(lambda k: k[0] == tr, everything=True)
        return out

    def _drop(self, match, everything=False):
        for d in (self.request, self.first_token, self.turn, *((self.endpoint, self.turn_text) if everything else ())):
            for k in [k for k in d if match(k)]:
                del d[k]


def for_generation(trace: list[dict], gen: int) -> dict[str, Pair]:
    """The stages of one generation in one session's trace."""
    s = Stages()
    return {p.stage: p for e in trace for p in s.feed(e) if p.gen == gen}
