"""Offline acoustic measurements of frozen POC audio, with explicit missingness.

Run with ~/.local/share/uv/tools/mlx-audio/bin/python. No downloads or LLM calls.
Low energy is measured from PCM; alignment gaps are separate model estimates.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PARAMETERS = {
    'sample_rate': 16000, 'frame_length': 1024, 'hop_length': 160,
    'frame_center': True, 'padding': 'constant_zero', 'f0_method': 'librosa.pyin',
    'fmin_hz': 60, 'fmax_hz': 500, 'pyin_resolution_semitones': 0.1,
    'pyin_n_thresholds': 100, 'voiced_probability_min': 0.5,
    'reference_rms_percentile': 95, 'low_energy_below_reference_db': 35,
    'digital_floor_dbfs': -90, 'low_energy_min_duration_seconds': 0.12,
    'local_reference_radius_seconds': 2.5, 'local_pitch_min_voiced_frames': 3,
    'word_edge_window_seconds': 0.1, 'word_edge_min_voiced_frames': 3,
    'duration_local_radius_words': 5, 'duration_local_min_neighbors': 3,
    'gain_negative_control': 0.5,
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    serialized = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    with path.open('x') as stream:
        stream.write(serialized)


def nullable(value):
    return float(value) if np.isfinite(value) else None


def finite_median(values, minimum=1):
    values = np.asarray(values)
    values = values[np.isfinite(values)]
    return float(np.median(values)) if len(values) >= minimum else float('nan')


def load_pcm(path):
    with wave.open(str(path)) as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getcomptype()) != (1, 2, 16000, 'NONE'):
            raise ValueError('Expected frozen mono 16-bit 16 kHz PCM WAV')
        audio = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(np.float64)/32768.0
    if len(audio) == 0:
        raise ValueError('Empty audio')
    return audio


def low_energy_intervals(mask, times, duration):
    changes = np.diff(np.r_[False, mask, False].astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    half_hop = PARAMETERS['hop_length']/PARAMETERS['sample_rate']/2
    intervals = []
    for left, right in zip(starts, ends):
        start = max(0.0, float(times[left])-half_hop)
        end = min(duration, float(times[right-1])+half_hop)
        if end-start >= PARAMETERS['low_energy_min_duration_seconds']-1e-9:
            intervals.append({'start': round(start, 6), 'end': round(end, 6),
                              'duration_seconds': round(end-start, 6)})
    return intervals


def extract(audio, aligned_words):
    import librosa
    p = PARAMETERS
    sr, hop, length = p['sample_rate'], p['hop_length'], p['frame_length']
    rms = librosa.feature.rms(y=audio, frame_length=length, hop_length=hop,
                              center=True, pad_mode='constant')[0].astype(np.float64)
    times = np.arange(len(rms))*hop/sr
    with np.errstate(divide='ignore'):
        rms_dbfs = 20*np.log10(rms)
    reference = float(np.percentile(rms, p['reference_rms_percentile']))
    reference_dbfs = float(20*np.log10(reference)) if reference > 0 else -np.inf
    threshold = max(p['digital_floor_dbfs'], reference_dbfs-p['low_energy_below_reference_db'])
    low = rms_dbfs <= threshold
    zero_pcm = not bool(np.any(audio))
    if zero_pcm:
        f0 = np.full(len(rms), np.nan)
        probability = np.zeros(len(rms))
        raw_voiced = np.zeros(len(rms), dtype=bool)
    else:
        f0, raw_voiced, probability = librosa.pyin(
            audio, sr=sr, fmin=p['fmin_hz'], fmax=p['fmax_hz'],
            frame_length=length, hop_length=hop, n_thresholds=p['pyin_n_thresholds'],
            resolution=p['pyin_resolution_semitones'], center=True,
            pad_mode='constant', fill_na=np.nan)
    if not (len(f0) == len(rms) == len(probability)):
        raise ValueError('Frame grids differ')
    voiced = raw_voiced & (probability >= p['voiced_probability_min']) & ~low & np.isfinite(f0)
    f0 = np.where(voiced, f0, np.nan)
    relative_pitch = np.full(len(rms), np.nan)
    relative_energy = np.full(len(rms), np.nan)
    radius = round(p['local_reference_radius_seconds']*sr/hop)
    for i in range(len(rms)):
        left, right = max(0, i-radius), min(len(rms), i+radius+1)
        pitch_reference = finite_median(f0[left:right], p['local_pitch_min_voiced_frames'])
        if voiced[i] and np.isfinite(pitch_reference):
            relative_pitch[i] = 12*np.log2(f0[i]/pitch_reference)
        neighborhood = rms[left:right][~low[left:right]]
        if len(neighborhood) and rms[i] > 0:
            relative_energy[i] = 20*np.log10(rms[i]/np.median(neighborhood))
    words = []
    durations = np.array([w['end']-w['start'] for w in aligned_words])
    for i, word in enumerate(aligned_words):
        start, end = word['start'], word['end']
        mask = (times >= start) & (times < end)
        head = mask & (times < start+p['word_edge_window_seconds'])
        tail = mask & (times >= end-p['word_edge_window_seconds'])
        head_pitch = finite_median(f0[head], p['word_edge_min_voiced_frames'])
        tail_pitch = finite_median(f0[tail], p['word_edge_min_voiced_frames'])
        delta = 12*np.log2(tail_pitch/head_pitch) if np.isfinite(head_pitch) and np.isfinite(tail_pitch) else np.nan
        r = p['duration_local_radius_words']
        neighbors = np.r_[durations[max(0,i-r):i], durations[i+1:i+r+1]]
        neighbors = neighbors[neighbors > 0]
        baseline = finite_median(neighbors, p['duration_local_min_neighbors'])
        words.append({
            'word_index': word['word_index'], 'word_index_zero_based': word['word_index']-1,
            'text': word['text'], 'start': start, 'end': end, 'duration_seconds': round(end-start, 6),
            'frame_count': int(mask.sum()), 'voiced_frame_count': int(voiced[mask].sum()),
            'voiced_fraction': float(voiced[mask].mean()) if mask.any() else None,
            'f0_median_hz': nullable(finite_median(f0[mask])),
            'f0_slope_semitones': nullable(delta),
            'relative_pitch_semitones': nullable(finite_median(relative_pitch[mask])),
            'rms_median': nullable(finite_median(rms[mask])),
            'rms_dbfs_median': nullable(finite_median(rms_dbfs[mask])),
            'relative_rms_db': nullable(finite_median(relative_energy[mask])),
            'duration_relative_local_median': nullable(durations[i]/baseline),
            'alignment_gap_after_seconds': word['gap_after_seconds'],
        })
    frames = [{
        'time_seconds': round(float(times[i]), 6), 'rms': float(rms[i]),
        'rms_dbfs': nullable(rms_dbfs[i]), 'f0_hz': nullable(f0[i]),
        'voiced_probability': nullable(probability[i]), 'voiced': bool(voiced[i]),
        'pyin_voiced_before_energy_gate': bool(raw_voiced[i]), 'low_energy': bool(low[i]),
        'relative_pitch_semitones': nullable(relative_pitch[i]),
        'relative_rms_db': nullable(relative_energy[i]),
    } for i in range(len(rms))]
    intervals = low_energy_intervals(low, times, len(audio)/sr)
    return {
        'pre_f0_gate': {'zero_pcm': zero_pcm, 'f0_estimator_called': not zero_pcm},
        'measured_thresholds': {'reference_rms': reference, 'reference_rms_dbfs': nullable(reference_dbfs),
                                'low_energy_threshold_dbfs': threshold},
        'frames': frames, 'words': words, 'low_energy_intervals': intervals,
        'summary': {'frame_count': len(rms), 'voiced_frame_count': int(voiced.sum()),
                    'voiced_fraction': float(voiced.mean()), 'word_count': len(words),
                    'words_with_missing_f0': sum(w['f0_median_hz'] is None for w in words),
                    'low_energy_interval_count': len(intervals),
                    'low_energy_seconds': round(sum(x['duration_seconds'] for x in intervals), 6)},
    }


def validate_results(results):
    errors, checks = [], {}
    a, half, silence = results['A'], results['A-gain-half'], results['silence-A']
    checks['silence_has_no_f0'] = all(f['f0_hz'] is None and not f['voiced'] for f in silence['frames'])
    checks['silence_bypassed_f0_estimator'] = not silence['pre_f0_gate']['f0_estimator_called']
    checks['silence_has_no_word_alignment'] = not silence['words']
    checks['silence_full_duration_low_energy'] = silence['low_energy_intervals'] == [{'start': 0.0, 'end': 60.0, 'duration_seconds': 60.0}]
    comparisons = {}
    for collection, fields in [('frames', ['f0_hz', 'relative_pitch_semitones', 'relative_rms_db']),
                               ('words', ['relative_pitch_semitones', 'relative_rms_db', 'f0_slope_semitones', 'duration_relative_local_median'])]:
        for field in fields:
            values = [(x[field], y[field]) for x,y in zip(a[collection],half[collection])]
            missing_equal = all((x is None) == (y is None) for x,y in values)
            delta = max([abs(x-y) for x,y in values if x is not None and y is not None] or [0])
            comparisons[collection+'.'+field] = {'missingness_equal': missing_equal, 'max_absolute_difference': delta, 'tolerance': 1e-6}
            checks[collection+'.'+field+'_gain_invariant'] = missing_equal and delta <= 1e-6
    checks['low_energy_intervals_gain_invariant'] = a['low_energy_intervals'] == half['low_energy_intervals']
    expected_shift = 20*np.log10(PARAMETERS['gain_negative_control'])
    shift_errors = [abs((y['rms_dbfs']-x['rms_dbfs'])-expected_shift) for x,y in zip(a['frames'],half['frames']) if x['rms_dbfs'] is not None and y['rms_dbfs'] is not None]
    checks['absolute_rms_dbfs_halving_matches_minus_6db'] = bool(max(shift_errors, default=0) < 1e-6)
    for name,result in results.items():
        checks[name+'_unvoiced_f0_is_null'] = all(f['f0_hz'] is None for f in result['frames'] if not f['voiced'])
        checks[name+'_no_nonfinite_json'] = bool(json.dumps(result, allow_nan=False))
    errors = [key for key,value in checks.items() if not value]
    return {'schema_version': 1, 'checks': checks, 'comparisons': comparisons,
            'expected_absolute_rms_db_shift': float(expected_shift), 'errors': errors, 'passed': not errors,
            'scope': 'Measured gain invariance and missingness only; no human pitch/boundary accuracy ground truth.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--alignment-dir', type=Path, default=ROOT/'artifacts/local-prosody-poc/20260919/alignment')
    parser.add_argument('--audio-dir', type=Path, default=ROOT/'artifacts/gemini-prosody-poc/20260917')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'artifacts/local-prosody-poc/20260919-acoustics/features')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # Numba's default package-side cache is outside the writable workspace.
    # Keep compilation artifacts beside this experiment's outputs instead.
    os.environ.setdefault('NUMBA_CACHE_DIR', str(args.output_dir.parent/'numba-cache'))
    config_hash = sha(args.audio_dir/'config.json')
    runtime = {name: importlib.metadata.version(name) for name in ('numpy','scipy','librosa','numba')}
    code_hash = sha(__file__)
    results = {}
    for name, base, gain in [('A','A',1.0), ('B','B',1.0), ('silence-A','silence-A',1.0), ('A-gain-half','A',0.5)]:
        alignment_path = args.alignment_dir/(base+'.json')
        alignment = json.loads(alignment_path.read_text())
        audio_path = args.audio_dir/(base+'.wav')
        if sha(audio_path) != alignment['input']['audio_sha256'] or config_hash != alignment['input']['config_sha256']:
            raise ValueError('Frozen input mismatch: '+base)
        if alignment['validation_errors']:
            raise ValueError('Invalid alignment: '+base)
        audio = load_pcm(audio_path)*gain
        identity = {'audio_path': str(audio_path.resolve()), 'audio_sha256': sha(audio_path),
                    'alignment_sha256': sha(alignment_path), 'config_sha256': config_hash,
                    'source_start': alignment['input']['source_start'], 'source_id': alignment['input']['source_id'],
                    'canonical_url': alignment['input']['canonical_url'], 'source_sha256': alignment['input']['source_sha256'],
                    'duration_seconds': len(audio)/16000, 'amplitude_multiplier': gain,
                    'processed_float64_pcm_sha256': hashlib.sha256(audio.astype('<f8').tobytes()).hexdigest(),
                    'gain_control_method': 'Exact float64 multiplication after PCM16 decoding; no requantization.'}
        target = args.output_dir/(name+'.json')
        if target.exists():
            previous = json.loads(target.read_text())
            if previous['input'] != identity or previous['parameters'] != PARAMETERS or previous['code_sha256'] != code_hash:
                raise ValueError('Existing output identity differs; choose fresh output directory')
            results[name] = previous
            print(name, 'reused', flush=True)
            continue
        start = time.monotonic()
        print(name, 'extracting', flush=True)
        result = {'schema_version': 1, 'id': name, 'review_state': 'experimental_unreviewed',
                  'input': identity, 'runtime': runtime, 'parameters': PARAMETERS, 'code_sha256': code_hash,
                  'definitions': {
                      'f0_missing': 'null when zero PCM, pyin unvoiced, probability < 0.5, or low energy; no interpolation.',
                      'relative_pitch_semitones': '12 log2(frame F0 / median voiced F0 within +/-2.5 seconds).',
                      'relative_rms_db': '20 log10(frame RMS / median non-low-energy RMS within +/-2.5 seconds).',
                      'f0_slope_semitones': 'Word-end 100ms vs word-start 100ms voiced median F0 difference in semitones; NOT per-second slope. Each edge requires >=3 voiced frames.',
                      'duration_relative_local_median': 'Word duration / median duration of up to 5 preceding and 5 following words, excluding self, requiring >=3 positive durations. Confounded by phonemes and lexical length; not direct stress evidence.',
                      'low_energy_intervals': 'Contiguous measured frame RMS <= max(-90 dBFS, clip P95 RMS dBFS minus 35 dB), minimum 120ms. Low energy is not proof of linguistic silence; 64ms centered windows smear boundaries.',
                      'alignment_gap_after_seconds': 'Imported model boundary difference, not measured silence. Alignment resolution 80ms.',
                      'word_indices': 'word_index is 1-based; word_index_zero_based is 0-based.',
                      'word_aggregation': 'Median of eligible frame-centered observations inside [word start, word end).',
                      'pitch_limit': 'F0 search restricted to 60-500 Hz; octave errors and accompaniment contamination remain possible.',
                  }, **extract(audio, alignment['words'])}
        result['elapsed_seconds'] = round(time.monotonic()-start, 4)
        write_new(target, result)
        results[name] = result
        print(name, result['summary'], result['elapsed_seconds'], flush=True)
    validation = validate_results(results)
    validation['result_sha256'] = {name: sha(args.output_dir/(name+'.json')) for name in results}
    target = args.output_dir/'validation.json'
    if target.exists():
        if json.loads(target.read_text()) != validation:
            raise ValueError('Existing validation differs')
    else:
        write_new(target, validation)
    print('validation', validation['passed'], validation['errors'], flush=True)
    if not validation['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
