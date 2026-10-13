# Compare a policy with the published baselines

`benchmark_runner.py` runs a user policy, the five original policies, and both
additional comparators through the same `choose(PolicyState)` interface.
It accepts the JSON/CSV panel format in [REUSE.md](REUSE.md) and the 1,152
synthetic cases used in the published binary-answer comparison. The seven
canonical adapters preserve the original random seeds, tie handling, stopping
rule, and paid query costs. The original implementations and stored results
remain unchanged.

This workflow is useful when testing an acquisition policy: keep the panel
orders, initially known labels, query costs, and response record fixed, then
compare how much evidence each policy acquires before it can certify the same
fixed-pick verdict. No private recruiter records are required. Passing the
benchmark is evidence about these cases, not about an application's expected
savings or users' agreement with the chosen quorum rule.

## Run the same comparison on either source

Only the Python standard library is required. From the resource directory:

```sh
# All seven policies, all 1,152 binary cases, four original tie slots: 32,256 runs.
python3 -S benchmark_runner.py --benchmark binary-extension \
  --jsonl-out /tmp/benchmark-runs.jsonl --csv-out /tmp/benchmark-runs.csv \
  --summary-out /tmp/benchmark-summary.json

# Supply your own complete panel orders and a separate fixed response record.
python3 -S benchmark_runner.py \
  --panel examples/open_resources/panel.json \
  --responses examples/open_resources/responses-negative.json \
  --jsonl-out /tmp/imported-runs.jsonl

# Compare the shipped example plug-in with the strongest published comparator.
python3 -S benchmark_runner.py --benchmark binary-extension \
  --instance f0000 --instance c0000 \
  --policy allen_round_robin_cached \
  --plugin examples/cost_sensitive_policy.py \
  --jsonl-out /tmp/plugin-comparison.jsonl

# The identical policy comparison on an imported panel.
python3 -S benchmark_runner.py \
  --panel examples/open_resources/panel.json \
  --responses examples/open_resources/responses-negative.json \
  --policy allen_round_robin_cached \
  --plugin examples/cost_sensitive_policy.py
```

Repeat `--policy` or `--plugin` to add policies. Without `--policy`, the seven
canonical policies are included. A plug-in is trusted local Python code
exporting `choose(state) -> int`, where the result is an available candidate
index. The supplied example uses only structural and revealed information.
It is reloaded for each run so its module state cannot leak between cases.
The callback state has no future answers, answer-provider handle, or latent
benchmark metadata. This is an information-flow contract, not a security
sandbox against Python code that reads external files or process memory.

The canonical methods are:

| CLI name | Next-query rule |
|---|---|
| `uniform_all` | Uniform among all available unknowns. |
| `pick_first_max_blockers` | Query the pick first, then maximize incidence among open judges. |
| `pick_first_uniform_blockers` | Query the pick first, then uniformly choose among available open-judge blockers. |
| `uniform_relevant` | Uniform among exactly relevant available unknowns. |
| `cheapest_relevant` | Minimum cost among exactly relevant available unknowns, with uniform ties. |
| `pick_first_cost_normalized_blockers` | Query the pick first, then maximize open-judge incidence divided by cost. |
| `allen_round_robin_cached` | The cached-answer, common-stopping adaptation of Allen et al.'s DNF round robin. |

For the first six methods, each tie uses `random.Random(seed).choice` on sorted
candidate indices, including singleton choices. Benchmark seed derivation is
unchanged: `stable_seed(original_seed, "tie", instance_id, replicate)`. The
Allen adapter is deterministic; its four slots are identical repetitions, not
four independent observations. Imported panels use the supplied `--seed`
(default 0), instance ID, and replicate index. A user plug-in controls its own
randomness; the runner does not inject a random generator into `choose`.
To coordinate a randomized plug-in's seed, construct its callable explicitly
in Python using the same public `stable_seed` function.

The generated cases specify blocker profiles. Their panel import constructs
complete orders with blockers first, the pick second, and all other candidates
last. This preserves exactly the published fixed-pick problem; it is a
canonical realization, not evidence about preferences among other candidates.
The callback receives this complete structure. Replay answers and latent
case metadata belong to the evaluator and are never part of policy state.

## Binary-only comparator assumptions

The Allen comparator applies to binary-answer settings where every untested
variable in its initially conditioned DNF is queryable. It keeps separate
virtual histories and cost ledgers for its two component streams, while each
physical answer is paid for at most once. It uses only already revealed
answers, including when synchronizing its final observation after global
certification.

When acquisition proceeds, an imported panel with an unavailable DNF variable
is rejected for this comparator before acquiring a query. Common logical
terminal checks run first and may return without initializing the adapter. An acquired nonanswer is rejected as
unsupported; the comparator is not silently substituted or assigned a
negative label. Use the other six policies for a replay containing
nonanswers, and report that scope explicitly. Initially certified cases
require no acquisitions. The adaptation and this interface make no new
approximation guarantee and do not extend the source theorem to failed
queries, budgeted optimization, or arbitrary stochastic response models.

