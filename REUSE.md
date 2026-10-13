# Reuse the toolkit with complete panel orders

For a direct comparison with all seven published acquisition policies,
including the cached DNF comparator, use the shared batch workflow in
[BENCHMARK.md](BENCHMARK.md). It accepts this same input format and
`choose(state)` plug-ins, and also runs the 1,152 published binary-answer
benchmark cases. The simple workflow below retains its existing deterministic
adapters and affordable-query budget behavior.

An evaluation researcher can use this workflow to compare eligibility-query
policies after collecting complete preference tiers for a fixed candidate
pool. The question is specific: **does the system's fixed first pick belong
to the panel's quorum top set under every remaining eligibility completion?**
The workflow imports tier data, derives strict blockers, acquires responses
through a callback, and returns either a certified verdict with a minimum
recorded certificate or an explicit unresolved result. It does not construct
complete preferences from incomplete ratings or decide which quorum rule a
community ought to use.

The interface and example require Python 3.10 or newer and only its standard
library. Run commands from the extracted artifact's directory. No installation,
network service, model API, applicant records, or additional study is needed.

## An example outside hiring

Suppose an institutional learning-resource recommender proposes a guide.
Three subject editors have ranked the same six resources, allowing ties.
A resource is eligible only if permission for its proposed course reuse has
been verified. The institution chooses a quorum of two editors. Each editor
supports the guide when no eligible resource lies strictly above it in that
editor's fixed order. Unknown permission status can change the answer even
when relevance preferences are complete.

**All names, orders, labels, costs, and responses in this example are
synthetic.** They are a plausible information-access illustration, not records
from a second deployment, evidence of external adoption, measured permission
verification costs, or a new human experiment. The example assumes a binary
eligibility predicate and independent logical completions; real permission
rules with cross-resource constraints would require a different model.

The fixture contains the same complete orders in inline JSON (`panel.json`)
and long-form CSV (`tiers.csv`, referenced by `panel-csv.json`). The guide is
initially eligible. Its strict blockers are:

| Editor | Resources strictly above the guide |
| --- | --- |
| editor_a | handbook, tutorial |
| editor_b | handbook, overview |
| editor_c | tutorial, overview |

`index` is tied with or below the guide. It is not a strict blocker.
Handbook, tutorial, and overview each block two editors if eligible;
glossary blocks none. The example includes three
distinct evidence situations: fully answered responses, an attempted query
that returns no answer, and a query that was unavailable from the start.

```bash
python3 -S reuse_demo.py --out /tmp/reuse-results.json
python3 -S verify_reuse.py --out /tmp/reuse-verification.json
```

The first command reproduces 18 deterministic runs (six scenarios × three
policies). `examples/open_resources/expected-results.json` stores the complete
expected JSON, including query traces. The second checks that output and
tests import errors, exact budget accounting, nonanswers, callback isolation,
and outcomes/certificates against independent complete-tier enumeration.

| Scenario | Max-blocker policy: attempts / cost | Cheapest-relevant and supplied plug-in: attempts / cost | Outcome |
| --- | --- | --- | --- |
| Negative record | 1 / 5 | 2 / 3 | Certified exclusion |
| Positive record | 3 / 8 | 3 / 8 | Certified inclusion |
| Handbook query gives no answer | 3 / 8 | 3 / 8 | Unresolved |
| Handbook query initially unavailable | 2 / 3 | 2 / 3 | Unresolved |
| Cost budget of 1 | 1 / 1 | 1 / 1 | Unresolved; user budget |
| Attempt budget of 1 | 1 / 5 | 1 / 1 | Unresolved; user budget |

These values illustrate mechanics, not comparative performance evidence.
In the negative record, cheapest-relevant acquires `tutorial = 0` and then
`overview = 1`. Its total acquisition cost is 3, while its minimum recorded
certificate is only `overview = 1`, cost 2. The unqueried `handbook = 1`
response is not eligible for that certificate. The unavailable and nonanswer
scenarios both leave `handbook` logically unknown; neither treats it as
ineligible. The free but irrelevant `index` query is unnecessary.

