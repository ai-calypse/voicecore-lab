"""Build the committed audio fixture set (S00-T03) from LibriSpeech, deterministically.

    uv run python harness/build_fixtures.py

Inputs: .cache/librispeech/{dev-clean,test-clean}.tar.gz (openslr.org/12, CC BY 4.0).
dev clips come from dev-clean, holdout clips from test-clean, so the splits share no
speaker. Each split reserves its own speaker to play the "agent" for echo and interrupt
clips, so no audio is shared between dev and holdout.

Every LibriSpeech utterance is trimmed to its first/last 20 ms window with peak >= 500,
then padded with silence we add, so speech labels are exact by construction.
"""
import hashlib
import json
import random
import subprocess
import tarfile
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache/librispeech"
OUT = ROOT / "fixtures/audio"
RATE, WIN = 16000, 320  # 20 ms windows
PEAK = 500
PAD_START_MS, PAD_END_MS = 1000, 1500
SEED = 42

# clips per category: (dev, holdout)
PLAN = {"single": (4, 3), "noisy_10db": (2, 2), "noisy_5db": (2, 2), "slow_0_8x": (2, 1),
        "mid_pause_600ms": (2, 2), "interrupt": (3, 2), "echo_only": (2, 2), "silence": (1, 1)}
AGENT_CLIPS = 5
AGENT_OFFSET_MS, INTERRUPT_AFTER_MS, ECHO_DELAY_MS, ECHO_GAIN_DB = 500, 1200, 40, -15
LEVEL_DBFS = -23  # agent clips and interrupting users are set to this RMS so the echo sits 15 dB under the user


def ms(n_samples):
    return n_samples * 1000 // RATE


def samples(ms_):
    return ms_ * RATE // 1000


def read_transcripts(tar_path):
    utts = {}
    with tarfile.open(tar_path) as tar:
        for m in tar:
            if m.name.endswith(".trans.txt"):
                for line in tar.extractfile(m).read().decode().splitlines():
                    uid, text = line.split(" ", 1)
                    utts[uid] = text.lower()
    return utts


def extract(tar_path, uids, dest):
    want = {f"{u}.flac" for u in uids if not (dest / f"{u}.flac").exists()}
    if not want:
        return
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path) as tar:
        for m in tar:
            name = m.name.rsplit("/", 1)[-1]
            if name in want:
                (dest / name).write_bytes(tar.extractfile(m).read())


def decode(path, tempo=None):
    cmd = ["ffmpeg", "-v", "error", "-i", str(path)]
    if tempo:
        cmd += ["-filter:a", f"atempo={tempo}"]
    cmd += ["-f", "s16le", "-ac", "1", "-ar", str(RATE), "-"]
    return np.frombuffer(subprocess.run(cmd, check=True, capture_output=True).stdout, dtype=np.int16)


def trim(x):
    peaks = np.abs(x[: len(x) // WIN * WIN].astype(np.int32)).reshape(-1, WIN).max(axis=1)
    voiced = np.nonzero(peaks >= PEAK)[0]
    if not len(voiced):
        raise ValueError(f"no 20 ms window reaches peak {PEAK}: audio too quiet or empty")
    return x[voiced[0] * WIN:(voiced[-1] + 1) * WIN]


def noise(n, color, rng):
    white = rng.standard_normal(n)
    if color == "white":
        return white
    if color == "brown":
        x = np.cumsum(white)
        x -= np.linspace(x[0], x[-1], n)  # remove drift
        return x
    spectrum = np.fft.rfft(white)  # pink: 1/f power
    spectrum /= np.sqrt(np.maximum(np.arange(len(spectrum)), 1))
    return np.fft.irfft(spectrum, n)


def scale_to_rms(x, target_rms):
    return x * (target_rms / np.sqrt(np.mean(x ** 2)))


def rms(x):
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))


def level(x):
    return to_int16(scale_to_rms(x.astype(np.float64), 32768 * 10 ** (LEVEL_DBFS / 20)))


