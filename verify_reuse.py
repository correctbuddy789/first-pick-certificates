#!/usr/bin/env python3
"""Independent small-world checks of the public import/callback workflow.

The reference evaluates each complete preference tier directly. It does not
call classify, relevance, minimum_certificate, or the blocker formulas. These
finite checks supplement, rather than replace, the existing core verifiers.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import itertools
import json
import random
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from decimal import Decimal
from pathlib import Path

from panel_io import (InputError, complete_tiers_to_blockers, load_panel,
                      load_responses, panel_from_dict, read_json, responses_from_dict)
from policy_runner import PolicyState, builtin_policy, run_policy
from reuse_demo import ROOT, demonstration, load_plugin

FIXTURE = ROOT / "examples" / "open_resources"
COUNTS = {"random_panels": 0, "policy_runs": 0, "direct_world_evaluations": 0,
          "minimum_certificate_subset_checks": 0, "malformed_input_checks": 0}


def direct_outcomes(panel, positive, negative):
    unknown = sorted(set(range(len(panel.candidate_ids))) - set(positive) - set(negative))
    outcomes = set()
    for bits in itertools.product((0, 1), repeat=len(unknown)):
        eligible = set(positive) | {c for c, bit in zip(unknown, bits) if bit}
        votes = 0
        for tiers in panel.tiers:
            for tier in tiers:
                survivors = set(tier) & eligible
                if survivors:
                    votes += panel.pick in survivors
                    break
        outcomes.add(int(panel.pick in eligible and votes >= panel.quorum))
        COUNTS["direct_world_evaluations"] += 1
    return outcomes


def direct_can_finish(panel, positive, negative, available):
    available = sorted(available)
    for bits in itertools.product((0, 1), repeat=len(available)):
        p = set(positive) | {c for c, bit in zip(available, bits) if bit}
        n = set(negative) | {c for c, bit in zip(available, bits) if not bit}
        if len(direct_outcomes(panel, p, n)) == 1:
            return True
    return False


def direct_minimum(panel, result):
    records = [(panel.candidate_ids.index(t["candidate"]), t["answer"])
               for t in result["trace"] if t["answer"] is not None]
    sufficient = []
    for bits in itertools.product((0, 1), repeat=len(records)):
        labels = [item for item, included in zip(records, bits) if included]
        p = set(panel.positive) | {c for c, answer in labels if answer == 1}
        n = set(panel.negative) | {c for c, answer in labels if answer == 0}
        COUNTS["minimum_certificate_subset_checks"] += 1
        if direct_outcomes(panel, p, n) == {result["verdict"]}:
            indices = tuple(sorted(c for c, _ in labels))
            sufficient.append((sum((panel.costs[c] for c in indices), Fraction(0)), len(indices), indices))
    return min(sufficient)


class PublicWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.document = read_json(FIXTURE / "panel.json")
        self.panel = panel_from_dict(self.document)

    def test_complete_tiers_csv_and_strict_ties(self):
        self.assertEqual(self.panel, load_panel(FIXTURE / "panel-csv.json"))
        self.assertEqual(self.panel.blockers, (frozenset({1, 2}), frozenset({1, 3}), frozenset({2, 3})))
        self.assertEqual(complete_tiers_to_blockers(["a", "b", "c"], "a",
                         [[["b"], ["a", "c"]], [["a", "b", "c"]]]),
                         (frozenset({1}), frozenset()))

    def test_document_validation(self):
        mutations = [
            lambda d: d.update(schema_version="0"),
            lambda d: d.update(unrecognised_field=True),
            lambda d: d.update(candidates=["guide", "guide"]),
            lambda d: d.update(candidates=[]),
            lambda d: d.update(pick="missing"),
            lambda d: d.update(quorum=True),
            lambda d: d.update(quorum=0),
            lambda d: d.update(quorum=4),
            lambda d: d.update(quorum=1.5),
            lambda d: d.update(judges=[]),
            lambda d: d["judges"][1].update(id="editor_a"),
            lambda d: d["judges"][0].update(tiers=[["guide"]]),
            lambda d: d["judges"][0]["tiers"].append(["guide"]),
            lambda d: d["judges"][0]["tiers"].append([]),
            lambda d: d["judges"][0]["tiers"][0].append("missing"),
            lambda d: d["eligibility"]["negative"].append("guide"),
            lambda d: d["eligibility"]["positive"].append("missing"),
            lambda d: d["eligibility"]["positive"].append("guide"),
            lambda d: d.update(available=["guide"]),
            lambda d: d.update(available=["missing"]),
            lambda d: d.update(available=["tutorial", "tutorial"]),
            lambda d: d.update(costs={"missing": 1}),
            lambda d: d.update(costs={"handbook": -1}),
            lambda d: d.update(costs={"handbook": float("nan")}),
            lambda d: d.update(costs={"handbook": float("inf")}),
            lambda d: d.update(costs={"handbook": True}),
            lambda d: d.update(costs={"handbook": "5"}),
            lambda d: d.update(synthetic="true"),
            lambda d: d.update(description=7),
            lambda d: d.update(tiers_csv="tiers.csv"),
        ]
        for change in mutations:
            document = copy.deepcopy(self.document)
            change(document)
            with self.subTest(document=document), self.assertRaises(InputError):
                panel_from_dict(document)
            COUNTS["malformed_input_checks"] += 1
        document = copy.deepcopy(self.document)
        del document["available"], document["costs"]
        defaults = panel_from_dict(document)
        self.assertEqual(defaults.available, frozenset(defaults.uncertain))
        self.assertEqual(set(defaults.costs), {Fraction(1)})

    def test_csv_and_json_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            path = base / "bad.json"
            for text in ('{"schema_version":"1.0","schema_version":"1.1"}', '{"cost":NaN}', '{'):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(InputError):
                    read_json(path)
                COUNTS["malformed_input_checks"] += 1
            document = read_json(FIXTURE / "panel-csv.json")
            for text in ("judge_id,candidate_id,tier\na,guide,1\n",
                         "judge_id,candidate_id,tier\na,guide,1\na,guide,2\n",
                         "judge_id,candidate_id,tier\na,guide,0\n",
                         "judge_id,candidate_id,tier\na,guide,1,extra\n",
                         "wrong,header\n"):
                (base / "tiers.csv").write_text(text, encoding="utf-8")
                with self.assertRaises(InputError):
                    panel_from_dict(document, csv_base=base)
                COUNTS["malformed_input_checks"] += 1
            for unsafe in ("../tiers.csv", "/tmp/tiers.csv"):
                document["tiers_csv"] = unsafe
                with self.assertRaises(InputError):
                    panel_from_dict(document, csv_base=base)
                COUNTS["malformed_input_checks"] += 1

    def test_explicit_responses_only(self):
        valid = read_json(FIXTURE / "responses-negative.json")
        for change in (lambda r: r["responses"].pop("handbook"),
                       lambda r: r["responses"].update(guide=1),
                       lambda r: r["responses"].update(handbook=True),
                       lambda r: r["responses"].update(handbook=0.0),
                       lambda r: r["responses"].update(handbook=2)):
            bad = copy.deepcopy(valid)
            change(bad)
            with self.assertRaises(InputError):
                responses_from_dict(bad, self.panel)
            COUNTS["malformed_input_checks"] += 1
        record = responses_from_dict(valid, self.panel)
        with self.assertRaises(TypeError):
            record["handbook"] = 0

    def test_callback_information_boundary(self):
        snapshots = []
        for answer_file in ("responses-negative.json", "responses-positive.json"):
            record = load_responses(FIXTURE / answer_file, self.panel)
            chosen, queried, states = [], [], []

            def choose(state):
                states.append(state)
                self.assertIsInstance(state, PolicyState)
                self.assertFalse(hasattr(state, "responses"))
                self.assertFalse(hasattr(state, "observed"))
                self.assertFalse(hasattr(state, "answer"))
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    state.pick = 2
                with self.assertRaises(AttributeError):
                    state.positive.add(2)
                self.assertEqual(len(queried), state.attempts_used)
                c = builtin_policy("max_blockers")(state)
                chosen.append(state.candidate_ids[c])
                return c

            def answer(candidate):
                self.assertEqual(candidate, chosen[len(queried)])
                queried.append(candidate)
                return record[candidate]

            run_policy(self.panel, choose, answer, max_attempts=1)
            snapshots.append(states[0])
        self.assertEqual(snapshots[0], snapshots[1], "unrevealed answers cannot alter the initial callback state")
        with self.assertRaises(InputError):
            run_policy(self.panel, lambda state: state.pick, lambda candidate: 0)
        with self.assertRaises(InputError):
            run_policy(self.panel, lambda state: True, lambda candidate: 0)
        with self.assertRaises(InputError):
            run_policy(self.panel, builtin_policy("max_blockers"), lambda candidate: True)

    def test_nonanswers_unavailable_and_real_attempt_cost(self):
        record = load_responses(FIXTURE / "responses-nonanswer.json", self.panel)
        result = run_policy(self.panel, builtin_policy("max_blockers"), record.__getitem__)
        self.assertEqual((result["query_attempts"], result["nonanswers"], result["total_cost"]), (3, 1, 8))
        self.assertEqual(result["possible_outcomes"], [0, 1])
        self.assertEqual(result["unavailable_unknown"], ["handbook"])
        self.assertIsNone(result["certificate"])
        self.assertNotIn("handbook", result["final_negative"])
        panel = load_panel(FIXTURE / "panel-unavailable.json")
        record = load_responses(FIXTURE / "responses-unavailable.json", panel)
        result = run_policy(panel, builtin_policy("max_blockers"), record.__getitem__)
        self.assertEqual((result["query_attempts"], result["total_cost"]), (2, 3))
        self.assertEqual(result["possible_outcomes"], [0, 1])
        self.assertNotIn("handbook", [x["candidate"] for x in result["trace"]])
        self.assertEqual(result["unqueried_available"], ["index"])
        self.assertEqual(result["stop_reason"], "no_certifying_completion_from_available_queries")

    def test_budgets_and_decimal_costs(self):
        record = load_responses(FIXTURE / "responses-positive.json", self.panel)
        for limit in (0, 1, 2):
            result = run_policy(self.panel, builtin_policy("cheapest_relevant"), record.__getitem__, max_attempts=limit)
            self.assertLessEqual(result["query_attempts"], limit)
            self.assertEqual(result["stop_reason"], "attempt_budget_exhausted")
        for limit in (0, 1, 2, 3, 7):
            result = run_policy(self.panel, builtin_policy("cheapest_relevant"), record.__getitem__, max_cost=limit)
            self.assertLessEqual(Fraction(result["total_cost_exact"]), limit)
            self.assertEqual(result["stop_reason"], "cost_budget_exhausted")
        document = {"schema_version": "1.0", "instance_id": "decimal-budget", "candidates": ["a", "b", "c"],
                    "pick": "a", "quorum": 1, "judges": [{"id": "j", "tiers": [["b", "c"], ["a"]]}],
                    "eligibility": {"positive": ["a"], "negative": []}, "costs": {"b": 0.1, "c": 0.2}}
        result = run_policy(panel_from_dict(document), builtin_policy("cheapest_relevant"), lambda candidate: 0, max_cost=0.3)
        self.assertEqual((result["verdict"], result["query_attempts"], result["total_cost_exact"]), (1, 2, "3/10"))
        document["costs"] = {"b": 0, "c": 0}
        result = run_policy(panel_from_dict(document), builtin_policy("cheapest_relevant"), lambda candidate: 0, max_cost=0)
        self.assertEqual((result["verdict"], result["query_attempts"], result["total_cost"]), (1, 2, 0))
        for kwargs in ({"max_attempts": -1}, {"max_attempts": True}, {"max_attempts": 1.5},
                       {"max_cost": -1}, {"max_cost": float("inf")}, {"max_cost": True}):
            with self.assertRaises(InputError):
                run_policy(self.panel, builtin_policy("cheapest_relevant"), record.__getitem__, **kwargs)

    def test_minimum_recorded_certificate_is_not_acquisition_cost(self):
        record = load_responses(FIXTURE / "responses-negative.json", self.panel)
        result = run_policy(self.panel, builtin_policy("cheapest_relevant"), record.__getitem__)
        self.assertEqual(result["total_cost"], 3)
        self.assertEqual(result["certificate"]["cost"], 2)
        self.assertEqual(result["certificate"]["labels"], {"overview": 1})
        self.assertNotIn("handbook", result["certificate"]["candidates"])

    def test_exact_json_and_cli_decimal_boundaries(self):
        prefix = ('{"schema_version":"1.0","instance_id":"precision",'
                  '"candidates":["a","b"],"pick":"a","quorum":1,'
                  '"judges":[{"id":"j","tiers":[["b"],["a"]]}],'
                  '"eligibility":{"positive":["a"],"negative":[]},"costs":{"b":')
        with tempfile.TemporaryDirectory() as folder:
            panel_path = Path(folder) / "panel.json"
            response_path = Path(folder) / "responses.json"
            response_path.write_text('{"schema_version":"1.0","responses":{"b":0}}', encoding="utf-8")
            for cost, below in (("0.100000000000000001", Decimal("0.1")),
                                ("1e-400", Decimal(0)),
                                ("1e400", Decimal("9e399"))):
                panel_path.write_text(prefix + cost + "}}", encoding="utf-8")
                panel = load_panel(panel_path)
                self.assertEqual(panel.costs[1], Fraction(Decimal(cost)))
                refused = run_policy(panel, builtin_policy("cheapest_relevant"), lambda _: 0, max_cost=below)
                self.assertEqual((refused["query_attempts"], refused["stop_reason"]), (0, "cost_budget_exhausted"))
                accepted = run_policy(panel, builtin_policy("cheapest_relevant"), lambda _: 0, max_cost=Decimal(cost))
                self.assertEqual((accepted["query_attempts"], accepted["verdict"]), (1, 1))
                self.assertEqual(Fraction(accepted["total_cost_exact"]), Fraction(Decimal(cost)))
                self.assertEqual(Fraction(accepted["certificate"]["cost_exact"]), Fraction(Decimal(cost)))
                if cost == "1e-400":
                    self.assertIsNone(accepted["total_cost"], "tiny positive cost must not be displayed as free")
            for cost, budget, expected_attempts in (("1", "0.999999999999999999", 0),
                                                    ("0.100000000000000001", "0.1", 0),
                                                    ("1e-400", "0", 0),
                                                    ("1e-400", "1e-400", 1)):
                panel_path.write_text(prefix + cost + "}}", encoding="utf-8")
                completed = subprocess.run([sys.executable, "-S", str(ROOT / "reuse_demo.py"),
                                            "--panel", str(panel_path), "--responses", str(response_path),
                                            "--max-cost", budget], text=True, capture_output=True, check=True)
                self.assertEqual(json.loads(completed.stdout)["query_attempts"], expected_attempts)
        for invalid in (Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-1e-400")):
            with self.assertRaises(InputError):
                run_policy(self.panel, builtin_policy("cheapest_relevant"), lambda _: 0, max_cost=invalid)

    def test_random_panels_against_complete_tier_worlds(self):
        rng = random.Random(20261013)
        plugin = load_plugin(ROOT / "examples" / "cost_sensitive_policy.py")
        for trial in range(500):
            ids = [f"c{i}" for i in range(rng.randint(2, 6))]
            judges = []
            for j in range(rng.randint(1, 4)):
                ranks = {c: rng.randrange(3) for c in ids}
                judges.append({"id": f"j{j}", "tiers": [[c for c in ids if ranks[c] == rank] for rank in sorted(set(ranks.values()))]})
            labels = {c: rng.choice((None, None, 0, 1)) for c in ids}
            available = [c for c in ids if labels[c] is None and rng.random() < 0.8]
            document = {"schema_version": "1.0", "instance_id": f"check-{trial}", "candidates": ids,
                        "pick": rng.choice(ids), "quorum": rng.randint(1, len(judges)), "judges": judges,
                        "eligibility": {"positive": [c for c in ids if labels[c] == 1],
                                        "negative": [c for c in ids if labels[c] == 0]},
                        "available": available, "costs": {c: rng.choice((0, 0.25, 1, 2.5)) for c in ids}, "synthetic": True}
            panel = panel_from_dict(document)
            records = {c: rng.choice((0, 1, None)) for c in available}
            all_p = set(panel.positive) | {ids.index(c) for c, a in records.items() if a == 1}
            all_n = set(panel.negative) | {ids.index(c) for c, a in records.items() if a == 0}
            expected_terminal = direct_outcomes(panel, all_p, all_n)
            COUNTS["random_panels"] += 1
            for name, choose in (("max", builtin_policy("max_blockers")),
                                 ("cheapest", builtin_policy("cheapest_relevant")), ("plugin", plugin)):
                with self.subTest(trial=trial, policy=name):
                    result = run_policy(panel, choose, records.__getitem__, policy_name=name)
                    COUNTS["policy_runs"] += 1
                    self.assertEqual(set(result["possible_outcomes"]), expected_terminal)
                    p = {ids.index(c) for c in result["final_positive"]}
                    n = {ids.index(c) for c in result["final_negative"]}
                    self.assertEqual(set(result["possible_outcomes"]), direct_outcomes(panel, p, n))
                    trace_ids = [ids.index(item["candidate"]) for item in result["trace"]]
                    self.assertEqual(len(trace_ids), len(set(trace_ids)))
                    self.assertLessEqual(set(trace_ids), panel.available)
                    self.assertEqual(Fraction(result["total_cost_exact"]), sum((panel.costs[c] for c in trace_ids), Fraction(0)))
                    if result["status"] == "certified":
                        cost, count, witness = direct_minimum(panel, result)
                        self.assertEqual(result["certificate"]["cost_exact"], str(cost))
                        self.assertEqual(result["certificate"]["size"], count)
                        self.assertEqual(result["certificate"]["candidates"], list(panel.names(witness)))
                    else:
                        remaining = {ids.index(c) for c in result["unqueried_available"]}
                        self.assertFalse(direct_can_finish(panel, p, n, remaining))

    def test_reproducible_complete_demo(self):
        actual = demonstration()
        expected = read_json(FIXTURE / "expected-results.json")
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual["results"]), 18)
        self.assertTrue(actual["csv_matches_json"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PublicWorkflowTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {"passed": result.wasSuccessful(), "tests_run": result.testsRun,
              "failures": len(result.failures), "errors": len(result.errors),
              **COUNTS, "seed": 20261013,
              "reference": "Independent enumeration of eligible subsets and first surviving complete tiers; not blocker formulas."}
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
