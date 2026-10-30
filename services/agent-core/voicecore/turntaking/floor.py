"""Who holds the floor: speech start, endpoint and (with playout) barge-in, one 20 ms frame at a time.

Echo gate: while the agent is playing, a frame only counts as user speech if the VAD is more sure
(threshold + 0.2) and the mic's 100 ms average power is at least `echo_gate_db` relative to what the
client played over the same window plus 40 ms (the echo delay). With the default -6 dB this assumes
the speaker-to-mic echo is at least 6 dB quieter than the user; it is a calibration knob per device.

Time is the sample position: frame k covers [20k, 20k + 20) ms and its decisions are stamped at
20(k + 1) ms, the moment the frame has been heard. Policies are configuration, not classes.
"""
import math
from collections import deque
from dataclasses import dataclass

import numpy as np


def power(pcm: np.ndarray) -> float:
    """Mean power of PCM16 samples on a 0..1 scale (the echo gate compares these)."""
    return float(np.mean((pcm.astype(np.float64) / 32768) ** 2)) if len(pcm) else 0.0


@dataclass(frozen=True)
class Policy:
    kind: str = "fixed"  # fixed | adaptive | asr_assisted (default chosen in docs/adr/0002-turn-policy.md)
    silence_ms: int = 800  # fixed policy
    adaptive_ms: tuple[int, int, int] = (400, 700, 1000)  # silence after < 1 s, 1-3 s, > 3 s of speech
    threshold: float = 0.5
    min_speech_ms: int = 60
    max_utterance_ms: int = 15000
    asr_silence_ms: int = 300
    playout_threshold_boost: float = 0.2
    playout_min_speech_ms: int = 160
    echo_gate_db: float = -6.0
    echo_tail_ms: int = 200  # the gate stays on this long after playout stops (echo delay + room)

    def silence_for(self, speech_ms: int) -> int:
        if self.kind == "fixed":
            return self.silence_ms
        short, mid, long = self.adaptive_ms
        return short if speech_ms < 1000 else mid if speech_ms <= 3000 else long


@dataclass(frozen=True)
class Event:
    kind: str  # speech_started | barge_in | endpoint
    t_ms: int
    onset_ms: int = 0  # speech_started: first voiced frame; endpoint: start of the utterance
    reason: str = ""  # endpoint: silence | max_length | asr


class Floor:
    def __init__(self, policy: Policy = Policy(), frame_ms: int = 20):
        self.policy, self.frame_ms = policy, frame_ms
        self.reset()

    def reset(self):
        self.t = 0  # ms at the end of the last frame
        self.voiced_run = 0  # consecutive voiced ms
        self.onset = None  # utterance start while the user holds the floor
        self.silence_start = None  # start of the current silence inside an utterance
        self.final = ""  # latest final transcript of this utterance
        self.mic = deque(maxlen=5)  # last 100 ms of mic power
        self.ref = deque(maxlen=7)  # last 140 ms of played power (window + echo delay)
        self.gate_until = -1  # ms; echo gate active while t <= this

    def frame(self, prob: float, mic_power: float | None = None, ref_power: float | None = None) -> list[Event]:
        """One frame: VAD probability, and while the agent is playing the mic and played-audio powers."""
        p, start = self.policy, self.t
        self.t += self.frame_ms
        playing = ref_power is not None
        if mic_power is not None:
            self.mic.append(mic_power)
        if playing:
            self.gate_until = self.t + p.echo_tail_ms
        gated = self.t <= self.gate_until
        if gated:
            self.ref.append(ref_power or 0.0)
        else:
            self.ref.clear()
        if gated and self.onset is None:
            voiced = prob >= p.threshold + p.playout_threshold_boost and self._above_echo()
            min_speech = p.playout_min_speech_ms
        else:
            voiced, min_speech = prob >= p.threshold, p.min_speech_ms
        self.voiced_run = self.voiced_run + self.frame_ms if voiced else 0
        if self.onset is None:
            if self.voiced_run >= min_speech:
                self.onset = self.t - self.voiced_run
                self.silence_start, self.final = None, ""
                return [Event("barge_in" if gated else "speech_started", self.t, self.onset)]
            return []
        if voiced:
            self.silence_start = None
        elif self.silence_start is None:
            self.silence_start = start
        if self.t - self.onset >= p.max_utterance_ms:
            return self._end("max_length")
        if self.silence_start is not None:
            silence = self.t - self.silence_start
            if p.kind == "asr_assisted" and self._punctuated() and silence >= p.asr_silence_ms:
                return self._end("asr")
            if silence >= p.silence_for(self.silence_start - self.onset):
                return self._end("silence")
        return []

    def transcript_final(self, text: str) -> list[Event]:
        """A final transcript arrived; with asr_assisted it can end the turn at once."""
        if self.onset is None:
            return []
        self.final = text
        p = self.policy
        if p.kind == "asr_assisted" and self._punctuated() and self.silence_start is not None and self.t - self.silence_start >= p.asr_silence_ms:
            return self._end("asr")
        return []

    def _above_echo(self) -> bool:
        db = lambda x: 10 * math.log10(sum(x) / len(x) + 1e-12)  # noqa: E731
        return bool(self.mic) and db(self.mic) >= db(self.ref) + self.policy.echo_gate_db

    def _punctuated(self) -> bool:
        return self.final.rstrip()[-1:] in (".", "?", "!")

    def _end(self, reason: str) -> list[Event]:
        e = Event("endpoint", self.t, self.onset, reason)
        self.onset, self.silence_start, self.voiced_run, self.final = None, None, 0, ""
        return [e]
