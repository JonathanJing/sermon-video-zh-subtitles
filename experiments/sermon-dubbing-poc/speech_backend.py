"""Spark first; MacBook MLX fallback only for unavailable inference resources."""
import os
import copy
import hashlib
import subprocess
from pathlib import Path
from prepare_voice_candidates import ASR, ALIGNER
from spark_speech import ASR as SPARK_ASR, ALIGNER as SPARK_ALIGNER, SparkModel


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


def spark_infrastructure_error(exc):
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
