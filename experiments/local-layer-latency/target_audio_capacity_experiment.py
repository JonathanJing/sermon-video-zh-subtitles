"""Fixed-quality local TTS capacity plans and evidence comparisons; never dispatches."""
from __future__ import annotations
import json
import math
from pathlib import Path
try:
    from scripts import sermon_sentence_interpretation as identity
except ImportError:
    import sermon_sentence_interpretation as identity


def plan(*, speech_job_sha256, sound_identity_sha256, unit_indices, max_generated_units,
         max_wall_seconds, replicas=(1, 8), batch_size=8):
    if (not all(isinstance(v, str) and len(v) == 64 and set(v) <= set('0123456789abcdef')
                for v in (speech_job_sha256, sound_identity_sha256))
            or not unit_indices or any(type(i) is not int or i < 0 for i in unit_indices)
            or len(set(unit_indices)) != len(unit_indices) or type(batch_size) is not int or batch_size not in (1, 2, 4, 8)
            or not replicas or any(type(n) is not int or n not in (1, 8) for n in replicas)
            or (8 in replicas and batch_size != 8)
            or type(max_generated_units) is not int or max_generated_units < 0
            or type(max_wall_seconds) not in (int,float) or not math.isfinite(max_wall_seconds) or max_wall_seconds <= 0):
        raise ValueError('Invalid bounded fixed-quality capacity plan')
    if (unit_indices != list(range(unit_indices[0], unit_indices[0] + len(unit_indices)))
            or unit_indices[0] % batch_size or len(unit_indices) % batch_size):
        raise ValueError('Capacity sample must cover complete fixed batch windows')
    cases = [{'caseId': f'r{r}-{temperature}-{source}', 'replicas': r, 'batchSize': batch_size,
              'modelState': temperature, 'workload': source}
             for r in replicas for temperature in ('cold', 'warm') for source in ('new_synthesis', 'cache_validation')]
    if sum(len(unit_indices) for c in cases if c['workload'] == 'new_synthesis') > max_generated_units:
        raise ValueError('Capacity experiment exceeds synthesis budget')
    value = {'schemaVersion': 'sermon-target-audio-capacity-plan-v1',
             'speechJobSha256': speech_job_sha256, 'soundIdentitySha256': sound_identity_sha256,
             'unitIndices': unit_indices, 'cases': cases,
             'quality': {'maxEndLagSeconds': 8.0, 'timeStretch': False, 'reserveGiB': 24,
                         'sameApprovedText': True, 'sameCheckpointVoiceSeed': True},
             'budget': {'maxGeneratedUnits': max_generated_units, 'maxWallSeconds': max_wall_seconds},
             'dispatch': 'not_started'}
    return value | {'planHash': identity.json_sha256(value)}


def _quality_evidence(row, experiment):
    try:
        from scripts import review_target_language_audio as review
        from scripts import validate_target_language_audio_unit as integrity
    except ImportError:
        import review_target_language_audio as review
        import validate_target_language_audio_unit as integrity
    if not {'speechJobPath', 'audioPackagePath', 'humanReviewReceiptPath'} <= row.keys():
        raise ValueError('Capacity comparison requires bound job, package, and human receipt files')
    job_path = Path(row['speechJobPath'])
    package_path = Path(row['audioPackagePath'])
    receipt_path = Path(row['humanReviewReceiptPath'])
    if identity.sha256(job_path) != experiment['speechJobSha256']:
        raise ValueError('Capacity speech job evidence differs')
    if identity.sha256(receipt_path) != row['humanReviewReceiptSha256']:
        raise ValueError('Capacity human receipt hash differs')
    job = json.loads(job_path.read_text()); package = json.loads(package_path.read_text())
    receipt = json.loads(receipt_path.read_text())
    review.validate(package, 'sermon-target-language-audio-package-v1.schema.json')
    schema = receipt.get('schemaVersion')
    if schema not in {'sermon-target-language-audio-human-review-receipt-v2',
                      'sermon-target-language-audio-human-review-receipt-v3',
                      'sermon-target-language-audio-human-review-receipt-v4'}:
        raise ValueError('Unsupported capacity human receipt')
    review.validate(receipt, schema + '.schema.json')
    if (package['status'] != 'human_reviewed'
            or receipt['targetLanguageAudioPackageJsonSha256'] != identity.json_sha256(package)
            or package['targetLanguageSpeechJobJsonSha256'] != identity.json_sha256(job)
            or receipt['trackSha256'] != package['track']['sha256']
            or receipt['fullPlayback'] != 'approved' or receipt['videoSync1x'] != 'approved'):
        raise ValueError('Capacity quality review binding differs')
    root = Path(row.get('artifactRoot', str(package_path.parent)))
    for ref in (package['track'], package['schedule']):
        path = root / ref['path']
        if identity.sha256(path) != ref['sha256']: raise ValueError('Capacity artifact changed')
    integrity.probe_full_decode(root / package['track']['path'])
    schedule = json.loads((root / package['schedule']['path']).read_text())
    if schedule.get('status') != 'pass' or schedule.get('policy', {}).get('maxEndLagSeconds') != 8.0:
        raise ValueError('Capacity evidence does not satisfy original eight-second target')


