"""Spark first; MacBook MLX fallback only for unavailable inference resources."""
import os
import copy
import hashlib
import subprocess
import json
import tempfile
import fcntl
from contextlib import contextmanager
from pathlib import Path
from prepare_voice_candidates import ASR, ALIGNER
from spark_speech import ASR as SPARK_ASR, ALIGNER as SPARK_ALIGNER, SparkModel, freeze_requests, batch_sha256


def infrastructure_error(exc):
    if isinstance(exc, (ImportError, ModuleNotFoundError, OSError)):
        return True
    return isinstance(exc, RuntimeError) and any(word in str(exc).lower() for word in ("out of memory", "out-of-memory", "metal", "device unavailable", "cuda unavailable"))


class SpeechModel:
    def __init__(self, model):
        if model not in (ASR, ALIGNER):
            raise ValueError("Unknown primary speech model")
        self.primary = model
        self.model = model
        self.last_receipt = None
        self.fallback_reason = None
        self.mode = os.environ.get("SERMON_SPEECH_BACKEND", "auto")
        if self.mode not in ("auto", "macbook", "spark"):
            raise ValueError("SERMON_SPEECH_BACKEND must be auto, macbook or spark")
        if self.mode == "macbook":
            self._macbook()
        else:
            self.model = SPARK_ASR if self.primary == ASR else SPARK_ALIGNER
            self.engine = SparkModel(self.model)
            self.backend = 'spark'
            if self.mode == 'spark':
                self.fallback_reason = 'explicit_spark_selection'

    def _macbook(self):
        from huggingface_hub import snapshot_download
        from mlx_audio.stt.utils import load_model
        self.model = self.primary
        self.engine = load_model(snapshot_download(repo_id=self.model[0], revision=self.model[1], local_files_only=True))
        self.backend = 'macbook'

    def generate(self, path, **kwargs):
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        frozen_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        frozen_kwargs = copy.deepcopy(kwargs)
        try:
            result = self.engine.generate(path, **copy.deepcopy(frozen_kwargs))
        except Exception as exc:
            if self.mode != "auto" or self.backend != 'spark' or not spark_infrastructure_error(exc):
                raise
            if hashlib.sha256(path.read_bytes()).hexdigest() != frozen_hash:
                raise ValueError('Speech audio changed before MacBook fallback') from exc
            self._macbook()
            self.fallback_reason = type(exc).__name__ + ': Spark speech runtime unavailable'
            result = self.engine.generate(path, **copy.deepcopy(frozen_kwargs))
        if hashlib.sha256(path.read_bytes()).hexdigest() != frozen_hash:
            raise ValueError('Speech audio changed during inference')
        if self.backend == 'spark':
            self.last_receipt = {**self.engine.last_receipt, "fallbackReason": self.fallback_reason}
        else:
            self.last_receipt = {"executionHost": "macbook", "device": "mlx", "model": self.model[0], "revision": self.model[1],
                                 "fallbackReason": self.fallback_reason, 'audioSha256': frozen_hash}
            import mlx.core as mx
            mx.clear_cache()
        return result


    def generate_batch(self, requests, *, on_result=None, dispatch_dir=None, job_sha256=None):
        if dispatch_dir is None:
            return self._generate_batch(requests, on_result=on_result)
        with dispatch_lease(Path(dispatch_dir)):
            return self._generate_journaled_batch(requests, on_result=on_result,
                dispatch_dir=dispatch_dir, job_sha256=job_sha256)

    def _generate_journaled_batch(self, requests, *, on_result=None, dispatch_dir=None, job_sha256=None):
        if dispatch_dir is None:
            return self._generate_batch(requests, on_result=on_result)
        dispatch_dir = Path(dispatch_dir)
        require_resolved_dispatches(dispatch_dir)
        if self.backend != 'spark':
            return self._generate_batch(requests, on_result=on_result)
        pinned = SPARK_ASR if self.primary == ASR else SPARK_ALIGNER
        frozen = freeze_requests(requests, pinned)
        batch_hash = batch_sha256(frozen)
        for saved in dispatch_dir.glob('batch-*.json'):
            prior = json.loads(saved.read_text())
            if prior.get('jobSha256') != job_sha256:
                continue
            committed = [row for row in prior['units'] if row['unitId'] in prior['completedUnitIds']]
            if any(row in committed for row in ({'unitId': item['unitId'], 'identity': item['identity']} for item in frozen)):
                raise ValueError('Speech request already committed by another batch; reload existing unit caches')
        path = dispatch_dir / f'batch-{batch_hash}.json'
        record = {'schemaVersion': 'spark-speech-dispatch-v1', 'batchSha256': batch_hash,
                  'jobSha256': job_sha256, 'status': 'started', 'completedUnitIds': [],
                  'units': [{'unitId': row['unitId'], 'identity': row['identity']} for row in frozen]}
        write_dispatch(path, record)

        def save(unit_id, result, receipt):
            if on_result is not None:
                on_result(unit_id, result, receipt)
            record['completedUnitIds'].append(unit_id)
            write_dispatch(path, record)

        try:
            results = self._generate_batch(requests, on_result=save)
        except Exception as exc:
            if self.backend == 'macbook':
                status = 'failed_invalid' if isinstance(exc, ValueError) else 'confirmed_terminal'
            elif getattr(exc, 'speechOutcomeUnknown', False) or isinstance(exc, subprocess.TimeoutExpired) or (isinstance(exc, subprocess.CalledProcessError)
                    and exc.returncode in (-9, -11, 255) and not spark_infrastructure_error(exc)):
                status = 'unknown'
            else:
                status = 'confirmed_terminal' if spark_infrastructure_error(exc) else 'failed_invalid'
            write_dispatch(path, {**record, 'status': status, 'errorType': type(exc).__name__})
            raise
        write_dispatch(path, {**record, 'status': 'complete'})
        return results

    def _generate_batch(self, requests, *, on_result=None):
        requests = copy.deepcopy(requests)
        pinned = SPARK_ASR if self.primary == ASR else SPARK_ALIGNER
        frozen = freeze_requests(requests, pinned)
        self.last_receipts, results = [], []
        callback_failed = False

        def unchanged():
            for row, bound in zip(requests, frozen):
                if hashlib.sha256(Path(row['path']).read_bytes()).hexdigest() != bound['identity']['audioSha256']:
                    raise ValueError('Speech audio changed during batch inference or before MacBook fallback')

        def accept(unit_id, result, receipt):
            nonlocal callback_failed
            unchanged()
            index = len(results)
            if index >= len(requests) or unit_id != requests[index]['unitId']:
                raise ValueError('Speech batch order/cardinality differs')
            receipt = copy.deepcopy(receipt)
            if self.backend == 'spark':
                receipt.update(model=receipt['identity']['model'], revision=receipt['identity']['revision'])
            receipt['fallbackReason'] = self.fallback_reason
            results.append(result)
            self.last_receipts.append(receipt)
            self.last_receipt = receipt
            if on_result is not None:
                try:
                    on_result(unit_id, result, receipt)
                except Exception:
                    callback_failed = True
                    raise

        if self.backend == 'spark':
            try:
                self.engine.generate_batch(requests, on_result=accept)
            except Exception as exc:
                if callback_failed or len(results) == len(requests) or self.mode != 'auto' or not spark_infrastructure_error(exc):
                    raise
                unchanged()
                self._macbook()
                self.fallback_reason = type(exc).__name__ + ': Spark speech runtime unavailable'
        if self.backend == 'macbook':
            for index in range(len(results), len(requests)):
                unchanged()
                row = requests[index]
                keys = ('language', 'text') if self.primary == ALIGNER else ('language', 'max_tokens', 'text')
                kwargs = {key: row[key] for key in keys if key in row}
                result = self.engine.generate(Path(row['path']), **copy.deepcopy(kwargs))
                receipt = {'executionHost': 'macbook', 'device': 'mlx', 'model': self.model[0],
                           'revision': self.model[1], 'audioSha256': frozen[index]['identity']['audioSha256'],
                           'unitId': row['unitId']}
                if 'locale' in row:
                    receipt['locale'] = row['locale']
                accept(row['unitId'], result, receipt)
            import mlx.core as mx
            mx.clear_cache()
        unchanged()
        if len(results) != len(requests):
            raise ValueError('Speech batch coverage incomplete')
        return results


