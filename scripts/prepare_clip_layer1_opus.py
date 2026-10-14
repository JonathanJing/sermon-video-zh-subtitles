#!/usr/bin/env python3
"""Build a source-only weekly test clip and gate its Layer 1 anchors with Opus.

The original approved sermon window and source package are read-only. The rebased
clip review is explicitly test-only; the Opus judge is machine evidence, never a
new human approval. Returned CLI responses are cached before they are parsed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_dev_180s_simulated_inputs as clip
from scripts import build_english_source_package as source_builder
from scripts import judge_english_source_for_translation as judge
from scripts import delivery_contract as contract
from scripts.claude_layer2_transport import ClaudeLayer2Transport, chat_envelope

MODEL = 'claude-opus-5-5'
EFFORT = 'high'
SIM = 'simulation test only - not a real human approval'


def derived_clip_review(spec: dict, details: dict, anchor: dict, aligned_path: Path) -> dict:
    """Check the frozen parent's identity and the complete rebased sentence slice."""
    parent = clip.read(spec['englishSourcePackage']['path'])
    full = clip.read(spec['anchor']['path'])
    lo, hi = spec['unitRange']
    before = float(spec['marginSeconds']['before'])
    offset = max(0.0, full['sourceUnits'][lo]['start'] - before)
    selected = full['sourceUnits'][lo:hi]
    unit_ids = {row['sourceUnitId'] for row in selected}
    checks = []

    def record(name, passed, evidence):
        checks.append({'checkId': name, 'status': 'pass' if passed else 'fail', 'evidence': evidence})

    record('frozenParent', contract.sha(parent) == spec['englishSourcePackage']['jsonSha256']
           and parent['anchors']['artifact']['jsonSha256'] == contract.sha(full)
           and parent['transcript']['artifact']['sha256'] == clip.sha(spec['alignedSegments']['path'])
           and parent['source']['approvedWindow']['humanApproval'] is True,
           'the original approved source, aligned segments and anchors match the clip specification')
    record('completeSentences', bool(selected)
           and selected[0]['sourceSentenceId'] not in {u['sourceSentenceId'] for u in full['sourceUnits'][:lo]}
           and selected[-1]['sourceSentenceId'] not in {u['sourceSentenceId'] for u in full['sourceUnits'][hi:]},
           'the selected unit range contains every unit of its boundary sentences')
    rows = anchor['sourceUnits']
    record('rebasedUnitIdentity', len(rows) == len(selected) and all(
        row['sourceUnitId'] == original['sourceUnitId']
        and row['sourceSentenceId'] == original['sourceSentenceId']
        and row['english'] == original['english']
        and row['sourceWordIds'] == original['sourceWordIds']
        and abs(row['start'] - (original['start'] - offset)) < 0.000002
        and abs(row['end'] - (original['end'] - offset)) < 0.000002
        for row, original in zip(rows, selected)),
        'every English unit and word ID is the frozen parent unit with one timeline offset')
    record('translationRequestCoverage', [r['sourceUnitIds'] for r in anchor['translationRequests']]
           == [[r['sourceUnitId']] for r in rows]
           and all(set(r['sourceUnitIds']) <= unit_ids for r in anchor['translationRequests']),
           'one translation request covers each selected source unit in order')
    record('alignedAndMediaBounds', anchor['input']['mfaSegmentsSha256'] == clip.sha(aligned_path)
           and bool(details['segments'])
           and clip.duration(details['media']) >= rows[-1]['end']
           and float(spec['approvedWindowStartSeconds']) + offset >= parent['source']['approvedWindow']['startSeconds']
           and float(spec['approvedWindowStartSeconds']) + offset + clip.duration(details['media'])
           <= parent['source']['approvedWindow']['endSeconds'] + 0.2,
           'aligned English and clip media remain inside the original approved sermon window')
    issues = [row['checkId'] for row in checks if row['status'] != 'pass']
    return {'status': 'pass' if not issues else 'fail', 'checks': checks, 'issues': issues}


