# Posthoc policy explanation

All differences are cached DNF round robin minus the stated comparator, averaged over each case’s four stored slots. The DNF slots are deterministic duplicates. Strata overlap and reuse latent design draws; these are benchmark descriptions, not population estimates or causal effects.

## Heterogeneous factorial: DNF versus cheapest relevance

Across 512 cases, DNF is cheaper on 171, dearer on 134, and tied on 207. Mean costs are 16.488281 and 17.305176; paired difference -0.816895.

| Factor | Level | Cases | DNF cost | Cheapest cost | Difference | Cheaper / tied / dearer |
|---|---|---:|---:|---:|---:|---|
| judges | 4 | 256 | 14.348 | 14.922 | -0.574 | 77 / 114 / 65 |
| judges | 8 | 256 | 18.629 | 19.688 | -1.060 | 94 / 93 / 69 |
| candidates | 12 | 256 | 13.574 | 14.161 | -0.587 | 89 / 106 / 61 |
| candidates | 40 | 256 | 19.402 | 20.449 | -1.047 | 82 / 101 / 73 |
| expected_blockers | 2 | 256 | 13.266 | 14.201 | -0.936 | 82 / 107 / 67 |
| expected_blockers | 6 | 256 | 19.711 | 20.409 | -0.698 | 89 / 100 / 67 |
| overlap | 0.0 | 256 | 19.211 | 20.557 | -1.346 | 94 / 99 / 63 |
| overlap | 0.75 | 256 | 13.766 | 14.054 | -0.288 | 77 / 108 / 71 |
| known_probability | 0.0 | 256 | 19.332 | 20.400 | -1.068 | 109 / 65 / 82 |
| known_probability | 0.25 | 256 | 13.645 | 14.210 | -0.565 | 62 / 142 / 52 |
| eligibility_probability | 0.1 | 256 | 26.055 | 27.772 | -1.718 | 90 / 95 / 71 |
| eligibility_probability | 0.4 | 256 | 6.922 | 6.838 | +0.084 | 81 / 112 / 63 |
| quorum_name | strict_majority | 256 | 21.227 | 22.049 | -0.822 | 93 / 95 / 68 |
| quorum_name | unanimity | 256 | 11.750 | 12.562 | -0.812 | 78 / 112 / 66 |
| outcome | negative | 416 | 9.844 | 10.668 | -0.825 | 158 / 145 / 113 |
| outcome | positive | 96 | 45.281 | 46.065 | -0.784 | 13 / 62 / 21 |
| initially_ambiguous | 0 | 82 | 0.000 | 0.000 | +0.000 | 0 / 82 / 0 |
| initially_ambiguous | 1 | 430 | 19.633 | 20.605 | -0.973 | 171 / 125 / 134 |
| absorbed_term_bin | 0 | 82 | 0.000 | 0.000 | +0.000 | 0 / 82 / 0 |
| absorbed_term_bin | 1 | 288 | 14.351 | 15.280 | -0.930 | 108 / 98 / 82 |
| absorbed_term_bin | 17+ | 24 | 48.750 | 57.323 | -8.573 | 19 / 2 / 3 |
| absorbed_term_bin | 2-4 | 89 | 25.551 | 25.489 | +0.062 | 33 / 24 / 32 |
| absorbed_term_bin | 5-16 | 29 | 29.828 | 28.112 | +1.716 | 11 / 1 / 17 |

## Unit-cost coverage-negative reversal

Across 32 constructed cases, DNF uses 13.562500 queries versus 12.664062 for pick-first maximum blockers (difference +0.898438); cheaper / tied / dearer cases: 10 / 0 / 22.

## Deterministically selected traces

For each requested direction, take the lexicographically first qualifying case by its four-slot mean; then take the lowest replicate with that paired sign. These illustrate mechanisms, not typical cases. The JSON includes blockers, conditioned DNF terms, every physical query and the DNF virtual scheduler ledger.

### factorial_allen_cheaper: f0002, replicate 0

Initial eligible []; ineligible []; quorum 3 of 4; terms [[0, 2, 3, 9, 11], [0, 2, 3, 4, 5, 8, 10], [0, 3, 4, 5, 8, 9, 10, 11]].

- allen_round_robin_cached: 2 queries, cost 5; candidate:eligibility@cost = 10:0@1, 0:0@4.
- cheapest_relevant: 4 queries, cost 13; candidate:eligibility@cost = 10:0@1, 4:0@4, 2:0@4, 0:0@4.

### factorial_allen_dearer: f0075, replicate 0

Initial eligible []; ineligible []; quorum 4 of 4; terms [[0, 2, 3, 4, 5, 6, 7, 11]].

- allen_round_robin_cached: 2 queries, cost 2; candidate:eligibility@cost = 2:0@1, 6:1@1.
- cheapest_relevant: 1 queries, cost 1; candidate:eligibility@cost = 6:1@1.

### coverage_negative_allen_dearer: c0001, replicate 0

Initial eligible [0]; ineligible []; quorum 2 of 4; terms [[3, 4, 23, 29], [3, 14, 19, 23], [3, 23, 28, 30], [4, 14, 19, 29], [4, 28, 29, 30], [14, 19, 28, 30]].

- allen_round_robin_cached: 8 queries, cost 8; candidate:eligibility@cost = 3:1@1, 4:0@1, 14:0@1, 23:0@1, 19:1@1, 29:0@1, 28:0@1, 30:1@1.
- pick_first_max_blockers: 4 queries, cost 4; candidate:eligibility@cost = 3:1@1, 19:1@1, 29:0@1, 30:1@1.

## What the traces explain

In f0002, both methods first acquire cheap candidate 10. The DNF scheduler next acquires the pick, whose ineligibility certifies a negative verdict, for cost 5. Cheapest relevance instead selects two equally priced competitors before the pick, for cost 13. In f0075, the negative verdict requires only one eligible blocker under unanimity: a uniform cost tie places that blocker first for cheapest relevance, while deterministic DNF ordering first tests another equally cheap candidate. This is a tie-order loss, not an example of cost domination.

In c0001, eligibility of candidate 3 already blocks the judge whose blockers are {3,23}. Nevertheless, the one-certificate DNF stream later tests candidate 23 while completing its initially chosen term {3,4,23,29}. That variable is no longer globally relevant. The other extra queries in this trace reflect the two methods’ different ordering. The adapter follows Section 5.2’s term-completion rule and keeps private stream histories; common global stopping still ends the run as soon as a certificate exists. Thus this trace gives one explicit source of extra work, not a complete explanation of the 32-case mean.

Primary algorithm checked: [Allen et al., Section 5.2, author manuscript p.14](https://www.cs.cmu.edu/afs/cs/user/srallen/www/papers/dnfeval.pdf). The published Algorithmica version remains the paper’s bibliography entry; the author copy was used to inspect the algorithm.

The matched filter experiment is separate and holds pick-first and priority fixed; this posthoc DNF comparison does not isolate a single algorithmic component.