@contextmanager
def dispatch_lease(folder):
    folder.mkdir(parents=True, exist_ok=True)
    lock_path = folder / '.dispatch.lock'
    if folder.is_symlink() or lock_path.is_symlink():
        raise ValueError('Unsafe speech dispatch lease path')
    with lock_path.open('a') as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another speech batch owns this dispatch directory') from exc
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def write_dispatch(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Unsafe speech dispatch path')
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write((json.dumps(record, ensure_ascii=False, indent=2) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def require_resolved_dispatches(folder):
    folder = Path(folder)
    for path in sorted(folder.glob('batch-*.json')):
        record = json.loads(path.read_text())
        if record.get('schemaVersion') != 'spark-speech-dispatch-v1' or record.get('status') not in ('complete', 'confirmed_terminal'):
            raise RuntimeError(f'Unresolved Spark speech dispatch; reconcile remote execution and receipts before retry: {path}')


def add_batch_argument(parser):
    value = int(os.environ.get('SERMON_SPEECH_BATCH_SIZE', '4'))
    if value not in (1, 2, 4, 8):
        raise ValueError('SERMON_SPEECH_BATCH_SIZE must be 1, 2, 4 or 8')
    parser.add_argument('--speech-batch-size', type=int, choices=(1, 2, 4, 8), default=value)


def bounded_batches(requests, size):
    if size not in (1, 2, 4, 8):
        raise ValueError('Speech batch size must be 1, 2, 4 or 8')
    for start in range(0, len(requests), size):
        yield requests[start:start + size]


def spark_infrastructure_error(exc):
    if getattr(exc, 'speechOutcomeUnknown', False) or isinstance(exc, InterruptedError):
        return False
    if isinstance(exc, subprocess.TimeoutExpired):
        # The SSH child may be gone while the remote inference is still active.
        return False
    if isinstance(exc, subprocess.CalledProcessError):
        if exc.returncode in (75, 126, 127, 137, 139):
            return True
        detail = exc.stderr or ''
        if isinstance(detail, bytes):
            detail = detail.decode(errors='replace')
        if exc.returncode == 255:
            return any(token in detail.lower() for token in (
                'connection refused', 'no route to host', 'network is unreachable',
                'connection timed out', 'could not resolve hostname',
                'permission denied (', 'host key verification failed'))
        terminal = detail.strip().splitlines()[-1] if detail.strip() else ''
        return (terminal.startswith(('ModuleNotFoundError:', 'ImportError:', 'MemoryError:',
                                     'torch.OutOfMemoryError:', 'huggingface_hub.errors.LocalEntryNotFoundError:'))
                or terminal.startswith('RuntimeError: Spark CUDA is unavailable;'))
    return infrastructure_error(exc)


def accepted_model(model, revision, kind):
    return (model, revision) in ((ASR, SPARK_ASR) if kind == "asr" else (ALIGNER, SPARK_ALIGNER))


def same_identity(actual, expected):
    return (accepted_model(actual.get("model"), actual.get("revision"), "asr")
            and {k: v for k, v in actual.items() if k not in ("model", "revision")}
            == {k: v for k, v in expected.items() if k not in ("model", "revision")})
