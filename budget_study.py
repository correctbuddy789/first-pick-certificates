#!/usr/bin/env python3
# Copyright (c) 2026 Tushar Nain. SPDX-License-Identifier: MIT
"""Frozen budget-prefix experiment through the public benchmark runner.

python3 -S budget_study.py --run
python3 -S budget_study.py --verify-stored
python3 budget_study.py --figures  # requires matplotlib, never recomputes outcomes

Old study files are read only. The complete-trace optimization is checked
against direct budget calls on a subset selected before budget outcomes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
import time

from certificates import classify

ROOT = Path(__file__).resolve().parent
PHASES = ("factorial", "constructed")
COSTS = ("unit", "heterogeneous")
INTEGER_FIELDS = ("replicate", "queries", "certified", "initially_ambiguous",
                  "certificate_size", "full_queries")
FIELDS = ("instance", "phase", "family", "cost_mode", "method", "replicate",
          "budget_fraction", "total_available_cost_exact", "budget_cost_exact",
          "queries", "paid_cost_exact", "paid_fraction_exact", "certified",
          "outcome", "initially_ambiguous", "certificate_cost_exact",
          "certificate_size", "full_queries", "full_cost_exact")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_protected(design):
    for name, expected in design["protected_inputs"].items():
        assert sha(ROOT / name) == expected, f"Frozen input changed: {name}"


def direct_case_ids(instances):
    """Outcome-independent, design-frozen selection of 16 verification cases."""
    selected = []
    for phase in PHASES:
        for cost in COSTS:
            ids = [i["meta"]["instance"] for i in instances
                   if i["meta"]["phase"] == phase and i["meta"]["cost_mode"] == cost]
            ids.sort(key=lambda key: (hashlib.sha256(key.encode()).hexdigest(), key))
            selected.extend(ids[:4])
    assert len(selected) == len(set(selected)) == 16
    return frozenset(selected)


def outcome_name(outcomes):
    return "positive" if outcomes == {True} else "negative" if outcomes == {False} else "unresolved"


def validate_complete(panel, result):
    """Check observed labels and certificate soundness without hidden records."""
    assert result["status"] == "certified"
    index = {name: c for c, name in enumerate(panel.candidate_ids)}
    seen, revealed = set(), {}
    cost = Fraction(0)
    for item in result["trace"]:
        c = index[item["candidate"]]
        assert c in panel.available and c not in seen
        assert type(item["answer"]) is int and item["answer"] in (0, 1)
        assert Fraction(item["cost_exact"]) == panel.costs[c]
        seen.add(c)
        revealed[c] = item["answer"]
        cost += panel.costs[c]
    assert len(seen) == result["query_attempts"]
    assert cost == Fraction(result["total_cost_exact"])
    witness = result["certificate"]
    assert witness is not None and witness["relative_to_initial_labels"]
    keys = {index[c] for c in witness["candidates"]}
    assert keys <= seen and len(keys) == witness["size"]
    assert set(witness["labels"]) == set(witness["candidates"])
    assert all(witness["labels"][name] == revealed[index[name]] for name in witness["labels"])
    p = set(panel.positive) | {c for c in keys if revealed[c] == 1}
    n = set(panel.negative) | {c for c in keys if revealed[c] == 0}
    assert classify(p, n, panel.pick, panel.blockers, panel.quorum) == {result["verdict"]}
    witness_cost = sum((panel.costs[c] for c in keys), Fraction(0))
    assert witness_cost == Fraction(witness["cost_exact"]) <= cost


def prefix_result(panel, full, budget):
    """Return the longest canonical prefix affordable under an exact budget."""
    spent, trace = Fraction(0), []
    for item in full["trace"]:
        next_cost = Fraction(item["cost_exact"])
        if spent + next_cost > budget:
            break
        trace.append(item)
        spent += next_cost
    certified = len(trace) == len(full["trace"])
    # Full traces stop at the first exact certificate. An earlier prefix
    # cannot already be certified, which is checked directly below.
    p, n = set(panel.positive), set(panel.negative)
    index = {name: c for c, name in enumerate(panel.candidate_ids)}
    for item in trace:
        (p if item["answer"] else n).add(index[item["candidate"]])
    outcomes = classify(p, n, panel.pick, panel.blockers, panel.quorum)
    assert (len(outcomes) == 1) == certified
    if certified:
        assert outcomes == {full["verdict"]}
    assert spent <= budget
    return {"trace": trace, "total_cost_exact": str(spent),
            "query_attempts": len(trace), "certified": certified,
            "possible_outcomes": sorted(outcomes),
            "certificate": full["certificate"] if certified else None,
            "outcome": outcome_name(outcomes)}


def verify_direct(prefix, direct):
    assert prefix["trace"] == direct["trace"]
    assert Fraction(prefix["total_cost_exact"]) == Fraction(direct["total_cost_exact"])
    assert prefix["query_attempts"] == direct["query_attempts"]
    assert prefix["certified"] == (direct["status"] == "certified")
    assert prefix["possible_outcomes"] == direct["possible_outcomes"]
    assert prefix["certificate"] == direct["certificate"]


def run(design, traces_input=None):
    # Imported lazily so --verify-stored and --figures need no runner execution.
    from benchmark_runner import benchmark_cases, panel_from_instance, run_instance

    check_protected(design)
    instances = list(benchmark_cases())
    assert len(instances) == design["selection"]["expected_instances"]
    direct_ids = direct_case_ids(instances)
    grid = tuple(Fraction(x) for x in design["budgets"]["fractions"])
    old = {(r["instance"], r["method"], int(r["replicate"])): r
           for r in csv.DictReader((ROOT / "extension-results.csv").open())}
    # Optional cache of the exact public-runner output, created by the
    # full-equivalence verifier. Never use old extension aggregates as traces.
    trace_stream = Path(traces_input).open() if traces_input else None
    original_seed = json.loads((ROOT / "computational_design.json").read_text())["seed"]
    rows, full_checks, direct_checks, certificate_checks = [], 0, 0, 0
    start = time.perf_counter()
    for number, instance in enumerate(instances, 1):
        meta = instance["meta"]
        panel = panel_from_instance(instance)
        assert all(panel.costs[c] > 0 for c in panel.available)
        assert all(type(y) is int and y in (0, 1) for y in instance["observed"].values())
        total = sum((panel.costs[c] for c in panel.available), Fraction(0))
        initial = classify(panel.positive, panel.negative, panel.pick, panel.blockers, panel.quorum)
        ambiguous = int(len(initial) > 1)
        for method in design["methods"]:
            for replicate in range(design["tie_slots"]):
                if trace_stream is None:
                    full = run_instance(instance, method, replicate=replicate,
                                        original_seed=original_seed)
                else:
                    line = next(trace_stream, None)
                    assert line is not None, "Incomplete public-runner trace cache"
                    full = json.loads(line)
                    assert (full["instance_id"], full["policy"], full["replicate"]) == (
                        meta["instance"], method, replicate), "Trace cache order or identity mismatch"
                validate_complete(panel, full)
                index = {name: c for c, name in enumerate(panel.candidate_ids)}
                assert all(item["answer"] == instance["observed"][index[item["candidate"]]]
                           for item in full["trace"])
                certificate_checks += 1
                previous = old[(meta["instance"], method, replicate)]
                assert full["query_attempts"] == int(previous["queries"])
                assert Fraction(full["total_cost_exact"]) == Fraction(previous["cost"])
                assert outcome_name(set(full["possible_outcomes"])) == previous["outcome"]
                full_checks += 1
                for fraction in grid:
                    budget = total * fraction
                    prefix = prefix_result(panel, full, budget)
                    if meta["instance"] in direct_ids:
                        direct = run_instance(instance, method, replicate=replicate, max_cost=budget,
                                              original_seed=original_seed)
                        verify_direct(prefix, direct)
                        direct_checks += 1
                    paid = Fraction(prefix["total_cost_exact"])
                    witness = prefix["certificate"]
                    rows.append({"instance": meta["instance"], "phase": meta["phase"],
                        "family": meta.get("family", "factorial"), "cost_mode": meta["cost_mode"],
                        "method": method, "replicate": replicate, "budget_fraction": str(fraction),
                        "total_available_cost_exact": str(total), "budget_cost_exact": str(budget),
                        "queries": prefix["query_attempts"], "paid_cost_exact": str(paid),
                        "paid_fraction_exact": str(paid / total) if total else "0",
                        "certified": int(prefix["certified"]), "outcome": prefix["outcome"],
                        "initially_ambiguous": ambiguous,
                        "certificate_cost_exact": witness["cost_exact"] if witness else "",
                        "certificate_size": witness["size"] if witness else -1,
                        "full_queries": full["query_attempts"], "full_cost_exact": full["total_cost_exact"]})
        if number % 64 == 0:
            print(f"Budget benchmark: {number}/1152 instances; {time.perf_counter() - start:.1f}s", flush=True)
    assert full_checks == design["execution"]["expected_complete_traces"]
    assert direct_checks == design["verification"]["expected_direct_runs"]
    if trace_stream is not None:
        assert next(trace_stream, None) is None, "Unexpected extra cached traces"
        trace_stream.close()
    checks = verify_rows(rows, design)
    checks.update({"full_public_traces_match_original_extension": full_checks,
                   "full_revealed_only_certificates_checked": certificate_checks,
                   "direct_prefix_equivalence_cases": len(direct_ids),
                   "direct_prefix_equivalence_runs": direct_checks,
                   "direct_case_ids": sorted(direct_ids)})
    if traces_input:
        checks["public_runner_trace_cache_sha256"] = sha(traces_input)
    # Rejecting None is part of the public DNF adapter's domain contract,
    # checked directly with an initially ambiguous real synthetic input.
    from benchmark_runner import run_case
    specimen = next(i for i in instances if len(classify(i["positive"], i["negative"],
                                                        i["pick"], i["blockers"], i["quorum"])) > 1)
    panel = panel_from_instance(specimen)
    try:
        run_case(panel, lambda _: None, "allen_round_robin_cached", seed=0)
    except (ValueError, TypeError) as exc:
        checks["cached_dnf_rejects_nonanswer"] = True
        checks["cached_dnf_nonanswer_error"] = str(exc)
    else:
        raise AssertionError("DNF adapter accepted an unsupported nonanswer")
    check_protected(design)
    return rows, checks, time.perf_counter() - start


def read_rows(path):
    rows = list(csv.DictReader(Path(path).open()))
    for row in rows:
        for key in INTEGER_FIELDS:
            row[key] = int(row[key])
    return rows


def verify_rows(rows, design):
    assert len(rows) == design["execution"]["expected_budget_rows"]
    grid = tuple(Fraction(x) for x in design["budgets"]["fractions"])
    ids, keys = set(), set()
    grouped = defaultdict(list)
    first = {}
    for r in rows:
        key = (r["instance"], r["method"], r["replicate"], r["budget_fraction"])
        assert key not in keys
        keys.add(key)
        ids.add(r["instance"])
        first[r["instance"]] = r
        grouped[key[:3]].append(r)
        budget = Fraction(r["budget_cost_exact"])
        paid = Fraction(r["paid_cost_exact"])
        total = Fraction(r["total_available_cost_exact"])
        assert budget == Fraction(r["budget_fraction"]) * total
        assert 0 <= paid <= budget
        assert Fraction(r["paid_fraction_exact"]) == (paid / total if total else 0)
        assert r["certified"] in (0, 1)
        assert bool(r["certified"]) == (r["outcome"] in ("positive", "negative"))
        assert r["queries"] <= r["full_queries"]
        if r["certified"]:
            assert r["certificate_size"] >= 0
            assert Fraction(r["certificate_cost_exact"]) <= paid
            assert r["queries"] == r["full_queries"]
            assert paid == Fraction(r["full_cost_exact"])
        else:
            assert r["certificate_size"] == -1 and r["certificate_cost_exact"] == ""
        if not r["initially_ambiguous"]:
            assert r["certified"] == 1 and r["queries"] == 0 and paid == 0
    assert len(ids) == design["selection"]["expected_instances"]
    assert len(grouped) == design["execution"]["expected_complete_traces"]
    original = {(r["instance"], r["method"], int(r["replicate"])): r
                for r in csv.DictReader((ROOT / "extension-results.csv").open())}
    for key, group in grouped.items():
        group.sort(key=lambda r: Fraction(r["budget_fraction"]))
        assert tuple(Fraction(r["budget_fraction"]) for r in group) == grid
        assert group[0]["certified"] == 1 - group[0]["initially_ambiguous"]
        assert group[-1]["certified"] == 1
        assert [r["certified"] for r in group] == sorted(r["certified"] for r in group)
        assert [r["queries"] for r in group] == sorted(r["queries"] for r in group)
        costs = [Fraction(r["paid_cost_exact"]) for r in group]
        assert costs == sorted(costs)
        old = original[key]
        assert group[-1]["queries"] == int(old["queries"])
        assert costs[-1] == Fraction(old["cost"])
        assert group[-1]["outcome"] == old["outcome"]
    for identifier in ids:
        assert all((identifier, method, slot) in grouped
                   for method in design["methods"] for slot in range(design["tie_slots"]))
    strata = Counter(f"{r['phase']}_{r['cost_mode']}" for r in first.values())
    assert dict(strata) == design["selection"]["expected_phase_and_cost"]
    initial = sum(1 - r["initially_ambiguous"] for r in first.values())
    assert initial == 164
    return {"instances": len(ids), "initially_certified": initial,
            "initially_ambiguous": len(ids) - initial, "complete_trace_slots": len(grouped),
            "budget_rows": len(rows), "phase_and_cost_denominators": dict(strata),
            "unique_complete_factorial_design": True,
            "zero_budget_equals_initial_certification": True,
            "full_budget_certifies_every_case": True,
            "monotone_certification_queries_and_cost": True,
            "exact_budget_caps_respected": True,
            "recorded_certificate_cost_bounded_by_acquisition": True}


def metrics(rows):
    if not rows:
        return {"instances": 0, "trace_slots": 0}
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["instance"]].append(row)
    # Explicit within-instance averaging prevents tie slots being mistaken
    # for independent cases and remains correct if the storage format changes.
    per_instance = []
    for group in grouped.values():
        assert len(group) == 4 and {r["replicate"] for r in group} == set(range(4))
        values = {"certified_fraction": sum(Fraction(r["certified"]) for r in group) / 4,
                  "mean_queries": sum(Fraction(r["queries"]) for r in group) / 4,
                  "mean_paid_cost": sum(Fraction(r["paid_cost_exact"]) for r in group) / 4,
                  "mean_paid_fraction": sum(Fraction(r["paid_fraction_exact"]) for r in group) / 4}
        for outcome in ("positive", "negative", "unresolved"):
            values[f"{outcome}_fraction"] = Fraction(sum(r["outcome"] == outcome for r in group), 4)
        per_instance.append(values)
    result = {"instances": len(grouped), "trace_slots": len(rows)}
    for key in per_instance[0]:
        exact = sum((r[key] for r in per_instance), Fraction(0)) / len(per_instance)
        result[key] = float(exact)
        result[f"{key}_exact"] = str(exact)
    certified_count = Fraction(result["certified_fraction_exact"]) * len(grouped)
    result["certified_instance_equivalents_exact"] = str(certified_count)
    return result


def summaries(rows, design):
    categories = {"all": rows}
    for phase in PHASES:
        categories[phase] = [r for r in rows if r["phase"] == phase]
    for cost in COSTS:
        categories[cost] = [r for r in rows if r["cost_mode"] == cost]
    for phase in PHASES:
        for cost in COSTS:
            categories[f"{phase}_{cost}"] = [r for r in rows if r["phase"] == phase and r["cost_mode"] == cost]
    result = {}
    for name, group in categories.items():
        first = {r["instance"]: r for r in group}
        summary = {"instances": len(first),
                   "initially_certified": sum(1 - r["initially_ambiguous"] for r in first.values()),
                   "initially_ambiguous": sum(r["initially_ambiguous"] for r in first.values()),
                   "policies": {}}
        indexed = defaultdict(list)
        for r in group:
            indexed[r["method"], r["budget_fraction"]].append(r)
        for method in design["methods"]:
            summary["policies"][method] = {}
            for budget in design["budgets"]["fractions"]:
                selected = indexed[method, budget]
                summary["policies"][method][budget] = metrics(selected)
                summary["policies"][method][budget]["initially_ambiguous_only"] = metrics(
                    [r for r in selected if r["initially_ambiguous"]])
        result[name] = summary
    return result


def figures(payload):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    styles = [
        ("uniform_all", "Uniform all", "#777777", "o", ":"),
        ("pick_first_max_blockers", "Pick + max blockers", "#CC7733", "^", "-"),
        ("pick_first_uniform_blockers", "Pick + uniform blockers", "#AA3377", "v", "--"),
        ("uniform_relevant", "Uniform relevant", "#4477AA", "s", "--"),
        ("cheapest_relevant", "Cheapest relevant", "#228833", "D", "-"),
        ("pick_first_cost_normalized_blockers", "Cost-normalized blockers", "#66AABB", "P", "-."),
        ("allen_round_robin_cached", "Cached DNF", "#000000", "*", "-"),
    ]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8,
                         "axes.titlesize": 9, "axes.labelsize": 8,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42, "ps.fonttype": 42})
    # Sized for a 13 cm LNCS text width; avoid shrinking a larger canvas.
    fig, axes = plt.subplots(2, 2, figsize=(5.12, 4.8), sharey=True)
    fractions = payload["budget_fractions"]
    for axis, phase, cost, letter in zip(axes.flat,
                                        ("factorial", "factorial", "constructed", "constructed"),
                                        ("unit", "heterogeneous", "unit", "heterogeneous"), "abcd"):
        summary = payload["summaries"][f"{phase}_{cost}"]
        for key, label, color, marker, linestyle in styles:
            values = [summary["policies"][key][q] for q in fractions]
            axis.plot([100 * v["mean_paid_fraction"] for v in values],
                      [100 * v["certified_fraction"] for v in values],
                      label=label, color=color, marker=marker, linestyle=linestyle,
                      markersize=4 if marker != "*" else 6, linewidth=1.05,
                      markerfacecolor="white" if key != "allen_round_robin_cached" else color,
                      markeredgewidth=.75)
        cost_label = "unit costs" if cost == "unit" else "unequal costs"
        axis.set_title(f"({letter}) {phase.capitalize()}, {cost_label}\n(n = {summary['instances']})")
        axis.set_ylim(-2, 103)
        axis.set_xlim(left=-1)
        axis.set_yticks([0, 25, 50, 75, 100])
        axis.grid(axis="y", alpha=.2, linewidth=.5)
        axis.tick_params(labelsize=7)
    axes[0, 0].set_ylabel("Instances certified (%)")
    axes[1, 0].set_ylabel("Instances certified (%)")
    for axis in axes[1]:
        axis.set_xlabel("Mean paid share of\ninitial available cost (%)")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False,
               fontsize=7, columnspacing=1.25, handlelength=2.2,
               bbox_to_anchor=(.5, .005))
    fig.tight_layout(rect=(0, .18, 1, 1), h_pad=1.8, w_pad=1.4)
    destination = ROOT / "figures"
    destination.mkdir(exist_ok=True)
    for suffix in ("pdf", "png"):
        fig.savefig(destination / f"budgeted-acquisition.{suffix}", dpi=220,
                    bbox_inches="tight", pad_inches=.035)
    plt.close(fig)
    print("Created figures/budgeted-acquisition.pdf and .png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", action="store_true")
    group.add_argument("--verify-stored", action="store_true")
    group.add_argument("--figures", action="store_true")
    parser.add_argument("--results-out", type=Path, default=ROOT / "budget-results.json")
    parser.add_argument("--csv-out", type=Path, default=ROOT / "budget-results.csv")
    parser.add_argument("--checks-out", type=Path, default=ROOT / "budget-checks.json")
    parser.add_argument("--traces-input", type=Path,
                        help="Optional exact public-runner JSONL cache from verify_benchmark_runner")
    args = parser.parse_args()
    design = json.loads((ROOT / "budget_design.json").read_text())
    check_protected(design)
    if args.run:
        rows, checks, elapsed = run(design, args.traces_input)
        with args.csv_out.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        checks.update({"design_sha256": sha(ROOT / "budget_design.json"),
                       "csv_sha256": sha(args.csv_out), "status": "passed"})
        args.checks_out.write_text(json.dumps(checks, indent=2, sort_keys=True) + "\n")
        payload = {"status": "complete", "design_sha256": sha(ROOT / "budget_design.json"),
                   "csv_sha256": sha(args.csv_out), "checks_sha256": sha(args.checks_out),
                   "elapsed_seconds": elapsed, "budget_fractions": design["budgets"]["fractions"],
                   "sources": {name: sha(ROOT / name) for name in
                               ("budget_study.py", "benchmark_runner.py", "policy_runner.py", "panel_io.py")},
                   "checks": checks, "summaries": summaries(rows, design)}
        args.results_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(json.dumps(checks, indent=2))
    else:
        payload = json.loads(args.results_out.read_text())
        assert payload["design_sha256"] == sha(ROOT / "budget_design.json")
        assert payload["csv_sha256"] == sha(args.csv_out)
        assert payload["checks_sha256"] == sha(args.checks_out)
        for name, expected in payload["sources"].items():
            assert sha(ROOT / name) == expected, name
        if args.verify_stored:
            rows = read_rows(args.csv_out)
            checks = verify_rows(rows, design)
            assert all(payload["checks"][key] == value for key, value in checks.items())
            assert summaries(rows, design) == payload["summaries"]
            print("Stored budget experiment: hashes, exact cost caps, denominators, monotonicity, all summaries verified")
        else:
            figures(payload)


if __name__ == "__main__":
    main()
