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


def test_turn_breakdown_ignores_an_earlier_endpoint_that_started_no_generation():
    from timeline import turn_breakdown

    client = [{"type": "mic.start", "t0_us": 0}, {"type": "agent.generation_started", "gen": 1, "t_us": 0},
              {"type": "playout.started", "gen": 1, "dir": "out", "t_us": 5_000_000}]
    early = {"span": "turn", "event": "endpoint", "t_mono_us": 1_000, "attrs": {"capture_end_us": 2_000_000}}
    trace = [early, {"span": "stt", "event": "turn_text", "t_mono_us": 1_100, "attrs": {}},
             {"span": "turn", "event": "endpoint", "t_mono_us": 3_000_000, "attrs": {"capture_end_us": 4_000_000}},
             {"span": "stt", "event": "turn_text", "t_mono_us": 3_000_500, "attrs": {}},
             {"span": "llm", "event": "request", "generation_id": 1, "t_mono_us": 3_000_500, "attrs": {}},
             {"span": "llm", "event": "first_token", "generation_id": 1, "t_mono_us": 3_400_000, "attrs": {}},
             {"span": "tts", "event": "first_audio", "generation_id": 1, "t_mono_us": 3_800_000, "attrs": {}}]
    b = turn_breakdown(client, trace, turn_end_ms=3200)
    assert (b["endpoint_delay_ms"], b["stt_settle_ms"], b["residual_ms"]) == (800.0, 0.5, 200.0)


def test_recall_at_k_and_mrr_on_a_hand_worked_example():
    from timeline import mrr, recall_at_k

    ranked = [["a", "x", "y"], ["x", "y", "b"], ["x", "y", "z"]]  # relevant: a, b, c
    relevant = [{"a"}, {"b"}, {"c"}]
    assert recall_at_k(ranked, relevant, 2) == 1 / 3
    assert recall_at_k(ranked, relevant, 3) == 2 / 3
    assert mrr(ranked, relevant) == (1 + 1 / 3 + 0) / 3


def test_three_logs_with_a_known_12ms_offset_merge_in_the_right_order():
    from timeline import merge, ntp_offset

    # browser clock = gateway clock - 12 ms; agent-core clock = gateway clock + 5 s
    pings = [(1_000_000, 1_012_400, 1_000_800), (3_000_000, 3_012_350, 3_000_700)]  # (client send, server, client recv)
    assert ntp_offset(pings) == 12_000  # gateway - browser, from the sample with the smallest round trip
    browser = [{"process": "browser", "span": "playout", "event": "started", "t_mono_us": 2_000_030}]
    gateway = [{"process": "gateway", "span": "gateway", "event": "frame_out", "t_mono_us": 2_012_010}]
    agent = [{"process": "agent-core", "span": "tts", "event": "first_audio", "t_mono_us": 5_002_012_000}]
    merged = merge({"browser": browser, "gateway": gateway, "agent-core": agent},
                   {"browser": 0, "gateway": -12_000, "agent-core": -5_000_012_000})
    assert [e["event"] for e in merged] == ["first_audio", "frame_out", "started"]
    assert [e["t_us"] for e in merged] == [2_000_000, 2_000_010, 2_000_030]


def test_merged_timeline_has_no_text_unless_include_text():
    from timeline import merge

    events = [{"process": "agent-core", "span": "stt", "event": "final", "t_mono_us": 1, "attrs": {"text": "secret question", "chars": 15}}]
    assert merge({"agent-core": events}, {"agent-core": 0})[0]["attrs"] == {"chars": 15}
    assert merge({"agent-core": events}, {"agent-core": 0}, include_text=True)[0]["attrs"]["text"] == "secret question"
