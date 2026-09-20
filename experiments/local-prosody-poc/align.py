"""Offline forced alignment of frozen POC inputs; silence never reaches the model.

Run with ~/.local/share/uv/tools/mlx-audio/bin/python. This supplies candidate
word times, not ASR evidence, calibrated confidence, or prosody classification.
"""
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import time
import wave
from pathlib import Path

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'

ROOT = Path(__file__).resolve().parents[2]
MODEL_ID = 'mlx-community/Qwen3-ForcedAligner-0.6B-8bit'
SNAPSHOT = '0e1a68e91d815300c7c9754b2a7639378b23db15'
MODEL_PATH = Path.home()/'.cache/huggingface/hub/models--mlx-community--Qwen3-ForcedAligner-0.6B-8bit/snapshots'/SNAPSHOT


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_new(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def pcm_gate(path):
    import numpy as np
    with wave.open(str(path)) as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getcomptype()) != (1, 2, 16000, 'NONE'):
            raise ValueError('Expected frozen mono 16-bit PCM 16 kHz WAV')
        pcm = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2')
    nonzero = int(np.count_nonzero(pcm))
    if len(pcm) == 0:
        raise ValueError('Empty PCM input')
    return {'pcm_sample_count': len(pcm), 'nonzero_sample_count': nonzero,
            'peak_pcm': int(np.abs(pcm.astype(np.int32)).max()),
            'rms_pcm': float(np.sqrt(np.mean(pcm.astype(np.float64)**2))),
            'zero_pcm': nonzero == 0, 'passed': nonzero > 0,
            'policy': 'Reject exactly zero PCM; nonzero is not proof of speech.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, default=ROOT/'artifacts/gemini-prosody-poc/20260917')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'artifacts/local-prosody-poc/20260919/alignment')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    config = json.loads((args.input_dir/'config.json').read_text())
    model_info = {'id': MODEL_ID, 'snapshot': SNAPSHOT, 'path': str(MODEL_PATH),
                  'files_sha256': {p.name: sha(p) for p in sorted(MODEL_PATH.iterdir()) if p.is_file()},
                  'runtime': {name: importlib.metadata.version(name) for name in ('mlx-audio', 'mlx', 'transformers')}}
    prepared = []
    # Inspect all three inputs and persist gates before loading any model.
    for name, prior_name in [('silence-A', 'A-silence'), ('A', 'A-audio'), ('B', 'B-audio')]:
        prior_path = args.input_dir/(prior_name+'.json')
        prior = json.loads(prior_path.read_text())
        wav = args.input_dir/prior['audio_file']
        actual_hash = sha(wav)
        if actual_hash != prior['audio_sha256']:
            raise ValueError('Frozen input audio hash changed: '+name)
        if prior['source_sha256'] != config['source_sha256']:
            raise ValueError('Source identity mismatch: '+name)
        gate = pcm_gate(wav)
        duration = gate['pcm_sample_count']/16000
        if duration != prior['duration'] or duration > 60:
            raise ValueError('Unexpected duration: '+name)
        words = prior['words']
        record = {'schema_version': 1, 'id': name, 'status': 'preflight_passed' if gate['passed'] else 'rejected_zero_pcm',
                  'review_state': 'experimental_unreviewed', 'model': model_info,
                  'input': {'audio_path': str(wav.resolve()), 'audio_sha256': actual_hash,
                            'config_sha256': sha(args.input_dir/'config.json'), 'prior_result_sha256': sha(prior_path),
                            'words_sha256': hashlib.sha256(json.dumps(words, ensure_ascii=False).encode()).hexdigest(),
                            'source_sha256': config['source_sha256'], 'canonical_url': config['canonical_url'],
                            'source_id': config['source_id'], 'source_start': prior['source_start'], 'duration': duration},
                  'pre_model_gate': gate, 'model_called': False, 'frozen_words': words, 'words': [],
                  'validation_errors': [], 'confidence': None,
                  'limitation': 'Forced text alignment is not transcript verification, calibrated confidence, or listening proof.'}
        target = args.output_dir/(name+'.json')
        if target.exists():
            existing = json.loads(target.read_text())
            # Moving an identical frozen experiment into a worktree changes its
            # display path, not its audio/content identity. Keep original provenance.
            prior_identity = {k:v for k,v in existing['input'].items() if k != 'audio_path'}
            current_identity = {k:v for k,v in record['input'].items() if k != 'audio_path'}
            if prior_identity != current_identity or existing['model'] != record['model']:
                raise ValueError('Existing result identity changed; use fresh output directory')
            print(name, 'reused', existing['status'], flush=True)
            continue
        preflight = args.output_dir/(name+'.preflight.json')
        if preflight.exists():
            if json.loads(preflight.read_text()) != record:
                raise ValueError('Previous preflight identity mismatch: '+name)
        else:
            write_new(preflight, record)
        if not gate['passed']:
            record['model_latency_seconds'] = 0
            write_new(target, record)
            print(name, 'rejected_zero_pcm', flush=True)
        else:
            prepared.append((record, wav, target))
    if not prepared:
        return
    from mlx_audio.stt import load
    started = time.monotonic()
    model = load(str(MODEL_PATH), strict=True)
    load_seconds = time.monotonic()-started
    for record, wav, target in prepared:
        started = time.monotonic()
        result = model.generate(audio=str(wav), text=' '.join(record['frozen_words']), language='English')
        record['model_latency_seconds'] = round(time.monotonic()-started, 4)
        record['model_load_seconds'] = round(load_seconds, 4)
        record['model_called'] = True
        record['status'] = 'aligned_candidate'
        aligned = result.segments
        same_words = [item['text'] for item in aligned] == record['frozen_words']
        if not same_words:
            record['validation_errors'].append('aligner_tokenization_differs_from_frozen_words')
        for index, item in enumerate(aligned):
            word = dict(item)
            word['word_index'] = index+1 if same_words else None
            word['gap_after_seconds'] = round(aligned[index+1]['start']-item['end'], 3) if index+1<len(aligned) else None
            record['words'].append(word)
            if not (math.isfinite(item['start']) and math.isfinite(item['end']) and 0 <= item['start'] <= item['end'] <= record['input']['duration']):
                record['validation_errors'].append('invalid_time_at_item_'+str(index+1))
            if index and item['start'] < aligned[index-1]['end']:
                record['validation_errors'].append('overlap_at_item_'+str(index+1))
        write_new(target, record)
        print(record['id'], len(aligned), record['model_latency_seconds'], record['validation_errors'], flush=True)


if __name__ == '__main__':
    main()
