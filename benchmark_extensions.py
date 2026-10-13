#!/usr/bin/env python3
"""Frozen amendment: seven-policy paired comparison on binary-answer cases.

python3 -S benchmark_extensions.py --run
python3 -S benchmark_extensions.py --verify-stored

Original files are read, never rewritten. All extra results are synthetic.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import random
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from certificates import can_certify_with, classify
from computational_study import (GuardedResponses, METHODS, constructed_instances,
                                  environment, factorial_instances, outcome_name,
                                  stable_seed, structure_only)
from dnf_baselines import (AllenRoundRobinCached, cost_normalized_blocker_choices,
                           quorum_terms)
from query_policies import MaskContext, selectable

ROOT = Path(__file__).resolve().parent
ADDED = ("pick_first_cost_normalized_blockers", "allen_round_robin_cached")
ALL_METHODS = METHODS + ADDED


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def selected_instances(original):
    for instance in factorial_instances(original):
        if instance["meta"]["nonanswer_probability"] == 0:
            yield instance
    for instance in constructed_instances(original):
        if instance["meta"]["family"] in ("positive_multilabel", "coverage_negative"):
            yield instance


def replay_extension(instance, method, seed, audit=None):
    """Shared original terminal contract with guarded post-selection answers.

    Return acquisition outcomes, trace, and exploratory cold policy overhead.
    Timing includes initialization and choice/update only, not common stopping,
    response lookup, diagnostic extraction, or validation/audit callbacks.
    """
    public = structure_only(instance)
    p, n = set(public["positive"]), set(public["negative"])
    available = set(public["uncertain"])
    pick, blockers, h = public["pick"], public["blockers"], public["quorum"]
    rng = random.Random(seed)
    responses = GuardedResponses(instance["observed"])
    started = time.perf_counter_ns()
    policy = AllenRoundRobinCached(public) if method == ADDED[1] else None
    context = MaskContext(public) if method in METHODS else None
    initialization_ns = time.perf_counter_ns() - started
    selection_ns = 0
    cost, trace = 0, []
    while True:
        verdict = classify(p, n, pick, blockers, h)
        possible = can_certify_with(p, n, available, pick, blockers, h)
        if audit is not None:
            audit(p, n, available, verdict, possible, None, method)
        if len(verdict) == 1 or not available or not possible:
            break
        started = time.perf_counter_ns()
        if policy is not None:
            chosen = policy.choose(p, n, available)
        else:
            if method == ADDED[0]:
                choices = cost_normalized_blocker_choices(
                    p, n, available, pick, blockers, public["costs"])
            else:
                choices = selectable(p, n, available, pick, blockers, h,
                                     method, context, public["costs"])
            assert choices and choices <= available
            chosen = rng.choice(sorted(choices))
        selection_ns += time.perf_counter_ns() - started
        assert chosen in available
        if audit is not None:
            audit(p, n, available, verdict, possible, {chosen}, method)
        available.remove(chosen)
        responses.permit(chosen)
        answer = responses[chosen]
        if answer not in (0, 1):
            raise ValueError("This extension evaluates binary-answer instances only")
        if policy is not None:
            started = time.perf_counter_ns()
            policy.observe(chosen, answer)
            selection_ns += time.perf_counter_ns() - started
        cost += public["costs"][chosen]
        trace.append((chosen, answer))
        (p if answer else n).add(chosen)
    assert len(trace) == len({c for c, _ in trace})
    return {"queries": len(trace), "cost": cost, "outcome": tuple(sorted(verdict)),
            "trace": trace, "initialization_ns": initialization_ns,
            "selection_ns": selection_ns,
            "policy_overhead_ns": initialization_ns + selection_ns,
            "virtual_queries": policy.diagnostics()["virtual_queries"] if policy else len(trace),
            "virtual_cost": policy.diagnostics()["virtual_cost"] if policy else cost,
            "cached_virtual_queries": policy.diagnostics()["cached_virtual_queries"] if policy else 0,
            "virtual_trace": policy.virtual_trace if policy else []}


def check_protected(design):
    for name, expected in design["protected_inputs"].items():
        if sha(ROOT / name) != expected:
            raise AssertionError(f"Frozen original input changed: {name}")


def summarize(rows):
    methods = tuple(dict.fromkeys(row["method"] for row in rows))
    identifiers = sorted({row["instance"] for row in rows})
    first = {row["instance"]: row for row in rows}
    out = {"instances": len(identifiers),
           "initially_certified": sum(not first[k]["initially_ambiguous"] for k in identifiers),
           "initially_ambiguous": sum(first[k]["initially_ambiguous"] for k in identifiers),
           "final_counts": dict(Counter(first[k]["outcome"] for k in identifiers)),
           "policies": {}, "paired_comparisons": {}}
    per_instance = {}
    for method in methods:
        group = [row for row in rows if row["method"] == method]
        ambiguous = [row for row in group if row["initially_ambiguous"]]
        per_instance[method] = {}
        grouped_cases = defaultdict(list)
        for row in group:
            grouped_cases[row["instance"]].append(row)
        for identifier in identifiers:
            case = grouped_cases[identifier]
            per_instance[method][identifier] = {
                metric: statistics.mean(r[metric] for r in case)
                for metric in ("queries", "cost")}
        stats = {"instances": len(identifiers), "trace_slots": len(group),
                 "tie_policy": "deterministic; four identical slots per case" if method == ADDED[1]
                               else "four seeded fresh-uniform-tie traces per case"}
        for metric in ("queries", "cost", "virtual_queries", "virtual_cost",
                       "cached_virtual_queries"):
            stats[f"mean_{metric}"] = statistics.mean(r[metric] for r in group)
        stats["initially_ambiguous"] = {
            "instances": out["initially_ambiguous"], "trace_slots": len(ambiguous),
            **{f"mean_{metric}": statistics.mean(r[metric] for r in ambiguous) if ambiguous else None
               for metric in ("queries", "cost")}}
        for metric in ("initialization_ns", "selection_ns", "policy_overhead_ns"):
            stats[f"mean_{metric}"] = statistics.mean(r[metric] for r in group)
            stats[f"median_{metric}"] = statistics.median(r[metric] for r in group)
        stats["selection_ns_per_query"] = (sum(r["selection_ns"] for r in group) /
                                            sum(r["queries"] for r in group)) if any(r["queries"] for r in group) else None
        out["policies"][method] = stats
    for left, right in itertools.combinations(methods, 2):
        dc = [per_instance[left][key]["cost"] - per_instance[right][key]["cost"]
              for key in identifiers]
        dq = [per_instance[left][key]["queries"] - per_instance[right][key]["queries"]
              for key in identifiers]
        out["paired_comparisons"][f"{left} minus {right}"] = {
            "instances": len(identifiers), "mean_cost_difference": statistics.mean(dc),
            "mean_query_difference": statistics.mean(dq),
            "left_cheaper": sum(d < 0 for d in dc),
            "equal_mean_cost": sum(d == 0 for d in dc),
            "right_cheaper": sum(d > 0 for d in dc)}
    return out


def summaries(rows):
    return {"all": summarize(rows),
            "by_phase": {phase: summarize([r for r in rows if r["phase"] == phase])
                         for phase in ("factorial", "constructed")},
            "by_cost": {cost: summarize([r for r in rows if r["cost_mode"] == cost])
                        for cost in ("unit", "heterogeneous")},
            "by_phase_and_cost": {f"{phase}_{cost}": summarize([r for r in rows if r["phase"] == phase and r["cost_mode"] == cost])
                                  for phase in ("factorial", "constructed") for cost in ("unit", "heterogeneous")},
            "constructed_by_family_and_cost": {f"{family}_{cost}": summarize([r for r in rows if r["family"] == family and r["cost_mode"] == cost])
                    for family in ("positive_multilabel", "coverage_negative") for cost in ("unit", "heterogeneous")}}


def check_rows(rows, original, extension):
    expected = {i["meta"]["instance"] for i in selected_instances(original)}
    assert len(expected) == extension["selection"]["expected_instances"]
    assert {r["instance"] for r in rows} == expected
    assert len(rows) == len(expected) * len(ALL_METHODS) * extension["random_tie_replicates"]
    keys = [(r["instance"], r["method"], r["replicate"]) for r in rows]
    assert len(set(keys)) == len(keys)
    lookup = {(row["instance"], row["method"]): row
              for row in csv.DictReader((ROOT / "computational-results.csv").open())}
    old_checks = 0
    grouped_cases = defaultdict(list)
    for row in rows:
        grouped_cases[row["instance"], row["method"]].append(row)
    for identifier in expected:
        for method in METHODS:
            group = grouped_cases[identifier, method]
            old = lookup[(identifier, method)]
            for metric in ("queries", "cost"):
                assert sum(r[metric] for r in group) == float(old[f"total_{metric}"])
                old_checks += 1
    for row in rows:
        assert row["outcome"] in ("positive", "negative")
        if not row["initially_ambiguous"]:
            assert row["queries"] == row["cost"] == 0
    return {"selected_instances": len(expected), "rows": len(rows),
            "original_policy_metric_totals_matched": old_checks,
            "all_final_outcomes_certified": True,
            "initial_certificates_have_zero_acquisition_cost": True}


def run(original, extension):
    check_protected(extension)
    rows = []
    started = time.perf_counter()
    for number, instance in enumerate(selected_instances(original), 1):
        assert all(y in (0, 1) for y in instance["observed"].values())
        public = structure_only(instance)
        initial = classify(instance["positive"], instance["negative"], instance["pick"],
                           instance["blockers"], instance["quorum"])
        full_p = instance["positive"] | {c for c, y in instance["observed"].items() if y}
        full_n = instance["negative"] | {c for c, y in instance["observed"].items() if not y}
        final = classify(full_p, full_n, instance["pick"], instance["blockers"], instance["quorum"])
        assert len(final) == 1
        counts = {"unabsorbed_terms": len(quorum_terms(public, absorb=False)),
                  "absorbed_terms": len(quorum_terms(public))}
        for method in ALL_METHODS:
            for rep in range(extension["random_tie_replicates"]):
                seed = stable_seed(original["seed"], "tie", instance["meta"]["instance"], rep)
                result = replay_extension(instance, method, seed)
                assert set(result["outcome"]) == set(final)
                assert result["cost"] == sum(instance["costs"][c] for c, _ in result["trace"])
                rows.append({**instance["meta"], **counts, "initially_ambiguous": int(len(initial) > 1),
                             "method": method, "replicate": rep, "outcome": outcome_name(final),
                             **{k: result[k] for k in ("queries", "cost", "initialization_ns", "selection_ns",
                                  "policy_overhead_ns", "virtual_queries", "virtual_cost", "cached_virtual_queries")}})
        if number % 128 == 0:
            print(f"Additional benchmark: {number}/1152 instances", flush=True)
    checks = check_rows(rows, original, extension)
    check_protected(extension)
    return rows, checks, time.perf_counter() - started


def read_rows(path):
    rows = list(csv.DictReader(Path(path).open()))
    numeric = ("replicate", "initially_ambiguous", "queries", "cost", "initialization_ns", "selection_ns",
               "policy_overhead_ns", "virtual_queries", "virtual_cost", "cached_virtual_queries")
    for row in rows:
        for key in numeric:
            row[key] = int(row[key])
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--verify-stored", action="store_true")
    parser.add_argument("--results-out", type=Path, default=ROOT / "extension-results.json")
    parser.add_argument("--csv-out", type=Path, default=ROOT / "extension-results.csv")
    args = parser.parse_args()
    original = json.loads((ROOT / "computational_design.json").read_text())
    extension = json.loads((ROOT / "extension-design.json").read_text())
    assert tuple(extension["methods"]) == ALL_METHODS
    check_protected(extension)
    if args.run:
        rows, checks, elapsed = run(original, extension)
        with args.csv_out.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        payload = {"status": "complete", "design_sha256": sha(ROOT / "extension-design.json"),
                   "csv_sha256": sha(args.csv_out), "elapsed_seconds": elapsed,
                   "environment": environment(), "checks": checks,
                   "sources": {name: sha(ROOT / name) for name in
                       ("dnf_baselines.py", "benchmark_extensions.py", "verify_dnf_baselines.py")},
                   "summaries": summaries(rows)}
        args.results_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(json.dumps(checks, indent=2))
    elif args.verify_stored:
        payload = json.loads(args.results_out.read_text())
        assert payload["design_sha256"] == sha(ROOT / "extension-design.json")
        assert payload["csv_sha256"] == sha(args.csv_out)
        for name, expected in payload["sources"].items():
            assert sha(ROOT / name) == expected, name
        rows = read_rows(args.csv_out)
        assert check_rows(rows, original, extension) == payload["checks"]
        assert summaries(rows) == payload["summaries"]
        print("Stored extension: hashes, denominators, all summaries, and original totals verified")
    else:
        parser.error("Choose --run or --verify-stored")


if __name__ == "__main__":
    main()