## Compare certification under a finite budget

```sh
python3 -S benchmark_runner.py --benchmark binary-extension \
  --instance f0000 --max-cost 3 --jsonl-out /tmp/budget-runs.jsonl
```

Canonical methods retain their **unbudgeted next-query order**. If the next
prescribed query costs more than the remaining budget, the runner stops
before accessing its answer or paying its cost and reports
`next_query_exceeds_cost_budget`. It does not skip that query to select a
cheaper one. Thus each budgeted trace is a prefix of the corresponding fully
funded trace, and the experiment measures certification under truncation,
not the optimum budget-aware policy. Free queries remain executable at zero
remaining monetary budget. `--max-attempts` provides a separate attempt cap.

`state.affordable` and the remaining budgets are accurate throughout.
Canonical adapters deliberately choose from `state.available`. A custom
policy may inspect the budget and choose differently; its resulting trace
need not be a prefix of its unbudgeted trace. If that policy can encounter an
empty affordable set, it should prescribe its next available query to let
the runner apply the explicit budget stop. The example plug-in is intended
for the unbudgeted comparisons above. The older `reuse_demo.py` retains its
default affordable-selection workflow; it is not silently changed to
canonical prefix truncation.

Use exact `Decimal` or `Fraction` values in Python. CLI decimals and JSON
costs preserve their original decimal spelling. `total_cost_exact` and each
query's `cost_exact` are authoritative, including tiny or very large values.
Costs do not disappear through floating-point underflow. Cost scaling used
inside old validation boundaries preserves comparisons and is reversed in
reported physical and virtual cost ledgers.

An unresolved budget stop leaves unknown eligibility unconstrained; it is
not a negative decision. Preserve initially certified and unresolved cases
in denominators when reporting certification rates. For a profile-specific
budget, use a declared structural normalization such as the sum of initially
available query costs, rather than a realized certificate cost that is
unknown at selection time.

## Python API and outputs

```python
from benchmark_runner import benchmark_cases, run_instance, run_case, policy_factory
from panel_io import load_panel, load_responses

case = next(benchmark_cases())            # evaluator-side object, includes answers
result = run_instance(case, "allen_round_robin_cached", replicate=0)

panel = load_panel("examples/open_resources/panel.json")
answers = load_responses("examples/open_resources/responses-negative.json", panel)
result = run_case(panel, answers.__getitem__, "allen_round_robin_cached", seed=17)

# A fresh custom choose(state) callable uses the identical runner.
def least_index_relevant(state):
    return min(state.relevant)

result = run_case(panel, answers.__getitem__, "my_policy", choose=least_index_relevant)
```

Create a fresh callable for each run if it holds state. `policy_factory(name,
seed)` exposes the canonical adapters independently. `run_instance` converts
the structure and guards each response access until after selection.
`run_case` receives an answer callback, which can replace a replay record
with an authorized interactive acquisition interface. It passes only the
immutable public state to the selector.

JSONL contains each full run: trace, outcome bounds, stop reason, exact paid
cost, acquired-answer certificate, and final unknowns. CSV contains run
metrics plus a `trace_json` column. Summaries preserve all run slots and
explicitly count unresolved cases. These are descriptive case comparisons;
the output does not interpret repeated tie slots as independent samples.
DNF `policy_diagnostics` distinguishes virtual queries/cost from unique paid
acquisitions. A budget-blocked selection may have consumed cached virtual
steps while identifying its next query; these diagnostic computations do not
acquire an answer or consume physical budget.

All policies pass through common exact relevance and certificate reporting in
this convenience runner, including policies that do not themselves require
those calculations. Its total wall time must not be substituted for the
policy-only overhead measurements in the frozen study. No new timing claim
is made here.

## Check that the interface preserves the published experiment

```sh
python3 -S verify_benchmark_runner.py
python3 -S verify_benchmark_runner.py --full-equivalence \
  --traces-out /tmp/verified-runs.jsonl --out /tmp/runner-checks.json
python3 -S verify_reuse.py
```

The full check compares all 32,256 run slots with every stored non-timing
field of `extension-results.csv`. A fixed case-order subset also compares
complete fresh original query traces and the Allen adapter's two private
virtual ledgers. Targeted tests check unaffordable next-query stopping,
binary-only errors, nonanswer preservation, answer access after selection,
imported and generated plug-in runs, exact decimal/zero/extreme costs, and
budgeted prefix equivalence. The existing reuse verifier independently
enumerates complete-tier worlds and checks certificates. None of these
checks replaces the mathematical assumptions or establishes external use.
