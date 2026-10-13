#!/usr/bin/env python3
"""Posthoc paired policy explanation and prospectively fixed matched ablation.

Standard library only. Reads existing synthetic results; never rewrites them.
python3 -S policy_explanation.py --explain
python3 -S policy_explanation.py --matched
python3 -S policy_explanation.py --verify-stored
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import itertools
import json
import random
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from benchmark_extensions import replay_extension
from certificates import can_certify_with, classify, dnf_relevant_candidates
from computational_study import (GuardedResponses, constructed_instances,
    factorial_instances, outcome_name, stable_seed, structure_only, TierWorldOracle)
from dnf_baselines import quorum_terms
from query_policies import MaskContext

ROOT = Path(__file__).resolve().parent
PRIORITIES = ('uniform', 'cheapest', 'max_incidence')
FILTERS = ('active', 'exact')
ALLEN = 'allen_round_robin_cached'
CHEAP = 'cheapest_relevant'
MAX = 'pick_first_max_blockers'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_design():
    design = json.loads((ROOT / 'matched-relevance-design.json').read_text())
    for name, expected in design['protected_inputs'].items():
        assert sha(ROOT / name) == expected, f'Protected input changed: {name}'
    return design


def original_instances():
    design = json.loads((ROOT / 'computational_design.json').read_text())
    return list(itertools.chain(factorial_instances(design), constructed_instances(design)))


def write_csv(path, rows):
    with Path(path).open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def dump(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')


def pair_summary(cases):
    result = {'instances': len(cases)}
    for metric in ('queries', 'cost'):
        values = [c[f'delta_{metric}'] for c in cases]
        result.update({f'mean_left_{metric}': statistics.mean(c[f'left_{metric}'] for c in cases),
                       f'mean_right_{metric}': statistics.mean(c[f'right_{metric}'] for c in cases),
                       f'mean_delta_{metric}': statistics.mean(values),
                       f'min_delta_{metric}': min(values), f'max_delta_{metric}': max(values),
                       f'left_less_{metric}': sum(v < 0 for v in values),
                       f'equal_{metric}': sum(v == 0 for v in values),
                       f'left_more_{metric}': sum(v > 0 for v in values)})
    return result


def per_case(rows, left, right, method_key='method'):
    bycase = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row[method_key] in (left, right):
            bycase[row['instance']][row[method_key]].append(row)
    cases = []
    for key in sorted(bycase):
        both = bycase[key]
        assert len(both[left]) == len(both[right]) == 4
        result = {k: v for k, v in both[left][0].items()
                  if k not in ('method', 'replicate', 'queries', 'cost', 'initialization_ns',
                    'selection_ns', 'policy_overhead_ns', 'virtual_queries', 'virtual_cost',
                    'cached_virtual_queries', 'nonanswers', 'filter', 'priority',
                    'meaningful_visits', 'strict_visits', 'changed_priority_visits')}
        for metric in ('queries', 'cost'):
            result[f'left_{metric}'] = statistics.mean(float(r[metric]) for r in both[left])
            result[f'right_{metric}'] = statistics.mean(float(r[metric]) for r in both[right])
            result[f'delta_{metric}'] = result[f'left_{metric}'] - result[f'right_{metric}']
        cases.append(result)
    return cases


def strata(cases, fields):
    result = {}
    for field in fields:
        result[field] = {str(value): pair_summary([c for c in cases if c[field] == value])
                         for value in sorted({c[field] for c in cases}, key=str)}
    return result


def term_bin(n):
    return '0' if n == 0 else '1' if n == 1 else '2-4' if n <= 4 else '5-16' if n <= 16 else '17+'


def active_candidates(instance, p, n, available):
    viable = [set(b) for b in instance['blockers'] if not set(b) & p]
    return (set().union(*viable) if viable else set()) & (set(available) - p - n) - {instance['pick']}


def trace_details(instance, result):
    p, n = set(instance['positive']), set(instance['negative'])
    available = set(instance['uncertain'])
    context = MaskContext(structure_only(instance))
    rows, cost = [], 0
    for c, answer in result['trace']:
        active = active_candidates(instance, p, n, available)
        exact = context.relevant(p, n, available)
        before = len(quorum_terms({**structure_only(instance), 'positive': p, 'negative': n}))
        cost += instance['costs'][c]
        rows.append({'candidate': c, 'eligibility': answer, 'cost': instance['costs'][c],
                     'cumulative_cost': cost, 'active_competitors_before': len(active),
                     'exact_relevant_before': len(exact), 'absorbed_terms_before': before,
                     'chosen_exact_relevant': c in exact,
                     'chosen_active_competitor': c in active})
        available.remove(c)
        if answer == 1: p.add(c)
        elif answer == 0: n.add(c)
    return rows


def representative(group, rows, instance_map, right, sign, original_seed):
    candidates = [c for c in group if c['delta_cost'] * sign > 0]
    chosen = min(candidates, key=lambda c: c['instance'])
    identifier = chosen['instance']
    paired = {(r['method'], int(r['replicate'])): r for r in rows if r['instance'] == identifier}
    rep = min(rep for rep in range(4)
              if (int(paired[ALLEN, rep]['cost']) - int(paired[right, rep]['cost'])) * sign > 0)
    instance = instance_map[identifier]
    seed = stable_seed(original_seed, 'tie', identifier, rep)
    results = {}
    for method in (ALLEN, right):
        replay = replay_extension(instance, method, seed)
        old = paired[method, rep]
        assert replay['queries'] == int(old['queries']) and replay['cost'] == int(old['cost'])
        results[method] = {'queries': replay['queries'], 'cost': replay['cost'],
                           'trace': trace_details(instance, replay),
                           'virtual_trace': replay['virtual_trace']}
    return {'selection': 'Lexicographically first case with requested per-case mean sign; lowest matching replicate.',
            'instance': identifier, 'replicate': rep, 'case_mean': chosen,
            'meta': instance['meta'], 'positive': sorted(instance['positive']),
            'negative': sorted(instance['negative']), 'pick': instance['pick'],
            'blockers': [sorted(b) for b in instance['blockers']],
            'quorum_terms': [sorted(t) for t in quorum_terms(instance)],
            'results': results}


def explain():
    design = read_design()
    rows = list(csv.DictReader((ROOT / 'extension-results.csv').open()))
    cases = per_case(rows, ALLEN, CHEAP)
    assert len(rows) == 32256 and len(cases) == 1152
    for c in cases:
        c['absorbed_term_bin'] = term_bin(int(c['absorbed_terms']))
    focus = [c for c in cases if c['phase'] == 'factorial' and c['cost_mode'] == 'heterogeneous']
    summary = pair_summary(focus)
    assert (summary['left_less_cost'], summary['left_more_cost'], summary['equal_cost']) == (171, 134, 207)
    reverse = [c for c in per_case(rows, ALLEN, MAX)
               if c['family'] == 'coverage_negative' and c['cost_mode'] == 'unit']
    assert len(reverse) == 32
    instances = {i['meta']['instance']: i for i in original_instances()}
    seed = json.loads((ROOT / 'computational_design.json').read_text())['seed']
    traces = {'factorial_allen_cheaper': representative(focus, rows, instances, CHEAP, -1, seed),
              'factorial_allen_dearer': representative(focus, rows, instances, CHEAP, 1, seed),
              'coverage_negative_allen_dearer': representative(reverse, rows, instances, MAX, 1, seed)}
    write_csv(ROOT / 'policy-explanation.csv', cases)
    payload = {'status': 'Posthoc descriptive analysis, no inferential or causal claims.',
               'design_sha256': sha(ROOT / 'matched-relevance-design.json'),
               'source_csv_sha256': sha(ROOT / 'extension-results.csv'),
               'analysis_source_sha256': sha(__file__),
               'paired_cases_csv_sha256': sha(ROOT / 'policy-explanation.csv'),
               'factorial_heterogeneous': summary,
               'factorial_heterogeneous_strata': strata(focus, design['stored_result_analysis']['strata']),
               'unit_coverage_negative_vs_max_incidence': pair_summary(reverse),
               'unit_coverage_negative_strata': strata(reverse, ['judges', 'group_width', 'quorum_name']),
               'representative_traces': traces}
    dump(ROOT / 'policy-explanation.json', payload)
    md = ['# Posthoc policy explanation', '',
          'All differences are cached DNF round robin minus the stated comparator, averaged over each case’s four stored slots. The DNF slots are deterministic duplicates. Strata overlap and reuse latent design draws; these are benchmark descriptions, not population estimates or causal effects.', '',
          '## Heterogeneous factorial: DNF versus cheapest relevance', '',
          f"Across {len(focus)} cases, DNF is cheaper on {summary['left_less_cost']}, dearer on {summary['left_more_cost']}, and tied on {summary['equal_cost']}. Mean costs are {summary['mean_left_cost']:.6f} and {summary['mean_right_cost']:.6f}; paired difference {summary['mean_delta_cost']:.6f}.", '',
          '| Factor | Level | Cases | DNF cost | Cheapest cost | Difference | Cheaper / tied / dearer |',
          '|---|---|---:|---:|---:|---:|---|']
    for field, levels in payload['factorial_heterogeneous_strata'].items():
        for value, stats in levels.items():
            md.append(f"| {field} | {value} | {stats['instances']} | {stats['mean_left_cost']:.3f} | {stats['mean_right_cost']:.3f} | {stats['mean_delta_cost']:+.3f} | {stats['left_less_cost']} / {stats['equal_cost']} / {stats['left_more_cost']} |")
    r = payload['unit_coverage_negative_vs_max_incidence']
    md += ['', '## Unit-cost coverage-negative reversal', '',
           f"Across 32 constructed cases, DNF uses {r['mean_left_queries']:.6f} queries versus {r['mean_right_queries']:.6f} for pick-first maximum blockers (difference {r['mean_delta_queries']:+.6f}); cheaper / tied / dearer cases: {r['left_less_cost']} / {r['equal_cost']} / {r['left_more_cost']}.", '',
           '## Deterministically selected traces', '',
           'For each requested direction, take the lexicographically first qualifying case by its four-slot mean; then take the lowest replicate with that paired sign. These illustrate mechanisms, not typical cases. The JSON includes blockers, conditioned DNF terms, every physical query and the DNF virtual scheduler ledger.']
    for name, value in traces.items():
        md += ['', f"### {name}: {value['instance']}, replicate {value['replicate']}", '',
               f"Initial eligible {value['positive']}; ineligible {value['negative']}; quorum {value['meta']['quorum']} of {value['meta']['judges']}; terms {value['quorum_terms']}.", '']
        for method, trace in value['results'].items():
            compact = ', '.join(f"{s['candidate']}:{s['eligibility']}@{s['cost']}" for s in trace['trace'])
            md.append(f"- {method}: {trace['queries']} queries, cost {trace['cost']}; candidate:eligibility@cost = {compact}.")
    md += ['', '## What the traces explain', '',
           'In f0002, both methods first acquire cheap candidate 10. The DNF scheduler next acquires the pick, whose ineligibility certifies a negative verdict, for cost 5. Cheapest relevance instead selects two equally priced competitors before the pick, for cost 13. In f0075, the negative verdict requires only one eligible blocker under unanimity: a uniform cost tie places that blocker first for cheapest relevance, while deterministic DNF ordering first tests another equally cheap candidate. This is a tie-order loss, not an example of cost domination.', '',
           'In c0001, eligibility of candidate 3 already blocks the judge whose blockers are {3,23}. Nevertheless, the one-certificate DNF stream later tests candidate 23 while completing its initially chosen term {3,4,23,29}. That variable is no longer globally relevant. The other extra queries in this trace reflect the two methods’ different ordering. The adapter follows Section 5.2’s term-completion rule and keeps private stream histories; common global stopping still ends the run as soon as a certificate exists. Thus this trace gives one explicit source of extra work, not a complete explanation of the 32-case mean.', '',
           'Primary algorithm checked: [Allen et al., Section 5.2, author manuscript p.14](https://www.cs.cmu.edu/afs/cs/user/srallen/www/papers/dnfeval.pdf). The published Algorithmica version remains the paper’s bibliography entry; the author copy was used to inspect the algorithm.', '',
           'The matched filter experiment is separate and holds pick-first and priority fixed; this posthoc DNF comparison does not isolate a single algorithmic component.', '']
    (ROOT / 'policy-explanation.md').write_text('\n'.join(md))
    read_design()
    print(json.dumps({'factorial_heterogeneous': summary, 'unit_coverage_negative': r}, indent=2), flush=True)


def priority_choices(choices, priority, instance, p):
    if priority == 'uniform': return set(choices)
    if priority == 'cheapest':
        low = min(instance['costs'][c] for c in choices)
        return {c for c in choices if instance['costs'][c] == low}
    viable = [b for b in instance['blockers'] if not b & p]
    scores = {c: sum(c in b for b in viable) for c in choices}
    high = max(scores.values())
    return {c for c, score in scores.items() if score == high}


def matched_replay(instance, priority, filtering, seed, state_cache):
    public = structure_only(instance)
    p, n = set(public['positive']), set(public['negative'])
    available = set(public['uncertain'])
    context = MaskContext(public)
    rng, responses = random.Random(seed), GuardedResponses(instance['observed'])
    queries = cost = nonanswers = meaningful = strict = changed = 0
    while True:
        verdict = classify(p, n, public['pick'], public['blockers'], public['quorum'])
        possible = can_certify_with(p, n, available, public['pick'], public['blockers'], public['quorum'])
        if len(verdict) == 1 or not available or not possible: break
        if public['pick'] in available:
            choices = {public['pick']}
        else:
            key = (frozenset(p), frozenset(n), frozenset(available))
            if key not in state_cache:
                active = active_candidates(public, p, n, available)
                exact = set(context.relevant(p, n, available))
                independent = set(dnf_relevant_candidates(p, n, available, public['uncertain'],
                    public['pick'], public['blockers'], public['quorum']))
                assert exact == independent and exact and exact <= active
                state_cache[key] = (active, exact)
            active, exact = state_cache[key]
            active_best = priority_choices(active, priority, public, p)
            exact_best = priority_choices(exact, priority, public, p)
            meaningful += 1
            strict += int(exact < active)
            changed += int(exact_best != active_best)
            choices = active_best if filtering == 'active' else exact_best
        chosen = rng.choice(sorted(choices))
        available.remove(chosen)
        responses.permit(chosen)
        answer = responses[chosen]
        queries += 1
        cost += public['costs'][chosen]
        if answer == 1: p.add(chosen)
        elif answer == 0: n.add(chosen)
        else:
            assert answer is None
            nonanswers += 1
    return {'queries': queries, 'cost': cost, 'nonanswers': nonanswers,
            'outcome': outcome_name(verdict), 'meaningful_visits': meaningful,
            'strict_visits': strict, 'changed_priority_visits': changed}


def matched_summaries(rows):
    result = {}
    for priority in PRIORITIES:
        cases = per_case([r for r in rows if r['priority'] == priority], 'exact', 'active', 'filter')
        result[priority] = {'all': pair_summary(cases),
                           'strata': strata(cases, ['phase', 'cost_mode', 'family', 'outcome', 'initially_ambiguous']),
                           'by_phase_and_cost': {f'{phase}_{cost}': pair_summary([c for c in cases if c['phase'] == phase and c['cost_mode'] == cost])
                                                for phase in ('factorial', 'constructed') for cost in ('unit', 'heterogeneous')}}
    return result


def matched_markdown(payload):
    states = payload['state_frequencies']
    md = ['# Matched exact-relevance comparison', '',
          'This amendment was fixed before these matched outcomes were run, after prior aggregate results were already known. It is not a preregistration. All 2,304 original synthetic cases, including initial certificates and final unresolved cases, and all four original tie seeds are retained (55,296 traces).', '',
          'Each paired policy queries an available unknown pick first and then uses the same priority (uniform, cheapest, or maximum active-judge incidence), costs, fresh uniform tie rule and original terminal checks. Only the filter changes: the union of available blockers of currently unblocked judges versus exact relevance. Nonanswers cost the full amount and remain logically unknown.', '',
          '## Reachable states', '',
          'A meaningful state is a pre-query state whose verdict is ambiguous, with at least one available query, can_certify_with=True, and the pick not available. The next query is therefore not forced by the common pick-first rule. A distinct state is the tuple (instance ID, known-positive set, known-negative set, available set); it is deduplicated across all six policy variants and four tie slots within each instance, but shared structures in different design cells remain distinct.', '',
          f"Exact relevance is a strict subset in {states['distinct_strict_states']:,}/{states['distinct_meaningful_states']:,} distinct meaningful states ({100*states['distinct_strict_states']/states['distinct_meaningful_states']:.2f}%). At the visit level it is strict in {states['strict_state_visits']:,}/{states['meaningful_state_visits']:,} visits. In total {states['instances_with_strict_state']:,}/{2304:,} cases encounter a strict subset; {states['instances_with_meaningful_state']:,}/{2304:,} cases reach any meaningful state. These visits and cases are dependent design observations, not independent samples.", '',
          '## Matched results', '',
          'Averages first give each case the mean of its four tie slots, then weight cases equally. Exact-minus-active differences below isolate the filter in this fixed experiment; they do not decompose the original uniform-all comparison, which also differs in pick-first behavior.', '',
          '| Scope | Priority | Cases | Active queries | Exact queries | Active cost | Exact cost | Exact cheaper / tied / dearer |',
          '|---|---|---:|---:|---:|---:|---:|---|']
    for priority in PRIORITIES:
        group = payload['summaries'][priority]
        scopes = [('all', group['all'])]
        scopes += [(phase, group['strata']['phase'][phase]) for phase in ('factorial', 'constructed')]
        scopes += list(group['by_phase_and_cost'].items())
        for scope, s in scopes:
            md.append(f"| {scope} | {priority} | {s['instances']} | {s['mean_right_queries']:.6f} | {s['mean_left_queries']:.6f} | {s['mean_right_cost']:.6f} | {s['mean_left_cost']:.6f} | {s['left_less_cost']} / {s['equal_cost']} / {s['left_more_cost']} |")
    md += ['', 'Exact filtering modestly reduces mean acquisition for uniform and cheapest selection here. Maximum-incidence selection already avoids almost all variables removed by exact filtering: its preferred set changes in only 3/41,112 active-policy meaningful visits, and the four-slot case means improve in only one case. Every constructed disjoint-group case has identical results between filters for each priority. The incremental value of exact filtering therefore depends on the acquisition policy and blocker structure.', '',
           'Exact filtering can have a larger cost in an individual seeded pair: changing the choice set changes the random tie trajectory. Reusing a seed is a common-random-number control, not pathwise dominance. The report makes no population-performance or general monotonic-improvement claim.', '',
           'All final outcomes match the same full-record verdict, including 338 unresolved cases. All initial certificates retain zero acquisition cost. The 13,824 original active uniform/max-incidence aggregate query, cost and nonanswer totals match exactly. At all 60,858 distinct meaningful states, mask relevance agrees with the separately implemented absorbed-DNF relevance; an explicit four-world tier example independently checks a redundant active blocker.', '']
    (ROOT / 'matched-relevance-results.md').write_text('\n'.join(md))


def check_matched(rows):
    old = {(r['instance'], r['method']): r for r in csv.DictReader((ROOT / 'computational-results.csv').open())}
    groups = defaultdict(list)
    for row in rows: groups[row['instance'], row['priority'], row['filter']].append(row)
    matched_metrics = 0
    for (identifier, priority, filtering), group in groups.items():
        assert len(group) == 4
        if filtering == 'active' and priority in ('uniform', 'max_incidence'):
            method = 'pick_first_uniform_blockers' if priority == 'uniform' else MAX
            for metric in ('queries', 'cost', 'nonanswers'):
                assert sum(int(r[metric]) for r in group) == int(old[identifier, method][f'total_{metric}'])
                matched_metrics += 1
        expected = old[identifier, MAX]['full_record_outcome']
        assert all(r['outcome'] == expected for r in group)
        for r in group:
            if not int(r['initially_ambiguous']): assert int(r['queries']) == int(r['cost']) == 0
    assert len(rows) == 2304 * 3 * 2 * 4
    assert len({(r['instance'], r['priority'], r['filter'], int(r['replicate'])) for r in rows}) == len(rows)
    return {'rows': len(rows), 'cases': 2304, 'old_metric_totals_matched': matched_metrics,
            'all_outcomes_match_full_record': True, 'all_initial_certificates_zero_cost': True}


def hand_oracle():
    # Two judges agree on blocker 1, one adds redundant blocker 2. A majority
    # is decided by candidate 1; active-blocker filtering unnecessarily keeps 2.
    ins = {'positive': frozenset({0}), 'negative': frozenset(), 'uncertain': (1, 2),
           'pick': 0, 'blockers': (frozenset({1}), frozenset({1}), frozenset({1, 2})),
           'quorum': 2, 'costs': {0: 1, 1: 1, 2: 1}}
    p, n, a = set(ins['positive']), set(ins['negative']), set(ins['uncertain'])
    direct = TierWorldOracle(ins).state(p, n, a)[2]
    assert direct == {1} and active_candidates(ins, p, n, a) == {1, 2}
    assert MaskContext(ins).relevant(p, n, a) == direct
    return {'active': [1, 2], 'exact': [1], 'explicit_tier_worlds': 4}


def matched():
    design = read_design()
    original = json.loads((ROOT / 'computational_design.json').read_text())
    start = time.perf_counter()
    rows, diagnostics = [], []
    for number, instance in enumerate(original_instances(), 1):
        initial = classify(instance['positive'], instance['negative'], instance['pick'], instance['blockers'], instance['quorum'])
        cache = {}
        case_rows = []
        for priority, filtering, rep in itertools.product(PRIORITIES, FILTERS, range(4)):
            seed = stable_seed(original['seed'], 'tie', instance['meta']['instance'], rep)
            result = matched_replay(instance, priority, filtering, seed, cache)
            case_rows.append({**instance['meta'], 'initially_ambiguous': int(len(initial) > 1),
                             'priority': priority, 'filter': filtering, 'replicate': rep, **result})
        strict_states = sum(exact < active for active, exact in cache.values())
        diagnostics.append({'instance': instance['meta']['instance'], 'phase': instance['meta']['phase'],
                            'distinct_meaningful_states': len(cache), 'distinct_strict_states': strict_states,
                            'ever_strict': bool(strict_states)})
        rows.extend(case_rows)
        if number % 128 == 0: print(f'Matched filters: {number}/2304 cases', flush=True)
    checks = check_matched(rows)
    checks['explicit_tier_hand_case'] = hand_oracle()
    checks['every_distinct_meaningful_state_mask_equals_dnf'] = True
    write_csv(ROOT / 'matched-relevance-results.csv', rows)
    payload = {'status': 'complete', 'design_sha256': sha(ROOT / 'matched-relevance-design.json'),
               'analysis_source_sha256': sha(__file__), 'csv_sha256': sha(ROOT / 'matched-relevance-results.csv'),
               'elapsed_seconds': time.perf_counter() - start, 'checks': checks,
               'summaries': matched_summaries(rows),
               'state_frequencies': {'definition': 'Acquisition can proceed and pick is not available; distinct states deduplicate within instance across all six policies/four seeds, but not across design cells.',
                   'meaningful_state_visits': sum(r['meaningful_visits'] for r in rows),
                   'strict_state_visits': sum(r['strict_visits'] for r in rows),
                   'distinct_meaningful_states': sum(r['distinct_meaningful_states'] for r in diagnostics),
                   'distinct_strict_states': sum(r['distinct_strict_states'] for r in diagnostics),
                   'instances_with_meaningful_state': sum(r['distinct_meaningful_states'] > 0 for r in diagnostics),
                   'instances_with_strict_state': sum(r['ever_strict'] for r in diagnostics),
                   'per_instance': diagnostics,
                   'by_priority_filter': {f'{priority}_{filtering}': {
                       'visits': sum(r['meaningful_visits'] for r in rows if r['priority'] == priority and r['filter'] == filtering),
                       'strict_visits': sum(r['strict_visits'] for r in rows if r['priority'] == priority and r['filter'] == filtering),
                       'changed_priority_visits': sum(r['changed_priority_visits'] for r in rows if r['priority'] == priority and r['filter'] == filtering)}
                       for priority in PRIORITIES for filtering in FILTERS}}}
    dump(ROOT / 'matched-relevance-results.json', payload)
    matched_markdown(payload)
    read_design()
    print(json.dumps({'checks': checks, 'all_summaries': {k: v['all'] for k, v in payload['summaries'].items()},
                      'state_frequencies': {k: v for k, v in payload['state_frequencies'].items() if k not in ('per_instance', 'by_priority_filter')}}, indent=2), flush=True)


def verify_stored():
    read_design()
    rows = list(csv.DictReader((ROOT / 'matched-relevance-results.csv').open()))
    for r in rows:
        for k in ('queries', 'cost', 'nonanswers', 'replicate', 'initially_ambiguous', 'meaningful_visits', 'strict_visits', 'changed_priority_visits'):
            r[k] = int(r[k])
    saved = json.loads((ROOT / 'matched-relevance-results.json').read_text())
    assert sha(ROOT / 'matched-relevance-results.csv') == saved['csv_sha256']
    assert matched_summaries(rows) == saved['summaries']
    checks = check_matched(rows)
    print(json.dumps(checks, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--explain', action='store_true')
    parser.add_argument('--matched', action='store_true')
    parser.add_argument('--verify-stored', action='store_true')
    args = parser.parse_args()
    if args.explain: explain()
    if args.matched: matched()
    if args.verify_stored: verify_stored()
    if not any(vars(args).values()): parser.error('Choose --explain, --matched, or --verify-stored')

if __name__ == '__main__': main()
