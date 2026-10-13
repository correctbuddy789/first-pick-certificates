#!/usr/bin/env python3
"""Public, data-free verification of exact relevance and query policies.

The legacy section reproduces the original 42,112 relevance checks and 1,542
priority orders. Added checks derive outcomes directly by restricting complete
orders to eligible candidates, never using blocker formulas for the oracle.
No private loaders, data, network services, or third-party packages are used.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import time
from collections import Counter
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

from certificates import (can_certify_with, dnf_relevant_candidates,
                          relevant_candidates)
from query_policies import (BooleanContext, DNFContext, MaskContext,
                            exact_priority_distribution, replay_priority,
                            selectable, verify_synthetic)


METHODS = ("uniform_all", "pick_first_uniform_all", "pick_first_max_blockers",
           "pick_first_uniform_blockers", "uniform_relevant",
           "pick_first_uniform_relevant", "cheapest_relevant")


def strict_tiers(blockers, size, pick=0):
    """Realize a blocker family by complete strict orders, independently."""
    universe = set(range(size))
    tiers = []
    for above in blockers:
        order = sorted(above) + [pick] + sorted(universe - above - {pick})
        ranks = [0] * size
        for rank, candidate in enumerate(order):
            ranks[candidate] = rank
        tiers.append(tuple(ranks))
    return tuple(tiers)


def world_values(tiers, pick, quorum):
    """Recompute each judge's highest eligible tier in every world."""
    size = len(tiers[0])
    values = []
    for mask in range(1 << size):
        eligible = {c for c in range(size) if mask & (1 << c)}
        if pick not in eligible:
            values.append(0)
            continue
        votes = sum(row[pick] == min(row[c] for c in eligible) for row in tiers)
        values.append(int(votes >= quorum))
    return tuple(values)


def oracle_relevance(values, positive, negative, unknown):
    p_mask = sum(1 << c for c in positive)
    n_mask = sum(1 << c for c in negative)
    feasible = [w for w in range(len(values)) if w & p_mask == p_mask and not (w & n_mask)]
    return {c for c in unknown if any(values[w] != values[w ^ (1 << c)]
                                      for w in feasible)}


def exhaustive_relevance():
    """Every three-candidate blocker profile, m=1..4, and every quorum."""
    universe = set(range(3))
    blocker_options = [frozenset(c for c in (1, 2) if mask & (1 << (c - 1)))
                       for mask in range(4)]
    cost_schemes = ({0: 1, 1: 1, 2: 1}, {0: 0, 1: 0, 2: 0},
                    {0: 0, 1: 2, 2: 1},
                    {0: Fraction(0), 1: Fraction(1, 2), 2: Fraction(3, 2)})
    counts = {"candidates": 3, "panel_sizes": [1, 2, 3, 4],
              "quorums": "every integer from one to panel size",
              "blocker_profiles": 0, "profile_quorum_pairs": 0,
              "partial_label_states": 0, "availability_states": 0,
              "states_with_unavailable_unknowns": 0,
              "mixed_available_unavailable_states": 0,
              "mask_relevance_checks": 0, "dnf_relevance_checks": 0,
              "boolean_context_checks": 0, "cached_context_checks": 0,
              "current_unknown_api_checks": 0, "cost_selection_checks": 0,
              "cost_schemes": ["unit", "all_zero", "mixed_zero", "fractional_zero"]}
    for judges in range(1, 5):
        for blockers in itertools.product(blocker_options, repeat=judges):
            counts["blocker_profiles"] += 1
            tiers = strict_tiers(blockers, 3)
            for quorum in range(1, judges + 1):
                counts["profile_quorum_pairs"] += 1
                instance = {"positive": set(), "negative": set(), "uncertain": (0, 1, 2),
                            "pick": 0, "blockers": blockers, "quorum": quorum}
                contexts = BooleanContext(instance), MaskContext(instance), DNFContext(instance)
                values = world_values(tiers, 0, quorum)
                for assignment in itertools.product((-1, 0, 1), repeat=3):
                    positive = {c for c, label in enumerate(assignment) if label == 1}
                    negative = {c for c, label in enumerate(assignment) if label == 0}
                    unknown = sorted(universe - positive - negative)
                    expected = oracle_relevance(values, positive, negative, unknown)
                    counts["partial_label_states"] += 1
                    for mask in range(1 << len(unknown)):
                        available = {c for i, c in enumerate(unknown) if mask & (1 << i)}
                        selected = expected & available
                        arguments = (positive, negative, available, universe, 0, blockers, quorum)
                        assert relevant_candidates(*arguments) == selected
                        assert dnf_relevant_candidates(*arguments) == selected
                        assert contexts[0].relevant(positive, negative, available) == selected
                        for context in contexts[1:]:
                            assert context.relevant(positive, negative, available) == selected
                            counts["cached_context_checks"] += 1
                        # Both original and current unknown universes are accepted.
                        for function in (relevant_candidates, dnf_relevant_candidates):
                            assert function(positive, negative, available, unknown,
                                            0, blockers, quorum) == selected
                            counts["current_unknown_api_checks"] += 1
                        for costs in cost_schemes:
                            cheapest = {c for c in selected if costs[c] == min(
                                (costs[d] for d in selected), default=0)}
                            assert selectable(positive, negative, available, 0, blockers,
                                              quorum, "cheapest_relevant", contexts[1], costs) == cheapest
                            counts["cost_selection_checks"] += 1
                        counts["availability_states"] += 1
                        counts["mask_relevance_checks"] += 1
                        counts["dnf_relevance_checks"] += 1
                        counts["boolean_context_checks"] += 1
                        counts["states_with_unavailable_unknowns"] += len(available) < len(unknown)
                        counts["mixed_available_unavailable_states"] += bool(available) and len(available) < len(unknown)
    assert counts["blocker_profiles"] == 340
    assert counts["profile_quorum_pairs"] == 1252
    assert counts["partial_label_states"] == 33804
    assert counts["availability_states"] == 80128
    return counts


