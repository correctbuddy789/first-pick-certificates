"""Additional acquisition policies; standard library, no data access.

Allen et al., Evaluation of Monotone DNF Formulas (Algorithmica, 2017), Section 5.2
and Algorithm 1 motivate AllenRoundRobinCached. This is an explicit adapter:
the two simulated algorithms retain private histories and full virtual costs,
while physical query answers are cached and the caller applies common early
certification. It is not the literal double-query cost experiment from the
proof, and this module makes no approximation guarantee. Binary answers only.

Public policy protocol: initialize with a structure-only instance; call
choose(positive, negative, available), acquire that answer, then observe(c, y).
The constructor and choose method never receive a hidden response mapping.
"""
from __future__ import annotations

import itertools
import math
from fractions import Fraction


def quorum_terms(instance, absorb=True):
    """Condition quorum membership into a monotone DNF.

    Variable c means eligible when c is the pick, ineligible otherwise.
    Empty tuple represents false; a tuple containing the empty set is true.
    All initially unknown variables remain in the model, regardless of query
    availability. Return immutable terms in size/index order.
    """
    p, n = set(instance["positive"]), set(instance["negative"])
    a, h = instance["pick"], instance["quorum"]
    unknown = set(instance["uncertain"]) - p - n
    if a in n:
        return ()
    viable = [set(b) for b in instance["blockers"] if not set(b) & p]
    terms = set()
    for panel in itertools.combinations(viable, h):
        term = (set().union(*panel) - n) & unknown
        if a in unknown:
            term.add(a)
        terms.add(frozenset(term))
    ordered = sorted(terms, key=lambda t: (len(t), tuple(sorted(t))))
    if not absorb:
        return tuple(ordered)
    minimal = []
    for term in ordered:
        if not any(other <= term for other in minimal):
            minimal.append(term)
    return tuple(minimal)


def dnf_value(terms, labels):
    """Return 0/1 when a monotone DNF is decided, otherwise None."""
    live = [term for term in terms if not any(labels.get(c) == 0 for c in term)]
    if not live:
        return 0
    if any(all(labels.get(c) == 1 for c in term) for term in live):
        return 1
    return None


def _validated_costs(variables, costs):
    result = {c: costs.get(c, 1) for c in variables}
    if any(not math.isfinite(v) or v < 0 for v in result.values()):
        raise ValueError("query costs must be finite and nonnegative")
    return result


def _ratio_choices(scores, costs):
    """Exact comparison for integer/rational costs; specified free-test tie."""
    scores = {c: v for c, v in scores.items() if v > 0}
    if not scores:
        return set()
    free = {c: v for c, v in scores.items() if costs[c] == 0}
    if free:
        high = max(free.values())
        return {c for c, v in free.items() if v == high}
    ratios = {c: Fraction(v) / Fraction(costs[c]) for c, v in scores.items()}
    high = max(ratios.values())
    return {c for c, value in ratios.items() if value == high}


def cost_normalized_blocker_choices(positive, negative, available, pick,
                                    blockers, costs):
    """Pick first; then maximize open-judge incidence per acquisition cost.

    An open judge has no known eligible blocker. This inexpensive comparator
    uses no exact relevance computation. Its caller owns stopping and ties.
    """
    available = set(available) - set(positive) - set(negative)
    costs = _validated_costs(available, costs)
    if pick in available:
        return {pick}
    open_judges = [set(b) for b in blockers if not set(b) & set(positive)]
    return _ratio_choices({c: sum(c in b for b in open_judges)
                           for c in available}, costs)