def prepare(spec_path: Path, out: Path, *, list_price_cap_usd: float = 3.0,
            preflight_only: bool = False) -> dict:
    spec_path, out = spec_path.resolve(), out.resolve()
    spec = clip.read(spec_path)
    if spec.get('schemaVersion') != clip.CLIP_SPEC_SCHEMA or not spec.get('sourceId') or not spec.get('sourceUrl'):
        raise ValueError('Source-only clip requires a v2 spec with real sourceId and sourceUrl')
    spec_sha = clip.sha(spec_path)
    binding = out / 'source-only-spec-sha256.txt'
    if binding.exists() and binding.read_text().strip() != spec_sha:
        raise ValueError('Source-only clip directory belongs to another specification')
    out.mkdir(parents=True, exist_ok=True)
    if not binding.exists():
        binding.write_text(spec_sha + '\n')
    details = clip.weekly_clip(spec, out / 'clip', source_only=True)
    media, anchor = details['media'], details['anchor']
    aligned_path = clip.save(out / 'aligned-segments.json', details['segments'])
    anchor['input']['mfaSegmentsSha256'] = clip.sha(aligned_path)
    anchor_path = clip.save(out / 'anchor.json', anchor)
    existing = out / 'source.json'
    if existing.exists():
        package = clip.read(existing)
        source_builder.validate_ready_package(package)
        if (package['anchors']['artifact']['jsonSha256'] != contract.sha(anchor)
                or package['evidence']['machineJudge']['path'] != str((out / 'opus-machine-review.json').resolve())):
            raise ValueError('Existing clip source package differs from Opus Layer 1 inputs')
        return package

    deterministic = derived_clip_review(spec, details, anchor, aligned_path)
    clip.save(out / 'clip-derivation-review.json', deterministic)
    if deterministic['status'] != 'pass':
        raise ValueError('Clip Layer 1 deterministic review failed before Opus dispatch')
    if preflight_only:
        return {'preflight': deterministic}
    transport = ClaudeLayer2Transport(model=MODEL, effort=EFFORT, timeout_seconds=300,
                                      receipts_dir=out / 'opus-cli-receipts')
    spent = 0.0
    for saved in (out / 'opus-judge/cache').glob('*.json'):
        if saved.name.endswith('.started.json'):
            continue
        amount = (clip.read(saved).get('response', {}).get('claudeCli') or {}).get('listPriceUsd')
        if not isinstance(amount, (int, float)) or amount < 0:
            raise ValueError('Saved Opus Layer 1 call has no list-price equivalent: ' + str(saved))
        spent += amount
    if spent > list_price_cap_usd:
        raise ValueError('Saved Opus Layer 1 calls already exceed the subscription list-price cap')

    def caller(api_key, payload):
        nonlocal spent
        if api_key or spent >= list_price_cap_usd:
            raise ValueError('Opus Layer 1 subscription list-price cap reached')
        response = transport('', dict(payload, max_completion_tokens=7000), role='source')
        envelope = chat_envelope(response, MODEL)
        envelope['created'] = int(time.time())
        amount = response.get('listPriceUsd')
        if not isinstance(amount, (int, float)) or amount < 0:
            raise ValueError('Opus Layer 1 returned without list-price equivalent')
        spent += amount
        return envelope

    machine = judge.run(aligned_path=aligned_path, manifest_path=anchor_path,
                        out=out / 'opus-machine-review.json', model=MODEL, effort=EFFORT,
                        batch_size=15, api_key='', cache_root=out / 'opus-judge', workers=1,
                        caller=caller, deterministic_clip_review=deterministic)
    if spent > list_price_cap_usd:
        raise ValueError('Opus Layer 1 subscription list-price cap exceeded; all returned calls remain cached')
    if not machine['layer2DevelopmentEligible']:
        raise ValueError('Opus Layer 1 did not approve the clip for Layer 2 test development')

    source_url = details['source_url']
    summary_path = clip.save(out / 'summary.json', {
        'sourceUrl': source_url, 'sourceDurationSeconds': clip.duration(media),
        'sermonStartSeconds': 0, 'sermonEndSeconds': clip.duration(media), 'readingAligner': 'mfa',
        'models': {'referenceAsr': 'gpt-transcribe (historical approved source)'},
        'pipelineInputIdentity': {'sourceAudio': {'sha256': clip.sha(media),
                                                 'sizeBytes': media.stat().st_size}}})
    approval = clip.save(out / 'window-review.json', {
        'status': 'approved', 'humanApproval': True,
        'sourceUrlHash': hashlib.sha256(source_url.encode()).hexdigest(),
        'sourceMediaSha256': clip.sha(media), 'approvedBy': SIM,
        'approvalText': SIM + '; derived from original approved source window and source package',
        'startTime': '00:00:00', 'endTime': clip.clock(clip.duration(media))})
    review = clip.save(out / 'english-review.json', {
        'schemaVersion': 'sermon-english-source-review-v1',
        'alignedSegmentsSha256': clip.sha(aligned_path),
        'anchorManifestJsonSha256': contract.sha(anchor), 'humanApproval': True,
        'reviewedBy': SIM, 'reviewedAt': datetime.now(timezone.utc).isoformat(),
        'reviewedSourceUnitIds': [u['sourceUnitId'] for u in anchor['sourceUnits']],
        'checks': {name: 'approved' for name in source_builder.APPROVED_CHECKS},
        'notes': SIM + '; this receipt is a test fixture, with Opus machine gate recorded separately'})
    package = source_builder.build_package(aligned_path, anchor_path, summary_path=summary_path,
        approval_evidence_path=approval, review_path=review,
        machine_judge_path=out / 'opus-machine-review.json', source_id=details['source_id'],
        source_url_hash=hashlib.sha256(source_url.encode()).hexdigest(),
        service_date=details['service_date'])
    source_builder.validate_ready_package(package)
    clip.save(existing, package)
    clip.save(out / 'layer1-opus-summary.json', {
        'schemaVersion': 'sermon-clip-layer1-opus-summary-v1', 'sourceOnly': True,
        'humanApproval': False, 'testFixtureReview': True, 'model': MODEL, 'effort': EFFORT,
        'sourceId': spec['sourceId'], 'sourcePackageJsonSha256': contract.sha(package),
        'anchorManifestJsonSha256': contract.sha(anchor), 'clipMediaSha256': clip.sha(media),
        'unitCount': len(anchor['sourceUnits']), 'sentenceCount': machine['counts']['sourceSentences'],
        'machineStatus': machine['status'], 'subscriptionListPriceUsd': round(spent, 6),
        'subscriptionListPriceCapUsd': list_price_cap_usd})
    return package


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clip-spec', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--list-price-cap-usd', type=float, default=3.0)
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args()
    result = prepare(args.clip_spec, args.out, list_price_cap_usd=args.list_price_cap_usd,
                     preflight_only=args.preflight_only)
    print(json.dumps({'status': 'preflight_pass' if args.preflight_only else 'source_ready',
                      'source': str((args.out / 'source.json').resolve()),
                      'resultSha256': contract.sha(result)}, ensure_ascii=False))