def independent_step_oracle(tiers, pick, quorum, costs):
    """Return a cached policy-step oracle based only on explicit worlds."""
    size = len(tiers[0])
    values = world_values(tiers, pick, quorum)

    @lru_cache(None)
    def step(p_mask, n_mask, available_mask, method):
        feasible = [w for w in range(len(values))
                    if w & p_mask == p_mask and not (w & n_mask)]
        outcomes = frozenset(values[w] for w in feasible)
        if len(outcomes) == 1 or not available_mask:
            return frozenset(), outcomes
        groups = {}
        for world in feasible:
            groups.setdefault(world & available_mask, set()).add(values[world])
        if not any(len(outcomes_in_group) == 1 for outcomes_in_group in groups.values()):
            return frozenset(), outcomes
        available = {c for c in range(size) if available_mask & (1 << c)}
        if method.startswith("pick_first_") and pick in available:
            return frozenset({pick}), outcomes
        if method in ("uniform_all", "pick_first_uniform_all"):
            return frozenset(available), outcomes
        if method in ("uniform_relevant", "pick_first_uniform_relevant", "cheapest_relevant"):
            relevant = {c for c in available if any(values[w] != values[w ^ (1 << c)]
                                                   for w in feasible)}
            if method == "cheapest_relevant":
                minimum = min(costs[c] for c in relevant)
                relevant = {c for c in relevant if costs[c] == minimum}
            return frozenset(relevant), outcomes
        positive = {c for c in range(size) if p_mask & (1 << c)}
        open_judges = [row for row in tiers
                       if not any(row[c] < row[pick] for c in positive)]
        scores = {c: sum(row[c] < row[pick] for row in open_judges) for c in available}
        if method == "pick_first_uniform_blockers":
            return frozenset(c for c in available if scores[c] > 0), outcomes
        if method == "pick_first_max_blockers":
            maximum = max(scores.values())
            return frozenset(c for c in available if scores[c] == maximum), outcomes
        raise ValueError(method)
    return step


def oracle_replay(step, observed, order, method, size):
    p_mask = n_mask = attempted = unanswered = 0
    available_mask = (1 << size) - 1
    priority = {c: i for i, c in enumerate(order)}
    while True:
        choices, outcomes = step(p_mask, n_mask, available_mask, method)
        if not choices:
            return attempted, unanswered, outcomes
        chosen = min(choices, key=priority.__getitem__)
        available_mask ^= 1 << chosen
        attempted += 1
        answer = observed.get(chosen)
        if answer == 1:
            p_mask |= 1 << chosen
        elif answer == 0:
            n_mask |= 1 << chosen
        else:
            unanswered += 1


