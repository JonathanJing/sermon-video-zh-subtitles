"""Read-only measured timing plan using the unchanged formal Layer 3 scheduler.

Rows describe whole approved groups; no text, WAV, source anchor, policy or review
is edited. A timing pass is machine feasibility evidence, never approval.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import render_formal_target_language_speech as formal

EPSILON = 1e-6


def _number(value, name, *, positive=False):
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError('Invalid ' + name)
    return float(value)


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def plan(source_seconds, rows, policy=None, *, identities=None, locale='und'):
    """Return hash-bound diagnostics; sourceStart/sourceEnd are clip-relative.

    gid, sourceStart, sourceEnd and audioSeconds are required. audioSha256 is
    optional but, if present, must be an actual SHA-256 supplied by the caller.
    identities is a name-to-SHA map for source/candidate/job/etc. Input hashes
    bind reported measurements; this function does not independently probe WAVs.
    """
    source_seconds = _number(source_seconds, 'source duration', positive=True)
    policy = dict(formal.DEFAULT_POLICY if policy is None else policy)
    if set(policy) != set(formal.DEFAULT_POLICY):
        raise ValueError('Invalid schedule policy fields')
    policy = {k: _number(v, k) for k, v in policy.items()}
    if not isinstance(rows, list) or not rows or not isinstance(locale, str) or not locale.strip():
        raise ValueError('Rows and locale are required')
    identities = dict(identities or {})
    if any(not isinstance(k, str) or not k or not isinstance(v, str) or not re.fullmatch('[a-f0-9]{64}', v) for k, v in identities.items()):
        raise ValueError('Input identities must be named SHA-256 values')
    normalized, seen, previous_end = [], set(), 0.0
    for row in rows:
        if not isinstance(row, dict) or set(row) - {'gid', 'sourceStart', 'sourceEnd', 'audioSeconds', 'audioSha256'}:
            raise ValueError('Invalid timing row fields')
        gid = row.get('gid')
        if not isinstance(gid, str) or not gid.strip() or gid in seen:
            raise ValueError('Missing or duplicate group ID')
        start = _number(row.get('sourceStart'), 'source start')
        end = _number(row.get('sourceEnd'), 'source end', positive=True)
        duration = _number(row.get('audioSeconds'), 'audio duration', positive=True)
        if not start < end <= source_seconds + EPSILON or start < previous_end - EPSILON:
            raise ValueError('Source groups must be ordered, non-overlapping and inside clip')
        value = {'gid': gid, 'sourceStart': start, 'sourceEnd': end, 'audioSeconds': duration}
        if 'audioSha256' in row:
            sha = row['audioSha256']
            if not isinstance(sha, str) or not re.fullmatch('[a-f0-9]{64}', sha):
                raise ValueError('Invalid audio SHA-256')
            value['audioSha256'] = sha
        normalized.append(value)
        seen.add(gid)
        previous_end = end
    context = {'anchor': {'sourceUnits': [{'sourceUnitId': r['gid'], 'start': r['sourceStart'], 'end': r['sourceEnd']} for r in normalized]},
               'clip_timeline_map': {'anchorOffsetSeconds': 0.0, 'clipDurationSeconds': source_seconds},
               'candidate': {'groups': [{'translationGroupId': r['gid'], 'sourceUnitIds': [r['gid']]} for r in normalized]},
               'job': {'targetLocale': locale}}
    scheduled = formal.schedule(context, [{'durationSeconds': r['audioSeconds']} for r in normalized], policy)
    observations, lag_violations, tail_violations, own_excess = [], [], [], []
    previous_end = 0.0
    for i, (row, entry) in enumerate(zip(normalized, scheduled['entries'])):
        source_span = row['sourceEnd'] - row['sourceStart']
        own = max(0.0, row['audioSeconds'] - source_span)
        lag = entry['plannedEnd'] - row['sourceEnd']
        lag_excess = max(0.0, lag - policy['maxEndLagSeconds'])
        clip_excess = max(0.0, entry['plannedEnd'] - source_seconds)
        if own > EPSILON:
            own_excess.append(row['gid'])
        if lag_excess > EPSILON:
            lag_violations.append(row['gid'])
        if clip_excess > EPSILON:
            tail_violations.append(row['gid'])
        next_start = normalized[i + 1]['sourceStart'] if i + 1 < len(normalized) else source_seconds
        observations.append({**row, 'sourceSpanSeconds': round(source_span, 6),
            'plannedStart': entry['plannedStart'], 'plannedEnd': entry['plannedEnd'],
            'ownSpanExcessSeconds': round(own, 6), 'ownSpanExcessWarning': own > EPSILON,
            'endLagSeconds': round(lag, 6), 'maxLagViolationSeconds': round(lag_excess, 6),
            'clipTailOverflowSeconds': round(clip_excess, 6),
            'propagatedStartDelaySeconds': round(max(0.0, entry['plannedStart'] - row['sourceStart'] - policy['reactionLagSeconds']), 6),
            'unusedGapBeforeSeconds': round(max(0.0, entry['plannedStart'] - previous_end - (policy['interUtteranceGapSeconds'] if i else 0.0)), 6),
            'remainingBeforeNextSourceStartSeconds': round(max(0.0, next_start - entry['plannedEnd']), 6),
            'requiresTimingReview': lag_excess > EPSILON or clip_excess > EPSILON})
        previous_end = entry['plannedEnd']
    audio_sum = sum(r['audioSeconds'] for r in normalized)
    gap_sum = (len(normalized) - 1) * policy['interUtteranceGapSeconds']
    natural_lower_bound = audio_sum + gap_sum
    earliest_lower_bound = normalized[0]['sourceStart'] + policy['reactionLagSeconds'] + natural_lower_bound
    minimum_recovery = max(0.0, earliest_lower_bound - source_seconds)
    tail_recovery = max(0.0, scheduled['entries'][-1]['plannedEnd'] - source_seconds)
    material = {'sourceSeconds': source_seconds, 'rows': normalized, 'policy': policy, 'locale': locale, 'identities': identities}
    return {'schemaVersion': 'sermon-target-audio-timing-plan-v1', 'status': 'diagnostic_only_requires_review',
        'diagnosticOnly': True, 'humanApproval': False, 'publicationEligible': False, 'grantsApproval': False,
        'modelCalls': 0, 'mutatesAudio': False, 'mutatesText': False, 'measurementsIndependentlyVerified': False,
        'sourceSeconds': source_seconds, 'locale': locale, 'policy': policy, 'inputIdentities': identities,
        'inputSha256': _hash(material), 'schedulerImplementationSha256': hashlib.sha256(Path(formal.__file__).read_bytes()).hexdigest(),
        'planImplementationSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'audioSeconds': round(audio_sum, 6), 'interGroupGapSeconds': round(gap_sum, 6),
        'naturalConcatenatedPlusGapLowerBoundSeconds': round(natural_lower_bound, 6),
        'earliestSerialLowerBoundSeconds': round(earliest_lower_bound, 6),
        'minimumDurationRecoverySeconds': round(minimum_recovery, 6),
        'scheduledTailRecoverySeconds': round(tail_recovery, 6),
        'unchangedAudioCannotFitSerialTimeline': minimum_recovery > EPSILON,
        'formalScheduleStatus': scheduled['status'], 'formalSchedule': scheduled,
        'ownSpanExcessWarnings': own_excess, 'maxLagViolations': lag_violations, 'clipTailOverflows': tail_violations,
        'groups': observations,
        'reviewActions': ['Review whole-group audio and source anchors; own-span excess alone is not a formal violation.',
            'Measure only actual edge silence before proposing lossless compaction; no automatic trim or approval.',
            'If unchanged serial audio cannot fit, retain independent audio timing with video synchronization unverified; scheduling alone cannot repair total duration.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    value = json.loads(args.input.read_text())
    result = plan(value['sourceSeconds'], value['rows'], value.get('policy'), identities=value.get('identities'), locale=value.get('locale', 'und'))
    if args.out.exists():
        raise ValueError('Use a new output path')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({k: result[k] for k in ('status', 'inputSha256', 'formalScheduleStatus', 'minimumDurationRecoverySeconds', 'scheduledTailRecoverySeconds', 'modelCalls')}))


if __name__ == '__main__':
    main()
