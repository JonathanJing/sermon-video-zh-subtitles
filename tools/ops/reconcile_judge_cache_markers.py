#!/usr/bin/env python3
"""Bind unknown Layer 1 judge-cache markers to Claude CLI calls that did return.

    .venv/bin/python tools/ops/reconcile_judge_cache_markers.py <judge cache root> <claude-cli-calls dir>...

A judge run that stops after the CLI answered but before the cache receipt is written (a
crash, a binding check, a killed driver) leaves ``<stage>-<hash>.started.json`` in the cache
and the answer in ``claude-cli-calls/<call>/response.json``. The cache refuses to retry an
unknown request by design. This tool matches each marker to the one returned call that names
exactly the marker's sentences for the marker's model, rebuilds the chat envelope the transport
would have returned and binds it with ``reconcile_returned_response``. It never calls a model;
a marker with no returned call, or more than one, stays unknown and is listed.
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import tongxing_host  # noqa: E402,F401  binds the production package ports
from tongxing_production.compute.transports.claude_layer2 import chat_envelope  # noqa: E402
from tongxing_production.source.english_source_judge_cache import reconcile_returned_response  # noqa: E402


def returned_calls(directories):
    calls = []
    for directory in directories:
        for path in sorted(glob.glob(str(Path(directory) / '*' / 'response.json'))):
            response = json.loads(Path(path).read_text(encoding='utf-8'))
            try:
                ids = [row['sourceSentenceId'] for row in json.loads(response['content']).get('sentences', [])]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            calls.append((Path(path), response, ids))
    return calls


def execution_identity(model, effort):
    """The transport identity for the envelope; None when the CLI is not available here."""
    try:
        from tongxing_production.compute.transports.claude_source_judge import ClaudeSourceJudgeTransport
        return ClaudeSourceJudgeTransport(model=model, effort=effort).execution_identity
    except Exception:  # the receipt still carries the original call's own identity
        return None


def reconcile(cache_root, call_directories, *, identity=execution_identity):
    cache = Path(cache_root) / 'cache'
    calls = returned_calls(call_directories)
    report = {'reconciled': [], 'unresolved': []}
    identities = {}
    for marker in sorted(cache.glob('*.started.json')):
        receipt = marker.with_name(marker.name[:-len('.started.json')] + '.json')
        if receipt.exists():
            continue
        saved = json.loads(marker.read_text(encoding='utf-8'))
        payload = saved['request']['payload']
        wanted = [row['sourceSentenceId'] for row in json.loads(payload['messages'][1]['content'])['sentences']]
        matches = [(path, response) for path, response, ids in calls
                   if ids == wanted and response.get('requestedModel') == payload['model']
                   and response.get('completed') is True]
        if len(matches) != 1:
            report['unresolved'].append({'marker': marker.name, 'matches': len(matches)})
            continue
        path, response = matches[0]
        key = (payload['model'], payload.get('reasoning_effort'))
        if key not in identities:
            identities[key] = identity(*key)
        envelope = chat_envelope(response, payload['model'])
        envelope['claudeCli']['executionIdentity'] = identities[key]
        envelope['claudeCli']['auxiliaryModelUsage'] = response.get('auxiliaryModelUsage', {})
        written = reconcile_returned_response(marker_path=marker, response=envelope,
                                              expected_request_sha256=saved['requestSha256'],
                                              requested_model=payload['model'])
        report['reconciled'].append({'marker': marker.name, 'call': path.parent.name, 'receipt': Path(written).name})
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('cache_root', help='judge cache root (the directory holding cache/)')
    parser.add_argument('call_directories', nargs='+', help='claude-cli-calls directories of the interrupted runs')
    args = parser.parse_args(argv)
    report = reconcile(args.cache_root, args.call_directories)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if not report['unresolved'] else 3


if __name__ == '__main__':
    raise SystemExit(main())
