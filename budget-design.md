# Budgeted acquisition: frozen design

Fixed at 2026-10-13T13:17:20.171380+00:00, before computing any budgeted outcomes.

Design SHA-256: `046bcddb916cf27d6b0e28e97d93de43f60ede9fd7b4001d03024a295ddce549`. This is an internal design amendment, not a preregistration. Original study and extension inputs are hash-protected in `budget_design.json`.

The experiment asks how often an existing policy can finish an exact fixed-pick membership audit under a limited synthetic acquisition allowance. It keeps all 1,152 binary-answer extension cases: 1,024 factorial and 128 constructed, with all seven existing policies and the four original tie slots. Initial certificates remain in the main denominator. A secondary analysis conditions on initial ambiguity.

Budgets are exact fractions 0, 1/16, 1/8, 1/4, 1/2, and 1 of the total cost of every initially available query, including irrelevant candidates. This shared, policy-independent normalization describes synthetic units; it is not human time or monetary cost. The denominator depends on pool composition.

Each policy follows its canonical unbudgeted choices and stops before the next prescribed query if that query is unaffordable. It does not skip to cheaper alternatives. The experiment evaluates truncated canonical policies, not policies optimized for success under a budget.

All complete traces run through the public unified interface. Their budget prefixes can be extracted without rerunning policy selection. Direct budget calls independently check equivalence for 16 predetermined cases: the first four SHA-256-sorted identifiers in each phase-by-cost stratum, for all seven policies, four slots, and six budgets (2,688 calls). No subset is selected using performance.

Each instance receives equal weight after averaging its four tie slots. Deterministic DNF slots are repeated for alignment, not independent replications. Results are descriptive, with no population inference or confidence intervals. Four panels plot realized mean normalized acquisition cost against certification fraction, with points at the six fixed budgets.
