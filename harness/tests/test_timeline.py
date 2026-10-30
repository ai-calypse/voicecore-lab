from timeline import endpoint_scores, percentile


def test_endpoint_delays_100_300_200_give_median_200():
    s = endpoint_scores([(1000, [1100]), (1000, [1300]), (1000, [1200])])
    assert s["delays_ms"] == [100, 300, 200]
    assert s["median_ms"] == 200


def test_endpoint_50ms_before_labelled_end_is_an_early_cutoff():
    s = endpoint_scores([(1000, [950, 1700]), (1000, [1400])])
    assert s["early_cutoffs"] == 1
    assert s["early_cutoff_rate"] == 0.5
    assert s["delays_ms"] == [400]  # a cut turn has no delay


def test_labelled_utterance_with_no_endpoint_is_missed():
    s = endpoint_scores([(1000, []), (1000, [1500]), (2000, [])])
    assert (s["missed"], s["missed_rate"]) == (2, 2 / 3)


def test_nearest_rank_percentile():
    assert percentile([5, 1, 4, 2, 3], 50) == 3
    assert percentile([5, 1, 4, 2, 3], 95) == 5
    assert percentile([10], 99) == 10


def test_turn_breakdown_uses_the_client_clock_for_the_total_and_the_server_clock_for_stages():
    from timeline import turn_breakdown

    client = [{"type": "mic.start", "t0_us": 1_000_000},
              {"type": "agent.generation_started", "gen": 1, "dir": "in", "t_us": 9_000_000},
              {"type": "playout.started", "gen": 1, "dir": "out", "t_us": 10_200_000}]
    trace = [{"span": "turn", "event": "endpoint", "t_mono_us": 50_000_000, "attrs": {"capture_end_us": 8_900_000}},
             {"span": "stt", "event": "turn_text", "t_mono_us": 50_100_000, "attrs": {}},
             {"span": "llm", "event": "request", "generation_id": 1, "t_mono_us": 50_100_000, "attrs": {}},
             {"span": "llm", "event": "first_token", "generation_id": 1, "t_mono_us": 50_600_000, "attrs": {}},
             {"span": "tts", "event": "first_audio", "generation_id": 1, "t_mono_us": 50_900_000, "attrs": {}}]
    b = turn_breakdown(client, trace, turn_end_ms=7000)  # speech ends at 1.0 s + 7.0 s = 8.0 s client time
    assert b == {"endpoint_delay_ms": 900.0, "stt_settle_ms": 100.0, "llm_first_token_ms": 500.0,
                 "tts_first_audio_ms": 300.0, "total_ms": 2200.0, "residual_ms": 400.0}
