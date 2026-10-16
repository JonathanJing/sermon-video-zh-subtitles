"""Lossless anomaly evidence and read-only PCM16 edge measurements.

Call preservation under the render lock. No synthesis, trimming, text repair or
approval is performed. Low-energy windows are observations, not safe trim points.
"""
from __future__ import annotations
from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import wave


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def bound_path(root, path):
    root = Path(root).resolve()
    path = Path(path)
    if not path.is_absolute():
        path = root / path
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise ValueError('Anomaly path escapes root') from None
    cursor = root
    for part in relative.parts:
        if part in ('.', '..'):
            raise ValueError('Anomaly path traversal')
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError('Anomaly symlink path')
    if not path.resolve().is_relative_to(root):
        raise ValueError('Anomaly path escapes root')
    return path


def measure_edges(path):
    """Full PCM16 decode; 10 ms RMS windows below -45 dBFS at either edge."""
    path = Path(path)
    before = digest(path)
    threshold = 32768 * 10 ** (-45 / 20)
    with wave.open(str(path), 'rb') as handle:
        rate, channels, width, total = (handle.getframerate(), handle.getnchannels(),
                                       handle.getsampwidth(), handle.getnframes())
        if width != 2 or handle.getcomptype() != 'NONE' or rate <= 0 or channels <= 0 or total <= 0:
            raise ValueError('Edge measurement requires nonempty uncompressed PCM16')
        window = max(1, round(rate * .01))
        leading, trailing, seen_active, frames = 0, 0, False, 0
        peak = 0
        while frames < total:
            count = min(window, total - frames)
            data = handle.readframes(count)
            if len(data) != count * channels * width:
                raise ValueError('Incomplete PCM16 decode')
            samples = array('h', data)
            if sys.byteorder != 'little':
                samples.byteswap()
            peak = max(peak, max(abs(x) for x in samples))
            quiet = math.sqrt(sum(x * x for x in samples) / len(samples)) < threshold
            if quiet:
                if not seen_active:
                    leading += count
                trailing += count
            else:
                seen_active = True
                trailing = 0
            frames += count
    if digest(path) != before:
        raise ValueError('Audio changed during measurement')
    # All-quiet audio cannot be a leading + trailing trim proposal.
    return {'status': 'full_pcm16_decode', 'audioSha256': before,
            'durationSeconds': total / rate, 'sampleRate': rate, 'channels': channels,
            'frames': total, 'peakDbfs': 20 * math.log10(peak / 32768) if peak else None,
            'method': 'all_channel_rms_10ms_windows_v1', 'thresholdDbfs': -45,
            'leadingLowEnergySeconds': leading / rate,
            'trailingLowEnergySeconds': trailing / rate if seen_active else 0,
            'allLowEnergy': not seen_active, 'safeTrimSeconds': None,
            'rootCause': 'not_determined'}


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def preserve(root, job, index, *, reason, timing=None, extra_paths=(), audio_relative_path=None):
    """Durable immutable snapshot before destructive repair, no source writes.

    Caller owns the render lock. Failure leaves the original WAV/receipts intact.
    Snapshots are hash-deduplicated and may contain private approved text; ignored
    render roots only. Runtime/checkpoint identity is retained, weights are not.
    """
    root = Path(root).resolve()
    if type(index) is not int or not 0 <= index < len(job['units']) or not isinstance(reason, str) or not reason.strip():
        raise ValueError('Anomaly requires explicit reason and valid unit')
    unit = job['units'][index]
    wav = bound_path(root, audio_relative_path or unit['outputRelativePath'])
    if not wav.is_file():
        raise ValueError('Anomaly WAV missing')
    paths = [wav]
    unavailable = []
    for relative in [*(f'receipts/unit-{index:04d}{suffix}.json' for suffix in ('', '.intent', '.render')),
                     'replica-runtime.json', *extra_paths]:
        path = bound_path(root, relative)
        if path.exists():
            if not path.is_file():
                raise ValueError('Anomaly evidence is not a file')
            paths.append(path)
        else:
            unavailable.append(str(path.relative_to(root)))
    paths = list(dict.fromkeys(paths))
    sources = [{'path': str(p.relative_to(root)), 'sha256': digest(p)} for p in paths]
    material = {'job': job, 'unitIndex': index, 'unit': unit, 'reason': reason,
                'timing': timing, 'sources': sources, 'unavailableEvidence': unavailable,
                'audioInputPath': str(wav.relative_to(root))}
    evidence_hash = hashlib.sha256(canonical(material)).hexdigest()
    parent = bound_path(root, 'anomalies')
    parent.mkdir(parents=True, exist_ok=True)
    _sync_directory(root)
    destination = bound_path(root, parent / f'unit-{index:04d}-{evidence_hash}')
    if destination.exists():
        receipt_path = bound_path(destination, 'anomaly.json')
        checksum_path = bound_path(destination, 'anomaly.json.sha256')
        if digest(receipt_path) != checksum_path.read_text().strip():
            raise ValueError('Anomaly snapshot receipt corrupted')
        receipt = json.loads((destination / 'anomaly.json').read_text())
        expected_saved = [{'path': 'files/' + source['path'], 'sha256': source['sha256']} for source in sources]
        expected_fields = {'schemaVersion': 'sermon-audio-anomaly-v1', 'unitIndex': index,
                           'evidenceSha256': evidence_hash, 'jobJsonSha256': hashlib.sha256(canonical(job)).hexdigest(),
                           'audioSha256': sources[0]['sha256'], 'reason': reason, 'timing': timing,
                           'saved': expected_saved, 'unavailableEvidence': unavailable,
                           'grantsApproval': False, 'modelCalls': 0, 'mutatesSource': False}
        if ({key: value for key, value in receipt.items() if key != 'acoustic'} != expected_fields
                or json.loads(bound_path(destination, 'context.json').read_text()) != material):
            raise ValueError('Anomaly snapshot identity conflict')
        for row in receipt['saved']:
            if digest(bound_path(destination, row['path'])) != row['sha256']:
                raise ValueError('Anomaly snapshot corrupted')
            with bound_path(destination, row['path']).open('rb') as handle:
                os.fsync(handle.fileno())
        for name in ('context.json', 'anomaly.json', 'anomaly.json.sha256'):
            with bound_path(destination, name).open('rb') as handle:
                os.fsync(handle.fileno())
        for directory, _, _ in os.walk(destination, topdown=False):
            _sync_directory(directory)
        _sync_directory(parent)
        _sync_directory(root)
        return receipt
    temporary = Path(tempfile.mkdtemp(prefix='.anomaly-', dir=parent))
    try:
        saved = []
        for path, source in zip(paths, sources):
            target = temporary / 'files' / source['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            if digest(target) != source['sha256']:
                raise ValueError('Anomaly copy verification failed')
            with target.open('rb') as handle:
                os.fsync(handle.fileno())
            saved.append({'path': str(target.relative_to(temporary)), 'sha256': source['sha256']})
        try:
            acoustic = measure_edges(temporary / saved[0]['path'])
        except (ValueError, wave.Error, EOFError) as error:
            acoustic = {'status': 'measurement_unavailable', 'errorType': type(error).__name__,
                        'safeTrimSeconds': None, 'rootCause': 'not_determined'}
        receipt = {'schemaVersion': 'sermon-audio-anomaly-v1', 'unitIndex': index,
                   'evidenceSha256': evidence_hash, 'jobJsonSha256': hashlib.sha256(canonical(job)).hexdigest(),
                   'audioSha256': sources[0]['sha256'], 'reason': reason, 'timing': timing,
                   'acoustic': acoustic, 'saved': saved, 'grantsApproval': False,
                   'unavailableEvidence': unavailable,
                   'modelCalls': 0, 'mutatesSource': False}
        for name, value in [('context.json', material), ('anomaly.json', receipt)]:
            with (temporary / name).open('xb') as handle:
                handle.write(canonical(value) + b'\n'); handle.flush(); os.fsync(handle.fileno())
        with (temporary / 'anomaly.json.sha256').open('x') as handle:
            handle.write(digest(temporary / 'anomaly.json') + '\n'); handle.flush(); os.fsync(handle.fileno())
        for directory, _, _ in os.walk(temporary, topdown=False):
            _sync_directory(directory)
        if any(digest(path) != source['sha256'] for path, source in zip(paths, sources)):
            raise ValueError('Source evidence changed before snapshot commit')
        temporary.rename(destination)
        _sync_directory(parent)
        return receipt
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def preserve_timing_risk(root, context, rows, plan, *, indices=None):
    """Record own excess, propagated lag and clip tail separately without repair."""
    anchors = {u['sourceUnitId']: u for u in context['anchor']['sourceUnits']}
    offset = context['clip_timeline_map']['anchorOffsetSeconds']
    selected = range(len(rows)) if indices is None else indices
    results = []
    for index in selected:
        if not 0 <= index < min(len(rows), len(context['candidate']['groups']), len(plan['entries']), len(context['job']['units'])):
            raise ValueError('Incomplete anomaly timing coverage')
        group, row, entry = context['candidate']['groups'][index], rows[index], plan['entries'][index]
        if not (group['translationGroupId'] == row['textGroupId'] == entry['textGroupId']
                == context['job']['units'][index]['translationGroupId']):
            raise ValueError('Anomaly timing group identity changed')
        start = anchors[group['sourceUnitIds'][0]]['start'] - offset
        end = anchors[group['sourceUnitIds'][-1]]['end'] - offset
        timing = {'sourceStart': start, 'sourceEnd': end, 'durationSeconds': row['durationSeconds'],
                  'ownSpanExcessSeconds': max(0., row['durationSeconds'] - (end - start)),
                  'propagatedStartDelaySeconds': max(0., entry['plannedStart'] - start - plan['policy']['reactionLagSeconds']),
                  'endLagSeconds': max(0., entry['plannedEnd'] - end),
                  'clipTailOverflowSeconds': max(0., entry['plannedEnd'] - context['clip_timeline_map']['clipDurationSeconds']),
                  'policy': plan['policy'], 'rootCause': 'not_determined'}
        if (timing['ownSpanExcessSeconds'] > 1e-6 or timing['endLagSeconds'] > plan['policy']['maxEndLagSeconds'] + 1e-6
                or timing['clipTailOverflowSeconds'] > 1e-6):
            path = bound_path(root, row['audio']['path'])
            if digest(path) != row['audio']['sha256']:
                raise ValueError('Anomaly audio binding changed')
            results.append(preserve(root, context['job'], index, reason='measured_timing_risk', timing=timing))
    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Read-only acoustic measurement; no trimming or model calls')
    parser.add_argument('--wav', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = measure_edges(args.wav)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x') as handle:
        json.dump(result, handle, indent=2, allow_nan=False); handle.write('\n')
    print(json.dumps({'status': result['status'], 'modelCalls': 0}))


if __name__ == '__main__':
    main()
