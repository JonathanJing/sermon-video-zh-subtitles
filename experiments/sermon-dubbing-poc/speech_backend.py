"""MacBook MLX first; Spark fallback only for unavailable inference resources."""
import os
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
        mode = os.environ.get("SERMON_SPEECH_BACKEND", "auto")
        if mode not in ("auto", "macbook", "spark"):
            raise ValueError("SERMON_SPEECH_BACKEND must be auto, macbook or spark")
        self.mode = mode
        if mode == "spark":
            self._fallback("explicit_spark_selection")
            return
        try:
            from huggingface_hub import snapshot_download
            from mlx_audio.stt.utils import load_model
            self.engine = load_model(snapshot_download(repo_id=model[0], revision=model[1], local_files_only=True))
        except Exception as exc:
            if mode != "auto" or not infrastructure_error(exc):
                raise
            self._fallback(type(exc).__name__ + ": local speech runtime unavailable")

    def _fallback(self, reason):
        self.model = SPARK_ASR if self.primary == ASR else SPARK_ALIGNER
        self.engine = SparkModel(self.model)
        self.fallback_reason = reason

    def generate(self, path, **kwargs):
        if not Path(path).is_file():
            raise FileNotFoundError(path)
        try:
            result = self.engine.generate(path, **kwargs)
        except Exception as exc:
            if self.mode != "auto" or isinstance(self.engine, SparkModel) or isinstance(exc, OSError) or not infrastructure_error(exc):
                raise
            self._fallback(type(exc).__name__ + ": local speech inference resource failure")
            result = self.engine.generate(path, **kwargs)
        if isinstance(self.engine, SparkModel):
            self.last_receipt = {**self.engine.last_receipt, "fallbackReason": self.fallback_reason}
        else:
            self.last_receipt = {"executionHost": "macbook", "device": "mlx", "model": self.model[0], "revision": self.model[1]}
            import mlx.core as mx
            mx.clear_cache()
        return result


def accepted_model(model, revision, kind):
    return (model, revision) in ((ASR, SPARK_ASR) if kind == "asr" else (ALIGNER, SPARK_ALIGNER))


def same_identity(actual, expected):
    return (accepted_model(actual.get("model"), actual.get("revision"), "asr")
            and {k: v for k, v in actual.items() if k not in ("model", "revision")}
            == {k: v for k, v in expected.items() if k not in ("model", "revision")})
