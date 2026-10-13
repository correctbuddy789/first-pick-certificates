"""Data-independent query policies and exact priority integration.

Only the Python standard library and certificates.py are required. Instances
use integer candidate indices and contain positive, negative, uncertain, pick,
blockers, quorum, and (for replay only) observed. The uncertain sequence retains
all initially unknown candidates, including queried nonanswers. Selection
functions never take unrevealed observations as an argument.

BooleanContext is an exponential truth-table oracle for small-instance checks;
MaskContext uses the exact fixed-panel relevance algorithm. Neither context
reads observed. A uniform priority is sampled independently of responses; the
exact distribution functions enumerate its relevant relative orders.
"""
from __future__ import annotations

import itertools
import math
import random
from collections import Counter
from fractions import Fraction
from functools import lru_cache

from certificates import (can_certify_with, classify, dnf_relevant_candidates,
                          relevant_candidates, truth_table)


class BooleanContext:
    """Exhaustive small-instance relevance oracle, without observed answers."""

    def __init__(self, instance):
        self.uncertain = tuple(instance["uncertain"])
        self.index = {c: i for i, c in enumerate(self.uncertain)}
        values = truth_table(instance["positive"], self.uncertain,
                             instance["pick"], instance["blockers"],
                             instance["quorum"])
        self.truth = sum(v << w for w, v in enumerate(values))
        self.all_worlds = (1 << len(values)) - 1
        self.yes = [sum(1 << w for w in range(len(values)) if w & (1 << i))
                    for i in range(len(self.uncertain))]

    def relevant(self, positive, negative, available):
        worlds = self.all_worlds
        for c, i in self.index.items():
            if c in positive:
                worlds &= self.yes[i]
            elif c in negative:
                worlds &= self.all_worlds ^ self.yes[i]
        result = set()
        for c in set(available) - positive - negative:
            i = self.index[c]
            high_ones = self.truth & worlds & self.yes[i]
            low_ones = (self.truth & worlds & (self.all_worlds ^ self.yes[i])) << (1 << i)
            if high_ones ^ low_ones:
                result.add(c)
        return result


class MaskContext:
    """Exact judge-mask relevance, caching repeated revealed-label states.

    Availability is intersected after computing relevance on the full unknown
    universe, so a nonanswer needs no recomputation and remains unresolved.
    The optional context cache grows with the number of distinct label states;
    the standalone relevance function has no persistent cache.
    """

    _oracle = staticmethod(relevant_candidates)

    def __init__(self, instance):
        self.uncertain = tuple(instance["uncertain"])
        self.pick = instance["pick"]
        self.blockers = tuple(frozenset(b) for b in instance["blockers"])
        self.quorum = instance["quorum"]
        self._cache = {}

    def relevant(self, positive, negative, available):
        state = frozenset(positive), frozenset(negative)
        if state not in self._cache:
            self._cache[state] = self._oracle(
                *state, self.uncertain, self.uncertain,
                self.pick, self.blockers, self.quorum)
        return self._cache[state] & frozenset(available)


class DNFContext(MaskContext):
    """The absorbed-quorum-DNF relevance comparator with the same cache."""

    _oracle = staticmethod(dnf_relevant_candidates)


def selectable(positive, negative, available, pick, blockers, quorum,
               method, context=None, costs=None):
    """Allowed next inputs, using fixed structure and revealed labels only.

    A caller first applies classify/can_certify_with and then chooses the
    earliest allowed candidate in an independently specified priority order.
    The relevant policies require a BooleanContext or MaskContext. Costs are
    additive, finite, nonnegative, and used only by cheapest_relevant (missing
    entries default to one); equal costs leave all tied candidates selectable.
    """
    available = set(available) - positive - negative
    if not available:
        return set()
    if method in ("pick_first_max_blockers", "pick_first_uniform_blockers",
                  "pick_first_uniform_relevant", "pick_first_uniform_all"):
        if pick in available:
            return {pick}
    if method in ("uniform_all", "pick_first_uniform_all"):
        return set(available)
    if method in ("uniform_relevant", "pick_first_uniform_relevant", "cheapest_relevant"):
        if context is None:
            raise ValueError("A relevance context must retain the full unknown universe")
        choices = set(context.relevant(positive, negative, available))
        if method != "cheapest_relevant" or not choices:
            return choices
        costs = costs or {}
        if any(not math.isfinite(v) or v < 0 for v in costs.values()):
            raise ValueError("query costs must be finite and nonnegative")
        cheapest = min(costs.get(c, 1) for c in choices)
        return {c for c in choices if costs.get(c, 1) == cheapest}
    open_judges = [b for b in blockers if not (b & positive)]
    scores = {c: sum(c in b for b in open_judges) for c in available}
    if method == "pick_first_uniform_blockers":
        return {c for c, v in scores.items() if v > 0}
    if method == "pick_first_max_blockers":
        top = max(scores.values())
        assert top > 0, "Non-pick irrelevant variables should never be needed"
        return {c for c, v in scores.items() if v == top}
    raise ValueError(method)


