"""Illustrative public policy plug-in; no answer record or data access.

After an available, affordable unknown pick is resolved, choose among exactly
relevant affordable competitors by cost / number of currently unblocked
judges they would block if eligible. Ties use input candidate order. This is
a heuristic with no claimed optimality or nonanswer robustness guarantee.
"""


def choose(state):
    if state.pick in state.affordable:
        return state.pick
    choices = state.relevant & state.affordable
    open_judges = [b for b in state.blockers if not (b & state.positive)]
    # Every relevant non-pick competes under at least one still-open judge.
    coverage = {c: sum(c in b for b in open_judges) for c in choices}
    if not choices or not all(coverage.values()):
        raise ValueError("the runner must supply a relevant affordable query")
    return min(choices, key=lambda c: (state.costs[c] / coverage[c], c))
