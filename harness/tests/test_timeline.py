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
