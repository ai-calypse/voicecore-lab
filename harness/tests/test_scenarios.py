"""S06-T03 (seam 9a): simulated users with noise and network delay, fake time."""
import random

from fixtures import load_manifest
from runner.chaos import normalized
from runner.inprocess import run_users
from test_chaos import fresh_loop


def complete(run) -> bool:
    gens = [e["gen"] for e in run["client"] if e["type"] == "agent.generation_started"]
    return bool(gens) and any(e["type"] == "playout.stopped" and e["gen"] == gens[-1] and e["reason"] == "done" for e in run["client"])


def test_two_users_seed_7_with_noise_and_delay_give_two_complete_and_repeatable_session_logs():
    rng = random.Random(7)
    clips = rng.sample([c for c in load_manifest()["clips"] if c["split"] == "dev" and c["category"] == "single"], 2)
    a = fresh_loop(run_users(clips, seed=7, net_ms=40, snr_db=15))
    b = fresh_loop(run_users(clips, seed=7, net_ms=40, snr_db=15))
    assert len(a) == 2 and all(complete(r) for r in a)
    assert [normalized(r) for r in a] == [normalized(r) for r in b]
