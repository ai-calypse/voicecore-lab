"""Silero VAD v6.2.3 (MIT, snakers4/silero-vad) on onnxruntime.

The model takes 512 new samples plus 64 samples of context at 16 kHz and a [2, 1, 128] state.
Frames arrive as 20 ms (320 samples), so they are buffered into 512-sample windows; each frame
reports the probability of the newest complete window (0.0 before the first one).
"""
from pathlib import Path

import numpy as np
import onnxruntime as ort

MODEL = Path(__file__).with_name("silero_vad.onnx")  # sha256 1a153a22f450…8788e3
WINDOW, CONTEXT = 512, 64


class SileroVAD:
    _session = None  # one inference session per process; state is per instance

    def __init__(self):
        if SileroVAD._session is None:
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = opts.inter_op_num_threads = 1
            SileroVAD._session = ort.InferenceSession(str(MODEL), opts, providers=["CPUExecutionProvider"])
        self.reset()

    def reset(self):
        self._state = np.zeros((2, 1, 128), np.float32)
        self._context = np.zeros(CONTEXT, np.float32)
        self._pending = np.zeros(0, np.float32)
        self.prob = 0.0

    def frame(self, pcm: np.ndarray) -> float:
        self._pending = np.concatenate([self._pending, pcm.astype(np.float32) / 32768])
        while len(self._pending) >= WINDOW:
            chunk, self._pending = self._pending[:WINDOW], self._pending[WINDOW:]
            x = np.concatenate([self._context, chunk])[None]
            out, self._state = self._session.run(None, {"input": x, "state": self._state, "sr": np.array(16000, np.int64)})
            self._context = chunk[-CONTEXT:]
            self.prob = float(out[0, 0])
        return self.prob