## Run an individual JSON or CSV import

```bash
python3 -S reuse_demo.py \
  --panel examples/open_resources/panel-csv.json \
  --responses examples/open_resources/responses-negative.json \
  --policy cheapest_relevant

python3 -S reuse_demo.py \
  --panel examples/open_resources/panel.json \
  --responses examples/open_resources/responses-nonanswer.json \
  --plugin examples/cost_sensitive_policy.py

python3 -S reuse_demo.py \
  --panel examples/open_resources/panel.json \
  --responses examples/open_resources/responses-positive.json \
  --policy cheapest_relevant --max-cost 1
```

The last command demonstrates a user-imposed budget stop. It does **not**
replace the computational benchmark's terminal rule, which continues until
the verdict is certified or no completion of remaining available queries
could certify it. A budget can stop earlier and is reported separately.

## Stable input schema 1.0

`panel_io.load_panel(path)` returns an immutable `Panel` with validated indices.
Unknown fields and duplicate JSON keys are rejected; arrays of identifiers
must not contain duplicates. Supply exactly one of `judges` and `tiers_csv`.

| Field | Meaning and validation |
| --- | --- |
| `schema_version` | Required string `"1.0"`. |
| `instance_id` | Required nonempty string. |
| `candidates` | Required nonempty array of unique string IDs; its order defines stable indices and tie breaks. This is the complete fixed universe. |
| `pick` | Required ID in `candidates`; fixed throughout the run. |
| `quorum` | Required integer from 1 through the number of judges; a Boolean is not an integer here. |
| `judges` | Nonempty array of `{"id": ..., "tiers": [[...], ...]}`. Judge IDs are unique. Tiers are nonempty, best first; every candidate appears exactly once per judge. Ties are allowed. |
| `tiers_csv` | Alternative path inside the JSON's directory, with exact header `judge_id,candidate_id,tier`. One row per judge/candidate pair; each judge covers the complete universe. Positive integer tier numbers are best first; gaps are allowed and carry no extra meaning. Judge order is order of first appearance. |
| `eligibility` | Required object with `positive` and `negative` arrays of candidate IDs. They are disjoint. Every other candidate is unknown. |
| `available` | Optional array of initially unknown IDs that can be queried. Defaults to all unknowns. Unknown IDs omitted here remain logically unknown. |
| `costs` | Optional map of candidate IDs to finite nonnegative numbers; omitted costs default to 1. Every attempt pays this cost, including a nonanswer. Zero costs are allowed. |
| `cost_unit` | Optional nonempty string, default `"query-cost units"`. |
| `synthetic` | Optional Boolean provenance marker, default false. It does not affect computation or verify provenance. |
| `description` | Optional explanatory string, never used for policy selection. |

Neither numerical tier gaps nor ordering within a tied tier affect blockers.
`complete_tiers_to_blockers(candidate_ids, pick, judges_tiers)` exposes this
conversion independently. `Panel.core_instance()` returns fresh structural
containers with original costs and no replay answers. For extreme costs,
use `run_policy`: it scales costs exactly for the frozen core's float-based
cost-validation boundary and reports original units. The structural adapter
alone does not perform that scaling.

Replay responses are a **separate file**:

```json
{
  "schema_version": "1.0",
  "responses": {"handbook": null, "tutorial": 0, "overview": 0, "index": 1}
}
```

`load_responses(path, panel)` requires exactly one explicit integer `0`
(ineligible), integer `1` (eligible), or `null` (nonanswer) for every initially
available unknown. Missing entries are errors. Unavailable unknowns have no
entry; an absent record is never silently interpreted as ineligible or as a
nonanswer. The fixed record supports reproducible replay; it is not a claim
that an actual human's response would be independent of query order.

## Add a policy without changing the core