class _PrivateStream:
    """One source-algorithm stream; deliberately sees only its own tests."""

    def __init__(self, terms, costs, kind):
        self.terms, self.costs, self.kind = terms, costs, kind
        self.labels = {}
        self.cost = 0
        # Section 5.2 evaluates original conditioned terms in cost order.
        self.ordered_terms = sorted(terms,
                                    key=lambda t: (sum(costs[c] for c in t),
                                                   tuple(sorted(t))))

    def next_test(self):
        if dnf_value(self.terms, self.labels) is not None:
            return None
        if self.kind == 0:
            uncovered = [t for t in self.terms
                         if not any(self.labels.get(c) == 0 for c in t)]
            variables = set().union(*uncovered) - self.labels.keys()
            scores = {c: sum(c in t for t in uncovered) for c in variables}
            return min(_ratio_choices(scores, self.costs))
        # Do not abandon the current term on its first zero. Section 5.2
        # specifies all variables in the term; Section 5.1 is different.
        for term in self.ordered_terms:
            pending = term - self.labels.keys()
            if pending:
                return min(pending, key=lambda c: (self.costs[c], c))
        raise AssertionError("A fully tested DNF must have a value")

    def observe(self, candidate, bit):
        if candidate in self.labels:
            raise ValueError("A private stream cannot repeat its own test")
        self.labels[candidate] = bit
        self.cost += self.costs[candidate]


class AllenRoundRobinCached:
    """Cost-balanced private streams with one paid physical query per variable.

    Virtual step ledger entries expose source scheduling and cached accesses
    for verification. Ledger costs are diagnostic; paid acquisition cost is
    the sum over unique physically queried candidates. choose consumes only
    its own already-revealed cache between physical queries. Caller must stop
    on classify/can_certify_with; queries must return a binary eligibility bit.
    """

    def __init__(self, instance):
        self.pick = instance["pick"]
        self.terms = quorum_terms(instance)
        variables = set().union(*self.terms) if self.terms else set()
        self.costs = _validated_costs(variables, instance.get("costs", {}))
        self.streams = tuple(_PrivateStream(self.terms, self.costs, k)
                             for k in (0, 1))
        self.cache = {}
        self.pending = None
        self.virtual_trace = []

    def _take_virtual_step(self, branch, candidate, bit, cached, nexts):
        before = tuple(stream.cost for stream in self.streams)
        self.streams[branch].observe(candidate, bit)
        self.virtual_trace.append({"branch": branch, "candidate": candidate,
                                   "bit": bit, "cached": cached,
                                   "ledger_before": before,
                                   "next_tests": tuple(nexts),
                                   "ledger_after": tuple(s.cost for s in self.streams)})

    def choose(self, positive, negative, available):
        if self.pending is not None:
            raise ValueError("Observe the pending physical answer first")
        if dnf_value(self.terms, self.cache) is not None:
            raise StopIteration("The combined evidence already decides the DNF")
        while True:
            nexts = [s.next_test() for s in self.streams]
            if None in nexts:
                # A private certificate also decides the union of evidence.
                raise StopIteration("A private stream already has a certificate")
            totals = [s.cost + self.costs[c] for s, c in zip(self.streams, nexts)]
            branch = 0 if totals[0] <= totals[1] else 1
            candidate = nexts[branch]
            if candidate in self.cache:
                self._take_virtual_step(branch, candidate, self.cache[candidate],
                                        True, nexts)
                continue
            if candidate not in available:
                raise ValueError("Allen comparator requires every untested variable queryable")
            self.pending = branch, candidate, tuple(nexts)
            return candidate

    def observe(self, candidate, eligibility):
        if eligibility not in (0, 1):
            raise ValueError("Allen comparator supports binary answers only; not nonanswers")
        if self.pending is None or self.pending[1] != candidate:
            raise ValueError("Answer must match the pending physical query")
        if candidate in self.cache:
            raise ValueError("A physical query cannot be repeated")
        branch, _, nexts = self.pending
        bit = eligibility if candidate == self.pick else 1 - eligibility
        self.cache[candidate] = bit
        self._take_virtual_step(branch, candidate, bit, False, nexts)
        self.pending = None

    def diagnostics(self):
        return {"virtual_queries": len(self.virtual_trace),
                "virtual_cost": sum(s.cost for s in self.streams),
                "cached_virtual_queries": sum(step["cached"] for step in self.virtual_trace),
                "terms": len(self.terms)}
