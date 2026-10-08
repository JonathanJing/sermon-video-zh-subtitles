#!/usr/bin/env python3
"""Sol 6.1 high fast (Codex CLI) versus Claude Opus (Claude CLI) initial translation A/B.

Experiment only. Both arms translate the same frozen prompts from an existing
baseline directory, interleaved per group with alternating order. Both use
subscription logins; neither receives an API key. No production admission,
retry, or model substitution: a started marker without a response requires
reconciliation before rerunning that arm.
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

ARMS = ('sol', 'opus')


def payloads(preview):
    payload = json.loads(preview.read_text())['payload']
    messages = payload['messages']
    source = json.loads(messages[1]['content'])
    sol = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high', 'service_tier': 'fast', 'messages': messages}
    return source, {'sol': sol, 'opus': {'messages': messages}}


def run_arm(job, arm, call, payload, source, schema):
    directory = job / arm
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


def summarize(pairs):
    summary = {'groups': len(pairs), 'units': sum(len(p['source']['sourceUnitIds']) for p in pairs),
               'humanApproval': False,
               'validation': 'schema, group/unit identity, coverage, independent sessions, no tools',
               'speedLimit': 'Interleaved sequential calls, alternating arm order; one run, service load uncontrolled',
               'costLimit': 'Both arms use subscription quota; opus listPriceUsd is the CLI list-price equivalent, not a charge'}
    for arm in ARMS:
        receipts = [p[arm]['receipt'] for p in pairs]
        times = [r['elapsedSeconds'] for r in receipts]
        summary[arm] = {'model': receipts[0]['requestedModel'], 'sumSeconds': sum(times),
                        'medianSeconds': statistics.median(times), 'minSeconds': min(times),
                        'maxSeconds': max(times), 'usage': usage_totals(receipts)}
    summary['opus']['listPriceUsd'] = sum(p['opus']['receipt'].get('listPriceUsd') or 0 for p in pairs)
    summary['opusFasterPairs'] = sum(p['opus']['receipt']['elapsedSeconds'] < p['sol']['receipt']['elapsedSeconds']
                                     for p in pairs)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True,
                        help='Directory with group-*-astra.policy-preview.json frozen prompts')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--opus-effort', choices=['medium', 'high', 'xhigh'], default='high')
    parser.add_argument('--codex-cli', type=Path, default=Path.home() / '.local/bin/codex')
    parser.add_argument('--claude-cli', type=Path)
    args = parser.parse_args(argv)
    baseline, out = args.baseline.resolve(), args.out.resolve()
    previews = sorted(baseline.glob('group-*-astra.policy-preview.json'))
    assert previews, 'Missing baseline prompts'
    schema = output_schema('translator')
    sol = CodexLayer2Transport(args.codex_cli, receipts_dir=out / '_cli_calls' / 'sol')
    opus = ClaudeLayer2Transport(args.claude_cli, effort=args.opus_effort, receipts_dir=out / '_cli_calls' / 'opus')
    identity = {'schemaVersion': 'claude-translation-ab-v1', 'baseline': str(baseline),
                'baselineHashes': {p.name: sha(p) for p in previews},
                'sol': {'model': 'gpt-6.1-sol', 'effort': 'high', 'serviceTier': 'fast',
                        'transport': sol.execution_identity},
                'opus': {'model': opus.model, 'effort': opus.effort, 'transport': opus.execution_identity},
                'runnerSha256': sha(Path(__file__)), 'schema': schema,
                'order': 'even groups sol first, odd groups opus first', 'workers': 1, 'humanApproval': False}
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'identity.json').exists():
        assert json.loads((out / 'identity.json').read_text()) == identity, 'Identity changed'
    else:
        assert not any(p.name != '_cli_calls' for p in out.iterdir()), 'Unidentified output directory'
        save(out / 'identity.json', identity)
    calls = {'sol': lambda payload: sol('', payload),
             'opus': lambda payload: opus('', payload, role='translator')}
    pairs, fresh = [], {arm: 0 for arm in ARMS}
    for index, preview in enumerate(previews):
        source, arm_payloads = payloads(preview)
        job = out / preview.name.split('-astra.')[0]
        receipts, results = {}, {}
        for arm in (ARMS if index % 2 == 0 else ARMS[::-1]):
            response, new = run_arm(job, arm, calls[arm], arm_payloads[arm], source, schema)
            fresh[arm] += new
            receipts[arm], results[arm] = response, json.loads(response['content'])
        pairs.append({'group': source['translationGroupId'], 'source': source,
                      **{arm: {'result': results[arm], 'receipt': receipts[arm]} for arm in ARMS}})
        print(json.dumps({'group': source['translationGroupId'],
                          **{arm + 'Seconds': round(receipts[arm]['elapsedSeconds'], 3) for arm in ARMS}}), flush=True)
    save_or_check(out / 'pairs.json', pairs)
    blinded, mapping = [], []
    for index, pair in enumerate(pairs):
        order = list(ARMS) if index % 2 == 0 else list(ARMS[::-1])
        blinded.append({'group': pair['group'], 'source': pair['source'],
                        'X': pair[order[0]]['result'], 'Y': pair[order[1]]['result']})
        mapping.append({'group': pair['group'], 'X': order[0], 'Y': order[1]})
    save_or_check(out / 'blind.json', blinded)
    save_or_check(out / 'blind-key.json', mapping)
    save_or_check(out / 'summary.json', summarize(pairs))
    print(json.dumps({'freshCalls': fresh, 'groups': len(pairs)}), flush=True)


if __name__ == '__main__':
    main()
