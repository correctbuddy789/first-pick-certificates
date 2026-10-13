"""Version 1.0 JSON/CSV input contract for complete fixed-tier panel audits.

Only standard-library modules are used. Validation happens at the boundary;
the mathematical core continues to use integer candidate indices. JSON object
keys are strict so that, for example, a misspelled availability field cannot
silently turn an unavailable unknown into an available query.
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType

SCHEMA_VERSION = "1.0"


class InputError(ValueError):
    """An input does not satisfy the documented finite-panel contract."""


def _object(value, where, allowed, required=()):
    if not isinstance(value, dict):
        raise InputError(f"{where}: expected an object")
    extra, missing = set(value) - set(allowed), set(required) - set(value)
    if extra or missing:
        raise InputError(f"{where}: unknown fields {sorted(extra)}; missing fields {sorted(missing)}")


def _identifier(value, where):
    if not isinstance(value, str) or not value or value.strip() != value:
        raise InputError(f"{where}: expected a nonempty string without surrounding whitespace")
    return value


def _ids(value, where, universe=None, nonempty=False):
    if not isinstance(value, list):
        raise InputError(f"{where}: expected an array")
    result = tuple(_identifier(v, where) for v in value)
    if len(set(result)) != len(result) or (nonempty and not result):
        raise InputError(f"{where}: identifiers must be unique" + (" and nonempty" if nonempty else ""))
    if universe is not None and not set(result) <= set(universe):
        raise InputError(f"{where}: unknown candidate identifiers")
    return result


def cost_fraction(value, where="cost"):
    """Read a finite, nonnegative JSON number, rejecting booleans.

    Decimal spelling is interpreted exactly for addition/budget comparisons:
    0.1 + 0.2 consumes exactly 0.3 units. Inputs remain ordinary JSON numbers.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, Fraction)):
        raise InputError(f"{where}: expected a finite nonnegative number")
    # Do not coerce Decimal or Fraction through float: tiny positive decimal
    # costs must not become free, and large finite values are still finite.
    finite = value.is_finite() if isinstance(value, Decimal) else (
        math.isfinite(value) if isinstance(value, float) else True)
    valid = finite and value >= 0
    if not valid:
        raise InputError(f"{where}: expected a finite nonnegative number")
    if isinstance(value, (Decimal, Fraction, int)):
        return Fraction(value)
    # A caller supplying a float has already rounded it. Interpret its public
    # decimal spelling; use Decimal/Fraction when the original precision matters.
    return Fraction(str(value))


def _tier_indices(candidate_ids, tiers, where):
    if not isinstance(tiers, (list, tuple)) or not tiers:
        raise InputError(f"{where}: expected nonempty tiers, best first")
    index = {c: i for i, c in enumerate(candidate_ids)}
    flat, result = [], []
    for level, tier in enumerate(tiers, 1):
        if not isinstance(tier, (list, tuple)) or not tier:
            raise InputError(f"{where}: tier {level} must be nonempty")
        row = [_identifier(c, where) for c in tier]
        if not set(row) <= set(index):
            raise InputError(f"{where}: unknown candidate in tier {level}")
        flat.extend(row)
        result.append(tuple(index[c] for c in row))
    if len(flat) != len(candidate_ids) or set(flat) != set(candidate_ids):
        raise InputError(f"{where}: each candidate must occur exactly once")
    return tuple(result)


def complete_tiers_to_blockers(candidate_ids, pick, judges_tiers):
    """Convert complete weak orders (best tier first) to strict blocker sets.

    ``candidate_ids`` defines stable integer indices. ``judges_tiers`` is an
    iterable of complete nested lists of candidate identifiers, one per judge.
    A candidate tied with the pick is NOT a strict blocker.
    """
    candidate_ids = _ids(list(candidate_ids), "candidates", nonempty=True)
    if pick not in candidate_ids:
        raise InputError("pick: unknown candidate identifier")
    pick_index = candidate_ids.index(pick)
    result = []
    for j, tiers in enumerate(judges_tiers):
        converted = _tier_indices(candidate_ids, tiers, f"judge {j + 1}")
        prior = set()
        for tier in converted:
            if pick_index in tier:
                result.append(frozenset(prior))
                break
            prior.update(tier)
    if not result:
        raise InputError("judges: at least one complete order is required")
    return tuple(result)


