"""Public policy callback and one-attempt-per-candidate query runner.

The selector receives immutable fixed structure and revealed state. The answer
callback is called only AFTER selection. This is an information-flow contract,
not a sandbox against malicious Python code reading files or process memory.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math

from certificates import can_certify_with, classify, minimum_certificate
from panel_io import InputError, Panel, cost_fraction
from query_policies import MaskContext, selectable


@dataclass(frozen=True, slots=True)
class PolicyState:
    """Public callback input; all candidate references are stable integer indices.

    ``uncertain`` retains the ORIGINAL unknown universe. ``available`` removes
    every attempted query, including nonanswers. ``affordable`` is available
    intersected with the remaining cost budget; ``relevant`` is availability-
    restricted exact logical relevance, independent of affordability.
    """

    candidate_ids: tuple[str, ...]
    tiers: tuple[tuple[tuple[int, ...], ...], ...]
    pick: int
    blockers: tuple[frozenset[int], ...]
    quorum: int
    positive: frozenset[int]
    negative: frozenset[int]
    uncertain: tuple[int, ...]
    available: frozenset[int]
    relevant: frozenset[int]
    affordable: frozenset[int]
    costs: tuple[Fraction, ...]
    attempts_used: int
    cost_used: Fraction
    remaining_attempts: int | None
    remaining_cost: Fraction | None


def builtin_policy(name):
    """Deterministic adapters for existing policies; ties use candidate order.

    Names: ``max_blockers`` (pick first, then max active-judge incidence),
    ``cheapest_relevant``, and ``first_relevant`` (fixed order, NOT random).
    These adapters use existing query_policies.selectable without modifying it.
    """
    names = {"max_blockers": "pick_first_max_blockers",
             "cheapest_relevant": "cheapest_relevant",
             "first_relevant": "uniform_relevant"}
    if name not in names:
        raise InputError(f"unknown built-in policy: {name}")

    def choose(state):
        instance = {"uncertain": state.uncertain, "pick": state.pick,
                    "blockers": state.blockers, "quorum": state.quorum}
        context = MaskContext(instance)
        choices = selectable(set(state.positive), set(state.negative),
                             set(state.affordable), state.pick, state.blockers,
                             state.quorum, names[name], context,
                             _core_costs(state.costs))
        if not choices:
            raise InputError(f"{name}: no affordable candidate was selected")
        return min(choices)

    return choose


def _number(value):
    """Convenience numeric display; the paired *_exact string is authoritative."""
    if value.denominator == 1:
        return value.numerator
    try:
        approximate = float(value)
    except OverflowError:
        return None
    if not math.isfinite(approximate) or (value and not approximate):
        return None
    return approximate


def _core_costs(costs):
    """Preserve exact cost comparisons within the core's float-finiteness check.

    Dividing every cost by one common positive scale changes neither minima
    nor ties. Core routines therefore handle finite Decimal-derived values
    beyond float range without modifying their implementation. Reporting and
    budgets always use the original unscaled Fractions.
    """
    scale = max(Fraction(1), *costs)
    return {c: value / scale for c, value in enumerate(costs)}


def run_policy(panel: Panel, choose, answer, *, policy_name="custom",
               max_attempts=None, max_cost=None):
    """Run a fixed panel audit with external selection and answer callbacks.

    ``choose(PolicyState) -> int`` selects an available affordable index.
    ``answer(candidate_id) -> 0 | 1 | None`` supplies the acquired response.
    Any nonanswer still consumes one attempt and its complete stated cost.
    Budgets are optional user-imposed stops, not the benchmark's logical
    terminal rule. No selected query can exceed either supplied budget.

    The certificate minimizes additive cost among the REVEALED binary labels,
    relative to the initial labels. It cannot use unqueried response records.
    This hindsight witness cost is distinct from the total acquisition cost.
    """
    if not isinstance(panel, Panel):
        raise InputError("run_policy requires a Panel returned by load_panel/panel_from_dict")
    if max_attempts is not None and (type(max_attempts) is not int or max_attempts < 0):
        raise InputError("max_attempts: expected a nonnegative integer or None")
    budget = None if max_cost is None else cost_fraction(max_cost, "max_cost")
    p, n, available = set(panel.positive), set(panel.negative), set(panel.available)
    acquired_positive, acquired_negative = set(), set()
    context = MaskContext(panel.core_instance())
    spent, trace = Fraction(0), []
    while True:
        outcomes = classify(p, n, panel.pick, panel.blockers, panel.quorum)
        if len(outcomes) == 1:
            reason = "certified"
            break
        if not can_certify_with(p, n, available, panel.pick, panel.blockers, panel.quorum):
            reason = "no_certifying_completion_from_available_queries"
            break
        if max_attempts is not None and len(trace) >= max_attempts:
            reason = "attempt_budget_exhausted"
            break
        relevant = context.relevant(p, n, available)
        remaining_cost = None if budget is None else budget - spent
        affordable = {c for c in available if remaining_cost is None or panel.costs[c] <= remaining_cost}
        if not (affordable & relevant):
            reason = "cost_budget_exhausted"
            break
        state = PolicyState(panel.candidate_ids, panel.tiers, panel.pick,
                            panel.blockers, panel.quorum, frozenset(p), frozenset(n),
                            panel.uncertain, frozenset(available), relevant,
                            frozenset(affordable), panel.costs, len(trace), spent,
                            None if max_attempts is None else max_attempts - len(trace),
                            remaining_cost)
        chosen = choose(state)
        if type(chosen) is not int or chosen not in affordable:
            raise InputError("policy must return one currently available, affordable integer index")
        # No response is consulted before this point.
        response = answer(panel.candidate_ids[chosen])
        if response is not None and (type(response) is not int or response not in (0, 1)):
            raise InputError("answer callback must return integer 0, integer 1, or None")
        available.remove(chosen)
        spent += panel.costs[chosen]
        if response == 1:
            p.add(chosen)
            acquired_positive.add(chosen)
        elif response == 0:
            n.add(chosen)
            acquired_negative.add(chosen)
        trace.append({"attempt": len(trace) + 1, "candidate": panel.candidate_ids[chosen],
                      "answer": response, "cost": _number(panel.costs[chosen]),
                      "cost_exact": str(panel.costs[chosen])})

    certified = len(outcomes) == 1
    verdict = next(iter(outcomes)) if certified else None
    witness = None
    if certified:
        indices = minimum_certificate(set(panel.positive), set(panel.negative),
                                      acquired_positive, acquired_negative,
                                      panel.pick, panel.blockers, panel.quorum,
                                      verdict, _core_costs(panel.costs))
        if indices is None:
            raise AssertionError("certification must have a recorded witness")
        cost = sum((panel.costs[c] for c in indices), Fraction(0))
        witness = {"candidates": list(panel.names(indices)),
                   "labels": {panel.candidate_ids[c]: int(c in acquired_positive)
                              for c in sorted(indices)},
                   "cost": _number(cost), "cost_exact": str(cost),
                   "size": len(indices), "relative_to_initial_labels": True}
    remaining_unknown = set(panel.uncertain) - p - n
    return {"schema_version": "1.0", "instance_id": panel.instance_id,
            "synthetic": panel.synthetic, "policy": policy_name,
            "status": "certified" if certified else "unresolved",
            "verdict": verdict, "possible_outcomes": sorted(outcomes),
            "stop_reason": reason, "query_attempts": len(trace),
            "nonanswers": sum(item["answer"] is None for item in trace),
            "total_cost": _number(spent), "total_cost_exact": str(spent),
            "cost_unit": panel.cost_unit, "certificate": witness, "trace": trace,
            "final_positive": list(panel.names(p)), "final_negative": list(panel.names(n)),
            "remaining_unknown": list(panel.names(remaining_unknown)),
            "unavailable_unknown": list(panel.names(remaining_unknown - available)),
            "unqueried_available": list(panel.names(available)),
            "relevant_available": list(panel.names(context.relevant(p, n, available)))}
