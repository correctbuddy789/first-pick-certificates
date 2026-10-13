#!/usr/bin/env python3
"""Run an end-to-end synthetic reuse demonstration, or an external fixture.

No network calls, dependencies, or private records. A --plugin is trusted local
Python code exposing choose(PolicyState); executing it is not sandboxed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from panel_io import InputError, load_panel, load_responses
from policy_runner import builtin_policy, run_policy

ROOT = Path(__file__).resolve().parent


def decimal_argument(value):
    """Preserve a command-line cost's decimal spelling before validation."""
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("expected a decimal number") from exc


def load_plugin(path):
    path = Path(path).resolve()
    spec = importlib.util.spec_from_file_location("certificate_user_policy", path)
    if spec is None or spec.loader is None:
        raise InputError("plugin: could not import the supplied Python file")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    choose = getattr(module, "choose", None)
    if not callable(choose):
        raise InputError("plugin: define a callable choose(state)")
    return choose


def run_fixture(panel_path, responses_path, *, policy="cheapest_relevant",
                plugin=None, max_attempts=None, max_cost=None):
    panel = load_panel(panel_path)
    responses = load_responses(responses_path, panel)
    choose = builtin_policy(policy) if plugin is None else load_plugin(plugin)
    result = run_policy(panel, choose, responses.__getitem__,
                        policy_name=policy if plugin is None else "plugin:" + Path(plugin).name,
                        max_attempts=max_attempts, max_cost=max_cost)
    result["strict_blockers"] = {judge: list(panel.names(blockers))
                                 for judge, blockers in zip(panel.judge_ids, panel.blockers)}
    return result


def demonstration():
    fixture = ROOT / "examples" / "open_resources"
    plugin = ROOT / "examples" / "cost_sensitive_policy.py"
    scenarios = [
        ("negative", "panel.json", "responses-negative.json", {}),
        ("positive", "panel.json", "responses-positive.json", {}),
        ("nonanswer", "panel.json", "responses-nonanswer.json", {}),
        ("unavailable", "panel-unavailable.json", "responses-unavailable.json", {}),
        ("cost_budget", "panel.json", "responses-positive.json", {"max_cost": 1}),
        ("attempt_budget", "panel.json", "responses-positive.json", {"max_attempts": 1}),
    ]
    results = []
    for name, panel, responses, budget in scenarios:
        for policy in ("max_blockers", "cheapest_relevant", "cost_per_active_judge"):
            result = run_fixture(fixture / panel, fixture / responses, policy=policy,
                                 plugin=plugin if policy == "cost_per_active_judge" else None,
                                 **budget)
            result["scenario"] = name
            results.append(result)
    return {"description": "Wholly synthetic illustrative workflow; not measured external use or a new human study.",
            "csv_matches_json": load_panel(fixture / "panel.json") == load_panel(fixture / "panel-csv.json"),
            "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, help="JSON panel with inline or CSV tiers")
    parser.add_argument("--responses", type=Path, help="separate synthetic/fixed replay responses")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--policy", default="cheapest_relevant",
                           choices=("max_blockers", "cheapest_relevant", "first_relevant"))
    selection.add_argument("--plugin", type=Path, help="trusted Python file with choose(state)")
    parser.add_argument("--max-attempts", type=int)
    parser.add_argument("--max-cost", type=decimal_argument)
    parser.add_argument("--out", type=Path, help="write JSON here instead of stdout")
    args = parser.parse_args()
    if (args.panel is None) != (args.responses is None):
        parser.error("--panel and --responses must be supplied together")
    if args.panel is None and (args.plugin is not None or args.max_attempts is not None or args.max_cost is not None
                               or args.policy != "cheapest_relevant"):
        parser.error("policy/plugin/budget options require --panel and --responses")
    try:
        result = demonstration() if args.panel is None else run_fixture(
            args.panel, args.responses, policy=args.policy, plugin=args.plugin,
            max_attempts=args.max_attempts, max_cost=args.max_cost)
    except (InputError, OSError) as exc:
        parser.error(str(exc))
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out is None:
        print(text, end="")
    else:
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
