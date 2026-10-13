"""Exact certificates for a fixed first pick under uncertain eligibility.

Standard-library implementation. No data access, networking, or dependencies.
The functions assume complete, fixed ordinal tiers, a fixed quorum from 1 to
the number of judges, disjoint consistent labels, and unrestricted binary
completions of unknown labels. Blockers exclude the target pick. Query costs
are additive and nonnegative. These guarantees concern the specified rule,
not whether a human eligibility judgment is substantively correct.
"""
from __future__ import annotations
import itertools
import statistics
from functools import lru_cache


def bit_positions(mask):
    while mask:
        b = mask & -mask
        yield b.bit_length() - 1
        mask ^= b


def classify(positive, negative, pick, blockers, quorum):
    """Return exact {0}, {1}, or {0,1} support over binary completions.

positive/negative and each blocker set contain integer candidate indices.
All candidates not in positive|negative are uncertain.
"""
    if pick in negative:
        return frozenset({0})
    maximum = sum(not (b & positive) for b in blockers)
    if maximum < quorum:
        return frozenset({0})
    minimum = sum(b <= negative for b in blockers)
    if pick in positive and minimum >= quorum:
        return frozenset({1})
    return frozenset({0, 1})


def relevant_candidates(positive, negative, available, uncertain,
                        pick, blockers, quorum):
    """Return the available variables that can change the membership bit.

    A candidate is relevant if two consistent binary completions differing
    only at that candidate have different outcomes. ``uncertain`` contains
    the entire original (or current) unknown universe; known labels are
    subtracted here. In particular, it MUST include queried nonanswers:
    ``available`` restricts returned choices, not admissible completions.

    Reachability records the judges blocked by a subset of the other unknown
    non-pick candidates. With q = m - quorum + 1, a non-pick variable c is
    relevant when popcount(R) < q <= popcount(R | M(c)) for a reachable R.
    An unknown pick is relevant exactly when fewer than q judges are already
    blocked. This uses O(|U|^2 2^m) mask transitions for all variables and
    O(2^m) working masks, after incidence masks are built; m-bit operations
    are treated as constant time. No answer probabilities or costs are used.
    """
    unknown = set(uncertain) - positive - negative
    choices = set(available) & unknown
    if pick in negative or not choices:
        return frozenset()
    threshold = len(blockers) - quorum + 1
    initial = sum(1 << j for j, b in enumerate(blockers) if b & positive)
    if initial.bit_count() >= threshold:
        return frozenset()
    masks = {c: 0 for c in unknown - {pick}}
    for j, b in enumerate(blockers):
        for c in b & unknown:
            masks[c] |= 1 << j
    # Equal incidence masks are interchangeable. A union uses each distinct
    # mask at most once, but excluding c removes its mask only if c is the
    # sole unknown candidate carrying it. Availability never changes counts.
    groups = {}
    for c, mask in masks.items():
        mask &= ~initial
        masks[c] = mask
        if mask:
            groups.setdefault(mask, set()).add(c)
    relevant = {pick} & choices
    for cover, candidates in groups.items():
        if not (candidates & choices):
            continue
        found = (initial | cover).bit_count() >= threshold
        reachable = {initial}
        for mask in groups:
            if found:
                break
            if mask == cover and len(candidates) == 1:
                continue
            added = set()
            for state in reachable:
                new = state | mask
                # Masks already at the threshold cannot become a witness.
                if new.bit_count() < threshold:
                    if (new | cover).bit_count() >= threshold:
                        found = True
                        break
                    added.add(new)
            reachable |= added
        if found:
            relevant.update(candidates & choices)
    return frozenset(relevant)


def dnf_relevant_candidates(positive, negative, available, uncertain,
                            pick, blockers, quorum):
    """Exact comparator using absorbed monotone-DNF quorum terms.

    A feasible term requires the pick eligible and the strict blockers of h
    judges ineligible. Remove fixed literals, discard terms with known
    eligible blockers, and absorb duplicate/superset terms. In a monotone
    DNF exactly the variables in the remaining minimal terms are relevant.
    As in relevant_candidates, unavailable unknowns stay in the terms; only
    the final returned set is restricted to available. Enumerating at most
    binomial(m, h) terms can be faster than mask reachability for small m.
    """
    unknown = set(uncertain) - positive - negative
    choices = set(available) & unknown
    if pick in negative or not choices:
        return frozenset()
    eligible_judges = [b for b in blockers if not (b & positive)]
    terms = set()
    for judges in itertools.combinations(eligible_judges, quorum):
        term = (set().union(*judges) - negative) & unknown
        if pick in unknown:
            term.add(pick)
        if not term:
            return frozenset()
        terms.add(frozenset(term))
    minimal = []
    for term in sorted(terms, key=lambda s: (len(s), tuple(sorted(s)))):
        if not any(smaller <= term for smaller in minimal):
            minimal.append(term)
    return frozenset(set().union(*minimal) & choices)