def replay_priority(instance, order, method, context=None):
    """Run one fixed priority, accessing an answer only after selection."""
    if context is None:
        context = MaskContext(instance)
    p, n = set(instance["positive"]), set(instance["negative"])
    available = set(instance["uncertain"])
    a, bs, h = instance["pick"], instance["blockers"], instance["quorum"]
    priority = {c: i for i, c in enumerate(order)}
    count = unanswered = 0
    while len(classify(p, n, a, bs, h)) > 1 and available:
        if not can_certify_with(p, n, available, a, bs, h):
            break
        choices = selectable(p, n, available, a, bs, h, method, context,
                             instance.get("costs"))
        assert choices
        # Unlisted variables are initially irrelevant and cannot become
        # relevant under conditioning. The pick is explicitly prioritized.
        assert choices <= set(priority) | {a}
        chosen = min(choices, key=lambda c: (priority.get(c, -1), c))
        available.remove(chosen)
        count += 1
        answer = instance["observed"].get(chosen)
        if answer == 1:
            p.add(chosen)
        elif answer == 0:
            n.add(chosen)
        else:
            unanswered += 1
    return count, unanswered, classify(p, n, a, bs, h)


def exact_priority_distribution(instance, method, context=None):
    """Exact attempt/nonanswer marginals over independent uniform priorities.

    Return (attempt_distribution, nonanswer_distribution, orders_enumerated).
    Probabilities are Fractions. This is factorial in the number of initially
    active candidates and is intended as a small-instance calculation.
    """
    if context is None:
        context = MaskContext(instance)
    p, n = instance["positive"], instance["negative"]
    a, bs, h = instance["pick"], instance["blockers"], instance["quorum"]
    if len(classify(p, n, a, bs, h)) == 1:
        return {0: Fraction(1)}, {0: Fraction(1)}, 1
    if method in ("uniform_all", "pick_first_uniform_all"):
        active = set(instance["uncertain"])
    elif method in ("pick_first_max_blockers", "pick_first_uniform_blockers"):
        open_judges = [b for b in bs if not (b & p)]
        active = set(instance["uncertain"]) & set().union(*open_judges)
    else:
        active = set(context.relevant(p, n, set(instance["uncertain"])))
    if method.startswith("pick_first_"):
        active.discard(a)
    final_p = p | {c for c, answer in instance["observed"].items() if answer == 1}
    final_n = n | {c for c, answer in instance["observed"].items() if answer == 0}
    expected_outcomes = classify(final_p, final_n, a, bs, h)
    query_counts, unknown_counts = Counter(), Counter()
    for order in itertools.permutations(sorted(active)):
        count, unanswered, outcomes = replay_priority(instance, order, method, context)
        assert outcomes == expected_outcomes
        query_counts[count] += 1
        unknown_counts[unanswered] += 1
    total = math.factorial(len(active))
    assert sum(query_counts.values()) == total
    return ({k: Fraction(v, total) for k, v in query_counts.items()},
            {k: Fraction(v, total) for k, v in unknown_counts.items()}, total)


