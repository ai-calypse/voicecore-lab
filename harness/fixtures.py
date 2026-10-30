"""Fixture manifest access (seam 11). Clip paths in the manifest are relative to fixtures/audio/."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "fixtures/audio/manifest.json"
SPEECH_CATEGORIES = ("single", "noisy_10db", "noisy_5db", "slow_0_8x", "mid_pause_600ms")  # one user turn, labelled end


def load_manifest(path=MANIFEST):
    return json.loads(Path(path).read_text())


def read_pcm(clip):
    """Int16 samples of a manifest clip."""
    import wave

    import numpy as np

    with wave.open(str(MANIFEST.parent / clip["file"])) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


def played_power(clip, clips):
    """Per-frame power of what the client played (the clip's playout_ref) and whether it was playing."""
    import numpy as np

    by_id = {c["id"]: c for c in clips}
    ref, off = read_pcm(by_id[clip["playout_ref"]["clip"]]), clip["playout_ref"]["offset_ms"]
    n = len(read_frames(clip))
    track = np.zeros(n * 320, np.int16)
    track[off * 16 : off * 16 + len(ref)] = ref[: n * 320 - off * 16]
    from voicecore.turntaking.floor import power as frame_power

    power = np.array([frame_power(x) for x in track.reshape(-1, 320)])
    playing = (np.arange(n) * 20 >= off) & (np.arange(n) * 20 < off + len(ref) // 16)
    return power, playing


def read_frames(clip, frame=320):
    """20 ms frames of a clip; a short last frame is zero-padded."""
    import numpy as np

    x = read_pcm(clip)
    x = np.concatenate([x, np.zeros(-len(x) % frame, np.int16)])
    return x.reshape(-1, frame)