def compare(experiment, results):
    value = {k:v for k,v in experiment.items() if k != 'planHash'}
    if identity.json_sha256(value) != experiment.get('planHash'): raise ValueError('Capacity plan hash changed')
    cases = {row['caseId']: row for row in experiment['cases']}
    accepted = {}
    for row in results:
        case = cases.get(row.get('caseId'))
        if case is None or row['caseId'] in accepted: raise ValueError('Unknown or duplicate capacity case')
        if (row.get('planHash') != experiment['planHash']
                or row.get('speechJobSha256') != experiment['speechJobSha256']
                or row.get('soundIdentitySha256') != experiment['soundIdentitySha256']
                or row.get('unitIndices') != experiment['unitIndices']
                or row.get('fullDecode') != 'pass' or row.get('maxEndLagSeconds', math.inf) > 8
                or row.get('humanListeningReview') != 'approved'
                or not isinstance(row.get('humanReviewReceiptSha256'), str)
                or len(row['humanReviewReceiptSha256']) != 64
                or row.get('timeStretch') is not False):
            raise ValueError('Capacity result lacks matching quality evidence')
        lag = row.get('maxEndLagSeconds')
        if type(lag) not in (int,float) or not math.isfinite(lag) or not 0 <= lag <= 8:
            raise ValueError('Capacity result needs a finite measured end lag')
        peak = row.get('gpuPeakBytes')
        if peak is not None and (type(peak) is not int or peak < 0):
            raise ValueError('GPU peak must be measured bytes or null')
        seconds = row.get('wallSeconds')
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError('Capacity result needs measured wall time')
        generated = row.get('generatedUnits')
        if (type(generated) is not int or generated < 0
                or (case['workload'] == 'cache_validation' and generated != 0)
                or (case['workload'] == 'new_synthesis' and generated < len(experiment['unitIndices']))):
            raise ValueError('Capacity workload metrics differ')
        _quality_evidence(row, experiment)
        accepted[row['caseId']] = row
    if sum(row['generatedUnits'] for row in accepted.values()) > experiment['budget']['maxGeneratedUnits']:
        raise ValueError('Capacity results exceed synthesis budget')
    if sum(row['wallSeconds'] for row in accepted.values()) > experiment['budget']['maxWallSeconds']:
        raise ValueError('Capacity results exceed wall-time budget')
    return {'schemaVersion': 'sermon-target-audio-capacity-comparison-v1', 'planHash': experiment['planHash'],
            'status': 'complete' if set(accepted) == set(cases) else 'partial',
            'missingCases': sorted(set(cases) - set(accepted)),
            'measurements': [{'caseId': key, 'wallSeconds': row['wallSeconds'],
                              'generatedUnits': row['generatedUnits'],
                              'gpuPeakBytes': row.get('gpuPeakBytes'),
                              'gpuPeakStatus': 'measured' if row.get('gpuPeakBytes') is not None else 'unknown'}
                             for key, row in sorted(accepted.items())],
            'automaticProductionPolicyChange': False}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'compare'))
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--results', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text())
    if args.action == 'plan':
        result = plan(**data)
    else:
        if args.results is None: raise ValueError('Comparison requires results')
        result = compare(data, json.loads(args.results.read_text()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x') as handle: json.dump(result, handle, indent=2); handle.write('\n')


if __name__ == '__main__': main()
