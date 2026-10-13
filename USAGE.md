# Using the certificate toolkit on another panel

The toolkit answers whether one fixed candidate belongs to a quorum top set.
Its inputs are complete, fixed preference tiers and partly known binary
eligibility. It does not infer missing preferences or decide whether an
eligibility judgment is substantively correct.

## Input contract

| Input | Representation and meaning |
| --- | --- |
| Candidate pool | A finite collection of distinct integer indices. |
| `pick` | The index of the fixed candidate being audited. |
| `blockers` | One set per judge, containing precisely the candidates strictly preferred to the pick. Ties are excluded. Derive each set from a complete tier order. |
| `positive`, `negative` | Disjoint sets of known eligible and known ineligible candidates. |
| `uncertain` | All candidates whose eligibility remains unknown; the relevance API also accepts the original unknown universe and subtracts revealed labels. |
| `available` | Unknown candidates that can still be queried. A failed query removes availability without fixing eligibility. |
| `quorum` | Integer from one to the number of judges, inclusive. |
| `costs` | Optional finite, nonnegative cost by candidate index. Omitted entries default to one in certificate extraction. |

Every binary assignment of the unknown labels is permitted. The caller is
responsible for these input assumptions; the functions are not a general
schema-validation layer. For tiers `tiers[j][c]` with lower values preferred,
construct `blockers[j]` as `{c for c in candidates if tiers[j][c] < tiers[j][pick]}`.

## Three operations and their outputs

1. `classify(positive, negative, pick, blockers, quorum)` returns `{1}` for
   certified membership, `{0}` for certified nonmembership, or `{0, 1}` for
   an unresolved verdict. Nonmembership alone need not identify a replacement.
2. `minimum_certificate(positive, negative, observed_positive,
   observed_negative, pick, blockers, quorum, target, costs=None)` returns
   a minimum-cost subset of the recorded binary answers, or `None` when
   no such subset certifies the requested target. It has hindsight access
   to those answer signs and is not an online query policy.
3. `relevant_candidates(positive, negative, available, uncertain, pick,
   blockers, quorum)` returns the available candidates whose eligibility
   can change the verdict under some admissible completion. The equivalent
   `dnf_relevant_candidates` provides an independent algorithmic comparator.

`can_certify_with(positive, negative, available, pick, blockers, quorum)`
tests whether some answers to the remaining queries could certify either
verdict. If the current verdict is unresolved and this returns `False`,
stop without substituting a binary verdict.

## Worked example

Run `python3 walkthrough.py`. It reproduces the paper's three-judge example
and follows two possible answer branches, including an unanswered query.
The example uses illustrative inputs, not applicant records.

To add a query policy, choose using only the current tiers/blockers, costs,
availability, and revealed labels. Do not expose the response record before
selection. Charge every attempt. After a binary answer, update eligibility;
after any attempt, remove that candidate from `available`. Test certification
and `can_certify_with` after each update. Keep unavailable unknowns in
`uncertain` throughout relevance calculations.

## Reproduction and extensions

`README.md` lists commands for independent verification and for the fixed
synthetic study. The synthetic generators and expected-cost models permit
comparisons of alternative priorities under the same terminal rule. Preserve
initially certified and unresolved cases in the stated denominators. Runtime
values vary by machine. Historical aggregate results are included, while
the original applicant records and individual judgments remain restricted.
