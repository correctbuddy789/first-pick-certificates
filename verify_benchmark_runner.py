#!/usr/bin/env python3
# Copyright (c) 2026 Tushar Nain. SPDX-License-Identifier: MIT
"""Check the shared policy workflow against protected results and old traces.

Default: targeted interface/budget tests. --full-equivalence additionally
replays every one of 32,256 frozen extension slots, comparing every stored
non-timing result and fresh original traces for a fixed structural subset.
Optional --traces-out retains the unified records for further experiments.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from benchmark_extensions import ALL_METHODS, check_protected, replay_extension
from benchmark_runner import (ROOT, benchmark_cases, panel_from_instance,
                              policy_factory, run_case, run_instance)
from certificates import classify
from computational_study import stable_seed, structure_only
from dnf_baselines import quorum_terms
from panel_io import InputError, load_panel, load_responses, panel_from_dict
from policy_runner import builtin_policy, run_policy
from reuse_demo import load_plugin


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def small_panel(cost_b=5, cost_c=1, *, available=None):
    document = {"schema_version": "1.0", "instance_id": "prefix-check",
                "candidates": ["a", "b", "c"], "pick": "a", "quorum": 1,
                "judges": [{"id": "j", "tiers": [["b", "c"], ["a"]]}],
                "eligibility": {"positive": ["a"], "negative": []},
                "costs": {"b": cost_b, "c": cost_c}, "synthetic": True}
    if available is not None:
        document["available"] = available
    return panel_from_dict(document)


class SharedWorkflowTests(unittest.TestCase):
    def test_prefix_does_not_skip_expensive_next_query(self):
        panel = small_panel()
        queried, states = [], []

        def choose(state):
            states.append(state)
            return min(state.available)

        result = run_policy(panel, choose, lambda c: queried.append(c) or 0,
                            max_cost=1, budget_mode="prefix")
        self.assertEqual(result["stop_reason"], "next_query_exceeds_cost_budget")
        self.assertEqual(result["total_cost_exact"], "0")
        self.assertEqual(queried, [])
        self.assertEqual(states[0].affordable, frozenset({2}))
        self.assertEqual(states[0].available, frozenset({1, 2}))
        self.assertEqual(result["remaining_unknown"], ["b", "c"])
        # Existing affordable-selection behavior still uses the cheap query.
        old = run_policy(panel, builtin_policy("cheapest_relevant"), lambda c: 0, max_cost=1)
        self.assertEqual(old["query_attempts"], 1)
        self.assertEqual(old["trace"][0]["candidate"], "c")
        self.assertEqual(old["stop_reason"], "cost_budget_exhausted")

    def test_exact_decimal_budget_and_free_queries(self):
        panel = small_panel(Decimal("0.1000000000000000000000001"), 0)
        acquired = []
        result = run_case(panel, lambda c: acquired.append(c) or 0,
                          "allen_round_robin_cached", max_cost=Decimal("0.1"))
        self.assertEqual(acquired, ["c"])
        self.assertEqual(result["total_cost_exact"], "0")
        self.assertEqual(result["stop_reason"], "next_query_exceeds_cost_budget")
        result = run_case(panel, lambda c: 0, "allen_round_robin_cached",
                          max_cost=Decimal("0.1000000000000000000000001"))
        self.assertEqual(result["status"], "certified")
        self.assertEqual(Fraction(result["total_cost_exact"]), Fraction(panel.costs[1]))
        for cost in (Decimal("1e-1000"), Decimal("1e1000")):
            extreme = small_panel(cost, 0)
            result = run_case(extreme, lambda c: 0, "allen_round_robin_cached",
                              max_cost=Fraction(cost) / 2)
            self.assertEqual(result["query_attempts"], 1)
            self.assertEqual(result["total_cost_exact"], "0")
            self.assertEqual(result["status"], "unresolved")

    def test_binary_scope_and_unavailable_unknowns(self):
        panel = small_panel()
        with self.assertRaisesRegex(InputError, "binary answers"):
            run_case(panel, lambda c: None, "allen_round_robin_cached")
        panel = small_panel(available=["b"])
        calls = []
        with self.assertRaisesRegex(InputError, "every untested DNF variable available"):
            run_case(panel, lambda c: calls.append(c) or 0, "allen_round_robin_cached")
        self.assertEqual(calls, [])
        other = run_case(panel, lambda c: 0, "cheapest_relevant")
        self.assertEqual(other["status"], "unresolved")
        self.assertEqual(other["remaining_unknown"], ["c"])

    def test_actual_nonanswer_is_not_an_ineligible_label(self):
        result = run_case(small_panel(), lambda c: None, "cheapest_relevant")
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["final_negative"], [])
        self.assertTrue(result["remaining_unknown"])
        self.assertEqual(result["nonanswers"], result["query_attempts"])

    def test_information_boundary_and_plugin_on_both_sources(self):
        fixture = ROOT / "examples" / "open_resources"
        panel = load_panel(fixture / "panel.json")
        answers = load_responses(fixture / "responses-negative.json", panel)
        seen, selected = [], []

        def choose(state):
            self.assertFalse(hasattr(state, "__dict__"))
            for field in ("observed", "responses", "answer", "pick_true_eligible", "benchmark_metadata"):
                self.assertFalse(hasattr(state, field))
            self.assertEqual(state.attempts_used, len(seen))
            self.assertEqual(len(selected), len(seen))
            c = min(state.relevant)
            selected.append(state.candidate_ids[c])
            return c

        def answer(candidate):
            self.assertEqual(candidate, selected[-1])
            self.assertNotIn(candidate, seen)
            seen.append(candidate)
            return answers[candidate]

        result = run_case(panel, answer, "custom", choose=choose)
        self.assertEqual(result["status"], "certified")
        plugin = ROOT / "examples" / "cost_sensitive_policy.py"
        imported = run_case(panel, answers.__getitem__, "custom", choose=load_plugin(plugin))
        case = next(benchmark_cases())
        generated = run_instance(case, "custom", choose=load_plugin(plugin))
        self.assertEqual(imported["status"], "certified")
        self.assertEqual(generated["status"], "certified")

    def test_canonical_budget_runs_are_exact_unbudgeted_prefixes(self):
        design = json.loads((ROOT / "computational_design.json").read_text())
        cases = list(benchmark_cases(design))
        for position in (0, 37, 513, 1024, 1151):
            case = cases[position]
            for method in ALL_METHODS:
                full = run_instance(case, method, original_seed=design["seed"])
                total = Fraction(full["total_cost_exact"])
                for budget in (Fraction(0), total / 2, total):
                    prefix, spent = [], Fraction(0)
                    for query in full["trace"]:
                        if spent + Fraction(query["cost_exact"]) > budget:
                            break
                        prefix.append(query)
                        spent += Fraction(query["cost_exact"])
                    bounded = run_instance(case, method, max_cost=budget,
                                           original_seed=design["seed"])
                    self.assertEqual(bounded["trace"], prefix, (case["meta"], method, budget))
                    self.assertEqual(Fraction(bounded["total_cost_exact"]), spent)
                    self.assertLessEqual(spent, budget)
                    self.assertEqual(bounded["status"] == "certified", len(prefix) == len(full["trace"]))

    def test_cli_runs_custom_policy_and_baseline_on_same_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "runs.jsonl"
            subprocess.run([sys.executable, "-S", str(ROOT / "benchmark_runner.py"),
                            "--benchmark", "binary-extension", "--instance", "f0000",
                            "--policy", "allen_round_robin_cached", "--plugin",
                            str(ROOT / "examples" / "cost_sensitive_policy.py"),
                            "--replicates", "1", "--jsonl-out", str(out)],
                           capture_output=True, text=True, check=True)
            rows = [json.loads(line) for line in out.read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["policy"] for row in rows},
                             {"allen_round_robin_cached", "plugin:cost_sensitive_policy.py"})
            self.assertTrue(all(row["status"] == "certified" for row in rows))


def full_equivalence(traces_out=None):
    design = json.loads((ROOT / "computational_design.json").read_text())
    amendment = json.loads((ROOT / "extension-design.json").read_text())
    check_protected(amendment)
    protected = {name: sha(ROOT / name) for name in (
        "extension-results.csv", "extension-results.json", "extension-design.json",
        "benchmark_extensions.py", "dnf_baselines.py", "verify_dnf_baselines.py")}
    with (ROOT / "extension-results.csv").open(newline="") as stream:
        expected = {(r["instance"], r["method"], int(r["replicate"])): r for r in csv.DictReader(stream)}
    cases = list(benchmark_cases(design))
    assert len(cases) == 1152
    # Every 64th generated profile plus both endpoints of each phase. Selection
    # is fixed by case order, never by whether a policy performed well.
    trace_positions = set(range(0, len(cases), 64)) | {0, 1023, 1024, 1151}
    rows, scalar_checks, trace_checks, ledger_checks = 0, 0, 0, 0
    output = Path(traces_out).open("w", encoding="utf-8") if traces_out else None
    try:
        for position, case in enumerate(cases):
            public = structure_only(case)
            initial = classify(public["positive"], public["negative"], public["pick"],
                               public["blockers"], public["quorum"])
            terms = {"unabsorbed_terms": len(quorum_terms(public, absorb=False)),
                     "absorbed_terms": len(quorum_terms(public))}
            panel = panel_from_instance(case)
            for method in ALL_METHODS:
                for rep in range(amendment["random_tie_replicates"]):
                    result = run_instance(case, method, rep, original_seed=design["seed"])
                    key = case["meta"]["instance"], method, rep
                    old = expected[key]
                    actual = {**case["meta"], **terms, "method": method, "replicate": rep,
                              "initially_ambiguous": int(len(initial) > 1),
                              "outcome": "positive" if result["verdict"] else "negative",
                              "queries": result["query_attempts"],
                              "cost": Fraction(result["total_cost_exact"]),
                              **{k: result["policy_diagnostics"][k] for k in
                                 ("virtual_queries", "virtual_cost", "cached_virtual_queries")}}
                    assert result["status"] == "certified", key
                    for field, value in actual.items():
                        # Numeric comparison avoids harmless 0 versus 0.0 formatting.
                        if isinstance(value, (int, float, Fraction)):
                            assert Fraction(str(old[field])) == Fraction(str(value)), (key, field, old[field], value)
                        else:
                            assert old[field] == str(value), (key, field, old[field], value)
                        scalar_checks += 1
                    if position in trace_positions:
                        seed = stable_seed(design["seed"], "tie", key[0], rep)
                        original = replay_extension(case, method, seed)
                        trace = [(panel.candidate_ids.index(row["candidate"]), row["answer"])
                                 for row in result["trace"]]
                        assert trace == original["trace"], key
                        trace_checks += 1
                        if method == "allen_round_robin_cached":
                            adapter = policy_factory(method, seed)
                            response = {panel.candidate_ids[c]: value for c, value in case["observed"].items()}
                            run_case(panel, response.__getitem__, method, seed, choose=adapter)
                            scaled = [] if adapter.dnf is None else [
                                {**step, "ledger_before": tuple(Fraction(v) * adapter.scale for v in step["ledger_before"]),
                                 "ledger_after": tuple(Fraction(v) * adapter.scale for v in step["ledger_after"])}
                                for step in adapter.dnf.virtual_trace]
                            assert scaled == original["virtual_trace"], key
                            ledger_checks += 1
                    if output:
                        output.write(json.dumps(result, sort_keys=True) + "\n")
                    rows += 1
            if (position + 1) % 128 == 0:
                print(f"Unified equivalence: {position + 1}/1152 cases", flush=True)
    finally:
        if output:
            output.close()
    assert rows == len(expected) == 32256
    check_protected(amendment)
    assert protected == {name: sha(ROOT / name) for name in protected}
    return {"cases": len(cases), "rows": rows,
            "stored_non_timing_scalar_fields_matched": scalar_checks,
            "full_original_traces_matched": trace_checks,
            "original_dnf_virtual_ledgers_matched": ledger_checks,
            "trace_subset_rule": "every 64th case plus phase endpoints; all methods and four tie slots",
            "protected_extension_sha256": protected,
            "all_outcomes_certified": True,
            "traces_sha256": sha(traces_out) if traces_out else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-equivalence", action="store_true")
    parser.add_argument("--traces-out", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.traces_out and not args.full_equivalence:
        parser.error("--traces-out requires --full-equivalence")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SharedWorkflowTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    payload = {"status": "passed", "targeted_tests": result.testsRun,
               "sources": {name: sha(ROOT / name) for name in
                           ("policy_runner.py", "benchmark_runner.py", "verify_benchmark_runner.py")}}
    if args.full_equivalence:
        payload["equivalence"] = full_equivalence(args.traces_out)
    if args.out:
        args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