def exact_pick_first_all(instance):
    """Uniform order of all remaining candidates, forcing the pick first."""
    u = instance["uncertain"]
    a, bs, h = instance["pick"], instance["blockers"], instance["quorum"]

    @lru_cache(None)
    def expected(asked):
        queried = {c for i, c in enumerate(u) if asked & (1 << i)}
        p = instance["positive"] | {c for c in queried if instance["observed"].get(c) == 1}
        n = instance["negative"] | {c for c in queried if instance["observed"].get(c) == 0}
        available = set(u) - queried
        if len(classify(p, n, a, bs, h)) == 1 or not available:
            return Fraction(0)
        if not can_certify_with(p, n, available, a, bs, h):
            return Fraction(0)
        choices = selectable(p, n, available, a, bs, h, "pick_first_uniform_all")
        return 1 + sum((expected(asked | (1 << u.index(c))) for c in choices),
                       Fraction(0)) / len(choices)
    return expected(0)


def convolve(left, right):
    out = Counter()
    for a, pa in left.items():
        for b, pb in right.items():
            out[a + b] += pa * pb
    return dict(out)


def describe_distribution(dist):
    assert sum(dist.values()) == 1
    mean = sum((k * prob for k, prob in dist.items()), Fraction(0))
    return {"mean": float(mean), "mean_exact": str(mean),
            "minimum": min(dist), "maximum": max(dist),
            "distribution": [{"queries": k, "probability": float(prob),
                              "probability_exact": str(prob)}
                             for k, prob in sorted(dist.items())]}


def verify_synthetic(seed=1729):
    """Check bitset relevance against direct edges of small truth tables.

Also verify that integrating out irrelevant permutation positions preserves
the exact cost distribution, including when historical queries had no answer.
These synthetic records never enter any empirical estimate.
"""
    rng = random.Random(seed)
    state_checks = permutation_checks = 0
    methods = ("pick_first_max_blockers", "pick_first_uniform_blockers",
               "pick_first_uniform_relevant", "uniform_relevant")
    for trial in range(1000):
        size, judges = rng.randint(2, 7), rng.randint(2, 6)
        pick, quorum = rng.randrange(size), judges // 2 + 1
        tiers = [[rng.randrange(4) for _ in range(size)] for _ in range(judges)]
        blockers = [frozenset(i for i in range(size) if row[i] < row[pick]) for row in tiers]
        labels = [rng.choice((-1, -1, 0, 1)) for _ in range(size)]
        p = {i for i, value in enumerate(labels) if value == 1}
        n = {i for i, value in enumerate(labels) if value == 0}
        u = tuple(sorted(set(range(size)) - p - n))
        instance = {"positive": p, "negative": n, "uncertain": u,
                    "pick": pick, "blockers": blockers, "quorum": quorum}
        context = BooleanContext(instance)
        values = truth_table(p, u, pick, blockers, quorum)
        for assignment in itertools.product((-1, 0, 1), repeat=len(u)):
            pp = p | {c for c, value in zip(u, assignment) if value == 1}
            nn = n | {c for c, value in zip(u, assignment) if value == 0}
            available = set(u) - pp - nn
            feasible = [w for w in range(len(values)) if all(
                value == -1 or ((w >> i) & 1) == value for i, value in enumerate(assignment))]
            expected = {c for i, c in enumerate(u) if c in available and any(
                values[w] != values[w ^ (1 << i)] for w in feasible)}
            assert context.relevant(pp, nn, available) == expected
            state_checks += 1
        # A separate fixed-seed generator avoids changing the relevance cases.
        if trial < 200 and len(u) <= 5:
            answer_rng = random.Random(seed + 1000 + trial)
            instance["observed"] = {c: answer_rng.randrange(2) for c in u
                                    if answer_rng.random() < 0.8}
            totals = {method: Counter() for method in (*methods, "pick_first_uniform_all")}
            for order in itertools.permutations(u):
                for method in totals:
                    count, _, _ = replay_priority(instance, order, method, context)
                    totals[method][count] += 1
                permutation_checks += 1
            denominator = math.factorial(len(u))
            for method in methods:
                expected = {k: Fraction(v, denominator) for k, v in totals[method].items()}
                computed, _, _ = exact_priority_distribution(instance, method, context)
                assert computed == expected
            expected_mean = sum(k * v for k, v in totals["pick_first_uniform_all"].items())
            assert exact_pick_first_all(instance) == Fraction(expected_mean, denominator)
    return {"seed": seed, "random_profiles": 1000,
            "partial_state_relevance_checks": state_checks,
            "full_priority_orders_checked": permutation_checks, "result": "PASS"}

