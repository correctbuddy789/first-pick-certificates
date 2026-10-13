# Additional acquisition benchmark: internal design amendment

This design was frozen after the initial computational results and the independent internal review, before evaluating the added policies. It is not a preregistration. `extension-design.json` is the authoritative machine-readable design and records hashes of the unchanged original code, design, and outputs.

Reuse all 1,024 factorial cases with zero nonanswer probability and all 128 constructed positive-multilabel and coverage-negative cases. Retain initially certified cases and every pick-eligibility outcome. Compare the original five methods with a pick-first cost-normalized blocker rule and the Allen et al. cost-balanced round-robin policy adapted to cache physical answers and share the original stopping contract. All seven methods use the same costs, responses, and initial information.

The round-robin implementation retains separate virtual test histories and full virtual cost ledgers. The adapter charges each physical query once and stops on the combined evidence. The report will distinguish these operational changes from the source algorithm and make no approximation-theorem claim. No failed-query instance enters this comparison.

The four original tie seeds are retained for each instance. The Allen comparator uses deterministic index tie breaks, so its four slots are identical and are not independent replications. Full per-trace results, all method values, paired differences, denominators, and exploratory construction/selection overhead will be released. The original five method totals must reproduce the frozen original CSV exactly.

Primary algorithm source: [Allen et al., author manuscript](https://www.cs.cmu.edu/afs/cs/user/srallen/www/papers/dnfeval.pdf), Section 5.2 and Algorithm 1. The full design specifies conversion, branch behavior, caching, terminal checks, and independent verification.