Write a trusted Python file exporting `choose(state) -> int` and pass it with
`--plugin`. It returns one candidate index in `state.affordable`. The runner
validates the selection before consulting the answer callback. State contains:

- Immutable fixed `candidate_ids`, complete `tiers`, `pick`, `blockers`, and
  `quorum`; `costs` as exact nonnegative `Fraction` values.
- Revealed `positive` and `negative` labels, and the **original** `uncertain`
  universe, which still includes nonanswers and unavailable unknowns.
- Currently `available`, exactly `relevant`, and `affordable` candidate sets;
  `relevant` is restricted to current availability, independent of budgets.
- `attempts_used`, `cost_used`, `remaining_attempts`, and `remaining_cost`.

There is no unrevealed response record, answer-provider handle, or hidden
true eligibility in the callback state. The callback contract is an
information-flow boundary, not a security sandbox: trusted Python plug-ins
can access their own globals/files. Researchers must not place future answers
there. The supplied plug-in reads only state and ranks relevant competitors
by cost per currently unblocked judge they would block if eligible. It has
no claimed approximation or optimality guarantee. Built-in deterministic
adapters are `max_blockers`, `cheapest_relevant`, and `first_relevant`; the
last uses fixed input order and is not a randomized uniform policy.

For interactive or application integration, use `run_policy` directly:

```python
from panel_io import load_panel
from policy_runner import builtin_policy, run_policy

panel = load_panel("examples/open_resources/panel.json")

def acquire(candidate_id):
    # Replace this prompt with your authorized label-acquisition interface.
    value = input(f"Eligibility of {candidate_id} (0, 1, or ?): ").strip()
    if value not in {"0", "1", "?"}:
        raise ValueError("Use 0, 1, or ?")
    return None if value == "?" else int(value)

result = run_policy(panel, builtin_policy("cheapest_relevant"), acquire)
```

The answer provider receives only the selected candidate ID. Each candidate
can be attempted once. A returned nonanswer removes its availability but
does not resolve its eligibility. Eligibility is assumed stable over the
audit; dynamic changes or repeat-attempt response models are outside this
interface.

## Interpret and extend the result

Every result gives the binary `possible_outcomes`, `status`, `stop_reason`,
trace, full attempt count/cost, and final unknown and unavailable sets.
`verdict = 1` certifies membership and `0` certifies nonmembership under the
specified rule. A negative does not necessarily identify a replacement or
establish that the pick is ineligible.

A certified result includes a minimum-cost certificate from **revealed
binary responses**, relative to initial labels, breaking cost ties by size
and then input index. An initially certified result has an empty, zero-cost
certificate. An unresolved result has `certificate = null` and an explicit
reason: no possible remaining available answers could certify, attempt budget
exhausted, or no relevant query fits the remaining cost budget. Budget reasons
are user-imposed constraints, not logical impossibility under full funding.
Costs are accumulated from decimal spellings using rational arithmetic;
JSON fractional numbers and `--max-cost` are parsed directly as decimals,
without first rounding through binary floating point. `total_cost_exact` and
certificate/trace `cost_exact` strings are authoritative. Their numeric
counterparts are convenience approximations; a noninteger value outside the
nonzero finite floating-point range is reported as `null` there, preserving
its exact string rather than displaying a positive cost as zero. Direct
Python callers should pass `Decimal` or `Fraction` when input precision
matters: an already rounded Python float cannot recover its original digits.

One reproducible extension is to hold complete tiers and response records
fixed, vary query-cost schedules and unavailable-query rates, and compare a
new policy's **acquisition cost and unresolved proportion** with the supplied
policies. Preserve initially certified and unresolved cases in denominators;
do not compare only successful runs. The shared input schema and callbacks
make those alternatives comparable without changing the target rule. Use
the main computational study for performance evidence: this tiny fixture
establishes a runnable import/extension path, not policy superiority, demand
for the quorum rule, or actual operational savings.
