#!/usr/bin/env python3
# Copyright (c) 2026 Tushar Nain. SPDX-License-Identifier: MIT
"""One choose(state) workflow for imported panels and the published benchmark.

The seven canonical adapters preserve the frozen extension's tie seeds and
choices. Replay records remain behind a post-selection answer callback. The
original study, comparator implementations, and stored results are read only.
See BENCHMARK.md for examples, assumptions, and prefix-budget semantics.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

from benchmark_extensions import ALL_METHODS, selected_instances
from computational_study import GuardedResponses, stable_seed
from dnf_baselines import AllenRoundRobinCached, cost_normalized_blocker_choices
from panel_io import InputError, load_panel, load_responses, panel_from_dict
from policy_runner import _core_costs, _number, run_policy
from query_policies import MaskContext, selectable
from reuse_demo import decimal_argument, load_plugin

ROOT = Path(__file__).resolve().parent


def benchmark_cases(design=None):
    """Generate all 1,152 frozen binary-extension cases, in their original order.

    These evaluator-side instances INCLUDE replay answers and provenance.
    Never pass an instance to a policy. panel_from_instance strips answers
    and latent metadata before constructing the public structural input.
    """
    if design is None:
        design = json.loads((ROOT / "computational_design.json").read_text())
    yield from selected_instances(design)


def panel_from_instance(instance):
    """Realize a generated blocker profile as complete weak orders.

    Each judge ranks its blockers, then the pick, then every other candidate.
    This deterministic realization preserves precisely the fixed-pick target;
    it does not recover an original ordering among the non-pick candidates.
    Initial eligibility and acquisition costs are preserved without rounding.
    """
    n = instance["meta"]["candidates"]
    ids = tuple(f"c{c}" for c in range(n))
    pick = instance["pick"]
    judges = []
    for j, blockers in enumerate(instance["blockers"]):
        tiers = [sorted(blockers), [pick],
                 [c for c in range(n) if c != pick and c not in blockers]]
        judges.append({"id": f"j{j}",
                       "tiers": [[ids[c] for c in tier] for tier in tiers if tier]})
    panel = panel_from_dict({
        "schema_version": "1.0", "instance_id": instance["meta"]["instance"],
        "candidates": list(ids), "pick": ids[pick], "judges": judges,
        "quorum": instance["quorum"],
        "eligibility": {"positive": [ids[c] for c in sorted(instance["positive"])],
                        "negative": [ids[c] for c in sorted(instance["negative"])]},
        "costs": {ids[c]: instance["costs"].get(c, 1) for c in range(n)},
        "cost_unit": "synthetic acquisition-cost units", "synthetic": True,
        "description": "Equivalent complete weak orders for a frozen synthetic blocker profile."})
    if panel.blockers != tuple(instance["blockers"]) or panel.uncertain != tuple(instance["uncertain"]):
        raise AssertionError("benchmark import changed the fixed-pick problem")
    return panel


class CanonicalPolicy:
    """State-only adapter with seeded ties and optional private DNF streams.

    Create a fresh instance per run. In prefix-budget mode canonical choices
    use available, not affordable; the runner stops before an unpaid choice.
    Allen observations are synchronized from already revealed public state,
    including the final answer when the common stopping rule terminates.
    """

    def __init__(self, method, seed):
        if method not in ALL_METHODS:
            raise InputError(f"unknown benchmark policy: {method}")
        self.method = method
        self.rng = random.Random(seed)
        self.context = None
        self.dnf = None
        self.scale = Fraction(1)
        self.pending = None
        self.requires_binary_answers = method == "allen_round_robin_cached"

    def _observe_revealed(self, positive, negative):
        if self.dnf is None or self.pending is None:
            return
        if self.pending in positive:
            self.dnf.observe(self.pending, 1)
        elif self.pending in negative:
            self.dnf.observe(self.pending, 0)
        else:
            raise InputError("Allen comparator requires a binary answer to its previous query")
        self.pending = None

    def __call__(self, state):
        if self.context is None:
            public = {"positive": set(state.positive), "negative": set(state.negative),
                      "uncertain": state.uncertain, "pick": state.pick,
                      "blockers": state.blockers, "quorum": state.quorum,
                      "costs": _core_costs(state.costs)}
            self.context = MaskContext(public)
            self.scale = max(Fraction(1), *state.costs)
            if self.requires_binary_answers:
                self.dnf = AllenRoundRobinCached(public)
                variables = set().union(*self.dnf.terms) if self.dnf.terms else set()
                if not variables <= state.available:
                    raise InputError("Allen comparator requires every untested DNF variable available")
        self._observe_revealed(state.positive, state.negative)
        if self.dnf is not None:
            chosen = self.dnf.choose(set(state.positive), set(state.negative),
                                     set(state.available))
            self.pending = chosen
            return chosen
        if self.method == "pick_first_cost_normalized_blockers":
            choices = cost_normalized_blocker_choices(
                set(state.positive), set(state.negative), set(state.available),
                state.pick, state.blockers, _core_costs(state.costs))
        else:
            choices = selectable(set(state.positive), set(state.negative),
                                 set(state.available), state.pick, state.blockers,
                                 state.quorum, self.method, self.context,
                                 _core_costs(state.costs))
        if not choices or not set(choices) <= state.available:
            raise InputError(f"{self.method}: no valid next query")
        # Even a singleton choice consumes RNG state, as in replay_extension.
        return self.rng.choice(sorted(choices))

    def finish(self, result, panel):
        """Finish accounting using only the returned acquired-answer trace."""
        if self.pending is not None:
            # A budget-blocked choice has no answer and must not be observed.
            acquired = {panel.candidate_ids.index(row["candidate"]): row["answer"]
                        for row in result["trace"]}
            if self.pending in acquired:
                bit = acquired[self.pending]
                if bit not in (0, 1):
                    raise InputError("Allen comparator supports binary answers only")
                self._observe_revealed({self.pending} if bit else set(),
                                       set() if bit else {self.pending})
        if self.dnf is None:
            cost = Fraction(result["total_cost_exact"])
            return {"virtual_queries": result["query_attempts"],
                    "virtual_cost": _number(cost), "virtual_cost_exact": str(cost),
                    "cached_virtual_queries": 0}
        diagnostic = self.dnf.diagnostics()
        virtual_cost = Fraction(diagnostic["virtual_cost"]) * self.scale
        return {"virtual_queries": diagnostic["virtual_queries"],
                "virtual_cost": _number(virtual_cost), "virtual_cost_exact": str(virtual_cost),
                "cached_virtual_queries": diagnostic["cached_virtual_queries"],
                "terms": diagnostic["terms"],
                "private_ledger_costs_exact": [str(Fraction(s.cost) * self.scale)
                                               for s in self.dnf.streams]}


def policy_factory(method, seed=0):
    """Return a fresh canonical choose(PolicyState) callable; no answers passed."""
    return CanonicalPolicy(method, seed)


def run_case(panel, answer, method="cheapest_relevant", seed=0, *, choose=None,
             max_attempts=None, max_cost=None):
    """Run either an imported panel or converted benchmark through one path.

    choose overrides the canonical policy and must be a fresh callable for
    each run if stateful. No policy receives the answer callback. Canonical
    methods retain their unbudgeted choices; custom policies may use budgets.
    """
    policy = policy_factory(method, seed) if choose is None else choose

    def acquire(candidate_id):
        response = answer(candidate_id)
        if getattr(policy, "requires_binary_answers", False) and (
                type(response) is not int or response not in (0, 1)):
            raise InputError("Allen comparator supports binary answers only; nonanswers are unsupported")
        return response

    result = run_policy(panel, policy, acquire, policy_name=method,
                        max_attempts=max_attempts, max_cost=max_cost, budget_mode="prefix")
    result["budget_mode"] = "prefix"
    if isinstance(policy, CanonicalPolicy):
        result["policy_diagnostics"] = policy.finish(result, panel)
    return result


def run_instance(instance, method="cheapest_relevant", replicate=0, *, choose=None,
                 max_attempts=None, max_cost=None, original_seed=None):
    """Replay one evaluator-side generated case, with the original tie seed."""
    if type(replicate) is not int or replicate < 0:
        raise InputError("replicate: expected a nonnegative integer")
    if original_seed is None:
        original_seed = json.loads((ROOT / "computational_design.json").read_text())["seed"]
    panel = panel_from_instance(instance)
    responses = GuardedResponses(instance["observed"])
    index = {candidate: c for c, candidate in enumerate(panel.candidate_ids)}

    def acquire(candidate):
        c = index[candidate]
        responses.permit(c)
        return responses[c]

    seed = stable_seed(original_seed, "tie", panel.instance_id, replicate)
    result = run_case(panel, acquire, method, seed, choose=choose,
                      max_attempts=max_attempts, max_cost=max_cost)
    result["replicate"] = replicate
    result["tie_seed"] = seed
    # Provenance belongs to results, not PolicyState.
    result["benchmark_metadata"] = dict(instance["meta"])
    return result


def summarize_results(results):
    """Descriptive run-slot means; retain unresolved and initial certificates."""
    groups = defaultdict(list)
    for result in results:
        groups[result["policy"]].append(result)
    summary = {"runs": len(results), "instances": len({r["instance_id"] for r in results}),
               "unit_of_summary": "run slot; tie slots are not independent observations",
               "policies": {}}
    for method, rows in groups.items():
        n = len(rows)
        cost = sum((Fraction(r["total_cost_exact"]) for r in rows), Fraction(0)) / n
        summary["policies"][method] = {
            "runs": n, "instances": len({r["instance_id"] for r in rows}),
            "certified": sum(r["status"] == "certified" for r in rows),
            "unresolved": sum(r["status"] != "certified" for r in rows),
            "mean_query_attempts": sum(r["query_attempts"] for r in rows) / n,
            "mean_cost": _number(cost), "mean_cost_exact": str(cost),
            "stop_reasons": dict(Counter(r["stop_reason"] for r in rows))}
    return summary


def _csv_row(result):
    return {"instance": result["instance_id"], "method": result["policy"],
            "replicate": result["replicate"], "status": result["status"],
            "outcome": ("positive" if result["verdict"] == 1 else "negative")
                       if result["status"] == "certified" else "unresolved",
            "stop_reason": result["stop_reason"], "queries": result["query_attempts"],
            "cost": result["total_cost"], "cost_exact": result["total_cost_exact"],
            "nonanswers": result["nonanswers"],
            "trace_json": json.dumps(result["trace"], separators=(",", ":"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--benchmark", choices=("binary-extension",))
    source.add_argument("--panel", type=Path)
    parser.add_argument("--responses", type=Path)
    parser.add_argument("--policy", action="append", choices=ALL_METHODS,
                        help="repeat to compare policies; default all seven")
    parser.add_argument("--plugin", action="append", type=Path,
                        help="trusted local choose(state) file; repeat to add policies")
    parser.add_argument("--instance", action="append", help="benchmark ID; repeat to select cases")
    parser.add_argument("--replicates", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0,
                        help="imported-panel tie seed; benchmark retains its frozen seed")
    parser.add_argument("--max-cost", type=decimal_argument)
    parser.add_argument("--max-attempts", type=int)
    parser.add_argument("--jsonl-out", type=Path, help="complete per-run records and traces")
    parser.add_argument("--csv-out", type=Path, help="per-run metrics and trace_json column")
    parser.add_argument("--summary-out", type=Path)
    args = parser.parse_args()
    if args.replicates < 1:
        parser.error("--replicates must be positive")
    if bool(args.panel) != bool(args.responses):
        parser.error("--responses is required exactly when --panel is used")
    if args.instance and not args.benchmark:
        parser.error("--instance applies only to --benchmark")
    methods = list(dict.fromkeys(args.policy or ALL_METHODS))
    plugins = args.plugin or []
    if len({p.resolve() for p in plugins}) != len(plugins) or len({p.name for p in plugins}) != len(plugins):
        parser.error("plug-in paths and basenames must be unique in a batch")
    specifications = [(method, None) for method in methods] + [("plugin:" + p.name, p) for p in plugins]
    results = []
    try:
        if args.benchmark:
            design = json.loads((ROOT / "computational_design.json").read_text())
            cases = list(benchmark_cases(design))
            if args.instance:
                wanted = set(args.instance)
                found = {case["meta"]["instance"] for case in cases}
                if not wanted <= found:
                    raise InputError(f"unknown or nonbinary benchmark IDs: {sorted(wanted - found)}")
                cases = [case for case in cases if case["meta"]["instance"] in wanted]
            for case in cases:
                for method, plugin in specifications:
                    for rep in range(args.replicates):
                        result = run_instance(case, method, rep,
                            choose=load_plugin(plugin) if plugin else None,
                            max_cost=args.max_cost, max_attempts=args.max_attempts,
                            original_seed=design["seed"])
                        results.append(result)
        else:
            panel = load_panel(args.panel)
            responses = load_responses(args.responses, panel)
            for method, plugin in specifications:
                for rep in range(args.replicates):
                    seed = stable_seed(args.seed, "tie", panel.instance_id, rep)
                    result = run_case(panel, responses.__getitem__, method, seed,
                        choose=load_plugin(plugin) if plugin else None,
                        max_cost=args.max_cost, max_attempts=args.max_attempts)
                    result.update(replicate=rep, tie_seed=seed)
                    results.append(result)
        summary = summarize_results(results)
        summary["source_sha256"] = {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("benchmark_runner.py", "policy_runner.py", "computational_design.json",
                         "extension-design.json")}
        summary["budget_semantics"] = "canonical unbudgeted choice order; stop before unaffordable next query"
        if args.jsonl_out:
            with args.jsonl_out.open("w", encoding="utf-8") as stream:
                for result in results:
                    stream.write(json.dumps(result, sort_keys=True) + "\n")
        if args.csv_out:
            with args.csv_out.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(_csv_row(results[0])))
                writer.writeheader()
                writer.writerows(_csv_row(result) for result in results)
        text = json.dumps(summary, indent=2, sort_keys=True) + "\n"
        if args.summary_out:
            args.summary_out.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
    except (InputError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
