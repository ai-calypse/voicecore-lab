"""Label-driven VAD for frame-exact floor tests: 1.0 for frames that overlap labelled speech, else 0.0."""


class FixtureVAD:
    def __init__(self, speech_ms: list[list[int]], frame_ms: int = 20):
        self.speech, self.frame_ms = speech_ms, frame_ms
        self.reset()

    def reset(self):
        self._t = 0

    def frame(self, _pcm=None) -> float:
        t, self._t = self._t, self._t + self.frame_ms
        return 1.0 if any(a < t + self.frame_ms and t < b for a, b in self.speech) else 0.0
