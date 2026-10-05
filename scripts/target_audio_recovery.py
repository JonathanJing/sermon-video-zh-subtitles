"""Measured audio diagnostics and explicit, lossless per-unit repair staging."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
try:
    from scripts import sermon_sentence_interpretation as identity
except ImportError:
    import sermon_sentence_interpretation as identity


def diagnose(context, rows, plan):
    anchors = {u['sourceUnitId']: u for u in context['anchor']['sourceUnits']}
    offset = context['clip_timeline_map']['anchorOffsetSeconds']
    units, previous_lag = [], 0.0
    for index, (group, row, entry) in enumerate(zip(context['candidate']['groups'], rows, plan['entries'])):
        start = float(anchors[group['sourceUnitIds'][0]]['start']) - offset
        end = float(anchors[group['sourceUnitIds'][-1]]['end']) - offset
        duration = row['durationSeconds']
        lag = max(0., entry['plannedEnd'] - end)
        ratio = duration / (end - start) if end > start else None
        own_overflow = duration + plan['policy']['reactionLagSeconds'] > end - start + plan['policy']['maxEndLagSeconds']
        units.append({'unitIndex': index, 'textGroupId': group['translationGroupId'],
                      'audioSha256': row['audio']['sha256'], 'targetTextSha256': row['targetTextSha256'],
                      'durationSeconds': duration, 'sourceDurationSeconds': end - start,
                      'durationSourceRatio': ratio, 'endLagSeconds': lag,
                      'lagJumpSeconds': lag - previous_lag,
                      'classification': 'single_unit_overflow' if own_overflow else
                                        'propagated_lag' if lag > plan['policy']['maxEndLagSeconds'] else 'within_policy',
                      'repairDecision': 'operator_required' if own_overflow else 'not_selected'})
        previous_lag = lag
    runs, active = [], []
    for row in units:
        if row['classification'] != 'within_policy': active.append(row['unitIndex'])
        elif active:
            runs.append(active); active = []
    if active: runs.append(active)
    return {'schemaVersion': 'sermon-target-audio-diagnostics-v1', 'evidenceKind': 'measured',
            'jobJsonSha256': identity.json_sha256(context['job']),
            'policy': plan['policy'], 'units': units, 'highRiskRuns': runs,
            'rootCause': 'not_determined', 'automaticToleranceChange': False}


def quarantine_unit(root: Path, job, index: int, *, reason: str):
    """Call under the formal render lock. Preserve bytes before reopening one unit.

    Unit identity/seed remain unchanged; a text or sound change requires a new
    approved job/root. Quarantining never decides whether text or TTS was wrong.
    """
    if not isinstance(reason, str) or not reason.strip() or type(index) is not int or not 0 <= index < len(job['units']):
        raise ValueError('Quarantine requires a valid unit and explicit reason')
    wav = root / job['units'][index]['outputRelativePath']
    if not wav.is_file() or not wav.resolve().is_relative_to(root.resolve()):
        raise ValueError('Quarantine WAV missing or outside render root')
    digest = identity.sha256(wav)
    destination = root / 'quarantine' / f'unit-{index:04d}-{digest}'
    if destination.is_symlink() or not destination.resolve().is_relative_to(root.resolve()):
        raise ValueError('Quarantine destination escapes render root')
    destination.mkdir(parents=True, exist_ok=True)
    paths = [wav] + [root / f'receipts/unit-{index:04d}{suffix}.json' for suffix in ('', '.intent', '.render')]
    # The prior whole-track manifest must not short-circuit repaired assembly.
    manifest_path = root / 'render-manifest.json'
    paths += [manifest_path]
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        for key in ('track', 'schedule', 'captions'):
            ref = manifest.get(key)
            if not isinstance(ref, dict) or not isinstance(ref.get('path'), str): continue
            path = root / ref['path']
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('Quarantined manifest asset escapes render root')
            paths.append(path)
            if key == 'track' and path.suffix == '.mp3': paths.append(path.with_suffix('.wav'))
    paths = list(dict.fromkeys(paths))
    saved = []
    for path in paths:
        if not path.exists(): continue
        target = destination / path.name
        if target.exists() and identity.sha256(target) != identity.sha256(path):
            raise ValueError('Quarantine destination conflict')
        if not target.exists(): shutil.copy2(path, target)
        if identity.sha256(target) != identity.sha256(path):
            raise ValueError('Quarantine copy verification failed')
        saved.append((path, target))
    receipt = {'schemaVersion': 'sermon-audio-quarantine-v1', 'unitIndex': index,
               'audioSha256': digest, 'jobJsonSha256': identity.json_sha256(job), 'reason': reason,
               'saved': [{'path': str(target.resolve()), 'sha256': identity.sha256(target)} for _, target in saved]}
    (destination / 'quarantine.json').write_text(json.dumps(receipt, indent=2) + '\n')
    for path, _ in saved: path.unlink()
    return receipt


ADJUDICATION_REASONS = {'asr_misrecognition', 'acceptable_reading', 'repair_audio', 'repair_text', 'unresolved'}


def bind_adjudication(unit, track, *, reason, evidence, corrected_transcript=None, artifact_root=None):
    """Supplemental evidence only; cannot create listening or release approval."""
    if reason not in ADJUDICATION_REASONS or not isinstance(evidence, str) or not evidence.strip():
        raise ValueError('Explicit adjudication reason and evidence required')
    if corrected_transcript is not None and (not isinstance(corrected_transcript, str) or not corrected_transcript.strip()):
        raise ValueError('Corrected transcript must be nonempty text or null')
    for artifact in (unit['audio'], track):
        path = Path(artifact['path'])
        if not path.is_absolute():
            if artifact_root is None: raise ValueError('Relative audio requires artifact root')
            path = (Path(artifact_root) / path).resolve()
            if not path.is_relative_to(Path(artifact_root).resolve()): raise ValueError('Audio escapes artifact root')
        if identity.sha256(path) != artifact['sha256']:
            raise ValueError('Adjudication audio hash changed')
    return {'schemaVersion': 'sermon-audio-adjudication-detail-v1',
            'textGroupId': unit['textGroupId'], 'audioSha256': unit['audio']['sha256'],
            'trackSha256': track['sha256'], 'targetTextSha256': unit['targetTextSha256'],
            'reason': reason, 'evidence': evidence, 'correctedTranscript': corrected_transcript,
            'grantsApproval': False}


def validate_adjudication(detail, unit, track, *, artifact_root=None):
    expected = bind_adjudication(unit, track, reason=detail.get('reason'),
                                 evidence=detail.get('evidence'),
                                 corrected_transcript=detail.get('correctedTranscript'), artifact_root=artifact_root)
    if detail != expected:
        raise ValueError('Adjudication text, unit WAV, or track binding changed')


def summarize_adjudications(details, units, track, *, artifact_root=None):
    """Report false alarms among individually adjudicated flagged units only."""
    by_group = {unit['textGroupId']: unit for unit in units}
    if len(by_group) != len(units): raise ValueError('Duplicate audio unit identity')
    seen, resolved, false_alarms = set(), 0, 0
    for detail in details:
        group = detail['textGroupId']
        if group in seen or group not in by_group:
            raise ValueError('Duplicate or unknown adjudicated group')
        seen.add(group)
        validate_adjudication(detail, by_group[group], track, artifact_root=artifact_root)
        if detail['reason'] != 'unresolved':
            resolved += 1
            false_alarms += detail['reason'] in {'asr_misrecognition', 'acceptable_reading'}
    return {'individuallyAdjudicatedUnits': resolved, 'falseAlarmUnits': false_alarms,
            'reviewQueueFalseAlarmFraction': false_alarms / resolved if resolved else None,
            'unresolvedUnits': len(details) - resolved,
            'scope': 'supplied_hash_bound_individual_adjudications_only'}


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Record optional ASR adjudication detail without granting approval')
    parser.add_argument('--audio-package', type=Path, required=True)
    parser.add_argument('--artifact-root', type=Path)
    parser.add_argument('--group', required=True)
    parser.add_argument('--reason', choices=sorted(ADJUDICATION_REASONS), required=True)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--corrected-transcript')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    package = json.loads(args.audio_package.read_text())
    units = [u for u in package['units'] if u['textGroupId'] == args.group]
    if len(units) != 1:
        raise ValueError('Adjudication group must identify exactly one audio unit')
    result = bind_adjudication(units[0], package['track'], reason=args.reason,
                              evidence=args.evidence, corrected_transcript=args.corrected_transcript,
                              artifact_root=args.artifact_root or args.audio_package.parent)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2); handle.write('\n')
    print(json.dumps({'status': 'supplemental_evidence_only', 'receipt': str(args.out.resolve())}))


if __name__ == '__main__':
    main()