def pad(x):
    return np.concatenate([np.zeros(samples(PAD_START_MS), np.int16), x, np.zeros(samples(PAD_END_MS), np.int16)])


def to_int16(x):
    return np.clip(np.round(x), -32768, 32767).astype(np.int16)


def write(rel, pcm):
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pick(pool, rng, n=1, same_speaker=False):
    """Pop n utterance ids from the shuffled pool; same_speaker picks n from one speaker."""
    if not same_speaker:
        return [pool.pop() for _ in range(n)]
    by_spk = {}
    for u in pool:
        by_spk.setdefault(u.split("-")[0], []).append(u)
    spk = rng.choice(sorted(s for s, us in by_spk.items() if len(us) >= n))
    chosen = by_spk[spk][:n]
    for u in chosen:
        pool.remove(u)
    return chosen


def main():
    rng = random.Random(SEED)
    nprng = np.random.default_rng(SEED)
    src = {"dev": CACHE / "dev-clean.tar.gz", "holdout": CACHE / "test-clean.tar.gz"}
    dataset = {"dev": "LibriSpeech dev-clean", "holdout": "LibriSpeech test-clean"}
    text, pools = {}, {}
    for split, tar in src.items():
        utts = read_transcripts(tar)
        text.update(utts)
        pools[split] = sorted(u for u, t in utts.items() if 12 <= len(t.split()) <= 24)
        rng.shuffle(pools[split])

    clips, flac = [], lambda split, u: CACHE / "extracted" / split / f"{u}.flac"

    def source(split, uids):
        return {"dataset": dataset[split], "utterances": uids, "speaker": uids[0].split("-")[0], "license": "CC BY 4.0"}

    def add(split, category, n, pcm, labels, src_, **extra):
        rel = f"{split}/{category}_{n:02d}.wav"
        clips.append({"id": f"{split}_{category}_{n:02d}", "file": rel, "sha256": write(rel, pcm), "split": split,
                      "category": category, "duration_ms": ms(len(pcm)), "source": src_, "labels": labels, **extra})

    # Each split reserves one speaker as its agent voice (the mic-side copy of what the agent "plays").
    agents, agent_spk = {}, {}
    for split in ("dev", "holdout"):
        agent_spk[split] = sorted({u.split("-")[0] for u in pools[split]})[0]
        agent_pool = [u for u in pools[split] if u.split("-")[0] == agent_spk[split]]
        pools[split] = [u for u in pools[split] if u.split("-")[0] != agent_spk[split]]
        extract(src[split], agent_pool, CACHE / "extracted" / split)
        agents[split] = []
        for u in agent_pool:
            a = level(trim(decode(flac(split, u))))
            if ms(len(a)) >= 2500:
                agents[split].append((f"ref_agent_{split}_{len(agents[split]) + 1:02d}", a))
                add("ref", f"agent_{split}", len(agents[split]), a, {"speech": [[0, ms(len(a))]]}, source(split, [u]),
                    transcript=text[u])
            if len(agents[split]) == AGENT_CLIPS:
                break

    for split in ("dev", "holdout"):
        pool, split_agents = pools[split], agents[split]
        need = {c: PLAN[c][split == "holdout"] for c in PLAN}
        ids = {c: [pick(pool, rng, 2, same_speaker=True) if c == "mid_pause_600ms" else pick(pool, rng)
                   for _ in range(need[c])] for c in PLAN if c not in ("silence", "echo_only")}
        extract(src[split], [u for groups in ids.values() for g in groups for u in g], CACHE / "extracted" / split)
        for c, groups in ids.items():
            for n, uids in enumerate(groups, 1):
                if c == "slow_0_8x":
                    u = trim(decode(flac(split, uids[0]), tempo=0.8))
                else:
                    u = trim(decode(flac(split, uids[0])))
                if c == "mid_pause_600ms":
                    b = trim(decode(flac(split, uids[1])))
                    if ms(len(u)) < 1500:  # the first part must be long enough to be a real utterance
                        if ms(len(b)) < 1500:
                            raise ValueError(f"mid_pause pair {uids} has no part >= 1500 ms")
                        u, b, uids = b, u, uids[::-1]
                    x = pad(np.concatenate([u, np.zeros(samples(600), np.int16), b]))
                    a_end = PAD_START_MS + ms(len(u))
                    speech = [[PAD_START_MS, a_end], [a_end + 600, a_end + 600 + ms(len(b))]]
                    add(split, c, n, x, {"speech": speech, "turn_end_ms": speech[-1][1]}, source(split, uids),
                        transcript=f"{text[uids[0]]} {text[uids[1]]}")
                    continue
                if c == "interrupt":
                    u = level(u)
                    ref_id, agent = split_agents[n - 1]
                    onset = AGENT_OFFSET_MS + INTERRUPT_AFTER_MS
                    length = samples(max(AGENT_OFFSET_MS + ECHO_DELAY_MS + ms(len(agent)), onset + ms(len(u))) + PAD_END_MS)
                    mix = np.zeros(length)
                    e0 = samples(AGENT_OFFSET_MS + ECHO_DELAY_MS)
                    mix[e0:e0 + len(agent)] += agent * 10 ** (ECHO_GAIN_DB / 20)
                    mix[samples(onset):samples(onset) + len(u)] += u
                    speech = [[onset, onset + ms(len(u))]]
                    add(split, c, n, to_int16(mix), {"speech": speech, "turn_end_ms": speech[0][1], "user_onset_ms": onset},
                        source(split, uids), transcript=text[uids[0]],
                        playout_ref={"clip": ref_id, "offset_ms": AGENT_OFFSET_MS, "echo_delay_ms": ECHO_DELAY_MS,
                                     "echo_gain_db": ECHO_GAIN_DB})
                    continue
                x = pad(u)
                speech = [[PAD_START_MS, PAD_START_MS + ms(len(u))]]
                extra = {}
                if c.startswith("noisy_"):
                    snr, color = (10, "pink") if c == "noisy_10db" else (5, "brown")
                    nz = scale_to_rms(noise(len(x), color, nprng), rms(u) / 10 ** (snr / 20))
                    x = to_int16(x + nz)
                    extra = {"noise": {"color": color, "snr_db": snr, "seed": SEED}}
                add(split, c, n, x, {"speech": speech, "turn_end_ms": speech[0][1]}, source(split, uids),
                    transcript=text[uids[0]], **extra)
        for n in range(1, need["echo_only"] + 1):
            ref_id, agent = split_agents[need["interrupt"] + n - 1]  # agent clips not used by interrupt clips
            x = np.zeros(samples(AGENT_OFFSET_MS + ECHO_DELAY_MS + ms(len(agent)) + PAD_END_MS))
            e0 = samples(AGENT_OFFSET_MS + ECHO_DELAY_MS)
            x[e0:e0 + len(agent)] += agent * 10 ** (ECHO_GAIN_DB / 20)
            add(split, "echo_only", n, to_int16(x), {"speech": []}, {"dataset": "derived from ref clip", "license": "CC BY 4.0"},
                playout_ref={"clip": ref_id, "offset_ms": AGENT_OFFSET_MS,
                             "echo_delay_ms": ECHO_DELAY_MS, "echo_gain_db": ECHO_GAIN_DB})
        for n in range(1, need["silence"] + 1):
            x = to_int16(scale_to_rms(noise(samples(10000), "white", nprng), 30.0))  # about -60 dBFS floor
            add(split, "silence", n, x, {"speech": []}, {"dataset": "synthetic white noise floor", "seed": SEED, "license": "CC0"})

    manifest = {"version": 1, "sample_rate": RATE, "format": "wav mono pcm16le",
                "trim_rule": f"first/last {WIN}-sample window with peak >= {PEAK}",
                "padding_ms": [PAD_START_MS, PAD_END_MS], "seed": SEED, "level_dbfs": LEVEL_DBFS, "agent_speakers": agent_spk, "clips": clips}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{len(clips)} clips, {sum((OUT / c['file']).stat().st_size for c in clips) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
