# Audio fixture attribution

The committed clips under `fixtures/audio/{dev,holdout,ref}/` are derived from **LibriSpeech ASR corpus** (Vassil Panayotov, Guoguo Chen, Daniel Povey, Sanjeev Khudanpur, "Librispeech: an ASR corpus based on public domain audio books", ICASSP 2015), distributed at <https://www.openslr.org/12> under **CC BY 4.0** (<https://creativecommons.org/licenses/by/4.0/>).

| Split | Source archive | SHA-256 of archive |
|---|---|---|
| dev, ref | `dev-clean.tar.gz` | `76f87d090650617fca0cac8f88b9416e0ebf80350acb97b343a85fa903728ab3` |
| holdout | `test-clean.tar.gz` | `39fde525e59672dc6d1551919b1478f724438a95aa55f874b576be21967e6c23` |

**Changes made** (by `harness/build_fixtures.py`, seed 42): decoded from FLAC to 16 kHz mono PCM16 WAV; trimmed to the first/last 20 ms window with peak ≥ 500; padded with silence; some clips time-stretched to 0.8× (ffmpeg `atempo`), mixed with synthetic pink/brown noise, joined with a 600 ms gap, or mixed with an attenuated, delayed copy of another LibriSpeech utterance to simulate loudspeaker echo. The exact source utterance IDs for every clip are in `manifest.json` (`source.utterances`).

`silence_*.wav` clips are synthetic white noise (seed 42) and contain no LibriSpeech audio.

Not committed (`fixtures/audio/local/`, gitignored): docs-question clips spoken by Deepgram Aura TTS (redistribution terms not confirmed) and the user's own recordings.
