# Record 10 holdout questions (S00-T03)

Your voice makes the held-out set realistic. These files stay on your machine (`fixtures/audio/local/` is gitignored) unless you decide otherwise.

1. Quiet room, normal speaking voice, laptop mic is fine.
2. Run each command, wait about half a second, then read the question once. Recording stops by itself after 6 seconds; don't touch the keyboard (a keypress gets recorded and skews the end-of-speech label).
   (List mic devices with `ffmpeg -f avfoundation -list_devices true -i ""` if `:0` is not your mic.)
3. Afterwards run `uv run python harness/build_local_fixtures.py` to trim, pad and add them to the local manifest.

```bash
mkdir -p fixtures/audio/local/raw
# q03: How do I update uv to the latest version?
ffmpeg -f avfoundation -i ":0" -ac 1 -ar 16000 -sample_fmt s16 -t 6 fixtures/audio/local/raw/user_q03.wav
# q05: How do I remove a package from my dev dependencies?
ffmpeg -f avfoundation -i ":0" -ac 1 -ar 16000 -sample_fmt s16 -t 6 fixtures/audio/local/raw/user_q05.wav
# q08: How much does uv cost for enterprise teams?
ffmpeg -f avfoundation -i ":0" -ac 1 -ar 16000 -sample_fmt s16 -t 6 fixtures/audio/local/raw/user_q08.wav
# q10: How do I upgrade a locked package to a specific version?
ffmpeg -f avfoundation -i ":0" -ac 1 -ar 16000 -sample_fmt s16 -t 6 fixtures/audio/local/raw/user_q10.wav
# q13: How do I pin the Python version for my project?
ffmpeg -f avfoundation -i ":0" -ac 1 -ar 16000 -sample_fmt s16 -t 6 fixtures/audio/local/raw/user_q13.wav
# q18: How do I reinstall the Python versions that uv manages?
ffmpeg -f avfoundation -i ":0" -ac 1 -ar 16000 -sample_fmt s16 -t 6 fixtures/audio/local/raw/user_q18.wav
# q20: How do I upgrade all of my installed tools at once?
ffmpeg -f avfoundation -i ":0" -ac 1 -ar 16000 -sample_fmt s16 -t 6 fixtures/audio/local/raw/user_q20.wav
# q26: How do I create a virtual environment with uv?
ffmpeg -f avfoundation -i ":0" -ac 1 -ar 16000 -sample_fmt s16 -t 6 fixtures/audio/local/raw/user_q26.wav
# q28: How do I clear the uv cache?
ffmpeg -f avfoundation -i ":0" -ac 1 -ar 16000 -sample_fmt s16 -t 6 fixtures/audio/local/raw/user_q28.wav
# q33: Does uv collect telemetry, and can I turn it off?
ffmpeg -f avfoundation -i ":0" -ac 1 -ar 16000 -sample_fmt s16 -t 6 fixtures/audio/local/raw/user_q33.wav
```
