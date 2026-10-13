#!/usr/bin/env python3
"""Independent formula/terminal checks and hand-derived scheduler fixtures.

python3 -S verify_dnf_baselines.py --out extension-checks.json
No private data or network use. Checks are finite evidence, not a theorem.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import random
from collections import Counter
from fractions import Fraction
from pathlib import Path

from benchmark_extensions import ALL_METHODS, replay_extension
from computational_study import METHODS, TierWorldOracle, replay
from dnf_baselines import (AllenRoundRobinCached, _PrivateStream,
                           cost_normalized_blocker_choices, dnf_value,
                           quorum_terms)

ROOT = Path(__file__).resolve().parent


def explicit_membership(tiers, eligible, pick, quorum):
    """Mechanical rule from full tiers, independently of blockers/formula."""
    if pick not in eligible:
        return 0
    votes = 0
    for row in tiers:
        best = min(row[c] for c in eligible)
        votes += row[pick] == best
    return int(votes >= quorum)


def formula_checks(counts):
    rng = random.Random(432021)
    for trial in range(24):
        size, judges = rng.randint(2, 5), rng.randint(2, 4)
        pick = rng.randrange(size)
        tiers = [[rng.randrange(3) for _ in range(size)] for _ in range(judges)]
        blockers = tuple(frozenset(c for c in range(size) if row[c] < row[pick])
                         for row in tiers)
        for quorum in range(1, judges + 1):
            for status in itertools.product((-1, 0, 1), repeat=size):
                p = {c for c, y in enumerate(status) if y == 1}
                n = {c for c, y in enumerate(status) if y == 0}
                u = tuple(c for c, y in enumerate(status) if y == -1)
                instance = {"positive": p, "negative": n, "uncertain": u,
                            "pick": pick, "blockers": blockers, "quorum": quorum}
                terms, raw = quorum_terms(instance), quorum_terms(instance, absorb=False)
                actual_values = set()
                for bits in itertools.product((0, 1), repeat=len(u)):
                    labels = dict(zip(u, bits))
                    eligible = p | {c for c, y in labels.items() if y}
                    actual = explicit_membership(tiers, eligible, pick, quorum)
                    encoded = {c: y if c == pick else 1 - y for c, y in labels.items()}
                    assert dnf_value(terms, encoded) == actual
                    assert dnf_value(raw, encoded) == actual
                    actual_values.add(actual)
                    counts["explicit_tier_world_comparisons"] += 1
                initial = dnf_value(terms, {})
                assert (initial is None) == (len(actual_values) == 2)
                if initial is not None:
                    assert actual_values == {initial}
                counts["partial_states_checked"] += 1


def instance_from_terms(terms, costs):
    variables = sorted(set().union(*map(set, terms)))
    return {"positive": frozenset({0}), "negative": frozenset(),
            "uncertain": tuple(variables), "pick": 0,
            "blockers": tuple(frozenset(t) for t in terms), "quorum": 1,
            "costs": costs}


def scheduler_checks(counts):
    # Next-cost balancing matters: Alg0 proposes 1 (cost 2) and Alg1
    # proposes 4 (cost 1). Equal spent ledgers must choose Alg1, not Alg0.
    profile = instance_from_terms(({1, 2}, {1, 3}, {4}), {1: 2, 2: 3, 3: 3, 4: 1})
    policy = AllenRoundRobinCached(profile)
    assert policy.choose({0}, set(), {1, 2, 3, 4}) == 4
    policy.observe(4, 1)  # Encoded zero; singleton term now false.
    assert policy.virtual_trace[0]["branch"] == 1
    assert policy.choose({0, 4}, set(), {1, 2, 3}) == 1
    policy.observe(1, 1)
    assert [s["branch"] for s in policy.virtual_trace] == [1, 0]
    counts["hand_derived_next_cost_scheduler_cases"] += 1

    # Shared variable 1 and then 2 are consumed by the second private
    # stream from the cache. Their full virtual costs remain in K1.
    profile = instance_from_terms(({1, 2}, {1, 3}), {1: 1, 2: 1, 3: 1})
    profile["observed"] = {1: 0, 2: 1, 3: 0}
    result = replay_extension(profile, "allen_round_robin_cached", 0)
    assert result["trace"] == [(1, 0), (2, 1), (3, 0)]
    assert result["queries"] == result["cost"] == 3
    assert result["virtual_queries"] == result["virtual_cost"] == 5
    assert result["cached_virtual_queries"] == 2
    assert [s["branch"] for s in result["virtual_trace"]] == [0, 1, 0, 1, 0]
    assert result["virtual_trace"][-1]["ledger_after"] == (3, 2)
    counts["hand_derived_cache_ledger_cases"] += 1

    # Section 5.2 deliberately differs from the earlier subsection: the
    # cheapest term's expensive second variable is retained after a zero.
    terms = (frozenset({1, 2}), frozenset({3, 4}))
    branch = _PrivateStream(terms, {1: 1, 2: 9, 3: 6, 4: 6}, 1)
    assert branch.next_test() == 1
    branch.observe(1, 0)
    assert branch.next_test() == 2
    branch.observe(2, 1)
    assert branch.next_test() == 3
    counts["all_variables_in_selected_term_cases"] += 1

    # Free and rational costs are valid library inputs (main study costs
    # are positive integers); tie resolution and ledgers remain exact.
    profile = instance_from_terms(({1, 2}, {1, 3}), {1: 0, 2: Fraction(1, 3), 3: Fraction(2, 3)})
    profile["observed"] = {1: 0, 2: 1, 3: 0}
    result = replay_extension(profile, "allen_round_robin_cached", 0)
    assert result["trace"][0] == (1, 0)
    assert result["cost"] == 1
    assert result["outcome"] == (1,)
    counts["free_fractional_cost_cases"] += 1

    # A cheap once-occurring blocker can outrank an expensive widely
    # occurring blocker; pick priority is held equal to the old heuristic.
    assert cost_normalized_blocker_choices({0}, set(), {1, 2}, 0,
           ({1, 2}, {1}, {1}), {1: 16, 2: 1}) == {2}
    assert cost_normalized_blocker_choices(set(), set(), {0, 1, 2}, 0,
           ({1, 2}, {1}, {1}), {0: 100, 1: 16, 2: 1}) == {0}
    assert cost_normalized_blocker_choices({0}, set(), {1, 2}, 0,
           ({1, 2}, {1}, {1}), {1: 0, 2: 0}) == {1}
    counts["hand_derived_cost_normalized_choices"] += 3

    for bad in (-1, float("inf"), float("nan")):
        try:
            AllenRoundRobinCached(instance_from_terms(({1},), {1: bad}))
        except ValueError:
            counts["invalid_cost_rejections"] += 1
        else:
            raise AssertionError("Invalid cost accepted")
    policy = AllenRoundRobinCached(instance_from_terms(({1},), {1: 1}))
    chosen = policy.choose({0}, set(), {1})
    try:
        policy.observe(chosen, None)
    except ValueError:
        counts["nonanswer_rejections"] += 1
    else:
        raise AssertionError("Nonanswer accepted by binary-only policy")


def trace_checks(counts):
    rng = random.Random(120261013)
    for trial in range(28):
        size, judges = rng.randint(2, 5), rng.randint(2, 4)
        pick = rng.randrange(size)
        tiers = [[rng.randrange(3) for _ in range(size)] for _ in range(judges)]
        blockers = tuple(frozenset(c for c in range(size) if row[c] < row[pick])
                         for row in tiers)
        # At least one initial unknown, with the pick sometimes known.
        states = [rng.choice((-1, -1, 0, 1)) for _ in range(size)]
        states[rng.randrange(size)] = -1
        p = frozenset(c for c, y in enumerate(states) if y == 1)
        n = frozenset(c for c, y in enumerate(states) if y == 0)
        u = tuple(c for c, y in enumerate(states) if y == -1)
        costs = {c: rng.choice((0, Fraction(1, 2), 1, 4, 16)) for c in range(size)}
        for quorum in range(1, judges + 1):
            structure = {"positive": p, "negative": n, "uncertain": u,
                         "pick": pick, "blockers": blockers, "quorum": quorum,
                         "costs": costs}
            oracle = TierWorldOracle(structure)
            def audit(positive, negative, available, verdict, possible, choices, method):
                expected, attainable, _ = oracle.state(frozenset(positive), frozenset(negative), frozenset(available))
                assert verdict == expected and possible == attainable
                if choices is not None:
                    assert choices <= available and len(expected) == 2
                counts["independent_terminal_states"] += 1
            for bits in itertools.product((0, 1), repeat=len(u)):
                observed = dict(zip(u, bits))
                instance = {**structure, "observed": observed}
                truth = explicit_membership(tiers, p | {c for c, y in observed.items() if y}, pick, quorum)
                for method in ALL_METHODS:
                    result = replay_extension(instance, method, trial, audit)
                    assert result["outcome"] == (truth,)
                    assert len(result["trace"]) == len({c for c, _ in result["trace"]})
                    assert result["cost"] == sum(costs[c] for c, _ in result["trace"])
                    if method in METHODS:
                        original = replay(instance, method, trial)
                        assert all(result[k] == original[k] for k in ("trace", "cost", "queries", "outcome"))
                        counts["original_replay_trace_matches"] += 1
                    for step in result["virtual_trace"]:
                        before, after = step["ledger_before"], step["ledger_after"]
                        c0, c1 = step["next_tests"]
                        expected_branch = 0 if before[0] + costs[c0] <= before[1] + costs[c1] else 1
                        assert step["branch"] == expected_branch
                        branch = step["branch"]
                        assert after[branch] - before[branch] == costs[step["candidate"]]
                        assert after[1 - branch] == before[1 - branch]
                        counts["virtual_ledger_steps"] += 1
                    counts["complete_policy_traces"] += 1


def verify():
    counts = Counter()
    formula_checks(counts)
    scheduler_checks(counts)
    trace_checks(counts)
    return {"passed": True,
            "scope": "Finite independent tier-world checks and hand-derived examples; no approximation theorem, human-data validation, or external peer review implied.",
            "checks": dict(counts),
            "sources": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                        for name in ("dnf_baselines.py", "benchmark_extensions.py", "verify_dnf_baselines.py")},
            "design_sha256": hashlib.sha256((ROOT / "extension-design.json").read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "extension-checks.json")
    args = parser.parse_args()
    result = verify()
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["checks"], indent=2))


if __name__ == "__main__":
    main()
