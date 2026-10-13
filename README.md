# When Can a Ranking Audit Stop? Certifying First Picks with Unresolved Eligibility

Tushar Nain · Grapevine · October 2026

Version 1.0.0: [versioned resource and download](https://github.com/correctbuddy789/first-pick-certificates/releases/tag/v1.0.0).
Code: MIT. Documentation, synthetic examples/results, figures, and publishable
aggregates: CC BY 4.0. See [LICENSING.md](LICENSING.md), [CITATION.cff](CITATION.cff),
and [MAINTENANCE.md](MAINTENANCE.md) for attribution, scope, and upkeep.

This artifact implements exact membership bounds, minimum-cost certificates,
query relevance, and sequential eligibility queries for a fixed pick and a
fixed panel. It accompanies the revised methods paper. All code needed for
the synthetic experiments and checks is included in this package.

Start with `python3 walkthrough.py` for the paper's three-judge example.
`USAGE.md` documents the input contract, outputs, nonanswer handling, and how
to evaluate another query policy.

For a complete application, run `python3 -S reuse_demo.py --out /tmp/reuse-results.json`.
It imports complete tiers, compares policies, and returns a certificate or an
explicit unresolved result. [REUSE.md](REUSE.md) documents JSON/CSV schema 1.0,
the custom-policy callback, and a fully synthetic learning-resource example.
No new human judgments, model calls, or private records are needed.

## What can be reproduced

| Component | Files | Requires private records? |
| --- | --- | --- |
| Bounds, certificates, stopping, mask and DNF relevance | `certificates.py` | No |
| Policies, answer-withholding replay, exact priority distributions | `query_policies.py` | No |
| Independent exhaustive and randomized verification | `verify_methods.py`, `verify_policies.py` | No |
| Fixed-design synthetic experiments, exact expected-cost comparison, relevance timings | `computational_study.py`, `computational_design.json` | No |
| Synthetic outputs and independent checks | `computational-results.json/csv`, `computational-checks.json` | No |
| Established DNF acquisition and cost-normalized blockers on 1,152 binary-answer cases | `dnf_baselines.py`, `benchmark_extensions.py`, `extension-design.json/md`, `extension-results.json/csv` | No |
| Additional independent comparator checks | `verify_dnf_baselines.py`, `extension-checks.json` | No |
| JSON/CSV tier import, policy callback, and synthetic recommendation workflow | `panel_io.py`, `policy_runner.py`, `reuse_demo.py`, `REUSE.md`, `examples/` | No |
| Complete-tier oracle and public workflow checks | `verify_reuse.py` | No |
| Historical audit outputs and reference-rule sensitivity | `public-aggregate-results.json`, `stress-results.json`, `target-sensitivity.json` | Aggregate outputs are included; rerunning the historical analysis requires private records |
| Manuscript figure | `make_figures.py`, `figures/` | No |

The implementation uses only the Python standard library. Figure generation
additionally uses Matplotlib. The package includes no applicant profiles,
candidate-level human judgments, candidate identifiers, query traces from the
historical audit, or private analysis loaders. Synthetic instances are generated
from the included design and seeds.

## Run the checks

A minimal example reproduces the paper's three-judge illustration. Candidate
0 is the eligible pick, 1 and 2 block one judge each, and 3 is tied with the
pick. Clearing either blocker certifies membership at quorum two:

```python
from certificates import classify, relevant_candidates

blockers = (frozenset({1}), frozenset({2}), frozenset())
positive, negative, unknown = frozenset({0}), frozenset(), frozenset({1, 2, 3})
assert classify(positive, negative, 0, blockers, 2) == {0, 1}
assert relevant_candidates(positive, negative, unknown, unknown,
                           0, blockers, 2) == {1, 2}
assert classify(positive, frozenset({1}), 0, blockers, 2) == {1}
```

When a query returns no answer, remove it from the available set (the third
argument to `relevant_candidates`) but retain it in the unknown universe
(the fourth argument).

From the extracted package:

```bash
python3 verify_methods.py --out verification-rerun.json
python3 verify_policies.py --out policy-verification-rerun.json
python3 computational_study.py --verify-only --checks-out computational-checks-rerun.json
python3 -S verify_dnf_baselines.py --out extension-checks-rerun.json
python3 -S benchmark_extensions.py --verify-stored
python3 -S verify_reuse.py --out reuse-verification-rerun.json
```

The first verifier compares bounds, stopping, and certificate optima with
independent enumeration, including every quorum for its extension profiles
and zero-cost labels. The second compares mask and absorbed-DNF relevance
with a direct-world oracle, checks policy choices with zero and fractional
costs, and compares replay and exact priority distributions on complete
ternary response records. Nonanswers remain unknown after becoming unavailable.

Recorded method totals are 62,713 bound checks, 153,679 stopping checks,
46,728 certificate comparisons, and 2,000 core policy checks. The policy
verifier retains the original 42,112 relevance and 1,542 permutation checks;
its additional exhaustive tests cover 80,128 availability states, 320,512
cost-selection checks, 122,472 replay comparisons, and 1,701 exact-distribution
comparisons. These are deterministic implementation checks, not independent
empirical observations. Machine-dependent elapsed times can differ.

## Reproduce the computational study

```bash
python3 computational_study.py --all
```

This regenerates the synthetic outputs. The design was saved before its
results were generated; it is an internal design freeze, not an external
preregistration. Read `computational-design.md` for the full protocol.
The main study includes 2,048 balanced factorial instances and 256 separately
reported constructed cases. A separate 128-instance experiment computes
exact expected policy costs under an explicit independent response model.
Runtime measurements are machine dependent; generated records, policy seeds,
and non-timing summaries are reproducible.

The old planted-instance runtime supplement remains in the development
repository and reviewed snapshot. It is superseded in this package
by the comparative experiment above.

## Compare established acquisition strategies

```bash
python3 -S benchmark_extensions.py --run --results-out /tmp/extension-rerun.json --csv-out /tmp/extension-rerun.csv
```

The internal design amendment in `extension-design.json/md` was frozen after
the first study and internal review, before evaluating its new comparators.
It reuses all 1,024 zero-nonanswer factorial cases and 128 binary-answer
constructed cases, including all 164 initial certificates. It adds a
cost-normalized blocker rule and a cached-answer/common-stopping adaptation
of Allen et al.'s published monotone k-term DNF round robin. The adapter has
no claimed transferred approximation guarantee or nonanswer extension.

The seven policies use the same initial information and response records.
All 11,520 original-policy count/cost totals reproduce the frozen CSV exactly.
The 32,256 output rows preserve four original tie seeds; the deterministic
DNF policy repeats identically and those slots are not independent replicates.
Its mean acquisition cost is lower in each design/cost stratum, with higher
measured policy overhead. Individual cases and constructed subfamilies differ.
The JSON supplies all paired comparisons, denominators, and timing components.
`--verify-stored` checks stored artifacts and the original-policy totals;
`--run` actually recomputes the new policies. Machine timings vary between runs.

## Regenerate the figure

```bash
python3 -m venv .venv
.venv/bin/python -m pip install matplotlib
.venv/bin/python make_figures.py
```

Both panels are computed from the included JSON outputs. The PDF and PNG
are written under `figures/`.

## Verify and rebuild this archive

```bash
python3 package_artifacts.py
```

The packager allowlists every file, checks manifest hashes, extracts the
archive into a fresh temporary directory, and runs the method, policy,
computational, comparator, and reuse verifiers with third-party Python
imports disabled. It needs
no private inputs when run from an extracted package. Repacking does
not rerun the full timing experiment.

## Restricted historical replay

The complete historical replay requires an authorized copy of the original
repository, including:

```text
paper/decision-certificates/analyze_certificates.py
paper/decision-certificates/stress_analysis.py
paper/decision-certificates/analyze_target_sensitivity.py
pilot/scripts/analyze.py
pilot/scripts/sensitivity.py
pilot/data/export-20260826.json
pilot/data/den_ranks.json
pilot/data/bm25_ranks.json
```

The original loader opens the BM25 file although this analysis does not
use its values. From that repository's root:

```bash
python3 paper/decision-certificates/analyze_certificates.py --tree
python3 paper/decision-certificates/stress_analysis.py
python3 paper/decision-certificates/analyze_target_sensitivity.py
```

The original eligibility and ranking input SHA-256 digests are:

```text
pilot/data/export-20260826.json
ee4c4088186ca327a0baf1433ff1f4276fd81d39a954f767d56edd453d8b9c4e

pilot/data/den_ranks.json
1ca8400ebc6a782654213bdf12110965aa04961d7885c552b8b536f4306fe4c8
```

Historical query counts concern residual eligibility adjudication after
600 initial eligibility assessments and 600 preference assessments.
Certificates use hindsight; replay assumes recorded answers remain fixed
under selective querying. Neither measures prospective human labor savings.
The outcome is the pick's mechanical quorum membership, including empty
and no-quorum reference sets. It is distinct from the original audit's
agreement with an adjudicated reference.