def independent_policy_checks():
    """Full responses/permutations on a nontrivial overlapping fixture."""
    blockers = (frozenset({1, 2}), frozenset({1, 3}), frozenset({2, 3}))
    tiers = strict_tiers(blockers, 4)
    costs = {0: 2, 1: 0, 2: 1, 3: 3}
    counts = {"fixture_candidates": 4, "fixture_judges": 3, "quorums": [1, 2, 3],
              "methods": list(METHODS), "costs_by_candidate": costs,
              "answer_patterns": 0, "complete_priority_orders": 0,
              "independent_replay_checks": 0, "relevance_contexts": ["mask", "dnf", "truth_table"],
              "exact_distribution_checks": 0}
    for quorum in range(1, 4):
        instance = {"positive": set(), "negative": set(), "uncertain": (0, 1, 2, 3),
                    "pick": 0, "blockers": blockers, "quorum": quorum, "costs": costs}
        contexts = MaskContext(instance), DNFContext(instance), BooleanContext(instance)
        step = independent_step_oracle(tiers, 0, quorum, costs)
        for answers in itertools.product((None, 0, 1), repeat=4):
            instance["observed"] = {c: answer for c, answer in enumerate(answers) if answer is not None}
            attempts = {method: Counter() for method in METHODS}
            nonanswers = {method: Counter() for method in METHODS}
            for order in itertools.permutations(range(4)):
                for method in METHODS:
                    expected = oracle_replay(step, instance["observed"], order, method, 4)
                    for context in contexts:
                        assert replay_priority(instance, order, method, context) == expected
                        counts["independent_replay_checks"] += 1
                    attempts[method][expected[0]] += 1
                    nonanswers[method][expected[1]] += 1
                counts["complete_priority_orders"] += 1
            for method in METHODS:
                expected_attempts = {k: Fraction(v, math.factorial(4)) for k, v in attempts[method].items()}
                expected_nonanswers = {k: Fraction(v, math.factorial(4)) for k, v in nonanswers[method].items()}
                actual_attempts, actual_nonanswers, _ = exact_priority_distribution(instance, method, contexts[0])
                assert actual_attempts == expected_attempts
                assert actual_nonanswers == expected_nonanswers
                counts["exact_distribution_checks"] += 1
            counts["answer_patterns"] += 1
    return counts


def nonanswer_regressions():
    blockers = (frozenset({1}), frozenset({2}))
    instance = {"positive": {0}, "negative": set(), "uncertain": (1, 2),
                "pick": 0, "blockers": blockers, "quorum": 1}
    contexts = MaskContext(instance), DNFContext(instance), BooleanContext(instance)
    # Candidate 2 was queried but stayed unknown: 1 is relevant via the
    # completion where 2 is eligible, although only 1 remains queryable.
    for context in contexts:
        assert context.relevant({0}, set(), {1, 2}) == {1, 2}
        assert context.relevant({0}, set(), {1}) == {1}
        assert context.relevant({0}, set(), set()) == set()
    assert can_certify_with({0}, set(), {1}, 0, blockers, 1)
    bypass = dict(instance, positive=set(), uncertain=(0, 1, 2), observed={1: 1, 2: 1})
    for context_type in (MaskContext, DNFContext, BooleanContext):
        assert replay_priority(bypass, (0, 1, 2), "pick_first_uniform_relevant",
                               context_type(bypass)) == (3, 1, frozenset({0}))
    assert not can_certify_with(set(), set(), {1, 2}, 0, (frozenset(),), 1)
    return {"unavailable_unknown_remains_relevant": "PASS",
            "nonanswer_pick_can_be_bypassed_by_blockers": "PASS",
            "indispensable_unavailable_pick_stops_uncertified": "PASS"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("policy-verification.json"))
    args = parser.parse_args()
    start = time.perf_counter()
    legacy = verify_synthetic()
    assert legacy["partial_state_relevance_checks"] == 42112
    assert legacy["full_priority_orders_checked"] == 1542
    report = {"legacy_relevance_and_orders": legacy,
              "all_quorum_relevance": exhaustive_relevance(),
              "independent_policy_checks": independent_policy_checks(),
              "nonanswer_regressions": nonanswer_regressions()}
    report["elapsed_seconds"] = round(time.perf_counter() - start, 3)
    report["result"] = "PASS"
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
