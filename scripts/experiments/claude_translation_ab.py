#!/usr/bin/env python3
"""Sol 6.1 high fast (Codex CLI) versus Claude Opus (Claude CLI) initial translation A/B.

Experiment only. Both arms translate the same frozen prompts from an existing
Layer 2 baseline directory, interleaved per group with alternating order. With
``--review`` each arm's draft then goes through the same Sol 6.1 medium fast
independent review, using the baseline's frozen reviewer prompt with only the
draft swapped in. Every call uses a subscription login; none receives an API
key. No production admission, retry, or model substitution: a started marker
without a response requires reconciliation before rerunning that call.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
from datetime import datetime, timezone

from scripts.codex_layer2_transport import CodexLayer2Transport, output_schema
from scripts.claude_layer2_transport import ClaudeLayer2Transport
from scripts.experiments.codex_translation_ab import save, save_or_check, sha, validate
from scripts.run_target_language_models import SEMANTIC_CHECKS

ARMS = ('sol', 'opus')
REPAIR_FIELDS = ('revisionBrief', 'partialRepair')


def load_baseline(baseline, first_group, group_count):
    """Frozen translator (and reviewer) prompts per group; repair revisions are skipped."""
    groups, skipped = [], []
    for preview in sorted(baseline.glob('group-*-astra.policy-preview.json')):
        stem = preview.name.split('-astra.')[0]
        number = int(stem.split('-')[1])
        if number < first_group or (group_count and number >= first_group + group_count):
            continue
        frozen = json.loads(preview.read_text())
        assert frozen.get('role', 'translator') == 'translator', f'Not a translator prompt: {preview}'
        messages = frozen['payload']['messages']
        source = json.loads(messages[1]['content'])
        if any(field in source for field in REPAIR_FIELDS):
            skipped.append(stem)
            continue
        reviewer_path = baseline / f'{stem}-sol.policy-preview.json'
        reviewer = json.loads(reviewer_path.read_text())['payload']['messages'] if reviewer_path.is_file() else None
        groups.append({'stem': stem, 'source': source, 'translator': messages, 'reviewer': reviewer,
                       'locale': (frozen.get('policy') or {}).get('targetLocale') or source.get('targetLocale'),
                       'hashes': {p.name: sha(p) for p in (preview, reviewer_path) if p.is_file()}})
    return groups, skipped


def translator_payloads(messages):
    sol = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high', 'service_tier': 'fast', 'messages': messages}
    return {'sol': sol, 'opus': {'messages': messages}}


def reviewer_payload(reviewer_messages, draft):
    """The baseline's frozen reviewer prompt with this arm's draft as the only change."""
    review_input = json.loads(reviewer_messages[1]['content'])
    assert 'astraDraft' in review_input, 'Baseline reviewer prompt has no draft field'
    review_input['astraDraft'] = draft
    messages = [reviewer_messages[0], {'role': 'user', 'content': json.dumps(review_input, ensure_ascii=False)}]
    return {'model': 'gpt-6.1-sol', 'reasoning_effort': 'medium', 'service_tier': 'fast', 'messages': messages}


def review_verdict(result, draft):
    review = result.get('semanticReview') or {}
    checks = review.get('checks') or {}
    passed = (review.get('status') == 'pass' and set(checks) == set(SEMANTIC_CHECKS)
              and all(value == 'pass' for value in checks.values())
              and not review.get('issues') and not review.get('uncertainty'))
    return {'passed': passed, 'status': review.get('status'),
            'failedChecks': sorted(name for name, value in checks.items() if value != 'pass'),
            'issues': review.get('issues') or [], 'uncertainty': review.get('uncertainty') or [],
            'reviewerEditedText': result.get('targetUtterances') != draft.get('targetUtterances')}


def run_call(directory, call, payload, source, schema):
    directory.mkdir(parents=True, exist_ok=True)
    response_path = directory / 'response.json'
    prompt_sha = hashlib.sha256(json.dumps(payload['messages'], sort_keys=True).encode()).hexdigest()
    if response_path.exists():
        response = json.loads(response_path.read_text())
        assert json.loads((directory / 'started.json').read_text())['promptSha256'] == prompt_sha, 'Cached prompt changed'
        validate(json.loads(response['content']), source, schema)
        return response, False
    assert not (directory / 'started.json').exists(), f'Unknown outcome in {directory}; reconcile receipts before retry'
    save(directory / 'started.json', {'startedAt': datetime.now(timezone.utc).isoformat(), 'promptSha256': prompt_sha})
    response = call(payload)
    validate(json.loads(response['content']), source, schema)
    save(response_path, response)
    return response, True


def usage_totals(responses):
    keys = ['inputTokens', 'cachedInputTokens', 'outputTokens', 'reasoningTokens']
    from scripts.sermon_model_call_observation import normalize_usage
    rows = [normalize_usage(r['usage']) if r.get('schemaVersion', '').startswith('codex') else r['usage']
            for r in responses]
    return {key: sum(row.get(key) or 0 for row in rows) for key in keys}


def timing(receipts):
    times = [r['elapsedSeconds'] for r in receipts]
    return {'sumSeconds': sum(times), 'medianSeconds': statistics.median(times),
            'minSeconds': min(times), 'maxSeconds': max(times), 'usage': usage_totals(receipts)}


def summarize(pairs, locale, skipped, reviewed):
    summary = {'targetLocale': locale, 'groups': len(pairs),
               'units': sum(len(p['source']['sourceUnitIds']) for p in pairs),
               'skippedRepairGroups': skipped, 'humanApproval': False,
               'validation': 'schema, group/unit identity, coverage, independent sessions, no tools',
               'speedLimit': 'Interleaved sequential calls, alternating arm order; one run, service load uncontrolled',
               'costLimit': 'All arms use subscription quota; opus listPriceUsd is the CLI list-price equivalent, not a charge'}
    for arm in ARMS:
        receipts = [p[arm]['receipt'] for p in pairs]
        summary[arm] = {'model': receipts[0]['requestedModel'], **timing(receipts)}
    summary['opus']['listPriceUsd'] = sum(p['opus']['receipt'].get('listPriceUsd') or 0 for p in pairs)
    summary['opusFasterPairs'] = sum(p['opus']['receipt']['elapsedSeconds'] < p['sol']['receipt']['elapsedSeconds']
                                     for p in pairs)
    if reviewed:
        for arm in ARMS:
            verdicts = [p[arm]['review']['verdict'] for p in pairs]
            summary[arm]['review'] = {
                'reviewer': 'gpt-6.1-sol medium fast', 'passed': sum(v['passed'] for v in verdicts),
                'failed': [p['group'] for p in pairs if not p[arm]['review']['verdict']['passed']],
                'reviewerEditedText': sum(v['reviewerEditedText'] for v in verdicts),
                **timing([p[arm]['review']['receipt'] for p in pairs])}
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True,
                        help='Layer 2 output directory with group-*-astra/-sol.policy-preview.json frozen prompts')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--first-group', type=int, default=1)
    parser.add_argument('--group-count', type=int, default=0, help='0 means every group from --first-group')
    parser.add_argument('--review', action='store_true',
                        help='Also run Sol 6.1 medium fast independent review on both arms')
    parser.add_argument('--opus-effort', choices=['medium', 'high', 'xhigh'], default='high')
    parser.add_argument('--codex-cli', type=Path, default=Path.home() / '.local/bin/codex')
    parser.add_argument('--claude-cli', type=Path)
    args = parser.parse_args(argv)
    baseline, out = args.baseline.resolve(), args.out.resolve()
    groups, skipped = load_baseline(baseline, args.first_group, args.group_count)
    assert groups, 'Missing baseline prompts'
    locales = {group['locale'] for group in groups}
    assert len(locales) == 1, f'One locale per run: {sorted(map(str, locales))}'
    locale = locales.pop()
    if args.review:
        assert all(group['reviewer'] for group in groups), 'Baseline lacks frozen reviewer prompts'
    schemas = {role: output_schema(role) for role in ('translator', 'reviewer')}
    sol = CodexLayer2Transport(args.codex_cli, receipts_dir=out / '_cli_calls' / 'sol')
    opus = ClaudeLayer2Transport(args.claude_cli, effort=args.opus_effort, receipts_dir=out / '_cli_calls' / 'opus')
    identity = {'schemaVersion': 'claude-translation-ab-v2', 'baseline': str(baseline), 'targetLocale': locale,
                'baselineHashes': {name: digest for group in groups for name, digest in group['hashes'].items()},
                'skippedRepairGroups': skipped,
                'sol': {'model': 'gpt-6.1-sol', 'effort': 'high', 'serviceTier': 'fast',
                        'transport': sol.execution_identity},
                'opus': {'model': opus.model, 'effort': opus.effort, 'transport': opus.execution_identity},
                'review': {'model': 'gpt-6.1-sol', 'effort': 'medium', 'serviceTier': 'fast'} if args.review else None,
                'runnerSha256': sha(Path(__file__)), 'schemas': schemas,
                'order': 'even groups sol first, odd groups opus first', 'workers': 1, 'humanApproval': False}
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'identity.json').exists():
        assert json.loads((out / 'identity.json').read_text()) == identity, 'Identity changed'
    else:
        assert not any(p.name != '_cli_calls' for p in out.iterdir()), 'Unidentified output directory'
        save(out / 'identity.json', identity)
    calls = {'sol': lambda payload: sol('', payload),
             'opus': lambda payload: opus('', payload, role='translator')}
    pairs, fresh = [], {'sol': 0, 'opus': 0, 'review': 0}
    for index, group in enumerate(groups):
        source, job = group['source'], out / group['stem']
        order = ARMS if index % 2 == 0 else ARMS[::-1]
        row = {'group': source['translationGroupId'], 'source': source}
        for arm in order:
            response, new = run_call(job / arm, calls[arm], translator_payloads(group['translator'])[arm],
                                     source, schemas['translator'])
            fresh[arm] += new
            row[arm] = {'result': json.loads(response['content']), 'receipt': response}
        if args.review:
            for arm in order:
                draft = row[arm]['result']
                response, new = run_call(job / f'{arm}-review', lambda payload: sol('', payload),
                                         reviewer_payload(group['reviewer'], draft), source, schemas['reviewer'])
                fresh['review'] += new
                result = json.loads(response['content'])
                row[arm]['review'] = {'result': result, 'receipt': response, 'verdict': review_verdict(result, draft)}
        pairs.append(row)
        print(json.dumps({'group': row['group'], **{arm + 'Seconds': round(row[arm]['receipt']['elapsedSeconds'], 3)
                                                    for arm in ARMS},
                          **({arm + 'ReviewPassed': row[arm]['review']['verdict']['passed'] for arm in ARMS}
                             if args.review else {})}), flush=True)
    save_or_check(out / 'pairs.json', pairs)
    blinded, mapping = [], []
    for index, pair in enumerate(pairs):
        order = list(ARMS) if index % 2 == 0 else list(ARMS[::-1])
        blinded.append({'group': pair['group'], 'source': pair['source'],
                        'X': pair[order[0]]['result'], 'Y': pair[order[1]]['result']})
        mapping.append({'group': pair['group'], 'X': order[0], 'Y': order[1]})
    save_or_check(out / 'blind.json', blinded)
    save_or_check(out / 'blind-key.json', mapping)
    save_or_check(out / 'summary.json', summarize(pairs, locale, skipped, args.review))
    print(json.dumps({'freshCalls': fresh, 'groups': len(pairs), 'targetLocale': locale}), flush=True)


if __name__ == '__main__':
    main()
