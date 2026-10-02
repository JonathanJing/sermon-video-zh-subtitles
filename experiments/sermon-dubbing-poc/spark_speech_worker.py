"""Bounded offline Spark speech batch; one hash/load, per-unit flushed receipts."""
import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import platform
import sys

PINS = {'Qwen/Qwen3-ASR-0.6B': '5eb144179a02acc5e5ba31e748d22b0cf3e303b0',
        'Qwen/Qwen3-ForcedAligner-0.6B': 'c7cbfc2048c462b0d63a45797104fc9db3ad62b7'}
SCHEMA = 'spark-speech-batch-v1'
MAX_BYTES = 32 * 1024 * 1024


def freeze(request):
    single = 'schemaVersion' not in request
    if single:
        rows = [{'unitId': 0, **request}]
    else:
        if request.get('schemaVersion') != SCHEMA:
            raise ValueError('Unknown speech batch schema')
        rows = request['requests']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
        raise ValueError('Speech batch must contain 1..8 units')
    identities, decoded, seen, size = [], [], set(), 0
    for row in rows:
        unit_id, identity = row['unitId'], row['identity']
        if type(unit_id) not in (str, int) or unit_id == '' or (type(unit_id), unit_id) in seen:
            raise ValueError('Duplicate or invalid speech unit ID')
        seen.add((type(unit_id), unit_id))
        if PINS.get(identity['model']) != identity['revision']:
            raise ValueError('Unpinned model')
        if not isinstance(identity['language'], str) or not identity['language'] or type(identity['maxTokens']) is not int or not 1 <= identity['maxTokens'] <= 2048:
            raise ValueError('Invalid speech language/token limit')
        if identity['text'] is not None and not isinstance(identity['text'], str):
            raise ValueError('Invalid speech text')
        if identity['model'].endswith('ForcedAligner-0.6B') and (not isinstance(identity['text'], str) or not identity['text'].strip()):
            raise ValueError('Forced aligner requires nonempty frozen text')
        if 'locale' in identity and (not isinstance(identity['locale'], str) or not identity['locale']):
            raise ValueError('Invalid speech locale')
        # Reject oversized encoded input before allocating its decoded buffer.
        if not isinstance(row['audio'], str) or len(row['audio']) > (MAX_BYTES * 4 // 3 + 4):
            raise ValueError('Speech audio exceeds byte bound')
        raw = base64.b64decode(row['audio'], validate=True)
        size += len(raw)
        if not raw or size > MAX_BYTES or hashlib.sha256(raw).hexdigest() != identity['audioSha256']:
            raise ValueError('Speech audio hash/size differs')
        identities.append({'unitId': unit_id, 'identity': identity})
        decoded.append(raw)
    if len({(row['identity']['model'], row['identity']['revision'], row['identity']['maxTokens']) for row in rows}) != 1:
        raise ValueError('Speech batch must share one model and token limit')
    batch_hash = hashlib.sha256(json.dumps(identities, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if not single and request.get('batchSha256') != batch_hash:
        raise ValueError('Speech batch identity mismatch')
    return single, rows, decoded, batch_hash


def execute(request, emit):
    single, rows, raw_audio, batch_hash = freeze(request)
    if platform.system() != 'Linux' or platform.machine() not in ('aarch64', 'arm64'):
        raise RuntimeError('Speech worker requires the Linux ARM64 Spark runtime')
    identity = rows[0]['identity']
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        import soundfile as sf
        from huggingface_hub import snapshot_download
        from qwen_asr import Qwen3ASRModel, Qwen3ForcedAligner
        import numpy as np
        if not torch.cuda.is_available():
            raise RuntimeError('Spark CUDA is unavailable; refusing CPU/Mac fallback')
        # Decode every unit before any model load/inference. A malformed later
        # input must not produce an earlier unit with an incomplete contract.
        audios = []
        for raw in raw_audio:
            audio, rate = sf.read(io.BytesIO(raw), dtype='float32')
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            if audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all() or type(rate) is not int or rate <= 0:
                raise ValueError('Invalid decoded speech audio')
            audios.append((audio, rate))
        snapshot = Path(snapshot_download(repo_id=identity['model'], revision=identity['revision'], local_files_only=True))
        hashes = {}
        for path in sorted(snapshot.rglob('*')):
            if path.is_file():
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
                hashes[str(path.relative_to(snapshot))] = digest.hexdigest()
        if not hashes:
            raise ValueError('Empty model snapshot')
        kwargs = dict(dtype=torch.bfloat16, device_map='cuda:0')
        asr = identity['model'].endswith('ASR-0.6B')
        if asr:
            model = Qwen3ASRModel.from_pretrained(str(snapshot), max_new_tokens=identity['maxTokens'], max_inference_batch_size=1, **kwargs)
        else:
            model = Qwen3ForcedAligner.from_pretrained(str(snapshot), **kwargs)
        import importlib.metadata
        common = {'executionHost': 'dgx-spark', 'hostname': platform.node(), 'device': 'cuda',
                  'modelFilesSha256': hashes, 'workerSha256': hashlib.sha256(sys.argv[1].encode()).hexdigest(),
                  'qwenAsrVersion': importlib.metadata.version('qwen-asr'), 'torchVersion': torch.__version__}
    for row, audio in zip(rows, audios):
        identity = row['identity']
        with contextlib.redirect_stdout(sys.stderr):
            if asr:
                text = model.transcribe(audio=audio, language=identity['language'])[0].text
                words = []
            else:
                aligned = model.align(audio=audio, text=identity['text'], language=identity['language'])[0]
                words = [{'text': word.text, 'start': float(word.start_time), 'end': float(word.end_time)} for word in aligned]
                text = identity['text']
        result = {**common, 'identity': identity, 'text': text, 'words': words}
        if not single:
            result.update(event='unit_result', unitId=row['unitId'], batchSha256=batch_hash)
        emit(result)
    if not single:
        emit({'event': 'batch_complete', 'batchSha256': batch_hash, 'count': len(rows)})


def main():
    def emit(result):
        print(json.dumps(result, ensure_ascii=False), flush=True)
    execute(json.load(sys.stdin), emit)


if __name__ == '__main__':
    main()
