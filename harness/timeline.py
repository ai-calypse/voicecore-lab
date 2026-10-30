"""Every reported metric is defined once here (seam 12)."""
import math


def percentile(xs, p):
    """Nearest-rank percentile: the smallest value with at least p% of values at or below it."""
    s = sorted(xs)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]


def endpoint_scores(cases):
    """cases: (labelled turn end ms, endpoint times ms) per utterance.

    The first endpoint decides: before the labelled end it is an early cutoff, none is a miss,
    otherwise its distance to the labelled end is the endpoint delay.
    """
    delays, early, missed = [], 0, 0
    for end, endpoints in cases:
        if not endpoints:
            missed += 1
        elif endpoints[0] < end:
            early += 1
        else:
            delays.append(endpoints[0] - end)
    n = len(cases)
    return {"n": n, "delays_ms": delays, "early_cutoffs": early, "missed": missed,
            "early_cutoff_rate": early / n, "missed_rate": missed / n,
            "median_ms": percentile(delays, 50) if delays else None,
            "p95_ms": percentile(delays, 95) if delays else None}