@dataclass(frozen=True, slots=True)
class Panel:
    """Validated public problem description, with no future answers."""

    instance_id: str
    candidate_ids: tuple[str, ...]
    judge_ids: tuple[str, ...]
    tiers: tuple[tuple[tuple[int, ...], ...], ...]
    pick: int
    blockers: tuple[frozenset[int], ...]
    quorum: int
    positive: frozenset[int]
    negative: frozenset[int]
    uncertain: tuple[int, ...]
    available: frozenset[int]
    costs: tuple[Fraction, ...]
    cost_unit: str
    synthetic: bool
    description: str

    def names(self, indices):
        return tuple(self.candidate_ids[c] for c in sorted(indices))

    def core_instance(self):
        """Return fresh containers compatible with certificates/query_policies."""
        return {"positive": set(self.positive), "negative": set(self.negative),
                "uncertain": self.uncertain, "pick": self.pick,
                "blockers": self.blockers, "quorum": self.quorum,
                "costs": dict(enumerate(self.costs))}


def _csv_judges(path, candidate_ids):
    rows = {}
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["judge_id", "candidate_id", "tier"]:
            raise InputError("tiers CSV: header must be judge_id,candidate_id,tier")
        for line, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise InputError(f"tiers CSV line {line}: wrong number of fields")
            judge = _identifier(row["judge_id"], f"tiers CSV line {line}")
            candidate = _identifier(row["candidate_id"], f"tiers CSV line {line}")
            if candidate not in candidate_ids:
                raise InputError(f"tiers CSV line {line}: unknown candidate")
            try:
                rank = int(row["tier"])
            except ValueError as exc:
                raise InputError(f"tiers CSV line {line}: tier must be a positive integer") from exc
            if rank < 1 or str(rank) != row["tier"]:
                raise InputError(f"tiers CSV line {line}: tier must be a canonical positive integer")
            seen = rows.setdefault(judge, {})
            if candidate in seen:
                raise InputError(f"tiers CSV line {line}: duplicate judge/candidate pair")
            seen[candidate] = rank
    if not rows:
        raise InputError("tiers CSV: no complete judge orders")
    result = []
    for judge, ranks in rows.items():
        if set(ranks) != set(candidate_ids):
            raise InputError(f"tiers CSV: judge {judge} does not rank every candidate")
        levels = sorted(set(ranks.values()))
        result.append({"id": judge,
                       "tiers": [[c for c in candidate_ids if ranks[c] == level]
                                 for level in levels]})
    return result