def minimum_certificate(known_positive, known_negative, observed_positive,
                        observed_negative, pick, blockers, quorum, target,
                        costs=None):
    """Return an observed, minimum-cost sufficient certificate.

Only binary outcomes that exist in the historical record can be used.
Unresolved historical answers are unavailable. Does not inspect human
preference adjudications. Returns None if observed evidence cannot certify.
Unit costs give minimum cardinality. Costs must be finite and nonnegative.
"""
    import math
    costs = costs or {}
    if target not in (0, 1):
        raise ValueError("target must be 0 or 1")
    if any(not math.isfinite(v) or v < 0 for v in costs.values()):
        raise ValueError("query costs must be finite and nonnegative")
    def key(items):
        return (sum(costs.get(c, 1) for c in items), len(items), tuple(sorted(items)))
    candidates = []
    if target == 1:
        if pick not in known_positive | observed_positive:
            return None
        eligible_judges = [j for j, b in enumerate(blockers)
                           if b <= known_negative | observed_negative]
        for judges in itertools.combinations(eligible_judges, quorum):
            need = set().union(*(blockers[j] for j in judges)) - known_negative
            if pick not in known_positive:
                need.add(pick)
            candidates.append(frozenset(need))
    else:
        if pick in known_negative:
            return frozenset()
        if pick in observed_negative:
            candidates.append(frozenset({pick}))
        initial = sum(1 << j for j, b in enumerate(blockers) if b & known_positive)
        threshold = len(blockers) - quorum + 1
        dp = {initial: frozenset()}
        for c in sorted(observed_positive - known_positive):
            covers = sum(1 << j for j, b in enumerate(blockers) if c in b)
            for mask, used in tuple(dp.items()):
                newmask, newused = mask | covers, used | {c}
                old = dp.get(newmask)
                if old is None or key(newused) < key(old):
                    dp[newmask] = newused
        candidates += [s for mask, s in dp.items() if mask.bit_count() >= threshold]
    if not candidates:
        return None
    return min(candidates, key=key)


def truth_table(positive, uncertain, pick, blockers, quorum):
    values = []
    for mask in range(1 << len(uncertain)):
        eligible = positive | {uncertain[i] for i in bit_positions(mask)}
        support = sum(not (b & eligible) for b in blockers)
        values.append(int(pick in eligible and support >= quorum))
    return tuple(values)


def decision_tree(values, n):
    """Minimize worst-case binary-query depth; break ties by query index.

Bitset recursion considers each ternary partial assignment at most once.
This is an exact small-instance baseline, not the scalable contribution.
"""
    truth = sum(v << i for i, v in enumerate(values))
    all_worlds = (1 << len(values)) - 1
    branches = [sum(1 << w for w in range(len(values)) if w & (1 << i))
                for i in range(n)]

    @lru_cache(None)
    def solve(worlds, available):
        if not (worlds & truth) or not (worlds & (all_worlds ^ truth)):
            return 0, None
        best = (n + 1, None)
        for i in bit_positions(available):
            yes, no = worlds & branches[i], worlds & (all_worlds ^ branches[i])
            # Irrelevant variables cannot improve a decision tree.
            if yes == 0 or no == 0:
                continue
            left = solve(no, available ^ (1 << i))[0]
            if 1 + left >= best[0]:
                continue
            right = solve(yes, available ^ (1 << i))[0]
            candidate = (1 + max(left, right), i)
            if candidate[0] < best[0]:
                best = candidate
        return best

    depth, _ = solve(all_worlds, (1 << n) - 1)
    return solve, branches, all_worlds, truth, depth


def replay(positive, negative, uncertain, observed, pick, blockers, quorum,
           method, values=None):
    """Sequential replay; the policy never sees an answer before querying.

For the heuristic, candidate priority is computed only from the current
positive/negative labels, fixed tiers, and fixed candidate-index order. If an
adjudicator historically remained unresolved, record the query and do not
repeat it. Stop when the verdict is certified or no unqueried input remains.
"""
    pos, neg = set(positive), set(negative)
    remaining, asked = set(uncertain), []
    while len(classify(pos, neg, pick, blockers, quorum)) > 1 and remaining:
        if not can_certify_with(pos, neg, remaining, pick, blockers, quorum):
            break
        if method == "pick_then_blockers":
            if pick in remaining:
                chosen = pick
            else:
                open_judges = [b for b in blockers if not (b & pos)]
                chosen = min(remaining, key=lambda c: (
                    -sum(c in b for b in open_judges), c))
        elif method == "candidate_order":
            chosen = min(remaining)
        else:
            raise ValueError(method)
        answer = observed.get(chosen)
        asked.append((chosen, answer))
        remaining.remove(chosen)
        if answer == 1:
            pos.add(chosen)
        elif answer == 0:
            neg.add(chosen)
    final = classify(pos, neg, pick, blockers, quorum)
    return {"queries": len(asked), "unresolved_answers": sum(v is None for _, v in asked),
            "certified": len(final) == 1, "possible_outcomes": sorted(final),
            "query_indices": [c for c, _ in asked]}


def can_certify_with(positive, negative, available, pick, blockers, quorum):
    """Could any answers to unqueried items determine the verdict?

Previously queried nonanswers remain uncertain. Unateness makes the two
favorable endpoint completions exact, without treating unknown as false.
"""
    own = {pick} & available
    others = available - {pick}
    positive_end = classify(positive | own, negative | others, pick, blockers, quorum)
    negative_end = classify(positive | others, negative | own, pick, blockers, quorum)
    return positive_end == {1} or negative_end == {0}


def random_order_expectation(positive, negative, uncertain, observed, pick, blockers, quorum):
    """Exact mean query count for a uniformly random permutation.

This integrates a prespecified random ordering over historical answers;
the query distribution never depends on hidden answers. The identical
certification and unanswerability stopping rules apply to all policies.
"""
    @lru_cache(None)
    def expected(asked_mask):
        asked = {uncertain[i] for i in bit_positions(asked_mask)}
        pos = positive | {c for c in asked if observed.get(c) == 1}
        neg = negative | {c for c in asked if observed.get(c) == 0}
        remaining = set(uncertain) - asked
        if len(classify(pos, neg, pick, blockers, quorum)) == 1:
            return 0.0
        if not remaining or not can_certify_with(pos, neg, remaining, pick, blockers, quorum):
            return 0.0
        indices = [i for i, c in enumerate(uncertain) if c in remaining]
        return 1 + statistics.mean(expected(asked_mask | (1 << i)) for i in indices)
    return expected(0)


