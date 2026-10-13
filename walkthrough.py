#!/usr/bin/env python3
"""Executable three-judge example from the paper; no private data needed."""
from certificates import classify, relevant_candidates, minimum_certificate, can_certify_with


def main():
    # 0=a (the fixed pick), 1=b, 2=c, 3=d (tied with a).
    blockers = (frozenset({1}), frozenset({2}), frozenset())
    positive, negative = frozenset({0}), frozenset()
    unknown = frozenset({1, 2, 3})
    relevant = relevant_candidates(positive, negative, unknown, unknown, 0, blockers, 2)
    assert classify(positive, negative, 0, blockers, 2) == {0, 1}
    assert relevant == {1, 2}
    print("Initial verdict: unresolved; relevant queries: b, c; tied d is irrelevant.")

    # One negative eligibility answer provides a positive membership certificate.
    certificate = minimum_certificate(positive, negative, frozenset(), frozenset({1}),
                                      0, blockers, 2, 1)
    assert set(certificate) == {1}
    assert classify(positive, frozenset({1}), 0, blockers, 2) == {1}
    print("If b is ineligible: membership is certified by the single answer about b.")

    # Different branch: b returns no answer; c is still worth asking.
    available = frozenset({2, 3})
    assert relevant_candidates(positive, negative, available, unknown, 0, blockers, 2) == {2}
    assert can_certify_with(positive, negative, available, 0, blockers, 2)
    print("If b gives no answer: b remains unknown; c is still a relevant query.")

    # If c then proves eligible, an unanswered b is indispensable.
    positive = positive | {2}
    available = frozenset({3})
    assert classify(positive, negative, 0, blockers, 2) == {0, 1}
    assert not can_certify_with(positive, negative, available, 0, blockers, 2)
    print("If c then proves eligible: stop unresolved; querying d cannot settle membership.")


if __name__ == "__main__":
    main()