def panel_from_dict(document, *, csv_base=None):
    """Validate schema 1.0; CSV paths are relative to the JSON's directory."""
    fields = {"schema_version", "instance_id", "candidates", "pick", "quorum",
              "judges", "tiers_csv", "eligibility", "available", "costs",
              "cost_unit", "synthetic", "description"}
    _object(document, "panel", fields,
            {"schema_version", "instance_id", "candidates", "pick", "quorum", "eligibility"})
    if document["schema_version"] != SCHEMA_VERSION:
        raise InputError(f"schema_version: expected {SCHEMA_VERSION}")
    instance_id = _identifier(document["instance_id"], "instance_id")
    ids = _ids(document["candidates"], "candidates", nonempty=True)
    index = {c: i for i, c in enumerate(ids)}
    pick_id = _identifier(document["pick"], "pick")
    if pick_id not in index:
        raise InputError("pick: unknown candidate identifier")
    if ("judges" in document) == ("tiers_csv" in document):
        raise InputError("panel: supply exactly one of judges or tiers_csv")
    if "tiers_csv" in document:
        if csv_base is None:
            raise InputError("tiers_csv: a CSV base directory is required")
        relative = Path(_identifier(document["tiers_csv"], "tiers_csv"))
        base = Path(csv_base).resolve()
        resolved = (base / relative).resolve()
        if relative.is_absolute() or not resolved.is_relative_to(base):
            raise InputError("tiers_csv: path must remain inside the JSON directory")
        judges = _csv_judges(resolved, ids)
    else:
        judges = document["judges"]
    if not isinstance(judges, list) or not judges:
        raise InputError("judges: expected a nonempty array")
    judge_ids, tiers, tier_names = [], [], []
    for j, judge in enumerate(judges):
        _object(judge, f"judges[{j}]", {"id", "tiers"}, {"id", "tiers"})
        judge_ids.append(_identifier(judge["id"], f"judges[{j}].id"))
        tiers.append(_tier_indices(ids, judge["tiers"], f"judges[{j}].tiers"))
        tier_names.append(judge["tiers"])
    if len(set(judge_ids)) != len(judge_ids):
        raise InputError("judges: identifiers must be unique")
    quorum = document["quorum"]
    if isinstance(quorum, bool) or not isinstance(quorum, int) or not 1 <= quorum <= len(judges):
        raise InputError("quorum: integer between one and the number of judges required")
    labels = document["eligibility"]
    _object(labels, "eligibility", {"positive", "negative"}, {"positive", "negative"})
    positive = frozenset(index[c] for c in _ids(labels["positive"], "eligibility.positive", ids))
    negative = frozenset(index[c] for c in _ids(labels["negative"], "eligibility.negative", ids))
    if positive & negative:
        raise InputError("eligibility: positive and negative labels must be disjoint")
    uncertain = tuple(c for c in range(len(ids)) if c not in positive | negative)
    if "available" in document:
        available = frozenset(index[c] for c in _ids(document["available"], "available", ids))
    else:
        available = frozenset(uncertain)
    if not available <= set(uncertain):
        raise InputError("available: only initially unknown candidates can be queried")
    cost_map = document.get("costs", {})
    _object(cost_map, "costs", set(ids))
    costs = tuple(cost_fraction(cost_map.get(c, 1), f"costs.{c}") for c in ids)
    cost_unit = _identifier(document.get("cost_unit", "query-cost units"), "cost_unit")
    synthetic = document.get("synthetic", False)
    if not isinstance(synthetic, bool):
        raise InputError("synthetic: expected a Boolean")
    description = document.get("description", "")
    if not isinstance(description, str):
        raise InputError("description: expected a string")
    return Panel(instance_id, ids, tuple(judge_ids), tuple(tiers), index[pick_id],
                 complete_tiers_to_blockers(ids, pick_id, tier_names), quorum,
                 positive, negative, uncertain, available, costs, cost_unit,
                 synthetic, description)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"JSON: duplicate key {key!r}")
        result[key] = value
    return result


def _reject_constant(value):
    raise InputError(f"JSON: invalid number {value}")


def read_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        try:
            return json.load(stream, object_pairs_hook=_unique_object, parse_float=Decimal,
                             parse_constant=_reject_constant)
        except json.JSONDecodeError as exc:
            raise InputError(f"JSON: {exc}") from exc


def load_panel(path):
    path = Path(path)
    return panel_from_dict(read_json(path), csv_base=path.parent)


def responses_from_dict(document, panel):
    """Validate a separate fixed response record for replay, not policy input.

    Every initially available unknown must have exactly one explicit 0, 1,
    or null entry. Missing data are errors, not implicit negative/nonanswers.
    An unavailable unknown has no replay entry and remains logically free.
    """
    _object(document, "response record", {"schema_version", "responses"},
            {"schema_version", "responses"})
    if document["schema_version"] != SCHEMA_VERSION:
        raise InputError(f"response schema_version: expected {SCHEMA_VERSION}")
    expected = set(panel.names(panel.available))
    _object(document["responses"], "responses", expected, expected)
    for candidate, answer in document["responses"].items():
        if answer is not None and (type(answer) is not int or answer not in (0, 1)):
            raise InputError(f"responses.{candidate}: expected integer 0, integer 1, or null")
    return MappingProxyType(dict(document["responses"]))


def load_responses(path, panel):
    return responses_from_dict(read_json(path), panel)
