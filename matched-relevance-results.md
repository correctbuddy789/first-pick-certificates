# Matched exact-relevance comparison

This amendment was fixed before these matched outcomes were run, after prior aggregate results were already known. It is not a preregistration. All 2,304 original synthetic cases, including initial certificates and final unresolved cases, and all four original tie seeds are retained (55,296 traces).

Each paired policy queries an available unknown pick first and then uses the same priority (uniform, cheapest, or maximum active-judge incidence), costs, fresh uniform tie rule and original terminal checks. Only the filter changes: the union of available blockers of currently unblocked judges versus exact relevance. Nonanswers cost the full amount and remain logically unknown.

## Reachable states

A meaningful state is a pre-query state whose verdict is ambiguous, with at least one available query, can_certify_with=True, and the pick not available. The next query is therefore not forced by the common pick-first rule. A distinct state is the tuple (instance ID, known-positive set, known-negative set, available set); it is deduplicated across all six policy variants and four tie slots within each instance, but shared structures in different design cells remain distinct.

Exact relevance is a strict subset in 4,709/60,858 distinct meaningful states (7.74%). At the visit level it is strict in 16,336/254,179 visits. In total 351/2,304 cases encounter a strict subset; 1,584/2,304 cases reach any meaningful state. These visits and cases are dependent design observations, not independent samples.

## Matched results

Averages first give each case the mean of its four tie slots, then weight cases equally. Exact-minus-active differences below isolate the filter in this fixed experiment; they do not decompose the original uniform-all comparison, which also differs in pick-first behavior.

| Scope | Priority | Cases | Active queries | Exact queries | Active cost | Exact cost | Exact cheaper / tied / dearer |
|---|---|---:|---:|---:|---:|---:|---|
| all | uniform | 2304 | 5.465386 | 5.364475 | 22.163628 | 21.737847 | 265 / 2005 / 34 |
| factorial | uniform | 2048 | 4.303101 | 4.189575 | 17.322998 | 16.843994 | 265 / 1749 / 34 |
| constructed | uniform | 256 | 14.763672 | 14.763672 | 60.888672 | 60.888672 | 0 / 256 / 0 |
| factorial_unit | uniform | 1024 | 4.284912 | 4.176025 | 4.284912 | 4.176025 | 134 / 871 / 19 |
| factorial_heterogeneous | uniform | 1024 | 4.321289 | 4.203125 | 30.361084 | 29.511963 | 131 / 878 / 15 |
| constructed_unit | uniform | 128 | 14.716797 | 14.716797 | 14.716797 | 14.716797 | 0 / 128 / 0 |
| constructed_heterogeneous | uniform | 128 | 14.810547 | 14.810547 | 107.060547 | 107.060547 | 0 / 128 / 0 |
| all | cheapest | 2304 | 5.384657 | 5.298177 | 17.354384 | 17.070964 | 237 / 2043 / 24 |
| factorial | cheapest | 2048 | 4.229004 | 4.131714 | 13.319458 | 13.000610 | 237 / 1787 / 24 |
| constructed | cheapest | 256 | 14.629883 | 14.629883 | 49.633789 | 49.633789 | 0 / 256 / 0 |
| factorial_unit | cheapest | 1024 | 4.284912 | 4.176025 | 4.284912 | 4.176025 | 134 / 871 / 19 |
| factorial_heterogeneous | cheapest | 1024 | 4.173096 | 4.087402 | 22.354004 | 21.825195 | 103 / 916 / 5 |
| constructed_unit | cheapest | 128 | 14.716797 | 14.716797 | 14.716797 | 14.716797 | 0 / 128 / 0 |
| constructed_heterogeneous | cheapest | 128 | 14.542969 | 14.542969 | 84.550781 | 84.550781 | 0 / 128 / 0 |
| all | max_incidence | 2304 | 5.174479 | 5.174262 | 21.158529 | 21.158312 | 1 / 2303 / 0 |
| factorial | max_incidence | 2048 | 3.975830 | 3.975586 | 16.192261 | 16.192017 | 1 / 2047 / 0 |
| constructed | max_incidence | 256 | 14.763672 | 14.763672 | 60.888672 | 60.888672 | 0 / 256 / 0 |
| factorial_unit | max_incidence | 1024 | 3.965332 | 3.964844 | 3.965332 | 3.964844 | 1 / 1023 / 0 |
| factorial_heterogeneous | max_incidence | 1024 | 3.986328 | 3.986328 | 28.419189 | 28.419189 | 0 / 1024 / 0 |
| constructed_unit | max_incidence | 128 | 14.716797 | 14.716797 | 14.716797 | 14.716797 | 0 / 128 / 0 |
| constructed_heterogeneous | max_incidence | 128 | 14.810547 | 14.810547 | 107.060547 | 107.060547 | 0 / 128 / 0 |

Exact filtering modestly reduces mean acquisition for uniform and cheapest selection here. Maximum-incidence selection already avoids almost all variables removed by exact filtering: its preferred set changes in only 3/41,112 active-policy meaningful visits, and the four-slot case means improve in only one case. Every constructed disjoint-group case has identical results between filters for each priority. The incremental value of exact filtering therefore depends on the acquisition policy and blocker structure.

Exact filtering can have a larger cost in an individual seeded pair: changing the choice set changes the random tie trajectory. Reusing a seed is a common-random-number control, not pathwise dominance. The report makes no population-performance or general monotonic-improvement claim.

All final outcomes match the same full-record verdict, including 338 unresolved cases. All initial certificates retain zero acquisition cost. The 13,824 original active uniform/max-incidence aggregate query, cost and nonanswer totals match exactly. At all 60,858 distinct meaningful states, mask relevance agrees with the separately implemented absorbed-DNF relevance; an explicit four-world tier example independently checks a redundant active blocker.
