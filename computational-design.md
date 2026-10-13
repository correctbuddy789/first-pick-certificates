# Fixed computational design

The machine-readable design is `computational_design.json`, written at 2026-10-12 14:37:09 UTC before generating policy results. This is a within-session design freeze, **not an external preregistration**. Its SHA-256 is recorded in every result file. The script implements all specified cells; it does not retry a generator until a desired outcome occurs.

The study separates three purposes. A balanced random factorial covers 2,048 instances on panels of four/eight and pools of 12/40. A further 256 explicitly constructed instances at pool size 40 exercise multi-label positive certificates, coverage-only negative certificates with an already eligible pick, bypassable nonanswers, and unresolvable records. A separate 128-case, six-candidate study compares exact expected online costs under a stated independent response model; its probability model is not asserted for the constructed or historical cases.

For each random structural draw, incidence probability is expected blockers per judge divided by the number of competitors. Each candidate has a shared Bernoulli incidence bit; each judge copies it with probability 0 or 0.75 and otherwise draws independently. Thus the expected number of blockers is held at two or six as pool size changes. Independent latent eligibility, initial-knowledge, nonanswer, and cost draws are reused across their factorial levels. These common draws make controlled comparisons possible; the 2,048 cells are not 2,048 independent samples from a population. All retained outcomes and initial certification states remain in the results.

The five methods are uniform choice over all available candidates; pick first then maximum active-judge incidence; pick first then uniform active blockers; uniform exact function-relevant candidates; and the cheapest exact function-relevant candidates. Every tie is drawn uniformly afresh. Each method receives four reproducible random streams per instance, coupled across methods. These are finite seeded averages, not exact priority-order expectations or sampling confidence intervals. The historical replay elsewhere in the paper retains its separately defined fixed-priority randomization.

Selection sees only structure, costs, and revealed labels. A candidate's response becomes readable only after selection. Every attempted query incurs its full cost, including a nonanswer, and a nonanswer can never be retried. All policies stop only when the same exact membership test is certified or the same exact query-availability test proves that no future response sequence could certify. The final verdict must equal the result obtained from all recorded binary answers.

The online oracle minimizes expected total cost using the known independent one-shot response probabilities. It considers possible future response branches, never a realized hidden response record. We also compute each simple policy's exact expectation using its stated fresh-tie rule. An observed minimum certificate is a different, hindsight quantity: its cost is reported only on full records that are certifiable. The corresponding conditional online costs are reported on that same event; an unresolvable record is not assigned a zero certificate.

Small-profile verification uses direct tier evaluation over all eligible worlds, explicit grouping by still-queryable assignments, and certificate-subset enumeration. It checks every ternary full record and every quorum for its fixed profiles, including all nonanswer patterns. Runtime measurements compare mask relevance against absorbed quorum-DNF relevance and a truth-table baseline, rather than assuming masks beat another fixed-panel method. Truth tables stop at 16 candidates; mask and DNF sizes extend to 1,000. Timings are exploratory observations in the recorded environment.

Run from this directory with Python's standard library only:

```sh
python3 -S computational_study.py --all
```

The generated CSV records every instance/policy mean and its denominator. The JSON adds exact online results, runtime repetitions, factor summaries, paired policy comparisons, source hashes, and environment details. `computational-checks.json` records independent oracle checks. No private replay loader, applicant data, or model calls are required.

For a quick fresh-extraction check, rerun the independent policy/certificate oracle and reconstruct the stored main summaries from the CSV:

```sh
python3 -S computational_study.py --verify-only --checks-out /tmp/computational-checks.json
```

The oracle portion took approximately 12 seconds in the recorded environment. It covers 5,832 full ternary records, 4,968 of them containing nonanswers, with 58,320 complete policy traces and 11,664 exhaustive certificate-subset comparisons. The integrity portion checks design/source/CSV hashes, every main aggregate, exact rational cost dominance over the online optimum, and the truth-table size cap. It does not repeat the full computational study. `--check-only` runs the same small oracle before study results exist.

The full online stage uses rational Bellman minimization over all queryable actions. Independently summing the achieved optimum policy over every possible full record checks its expected costs and certification rates; this is not enumeration of every possible policy. The separate read-only methods review includes a distinct weighted-record-partition optimizer for additional small-case confirmation.
