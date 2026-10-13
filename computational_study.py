#!/usr/bin/env python3
"""Fixed-design synthetic study; Python standard library and public modules only.

python3 -S computational_study.py --all
python3 -S computational_study.py --verify-only --checks-out /tmp/checks.json

No private-data loader is imported. Policy selection never receives a response
record. Exact online expectations use rational arithmetic and an independent,
one-shot response model, not hindsight optimization on a generated record.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import platform
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

from certificates import (can_certify_with, classify, dnf_relevant_candidates,
                          minimum_certificate, relevant_candidates)
from query_policies import BooleanContext, DNFContext, MaskContext, selectable


ROOT = Path(__file__).resolve().parent
METHODS = ("uniform_all", "pick_first_max_blockers", "pick_first_uniform_blockers",
           "uniform_relevant", "cheapest_relevant")
OPTIMUM = "optimal_expected_cost"
METRICS = ("cost", "certification_probability", "certified_cost_mass",
           "queries", "nonanswers", "nonanswer_cost")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stable_seed(seed, *parts):
    encoded = json.dumps([seed, *parts], separators=(",", ":"), sort_keys=True)
    return int.from_bytes(hashlib.sha256(encoded.encode()).digest()[:16], "big")


def environment():
    cpu = "unavailable"
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return {"python": sys.version.split()[0], "implementation": platform.python_implementation(),
            "platform": platform.platform(), "cpu": cpu,
            "timing_caveat": "Exploratory single-process wall-clock timings on one shared environment; no cross-machine performance claim."}


def source_hashes():
    return {name: sha256(ROOT / name) for name in
            ("computational_study.py", "certificates.py", "query_policies.py")}


def structure_only(instance):
    return {k: instance[k] for k in
            ("positive", "negative", "uncertain", "pick", "blockers", "quorum", "costs")}


def make_blockers(n, m, probability, overlap, rng):
    blockers = [set() for _ in range(m)]
    for c in range(1, n):
        common = rng.random() < probability
        for j in range(m):
            copied = rng.random() < overlap
            included = common if copied else rng.random() < probability
            if included:
                blockers[j].add(c)
    return tuple(frozenset(b) for b in blockers)


def quorum_value(name, m):
    return {"half": m // 2, "strict_majority": m // 2 + 1, "unanimity": m}[name]


def factorial_instances(design):
    spec, seed = design["main_factorial"], design["seed"]
    serial = 0
    for m, n, degree, overlap, rep in itertools.product(
            spec["judges"], spec["candidates"], spec["expected_blockers_per_judge"],
            spec["shared_incidence_probability"], range(spec["structural_replicates"])):
        key = (m, n, degree, overlap, rep)
        rng = random.Random(stable_seed(seed, "factorial_structure", key))
        blockers = make_blockers(n, m, degree / (n - 1), overlap, rng)
        latent = random.Random(stable_seed(seed, "factorial_labels_costs", key))
        eligible_u = [latent.random() for _ in range(n)]
        known_u = [latent.random() for _ in range(n)]
        nonanswer_u = [latent.random() for _ in range(n)]
        heterogeneous = {c: latent.choice(spec["heterogeneous_cost_values"]) for c in range(n)}
        for known, p, r, cost_mode, quorum_name in itertools.product(
                spec["initial_known_probability"], spec["competitor_eligible_probability"],
                spec["nonanswer_probability"], spec["cost_mode"], spec["quorum"]):
            truths = {c: int(eligible_u[c] < (spec["pick_eligible_probability"] if c == 0 else p))
                      for c in range(n)}
            positive = frozenset(c for c in range(n) if known_u[c] < known and truths[c])
            negative = frozenset(c for c in range(n) if known_u[c] < known and not truths[c])
            uncertain = tuple(c for c in range(n) if c not in positive | negative)
            observed = {c: None if nonanswer_u[c] < r else truths[c] for c in uncertain}
            costs = {c: 1 if cost_mode == "unit" else heterogeneous[c] for c in range(n)}
            meta = {"instance": f"f{serial:04d}", "phase": "factorial", "family": "random",
                    "judges": m, "candidates": n, "expected_blockers": degree, "overlap": overlap,
                    "known_probability": known, "eligibility_probability": p, "nonanswer_probability": r,
                    "cost_mode": cost_mode, "quorum_name": quorum_name,
                    "quorum": quorum_value(quorum_name, m), "structural_replicate": rep,
                    "group_width": "", "pick_true_eligible": truths[0]}
            serial += 1
            yield {"positive": positive, "negative": negative, "uncertain": uncertain,
                   "pick": 0, "blockers": blockers, "quorum": meta["quorum"], "observed": observed,
                   "costs": costs, "meta": meta}
    assert serial == spec["expected_instances"]


def constructed_instances(design):
    spec, seed = design["constructed_cases"], design["seed"]
    n, serial = spec["candidates"], 0
    for m, width, rep in itertools.product(spec["judges"], spec["blockers_per_disjoint_judge_group"],
                                         range(spec["structural_replicates"])):
        rng = random.Random(stable_seed(seed, "constructed_structure", m, width, rep))
        labels = list(range(1, n))
        rng.shuffle(labels)
        groups = [labels[j * width:(j + 1) * width] for j in range(m)]
        assert m * width < n
        blockers = tuple(frozenset(g) for g in groups)
        order = list(range(m))
        rng.shuffle(order)
        witness = [rng.choice(g) for g in groups]
        costs_drawn = {c: rng.choice((1, 4, 16)) for c in range(n)}
        irrelevant_truths = {c: rng.randrange(2) for c in labels[m * width:]}
        for quorum_name, cost_mode, family in itertools.product(spec["quorum"], spec["cost_mode"], spec["families"]):
            h = quorum_value(quorum_name, m)
            q = m - h + 1
            observed = {c: 0 for c in range(1, n)} | irrelevant_truths
            if family == "coverage_negative":
                for j in order[:q]:
                    observed[witness[j]] = 1
            elif family == "unresolved_nonanswer":
                for j in order[:q - 1]:
                    observed[witness[j]] = 1
                observed[witness[order[q - 1]]] = None
            elif family == "bypassable_nonanswer":
                observed[witness[order[0]]] = None
            else:
                assert family == "positive_multilabel"
            meta = {"instance": f"c{serial:04d}", "phase": "constructed", "family": family,
                    "judges": m, "candidates": n, "expected_blockers": "", "overlap": "",
                    "known_probability": "", "eligibility_probability": "", "nonanswer_probability": "",
                    "cost_mode": cost_mode, "quorum_name": quorum_name, "quorum": h,
                    "structural_replicate": rep, "group_width": width, "pick_true_eligible": 1}
            serial += 1
            yield {"positive": frozenset({0}), "negative": frozenset(), "uncertain": tuple(range(1, n)),
                   "pick": 0, "blockers": blockers, "quorum": h, "observed": observed,
                   "costs": {c: 1 if cost_mode == "unit" else costs_drawn[c] for c in range(n)}, "meta": meta}
    assert serial == spec["expected_instances"]


class GuardedResponses:
    """A record permits one access only after its query has been selected."""

    def __init__(self, responses):
        self._responses = responses
        self._permitted = None
        self._read = set()

    def permit(self, candidate):
        assert self._permitted is None and candidate not in self._read
        self._permitted = candidate

    def __getitem__(self, candidate):
        assert self._permitted == candidate and candidate not in self._read, "Unrevealed answer access"
        self._read.add(candidate)
        self._permitted = None
        return self._responses[candidate]


def replay(instance, method, seed, context=None, audit=None):
    public = structure_only(instance)
    context = context or MaskContext(public)
    p, n = set(public["positive"]), set(public["negative"])
    available = set(public["uncertain"])
    a, blockers, h = public["pick"], public["blockers"], public["quorum"]
    responses, rng = GuardedResponses(instance["observed"]), random.Random(seed)
    queries = cost = nonanswers = nonanswer_cost = 0
    trace = []
    while True:
        verdict = classify(p, n, a, blockers, h)
        possible = can_certify_with(p, n, available, a, blockers, h)
        if audit is not None:
            audit(p, n, available, verdict, possible, None, method)
        if len(verdict) == 1 or not available or not possible:
            break
        choices = selectable(p, n, available, a, blockers, h, method, context, public["costs"])
        assert choices and choices <= available
        if audit is not None:
            audit(p, n, available, verdict, possible, choices, method)
        chosen = rng.choice(sorted(choices))
        available.remove(chosen)
        responses.permit(chosen)
        answer = responses[chosen]
        queries += 1
        cost += public["costs"][chosen]
        trace.append((chosen, answer))
        if answer == 1:
            p.add(chosen)
        elif answer == 0:
            n.add(chosen)
        else:
            assert answer is None
            nonanswers += 1
            nonanswer_cost += public["costs"][chosen]
    assert queries == len(set(c for c, _ in trace))
    return {"queries": queries, "cost": cost, "nonanswers": nonanswers,
            "nonanswer_cost": nonanswer_cost, "outcome": tuple(sorted(verdict)), "trace": trace}


class TierWorldOracle:
    """Small independent oracle: explicit tiers, full worlds, and projections.

    Membership is evaluated by finding each judge's best eligible tier, not
    by calling classify, truth_table, relevance, or certificate routines.
    """

    def __init__(self, instance):
        self.initial_p = frozenset(instance["positive"])
        self.initial_n = frozenset(instance["negative"])
        self.u = tuple(instance["uncertain"])
        self.index = {c: i for i, c in enumerate(self.u)}
        self.pick, self.quorum = instance["pick"], instance["quorum"]
        universe = self.initial_p | self.initial_n | set(self.u)
        self.tiers = [{c: 0 if c in b else 1 if c == self.pick else 2 for c in universe}
                      for b in instance["blockers"]]
        values = []
        for w in range(1 << len(self.u)):
            eligible = self.initial_p | {c for i, c in enumerate(self.u) if w & (1 << i)}
            if self.pick not in eligible:
                values.append(0)
                continue
            support = sum(row[self.pick] == min(row[c] for c in eligible) for row in self.tiers)
            values.append(int(support >= self.quorum))
        self.values = tuple(values)

    def bitset(self, labels):
        return sum(1 << self.index[c] for c in labels if c in self.index)

    @lru_cache(None)
    def worlds(self, pbits, nbits):
        return tuple(w for w in range(len(self.values)) if w & pbits == pbits and not w & nbits)

    @lru_cache(None)
    def state_bits(self, pbits, nbits, available_bits):
        worlds = self.worlds(pbits, nbits)
        outcomes = frozenset(self.values[w] for w in worlds)
        groups = defaultdict(set)
        for w in worlds:
            groups[w & available_bits].add(self.values[w])
        possible = any(len(v) == 1 for v in groups.values())
        relevant = set()
        for c, i in self.index.items():
            bit = 1 << i
            if available_bits & bit and any(not w & bit and self.values[w] != self.values[w | bit] for w in worlds):
                relevant.add(c)
        return outcomes, possible, frozenset(relevant)

    def state(self, positive, negative, available):
        return self.state_bits(self.bitset(positive), self.bitset(negative), self.bitset(available))

    def best_certificate(self, observed, target, costs):
        usable = sorted(c for c, response in observed.items() if response is not None)
        best = None
        for bits in range(1 << len(usable)):
            used = frozenset(c for i, c in enumerate(usable) if bits & (1 << i))
            key = (sum(costs[c] for c in used), len(used), tuple(sorted(used)))
            if best is not None and key >= best[0]:
                continue
            p = self.initial_p | {c for c in used if observed[c] == 1}
            n = self.initial_n | {c for c in used if observed[c] == 0}
            if self.state(p, n, frozenset())[0] == {target}:
                best = key, used
        return None if best is None else best[1]


def oracle_choices(oracle, p, n, available, method, costs):
    if method.startswith("pick_first_") and oracle.pick in available:
        return {oracle.pick}
    if method == "uniform_all":
        return set(available)
    if method in ("uniform_relevant", "cheapest_relevant"):
        choices = set(oracle.state(p, n, available)[2])
        if method == "cheapest_relevant" and choices:
            best = min(costs[c] for c in choices)
            choices = {c for c in choices if costs[c] == best}
        return choices
    active_rows = [row for row in oracle.tiers if not any(row[c] < row[oracle.pick] for c in p)]
    degrees = {c: sum(row[c] < row[oracle.pick] for row in active_rows) for c in available}
    if method == "pick_first_uniform_blockers":
        return {c for c, degree in degrees.items() if degree > 0}
    assert method == "pick_first_max_blockers"
    top = max(degrees.values())
    return {c for c, degree in degrees.items() if degree == top}


def independent_checks(design):
    start, counts = time.perf_counter(), Counter()
    for m, profile in itertools.product((2, 3, 4), range(4)):
        n = 5
        rng = random.Random(stable_seed(design["seed"], "verification", m, profile))
        blockers = make_blockers(n, m, (0.25, 0.6)[profile % 2], (0.0, 0.75)[profile // 2], rng)
        p0 = frozenset({0}) if profile == 2 else frozenset()
        n0 = frozenset({n - 1}) if profile == 3 else frozenset()
        uncertain = tuple(c for c in range(n) if c not in p0 | n0)
        costs = {c: (0, 1, 4, 16)[(c + profile) % 4] for c in range(n)}
        for h in range(1, m + 1):
            instance = {"positive": p0, "negative": n0, "uncertain": uncertain, "pick": 0,
                        "blockers": blockers, "quorum": h, "costs": costs}
            oracle, seen = TierWorldOracle(instance), set()
            mask, dnf, boolean = MaskContext(instance), DNFContext(instance), BooleanContext(instance)

            def audit(p, n, available, verdict, possible, choices, method):
                state = frozenset(p), frozenset(n), frozenset(available)
                expected, future, relevant = oracle.state(*state)
                assert verdict == expected
                assert possible == future
                if state not in seen:
                    assert mask.relevant(*state) == relevant
                    assert dnf.relevant(*state) == relevant
                    assert boolean.relevant(*state) == relevant
                    seen.add(state)
                    counts["distinct_state_checks"] += 1
                if choices is not None:
                    assert choices == oracle_choices(oracle, *state, method, costs)
                    counts["selection_checks"] += 1

            for response_tuple in itertools.product((0, 1, None), repeat=len(uncertain)):
                observed = dict(zip(uncertain, response_tuple))
                instance["observed"] = observed
                final_p = p0 | {c for c, v in observed.items() if v == 1}
                final_n = n0 | {c for c, v in observed.items() if v == 0}
                expected = oracle.state(final_p, final_n, frozenset())[0]
                counts["full_ternary_records"] += 1
                counts["records_with_nonanswers"] += int(None in response_tuple)
                for target in (0, 1):
                    cert = minimum_certificate(p0, n0, final_p - p0, final_n - n0,
                                               0, blockers, h, target, costs)
                    want = oracle.best_certificate(observed, target, costs)
                    assert cert == want
                    counts["weighted_certificate_checks"] += 1
                for method in METHODS:
                    for tie_seed in (0, 1):
                        result = replay(instance, method, tie_seed, mask, audit)
                        assert frozenset(result["outcome"]) == expected
                        assert result["cost"] == sum(costs[c] for c, _ in result["trace"])
                        assert result["nonanswers"] == sum(v is None for _, v in result["trace"])
                        counts["complete_policy_traces"] += 1
                        counts["guarded_answer_reads"] += result["queries"]
            counts["profiles_with_quorum"] += 1
    return {"passed": True, "scope": "Twelve seeded five-candidate structures, all quorums for panels of two/three/four; every ternary full record, two tie seeds per method; zero and positive costs.",
            **dict(counts), "elapsed_seconds": time.perf_counter() - start}


def exact_instances(design):
    spec, seed = design["exact_online"], design["seed"]
    n, m, serial = spec["candidates"], spec["judges"], 0
    for density, overlap, rep in itertools.product(spec["blocker_probability"],
            spec["shared_incidence_probability"], range(spec["structural_replicates"])):
        rng = random.Random(stable_seed(seed, "exact_structure", density, overlap, rep))
        blockers = make_blockers(n, m, density, overlap, rng)
        costs_drawn = {c: rng.choice((1, 4, 16)) for c in range(n)}
        for h, p, r, cost_mode in itertools.product(spec["quorum"], spec["competitor_eligible_probability"],
                                                   spec["nonanswer_probability"], spec["cost_mode"]):
            instance = {"positive": frozenset(), "negative": frozenset(), "uncertain": tuple(range(n)),
                        "pick": 0, "blockers": blockers, "quorum": h,
                        "costs": {c: 1 if cost_mode == "unit" else costs_drawn[c] for c in range(n)}}
            p_each = {c: Fraction(str(spec["pick_eligible_probability"] if c == 0 else p)) for c in range(n)}
            r_exact = Fraction(str(r))
            probabilities = {c: ((0, (1 - r_exact) * (1 - p_each[c])),
                                  (1, (1 - r_exact) * p_each[c]), (None, r_exact)) for c in range(n)}
            meta = {"instance": f"e{serial:03d}", "candidates": n, "judges": m,
                    "blocker_probability": density, "overlap": overlap, "quorum": h,
                    "eligibility_probability": p, "nonanswer_probability": r,
                    "cost_mode": cost_mode, "structural_replicate": rep}
            serial += 1
            yield instance, probabilities, meta
    assert serial == spec["expected_instances"]


def exact_expected_values(instance, probabilities):
    """Exact Bellman recursion over unknown/0/1/nonanswer states.

    Each candidate's three response probabilities are fixed in advance. The
    recursion has no observed-record argument. All policies share terminal
    states. The last policy chooses the minimum expected-cost action; simple
    policies use fresh uniform ties. Certified cost mass is E[C * 1(cert)].
    """
    assert "observed" not in instance
    methods = METHODS + (OPTIMUM,)
    context = MaskContext(instance)
    u = tuple(instance["uncertain"])
    index = {c: i for i, c in enumerate(u)}
    actions, checked = {}, Counter()
    oracle = TierWorldOracle(instance)
    zero = Fraction(0)

    @lru_cache(None)
    def decode(state):
        p, n, available = set(instance["positive"]), set(instance["negative"]), set()
        for c, i in index.items():
            status = (state >> (2 * i)) & 3
            if status == 0:
                available.add(c)
            elif status == 1:
                n.add(c)
            elif status == 2:
                p.add(c)
        return frozenset(p), frozenset(n), frozenset(available)

    def transition(state, c, response):
        symbol = 3 if response is None else response + 1
        return state | (symbol << (2 * index[c]))

    @lru_cache(None)
    def solve(state):
        p, n, available = decode(state)
        verdict = classify(p, n, instance["pick"], instance["blockers"], instance["quorum"])
        future = can_certify_with(p, n, available, instance["pick"], instance["blockers"], instance["quorum"])
        independent_verdict, independent_future, _ = oracle.state(p, n, available)
        assert verdict == independent_verdict and future == independent_future
        checked["bellman_states_checked_against_world_oracle"] += 1
        if len(verdict) == 1:
            return tuple((zero, Fraction(1), zero, zero, zero, zero) for _ in methods)
        if not available or not future:
            return tuple((zero,) * len(METRICS) for _ in methods)
        action_values = {}
        for c in sorted(available):
            children = [(response, probability, solve(transition(state, c, response)))
                        for response, probability in probabilities[c] if probability]
            cost = instance["costs"][c]
            for j, method in enumerate(methods):
                means = [sum((probability * child[j][k] for _, probability, child in children), zero)
                         for k in range(len(METRICS))]
                means[0] += cost
                means[2] += cost * means[1]
                means[3] += 1
                r = sum((probability for response, probability, _ in children if response is None), zero)
                means[4] += r
                means[5] += r * cost
                action_values[c, method] = tuple(means)
        result = []
        for method in METHODS:
            choices = selectable(p, n, available, instance["pick"], instance["blockers"],
                                 instance["quorum"], method, context, instance["costs"])
            assert choices == oracle_choices(oracle, p, n, available, method, instance["costs"])
            assert choices
            result.append(tuple(sum((action_values[c, method][k] for c in choices), zero) / len(choices)
                                for k in range(len(METRICS))))
        chosen = min(available, key=lambda c: (action_values[c, OPTIMUM][0], c))
        actions[state] = chosen
        result.append(action_values[chosen, OPTIMUM])
        assert all(value[1] == result[-1][1] for value in result)
        assert all(value[0] >= result[-1][0] for value in result)
        return tuple(result)

    result = dict(zip(methods, solve(0)))
    checked["bellman_states"] = solve.cache_info().currsize
    return result, actions, decode, transition, oracle, checked


def exact_case(instance, probabilities, meta):
    values, actions, decode, transition, oracle, checked = exact_expected_values(instance, probabilities)
    zero = Fraction(0)
    total_probability = cert_probability = offline_cost_mass = offline_labels_mass = zero
    enumerated_optimum = [zero] * len(METRICS)
    u = tuple(instance["uncertain"])
    possible_responses = [[(response, probability) for response, probability in probabilities[c] if probability] for c in u]
    for full_record in itertools.product(*possible_responses):
        observed = {c: entry[0] for c, entry in zip(u, full_record)}
        probability = math.prod(entry[1] for entry in full_record)
        total_probability += probability
        p = instance["positive"] | {c for c, response in observed.items() if response == 1}
        n = instance["negative"] | {c for c, response in observed.items() if response == 0}
        final = oracle.state(p, n, frozenset())[0]
        certified = len(final) == 1
        cert_probability += probability * certified
        if certified:
            target = next(iter(final))
            cert = minimum_certificate(instance["positive"], instance["negative"], p, n,
                                       instance["pick"], instance["blockers"], instance["quorum"],
                                       target, instance["costs"])
            independent_cert = oracle.best_certificate(observed, target, instance["costs"])
            assert cert == independent_cert
            assert cert is not None
            offline_cost_mass += probability * sum(instance["costs"][c] for c in cert)
            unit = oracle.best_certificate(observed, target, {c: 1 for c in u})
            offline_labels_mass += probability * len(unit)
            checked["offline_certificates_checked_by_subset_enumeration"] += 1
        state = cost = queries = nonanswers = nonanswer_cost = 0
        while state in actions:
            chosen = actions[state]
            response = observed[chosen]
            cost += instance["costs"][chosen]
            queries += 1
            nonanswers += response is None
            nonanswer_cost += instance["costs"][chosen] * (response is None)
            state = transition(state, chosen, response)
        p_end, n_end, available_end = decode(state)
        assert oracle.state(p_end, n_end, available_end)[0] == final
        realised = (cost, int(certified), cost * certified, queries, nonanswers, nonanswer_cost)
        for k, value in enumerate(realised):
            enumerated_optimum[k] += probability * value
        checked["full_records_for_optimal_policy_enumeration"] += 1
    assert total_probability == 1
    assert tuple(enumerated_optimum) == values[OPTIMUM]
    assert all(value[1] == cert_probability for value in values.values())
    assert all(value[2] >= offline_cost_mass for value in values.values())

    def describe(value):
        result = {name: float(v) for name, v in zip(METRICS, value)}
        result["exact"] = {name: str(v) for name, v in zip(METRICS, value)}
        result["conditional_cost_if_certifiable"] = float(value[2] / cert_probability) if cert_probability else None
        result["conditional_cost_if_certifiable_exact"] = str(value[2] / cert_probability) if cert_probability else None
        return result

    return {**meta, "certification_probability": float(cert_probability), "certification_probability_exact": str(cert_probability),
            "offline_cost_mass_exact": str(offline_cost_mass), "offline_labels_mass_exact": str(offline_labels_mass),
            "offline_mean_cost_if_certifiable": float(offline_cost_mass / cert_probability) if cert_probability else None,
            "offline_mean_labels_if_certifiable": float(offline_labels_mass / cert_probability) if cert_probability else None,
            "policies": {method: describe(value) for method, value in values.items()}, "checks": dict(checked)}


def exact_summary(cases):
    number = len(cases)
    p_sum = sum((Fraction(case["certification_probability_exact"]) for case in cases), Fraction(0))
    lower_mass = sum((Fraction(case["offline_cost_mass_exact"]) for case in cases), Fraction(0))
    policies = {}
    for method in METHODS + (OPTIMUM,):
        totals = {metric: sum((Fraction(case["policies"][method]["exact"][metric]) for case in cases), Fraction(0))
                  for metric in METRICS}
        policies[method] = {f"mean_{metric}": float(value / number) for metric, value in totals.items()}
        policies[method]["mean_cost_exact"] = str(totals["cost"] / number)
        policies[method]["conditional_cost_if_certifiable"] = float(totals["certified_cost_mass"] / p_sum) if p_sum else None
        policies[method]["conditional_cost_if_certifiable_exact"] = str(totals["certified_cost_mass"] / p_sum) if p_sum else None
    return {"cases": number, "mean_certification_probability": float(p_sum / number),
            "mean_certification_probability_exact": str(p_sum / number),
            "offline_mean_cost_if_certifiable": float(lower_mass / p_sum) if p_sum else None,
            "offline_mean_cost_if_certifiable_exact": str(lower_mass / p_sum) if p_sum else None,
            "conditioning": "Uniformly choose one case in this stratum, then draw its independent full response record; condition on that record being certifiable.",
            "policies": policies}


def run_exact(design):
    start, cases = time.perf_counter(), []
    for instance, probabilities, meta in exact_instances(design):
        cases.append(exact_case(instance, probabilities, meta))
        if len(cases) % 16 == 0:
            print(f"exact online: {len(cases)}/{design['exact_online']['expected_instances']}", flush=True)
    checks = Counter()
    for case in cases:
        checks.update(case["checks"])
    return {"all": exact_summary(cases),
            "by_cost": {level: exact_summary([c for c in cases if c["cost_mode"] == level]) for level in ("unit", "heterogeneous")},
            "by_nonanswer": {str(level): exact_summary([c for c in cases if c["nonanswer_probability"] == level])
                             for level in design["exact_online"]["nonanswer_probability"]},
            "cases": cases, "verification_totals": dict(checks), "elapsed_seconds": time.perf_counter() - start}


def outcome_name(outcome):
    return "positive" if outcome == {1} else "negative" if outcome == {0} else "unresolved"


def run_main(design):
    start, rows = time.perf_counter(), []
    replications = design["policy_comparison"]["random_tie_replicates"]
    instances = itertools.chain(factorial_instances(design), constructed_instances(design))
    for count, instance in enumerate(instances, 1):
        public = structure_only(instance)
        p, n, u = instance["positive"], instance["negative"], instance["uncertain"]
        a, blockers, h = instance["pick"], instance["blockers"], instance["quorum"]
        context = MaskContext(public)
        initial = classify(p, n, a, blockers, h)
        initial_relevant = context.relevant(p, n, set(u))
        assert initial_relevant == DNFContext(public).relevant(p, n, set(u))
        p_full = p | {c for c, response in instance["observed"].items() if response == 1}
        n_full = n | {c for c, response in instance["observed"].items() if response == 0}
        final = classify(p_full, n_full, a, blockers, h)
        min_labels = min_cost = None
        if len(final) == 1:
            target = next(iter(final))
            cert = minimum_certificate(p, n, p_full - p, n_full - n, a, blockers, h, target)
            weighted = minimum_certificate(p, n, p_full - p, n_full - n, a, blockers, h, target, instance["costs"])
            assert cert is not None and weighted is not None
            min_labels = len(cert)
            min_cost = sum(instance["costs"][c] for c in weighted)
            for witness in (cert, weighted):
                assert classify(p | (p_full & witness), n | (n_full & witness), a, blockers, h) == final
        if instance["meta"]["phase"] == "constructed":
            family = instance["meta"]["family"]
            expected = {0, 1} if family == "unresolved_nonanswer" else {0} if family == "coverage_negative" else {1}
            assert final == expected
            if family == "coverage_negative":
                assert min_labels == len(blockers) - h + 1
            elif family in ("positive_multilabel", "bypassable_nonanswer"):
                assert min_labels == h * instance["meta"]["group_width"]
        for method in METHODS:
            totals = Counter()
            for rep in range(replications):
                result = replay(instance, method, stable_seed(design["seed"], "tie", instance["meta"]["instance"], rep), context)
                assert frozenset(result["outcome"]) == final
                if min_cost is not None:
                    assert result["cost"] >= min_cost
                    assert result["queries"] >= min_labels
                totals.update({key: result[key] for key in ("queries", "cost", "nonanswers", "nonanswer_cost")})
            row = {**instance["meta"], "initially_ambiguous": int(len(initial) > 1),
                   "initial_unknown": len(u), "initial_relevant": len(initial_relevant),
                   "blocker_incidences": sum(map(len, blockers)), "full_record_outcome": outcome_name(final),
                   "minimum_certificate_labels": min_labels, "minimum_certificate_cost": min_cost,
                   "method": method, "tie_replications": replications}
            for key in ("queries", "cost", "nonanswers", "nonanswer_cost"):
                row[f"total_{key}"] = totals[key]
                row[f"mean_{key}"] = totals[key] / replications
            rows.append(row)
        if count % 256 == 0:
            print(f"factorial/constructed instances: {count}/2304", flush=True)
    assert len(rows) == sum(design[key]["expected_instances"] for key in ("main_factorial", "constructed_cases")) * len(METHODS)
    return rows, time.perf_counter() - start


def summarize_rows(rows):
    instances = {row["instance"]: row for row in rows if row["method"] == METHODS[0]}
    assert instances
    n = len(instances)
    initially_ambiguous = {key for key, row in instances.items() if row["initially_ambiguous"]}
    newly_certifiable = {key for key in initially_ambiguous if instances[key]["full_record_outcome"] != "unresolved"}
    unresolved = {key for key, row in instances.items() if row["full_record_outcome"] == "unresolved"}
    sizes = [instances[key]["minimum_certificate_labels"] for key in newly_certifiable]
    policies = {}

    def policy_stats(group):
        count = len(group)
        return {"instances": count, "seeded_traces": sum(row["tie_replications"] for row in group),
                **{f"mean_{key}": sum(row[f"mean_{key}"] for row in group) / count if count else None
                   for key in ("queries", "cost", "nonanswers", "nonanswer_cost")}}

    for method in METHODS:
        group = [row for row in rows if row["method"] == method]
        assert len(group) == n
        policies[method] = {**policy_stats(group),
                           "initially_ambiguous": policy_stats([row for row in group if row["instance"] in initially_ambiguous]),
                           "newly_certifiable": policy_stats([row for row in group if row["instance"] in newly_certifiable]),
                           "unresolved": policy_stats([row for row in group if row["instance"] in unresolved])}
        cert_stats = policies[method]["newly_certifiable"]
        if newly_certifiable:
            cert_stats["offline_mean_cost"] = statistics.mean(instances[key]["minimum_certificate_cost"] for key in newly_certifiable)
            cert_stats["mean_cost_above_offline_bound"] = cert_stats["mean_cost"] - cert_stats["offline_mean_cost"]
    pairwise = {}
    by_method = {method: {row["instance"]: row for row in rows if row["method"] == method} for method in METHODS}
    for left, right in itertools.combinations(METHODS, 2):
        delta_cost = [by_method[left][key]["mean_cost"] - by_method[right][key]["mean_cost"] for key in instances]
        delta_query = [by_method[left][key]["mean_queries"] - by_method[right][key]["mean_queries"] for key in instances]
        pairwise[f"{left} minus {right}"] = {"instances": n, "mean_cost_difference": statistics.mean(delta_cost),
                                           "mean_query_difference": statistics.mean(delta_query),
                                           "left_cheaper": sum(d < 0 for d in delta_cost),
                                           "equal_mean_cost": sum(d == 0 for d in delta_cost),
                                           "right_cheaper": sum(d > 0 for d in delta_cost)}
    outcome_counts = Counter(row["full_record_outcome"] for row in instances.values())
    return {"instances": n, "initially_certified": n - len(initially_ambiguous),
            "initially_ambiguous": len(initially_ambiguous), "newly_certifiable": len(newly_certifiable),
            "final_counts": {key: outcome_counts[key] for key in ("positive", "negative", "unresolved")},
            "mean_initial_unknown": statistics.mean(row["initial_unknown"] for row in instances.values()),
            "mean_initial_relevant": statistics.mean(row["initial_relevant"] for row in instances.values()),
            "target_eligible_coverage_negatives": sum(row["full_record_outcome"] == "negative" and row["pick_true_eligible"]
                                                     for row in instances.values()),
            "newly_certifiable_certificate_labels": {"instances": len(sizes), "multilabel_instances": sum(size > 1 for size in sizes),
                "minimum": min(sizes) if sizes else None, "maximum": max(sizes) if sizes else None,
                "mean": statistics.mean(sizes) if sizes else None, "histogram": dict(sorted(Counter(sizes).items()))},
            "policies": policies, "paired_comparisons": pairwise}


def summarize_main(rows, elapsed):
    factorial = [row for row in rows if row["phase"] == "factorial"]
    constructed = [row for row in rows if row["phase"] == "constructed"]
    factors = ("judges", "candidates", "expected_blockers", "overlap", "known_probability", "eligibility_probability",
               "nonanswer_probability", "cost_mode", "quorum_name")
    factorial_strata = {}
    for key in factors:
        levels = sorted({row[key] for row in factorial})
        factorial_strata[key] = {str(level): summarize_rows([row for row in factorial if row[key] == level]) for level in levels}
    factorial_cross = {}
    for n in sorted({row["candidates"] for row in factorial}):
        for degree in sorted({row["expected_blockers"] for row in factorial}):
            factorial_cross[f"n={n},expected_blockers={degree}"] = summarize_rows(
                [row for row in factorial if row["candidates"] == n and row["expected_blockers"] == degree])
    return {"all": summarize_rows(rows), "factorial": summarize_rows(factorial), "constructed": summarize_rows(constructed),
            "factorial_strata": factorial_strata, "factorial_pool_by_density": factorial_cross,
            "constructed_by_family": {family: summarize_rows([row for row in constructed if row["family"] == family])
                                      for family in sorted({row["family"] for row in constructed})},
            "constructed_by_cost": {cost: summarize_rows([row for row in constructed if row["cost_mode"] == cost])
                                    for cost in ("unit", "heterogeneous")},
            "elapsed_seconds": elapsed}


def run_runtime(design):
    spec, start, rows = design["runtime"], time.perf_counter(), []
    for n, m, incidence, overlap in itertools.product(spec["candidates"], spec["judges"],
                                                     spec["incidence"], spec["shared_incidence_probability"]):
        rng = random.Random(stable_seed(design["seed"], "runtime", n, m, incidence, overlap))
        probability = min(1, 3 / (n - 1)) if incidence == "sparse_expected_3" else 0.35
        blockers = make_blockers(n, m, probability, overlap, rng)
        instance = {"positive": frozenset(), "negative": frozenset(), "uncertain": tuple(range(n)),
                    "pick": 0, "blockers": blockers, "quorum": m // 2 + 1, "costs": {c: 1 for c in range(n)}}
        available, expected, timings = frozenset(range(n)), None, {}
        methods = {"judge_mask": MaskContext, "absorbed_quorum_dnf": DNFContext}
        if n <= spec["truth_table_max_candidates"]:
            methods["truth_table"] = BooleanContext
        for name, factory in methods.items():
            repetitions = []
            for _ in range(spec["repetitions"]):
                before = time.perf_counter_ns()
                context = factory(instance)
                relevant = context.relevant(frozenset(), frozenset(), available)
                repetitions.append((time.perf_counter_ns() - before) / 1_000_000)
                if expected is None:
                    expected = relevant
                assert relevant == expected
            timings[name] = {"milliseconds": repetitions, "median_milliseconds": statistics.median(repetitions)}
        rows.append({"candidates": n, "judges": m, "incidence": incidence, "overlap": overlap,
                     "blocker_incidences": sum(map(len, blockers)), "relevant_candidates": len(expected), "timings": timings})
        if len(rows) % 8 == 0:
            print(f"runtime profiles: {len(rows)}/48", flush=True)
    summary = {}
    for n in spec["candidates"]:
        group = [row for row in rows if row["candidates"] == n]
        methods = sorted(set().union(*(set(row["timings"]) for row in group)))
        summary[str(n)] = {"profiles": len(group), "methods": {method: {
            "median_of_profile_medians_ms": statistics.median(row["timings"][method]["median_milliseconds"] for row in group),
            "minimum_profile_median_ms": min(row["timings"][method]["median_milliseconds"] for row in group),
            "maximum_profile_median_ms": max(row["timings"][method]["median_milliseconds"] for row in group)} for method in methods}}
    mask_faster = sum(row["timings"]["judge_mask"]["median_milliseconds"] < row["timings"]["absorbed_quorum_dnf"]["median_milliseconds"] for row in rows)
    return {"profiles": len(rows), "cold_repetitions_per_method": spec["repetitions"], "mask_faster_than_dnf_profiles": mask_faster,
            "by_pool_size": summary, "cases": rows, "elapsed_seconds": time.perf_counter() - start,
            "scope": "Cold context construction plus all-available relevance; no truth table for n>16; equal exact sets checked; environment-dependent exploratory timing."}


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_csv(path, rows):
    with Path(path).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    integer_fields = {"judges", "candidates", "quorum", "structural_replicate", "pick_true_eligible", "initially_ambiguous",
                      "initial_unknown", "initial_relevant", "blocker_incidences", "minimum_certificate_labels", "minimum_certificate_cost",
                      "tie_replications", "total_queries", "total_cost", "total_nonanswers", "total_nonanswer_cost"}
    float_fields = {"expected_blockers", "overlap", "known_probability", "eligibility_probability", "nonanswer_probability",
                    "group_width", "mean_queries", "mean_cost", "mean_nonanswers", "mean_nonanswer_cost"}
    with Path(path).open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for field in integer_fields:
            row[field] = None if row[field] == "" else int(row[field])
        for field in float_fields:
            if row[field] != "":
                # Factor levels with integral values retain their original string key in summaries.
                number = float(row[field])
                row[field] = int(number) if field in ("expected_blockers", "group_width") and number.is_integer() else number
    return rows


def check_stored(design, result_path, csv_path):
    result = json.loads(Path(result_path).read_text())
    assert result["design_sha256"] == sha256(ROOT / "computational_design.json")
    assert result["csv_sha256"] == sha256(csv_path)
    assert result["source_sha256"] == source_hashes(), "Source changed since the recorded experiment; recompute results"
    rows = read_csv(csv_path)
    expected = sum(design[key]["expected_instances"] for key in ("main_factorial", "constructed_cases"))
    assert len(rows) == expected * len(METHODS)
    assert len({row["instance"] for row in rows}) == expected
    for row in rows:
        assert row["method"] in METHODS
        for key in ("queries", "cost", "nonanswers", "nonanswer_cost"):
            assert row[f"mean_{key}"] * row["tie_replications"] == row[f"total_{key}"]
        if row["full_record_outcome"] == "unresolved":
            assert row["minimum_certificate_labels"] is None and row["minimum_certificate_cost"] is None
        else:
            assert row["mean_cost"] >= row["minimum_certificate_cost"]
    recomputed = summarize_main(rows, result["main"]["elapsed_seconds"])
    # JSON normalizes histogram integer keys to strings.
    assert json.loads(json.dumps(recomputed)) == result["main"]
    exact_cases = result["exact_online"]["cases"]
    assert len(exact_cases) == design["exact_online"]["expected_instances"]
    assert exact_summary(exact_cases) == result["exact_online"]["all"]
    for case in exact_cases:
        opt = Fraction(case["policies"][OPTIMUM]["exact"]["cost"])
        for method in METHODS:
            assert Fraction(case["policies"][method]["exact"]["cost"]) >= opt
    assert all(row["candidates"] <= design["runtime"]["truth_table_max_candidates"] or "truth_table" not in row["timings"]
               for row in result["runtime"]["cases"])
    return {"passed": True, "csv_rows": len(rows), "main_instances": expected,
            "exact_online_cases": len(exact_cases), "runtime_profiles": len(result["runtime"]["cases"]),
            "design_hash_matches": True, "source_hashes_match": True, "all_main_aggregates_reconstructed_from_csv": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--all", action="store_true", help="Run the entire fixed design and all independent checks")
    mode.add_argument("--verify-only", action="store_true", help="Independent small-profile checks plus stored-output integrity; no full study")
    mode.add_argument("--check-only", action="store_true", help="Independent small-profile checks before any study results exist")
    parser.add_argument("--results", type=Path, default=ROOT / "computational-results.json")
    parser.add_argument("--csv", type=Path, default=ROOT / "computational-results.csv")
    parser.add_argument("--checks-out", type=Path, default=ROOT / "computational-checks.json")
    args = parser.parse_args()
    design = json.loads((ROOT / "computational_design.json").read_text())
    assert tuple(design["policy_comparison"]["methods"]) == METHODS
    started = time.perf_counter()
    checks = {"design_sha256": sha256(ROOT / "computational_design.json"), "source_sha256": source_hashes(),
              "independent_oracle": independent_checks(design)}
    print("Independent all-ternary-record policy checks passed", flush=True)
    if args.all:
        rows, elapsed = run_main(design)
        result = {"schema_version": 1, "design_sha256": checks["design_sha256"], "source_sha256": source_hashes(),
                  "environment": environment(), "main": summarize_main(rows, elapsed),
                  "exact_online": run_exact(design), "runtime": run_runtime(design)}
        write_csv(args.csv, rows)
        result["csv_sha256"] = sha256(args.csv)
        result["elapsed_seconds"] = time.perf_counter() - started
        write_json(args.results, result)
        checks["exact_online_enumeration"] = result["exact_online"]["verification_totals"]
        checks["stored_results"] = check_stored(design, args.results, args.csv)
    elif args.verify_only:
        checks["stored_results"] = check_stored(design, args.results, args.csv)
    checks["passed"] = True
    checks["elapsed_seconds"] = time.perf_counter() - started
    write_json(args.checks_out, checks)
    print(json.dumps({"passed": True, "elapsed_seconds": round(checks["elapsed_seconds"], 3),
                      "independent_checks": checks["independent_oracle"],
                      "stored_results": checks.get("stored_results")}, indent=2), flush=True)


if __name__ == "__main__":
    main()
