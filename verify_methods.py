#!/usr/bin/env python3
"""Data-free exhaustive and randomized verification of the certificate method.

Independent oracle: enumerate eligible sets, remove ineligible candidates from
each judge's complete weak order, recompute the highest remaining tier, and
count votes. It does not use blocker sets to derive its expected answers.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import time
from pathlib import Path
from fractions import Fraction

from certificates import (classify, minimum_certificate, can_certify_with,
                          replay, random_order_expectation)


def weak_orders(n):
    return [t for t in itertools.product(range(n), repeat=n)
            if set(t) == set(range(max(t) + 1))]


def oracle(eligible, tiers, pick, quorum):
    if pick not in eligible:
        return 0
    votes = sum(row[pick] == min(row[c] for c in eligible) for row in tiers)
    return int(votes >= quorum)


def outcomes(values, p, n):
    return frozenset(v for eligible, v in values if p <= eligible and not (n & eligible))


def brute_certificate(values, initial_p, initial_n, available_p, available_n, target, costs):
    available = sorted(available_p | available_n)
    candidates = []
    for mask in range(1 << len(available)):
        selected = {c for i, c in enumerate(available) if mask & (1 << i)}
        p, n = initial_p | (selected & available_p), initial_n | (selected & available_n)
        if outcomes(values, p, n) == {target}:
            candidates.append(selected)
    if not candidates:
        return None
    return min(sum(costs[c] for c in s) for s in candidates)


def all_values(tiers, pick, quorum):
    n = len(tiers[0])
    return [(frozenset(c for c in range(n) if mask & (1 << c)),
             oracle({c for c in range(n) if mask & (1 << c)}, tiers, pick, quorum))
            for mask in range(1 << n)]


def blockers_for(tiers, pick):
    return [frozenset(i for i, v in enumerate(row) if v < row[pick]) for row in tiers]


def exhaustive():
    counts = {"weak_orders": len(weak_orders(3)), "preference_profiles": 0,
              "partial_state_bounds": 0, "available_query_stopping_states": 0,
              "minimum_certificate_checks": 0}
    universe = set(range(3))
    for tiers in itertools.product(weak_orders(3), repeat=3):
        counts["preference_profiles"] += 1
        blockers, values = blockers_for(tiers, 0), all_values(tiers, 0, 2)
        for assignment in itertools.product((-1, 0, 1), repeat=3):
            p = {i for i, a in enumerate(assignment) if a == 1}
            n = {i for i, a in enumerate(assignment) if a == 0}
            u = sorted(universe - p - n)
            expected = outcomes(values, p, n)
            assert classify(p, n, 0, blockers, 2) == expected
            counts["partial_state_bounds"] += 1
            for mask in range(1 << len(u)):
                available = {u[i] for i in range(len(u)) if mask & (1 << i)}
                brute = any(len(outcomes(values, p | (set(e) & available),
                                         n | (available - set(e)))) == 1
                            for e, _ in values if p <= e and not (n & e))
                assert can_certify_with(p, n, available, 0, blockers, 2) == brute
                counts["available_query_stopping_states"] += 1
        for eligible, target in values:
            for costs in ({i: 1 for i in universe}, {i: i + 1 for i in universe}):
                cert = minimum_certificate(set(), set(), set(eligible), universe - set(eligible),
                                           0, blockers, 2, target, costs)
                optimum = brute_certificate(values, set(), set(), set(eligible),
                                            universe - set(eligible), target, costs)
                assert cert is not None
                assert sum(costs[c] for c in cert) == optimum
                counts["minimum_certificate_checks"] += 1
    return counts


def random_checks(seed=20261012, trials=1000):
    rng = random.Random(seed)
    counts = {"seed": seed, "profiles": trials, "partial_state_bounds": 0,
              "minimum_certificate_checks": 0, "policy_checks": 0}
    for _ in range(trials):
        nc, nj = rng.randint(2, 7), rng.randint(2, 7)
        universe = set(range(nc))
        tiers = [[rng.randrange(4) for _ in range(nc)] for _ in range(nj)]
        pick, quorum = rng.randrange(nc), nj // 2 + 1
        blockers, values = blockers_for(tiers, pick), all_values(tiers, pick, quorum)
        initial = [rng.choice((-1, -1, -1, 0, 1)) for _ in range(nc)]
        p = {i for i, a in enumerate(initial) if a == 1}
        n = {i for i, a in enumerate(initial) if a == 0}
        uncertain = sorted(universe - p - n)
        observed = {c: rng.randrange(2) for c in uncertain if rng.random() < .8}
        op = {c for c, v in observed.items() if v == 1}
        on = {c for c, v in observed.items() if v == 0}
        target = outcomes(values, p | op, n | on)
        assert classify(p | op, n | on, pick, blockers, quorum) == target
        counts["partial_state_bounds"] += 1
        costs = {i: rng.randint(1, 9) for i in universe}
        for outcome in (0, 1):
            cert = minimum_certificate(p, n, op, on, pick, blockers, quorum, outcome, costs)
            optimum = brute_certificate(values, p, n, op, on, outcome, costs)
            assert (cert is None) == (optimum is None)
            if cert is not None:
                assert sum(costs[c] for c in cert) == optimum
            counts["minimum_certificate_checks"] += 1
        for policy in ("pick_then_blockers", "candidate_order"):
            result = replay(p, n, uncertain, observed, pick, blockers, quorum, policy)
            assert frozenset(result["possible_outcomes"]) == target
            assert result["queries"] <= len(uncertain)
            assert len(result["query_indices"]) == len(set(result["query_indices"]))
            counts["policy_checks"] += 1
    return counts


def permutation_baseline_check():
    # The uniform-order recurrence is checked against every permutation.
    tiers = [[1, 0, 2, 3], [1, 0, 2, 3], [0, 2, 1, 3], [0, 2, 1, 3]]
    bs, n = blockers_for(tiers, 0), 4
    total = checks = 0
    for answers in itertools.product((None, 0, 1), repeat=n):
        obs = {i: v for i, v in enumerate(answers) if v is not None}
        costs = []
        for order in itertools.permutations(range(n)):
            p, neg, available, count = set(), set(), set(range(n)), 0
            for c in order:
                if len(classify(p, neg, 0, bs, 3)) == 1:
                    break
                if not can_certify_with(p, neg, available, 0, bs, 3):
                    break
                available.remove(c)
                count += 1
                if obs.get(c) == 1:
                    p.add(c)
                elif obs.get(c) == 0:
                    neg.add(c)
            costs.append(count)
            total += 1
        exact = random_order_expectation(set(), set(), tuple(range(n)), obs, 0, bs, 3)
        assert abs(exact - sum(costs) / len(costs)) < 1e-12
        checks += 1
    return {"historical_answer_patterns": checks, "permutations_checked": total}


def extended_parameter_checks(seed=20261013, trials=300):
    """All quorums, zero/fractional costs, and unavailable binary answers.

    This extends rather than changes the historical exhaustive/randomized
    sections. Expected outcomes and certificate costs still use explicit
    top-tier recomputation and exhaustive subsets of recorded binary labels.
    """
    rng = random.Random(seed)
    counts = {"seed": seed, "profiles": trials, "profile_quorum_pairs": 0,
              "panel_size_range": [1, 7], "candidate_count_range": [2, 7],
              "quorums": "every integer from one to panel size",
              "quorum_one_cases": 0, "quorum_all_judges_cases": 0,
              "cost_schemes": ["unit", "all_zero", "mixed_zero", "fractional_zero"],
              "partial_state_bounds": 0, "available_query_stopping_states": 0,
              "stopping_states_with_unavailable_unknowns": 0,
              "minimum_certificate_checks": 0,
              "zero_cost_nonempty_certificates": 0,
              "certificates_with_multiple_labels": 0,
              "blocker_only_negative_certificates": 0,
              "unavailable_certificate_cases": 0}
    for trial in range(trials):
        nc, nj = rng.randint(2, 7), rng.randint(1, 7)
        universe = set(range(nc))
        tiers = [[rng.randrange(4) for _ in range(nc)] for _ in range(nj)]
        pick = rng.randrange(nc)
        blockers = blockers_for(tiers, pick)
        initial = [rng.choice((-1, -1, -1, 0, 1)) for _ in range(nc)]
        p = {c for c, label in enumerate(initial) if label == 1}
        n = {c for c, label in enumerate(initial) if label == 0}
        unknown = sorted(universe - p - n)
        observed = {c: rng.randrange(2) for c in unknown if rng.random() < .7}
        op = {c for c, label in observed.items() if label == 1}
        on = {c for c, label in observed.items() if label == 0}
        cost_schemes = ({c: 1 for c in universe}, {c: 0 for c in universe},
                        {c: (c + trial) % nc for c in universe},
                        {c: Fraction(c % 4, 2) for c in universe})
        for quorum in range(1, nj + 1):
            counts["profile_quorum_pairs"] += 1
            counts["quorum_one_cases"] += quorum == 1
            counts["quorum_all_judges_cases"] += quorum == nj
            values = all_values(tiers, pick, quorum)
            for pp, nn in ((p, n), (p | op, n | on)):
                assert classify(pp, nn, pick, blockers, quorum) == outcomes(values, pp, nn)
                counts["partial_state_bounds"] += 1
            for mask in range(1 << len(unknown)):
                available = {c for i, c in enumerate(unknown) if mask & (1 << i)}
                groups = {}
                for eligible, verdict in values:
                    if p <= eligible and not (n & eligible):
                        groups.setdefault(frozenset(eligible & available), set()).add(verdict)
                expected = any(len(verdicts) == 1 for verdicts in groups.values())
                assert can_certify_with(p, n, available, pick, blockers, quorum) == expected
                counts["available_query_stopping_states"] += 1
                counts["stopping_states_with_unavailable_unknowns"] += len(available) < len(unknown)
            for costs in cost_schemes:
                for target in (0, 1):
                    cert = minimum_certificate(p, n, op, on, pick, blockers, quorum, target, costs)
                    optimum = brute_certificate(values, p, n, op, on, target, costs)
                    assert (cert is None) == (optimum is None)
                    if cert is None:
                        counts["unavailable_certificate_cases"] += 1
                    else:
                        assert cert <= op | on
                        assert outcomes(values, p | (cert & op), n | (cert & on)) == {target}
                        assert sum(costs[c] for c in cert) == optimum
                        counts["zero_cost_nonempty_certificates"] += bool(cert) and optimum == 0
                        counts["certificates_with_multiple_labels"] += len(cert) >= 2
                        counts["blocker_only_negative_certificates"] += target == 0 and bool(cert) and pick not in cert
                    counts["minimum_certificate_checks"] += 1
    assert counts["zero_cost_nonempty_certificates"] > 0
    assert counts["certificates_with_multiple_labels"] > 0
    assert counts["blocker_only_negative_certificates"] > 0
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("verification.json"))
    args = parser.parse_args()
    start = time.perf_counter()
    report = {"exhaustive": exhaustive(), "randomized": random_checks(),
              "random_order_baseline": permutation_baseline_check(),
              "extended_parameters": extended_parameter_checks()}
    report["totals"] = {
        name: sum(section.get(name, 0) for section in (
            report["exhaustive"], report["randomized"], report["extended_parameters"]))
        for name in ("partial_state_bounds", "available_query_stopping_states",
                     "minimum_certificate_checks", "policy_checks")}
    report["elapsed_seconds"] = round(time.perf_counter() - start, 3)
    report["result"] = "PASS"
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
