# Which policies finish when acquisition has a budget?

The resource supports a question beyond complete-audit cost: **given an acquisition allowance, what fraction of membership decisions can a policy certify?** `budget_study.py` asks this question through the same public runner used for imported panels and policy plug-ins. It uses synthetic cases already present in the resource; it adds no human study.

## Results

A method with a low mean cost to finish is not necessarily best at every interruption point. On the 512 unequal-cost factorial cases, a cap of one eighth of each instance’s initial available cost certifies 73.6% with cached DNF, 73.2% with cheapest relevance, and 56.7% with maximum blockers. Their actual mean spending is 4.30%, 4.35%, and 5.05% of the initial available total, respectively. Among the 430 initially ambiguous cases in this stratum, the corresponding certification fractions are 68.6%, 68.1%, and 48.4%.

The ordering can change with the allowance. On the 64 unit-cost constructed cases, cached DNF certifies 1.6% at the one-eighth cap, compared with 3.5% for cheapest relevance; at the one-quarter cap it certifies 32.8%, compared with 28.1%. These are descriptive comparisons of the fixed cases, not claims of universal superiority or a budget-optimal policy.

The tables give percentages certified at every frozen allowance. Each table retains its initial certificates and averages tie slots within each instance. Percentages are rounded to one decimal; the JSON and CSV retain exact values.

**Factorial, unit costs: n = 512; initially certified = 82; initially ambiguous = 430.**

| Policy | 0 | 1/16 | 1/8 | 1/4 | 1/2 | 1 |
|---|---:|---:|---:|---:|---:|---:|
| Uniform all | 16.0 | 20.1 | 30.7 | 43.9 | 62.5 | 100.0 |
| Pick + max blockers | 16.0 | 31.6 | 55.3 | 74.4 | 90.8 | 100.0 |
| Pick + uniform blockers | 16.0 | 29.8 | 52.6 | 70.8 | 89.4 | 100.0 |
| Uniform relevant | 16.0 | 31.1 | 49.8 | 71.1 | 89.9 | 100.0 |
| Cheapest relevant | 16.0 | 31.1 | 49.8 | 71.1 | 89.9 | 100.0 |
| Cost-normalized blockers | 16.0 | 31.6 | 55.3 | 74.4 | 90.8 | 100.0 |
| Cached DNF | 16.0 | 33.0 | 55.1 | 74.0 | 92.2 | 100.0 |

**Factorial, unequal costs: n = 512; initially certified = 82; initially ambiguous = 430.**

| Policy | 0 | 1/16 | 1/8 | 1/4 | 1/2 | 1 |
|---|---:|---:|---:|---:|---:|---:|
| Uniform all | 16.0 | 24.2 | 30.7 | 41.5 | 59.9 | 100.0 |
| Pick + max blockers | 16.0 | 42.6 | 56.7 | 74.4 | 90.0 | 100.0 |
| Pick + uniform blockers | 16.0 | 41.0 | 55.0 | 72.4 | 88.3 | 100.0 |
| Uniform relevant | 16.0 | 39.2 | 52.8 | 69.6 | 88.4 | 100.0 |
| Cheapest relevant | 16.0 | 63.7 | 73.2 | 83.7 | 93.5 | 100.0 |
| Cost-normalized blockers | 16.0 | 52.0 | 69.6 | 84.0 | 94.1 | 100.0 |
| Cached DNF | 16.0 | 66.0 | 73.6 | 84.4 | 94.5 | 100.0 |

**Constructed, unit costs: n = 64; initially certified = 0; initially ambiguous = 64.**

| Policy | 0 | 1/16 | 1/8 | 1/4 | 1/2 | 1 |
|---|---:|---:|---:|---:|---:|---:|
| Uniform all | 0.0 | 0.0 | 0.0 | 0.4 | 7.8 | 100.0 |
| Pick + max blockers | 0.0 | 0.4 | 3.5 | 28.1 | 79.7 | 100.0 |
| Pick + uniform blockers | 0.0 | 0.4 | 3.5 | 28.1 | 79.7 | 100.0 |
| Uniform relevant | 0.0 | 0.4 | 3.5 | 28.1 | 79.7 | 100.0 |
| Cheapest relevant | 0.0 | 0.4 | 3.5 | 28.1 | 79.7 | 100.0 |
| Cost-normalized blockers | 0.0 | 0.4 | 3.5 | 28.1 | 79.7 | 100.0 |
| Cached DNF | 0.0 | 0.0 | 1.6 | 32.8 | 78.1 | 100.0 |

**Constructed, unequal costs: n = 64; initially certified = 0; initially ambiguous = 64.**

| Policy | 0 | 1/16 | 1/8 | 1/4 | 1/2 | 1 |
|---|---:|---:|---:|---:|---:|---:|
| Uniform all | 0.0 | 0.0 | 0.4 | 0.4 | 7.8 | 100.0 |
| Pick + max blockers | 0.0 | 2.3 | 13.3 | 39.1 | 76.2 | 100.0 |
| Pick + uniform blockers | 0.0 | 2.3 | 13.3 | 39.1 | 76.2 | 100.0 |
| Uniform relevant | 0.0 | 2.3 | 13.3 | 39.1 | 76.2 | 100.0 |
| Cheapest relevant | 0.0 | 11.3 | 31.2 | 62.9 | 87.9 | 100.0 |
| Cost-normalized blockers | 0.0 | 11.3 | 31.2 | 62.9 | 87.9 | 100.0 |
| Cached DNF | 0.0 | 12.5 | 31.2 | 68.8 | 98.4 | 100.0 |

## Reproduce the experiment

The computation needs only Python's standard library:

```sh
python3 -S budget_study.py --run
python3 -S budget_study.py --verify-stored
```

The full run generates all complete traces through `benchmark_runner.run_instance`, then extracts their budget prefixes. An optional `--traces-input FILE` accepts the complete JSONL emitted by `verify_benchmark_runner.py --full-equivalence`. This saves duplicate replay; it does not substitute aggregate results or alter choices. The budget code checks every cached trace against the previous per-slot query counts, costs, and verdicts, and checks every certificate against its acquired labels. The result records the cache hash when this option is used. The cache is optional and can be regenerated from the public files.

```sh
python3 -S verify_benchmark_runner.py --full-equivalence \
  --traces-out unified-benchmark-traces.jsonl
python3 -S budget_study.py --run --traces-input unified-benchmark-traces.jsonl
```

Independently of caching, the script reruns 2,688 direct budgeted calls: 16 cases, seven policies, four tie slots, and six budgets. The 16 identifiers are fixed by an outcome-independent rule recorded in the design. Every direct trace, cost, verdict, and certificate must equal prefix extraction.

To render the figure after verification, install `matplotlib` in a separate environment and run:

```sh
python3 budget_study.py --figures
```

Plotting reads the stored results and does not recompute outcomes. The computational experiment has no plotting dependency.

## A single budgeted case

The canonical CLI uses an absolute budget in the panel's stated cost units:

```sh
python3 -S benchmark_runner.py --benchmark binary-extension \
  --instance f0000 --policy allen_round_robin_cached \
  --policy cheapest_relevant --replicates 4 --max-cost 3 \
  --jsonl-out budget-example.jsonl --summary-out budget-example.json
```

For exact instance-normalized budgets, use the Python API:

```python
from fractions import Fraction
from benchmark_runner import benchmark_cases, panel_from_instance, run_instance

case = next(benchmark_cases())
panel = panel_from_instance(case)
total_available_cost = sum((panel.costs[c] for c in panel.available), Fraction(0))
result = run_instance(case, "allen_round_robin_cached", replicate=0,
                      max_cost=total_available_cost / 8)
print(result["status"], result["total_cost_exact"], result["certificate"])
```

Use a fresh policy object for every run when supplying a custom `choose(state)` callback. See `BENCHMARK.md` for the common imported-panel, benchmark, and plug-in workflow.

## What the budget means

Each allowance is 0, 1/16, 1/8, 1/4, 1/2, or 1 of the sum of costs of **all initially available queries**, including irrelevant candidates. The denominator is fixed, policy-independent, and specific to each instance. Exact rational arithmetic is used for allowances, payment, and comparisons. These are artificial acquisition units, not recruiter minutes or monetary costs. Including irrelevant labels makes the normalization depend on pool composition.

Canonical methods preserve their unbudgeted next-query order. If the next prescribed query is too expensive, the runner stops **before acquiring or paying for it**, even if a different query would be affordable. It never silently substitutes a cheaper query. This prefix rule preserves the original algorithm for comparison; it does not claim that any method is optimal for certification probability under a budget. A custom policy can explicitly use `state.remaining_cost` and `state.affordable` to investigate that distinct optimization problem.

The comparison includes the cached DNF adapter only on its supported binary-answer cases. Nonanswers remain part of the general resource's contract, but the DNF adapter rejects them rather than treating them as binary labels.

## Denominators and outputs

All 1,152 selected cases remain: 1,024 factorial and 128 constructed. The four phase-by-cost strata have 512, 512, 64, and 64 instances. The 164 initial certificates remain in every main denominator. Results conditional on the 988 initially ambiguous instances are reported separately.

There are seven methods, four original tie slots, and six budgets: 193,536 rows in `budget-results.csv`. First average the four slots within each instance, then average across instances. Repeated deterministic DNF slots maintain alignment with the other policies; they are not independent replications. Shared structural draws and selected synthetic cells do not support population confidence intervals or claims about actual human workloads.

`budget-results.json` reports every budget and policy for all cases, phase and cost strata, and each phase-by-cost combination. It includes certified, positive, negative, and unresolved fractions; mean query count; mean paid cost; mean paid fraction of initial available cost; and the conditional initial-ambiguity results. Each fraction and cost mean has an authoritative exact rational string as well as a convenient floating-point display. `certified_instance_equivalents_exact` can be fractional because it averages random-tie slots; it is not a count of independent people or studies.

The figure plots **actual mean paid cost as a percentage of the initial available total**, against the percentage of cases certified. The six points correspond to the fixed six allowances, with connecting lines for readability. The horizontal coordinate is actual spending, not the budget cap; methods can stop without spending the allowance. The curve is a descriptive set of operating points, not an optimal frontier.

`budget-checks.json` records checks for the frozen design and protected old inputs, complete-trace equivalence, direct budget equivalence, monotone certification, exact cost caps, initial certificates at zero budget, universal convergence at full budget, and sound revealed-only certificates. `budget-design.md` and `budget_design.json` record the timestamp and design hash fixed before outcomes. This amendment is not a preregistration.
