"""One bounded offline speech request; invoked on Spark by spark_speech.py."""
import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import platform
import sys


def main():
    request = json.load(sys.stdin)
    identity = request["identity"]
    pins = {"Qwen/Qwen3-ASR-0.6B": "5eb144179a02acc5e5ba31e748d22b0cf3e303b0", "Qwen/Qwen3-ForcedAligner-0.6B": "c7cbfc2048c462b0d63a45797104fc9db3ad62b7"}
    if pins.get(identity["model"]) != identity["revision"]:
        raise ValueError("Unpinned model")
    raw = base64.b64decode(request["audio"], validate=True)
    if hashlib.sha256(raw).hexdigest() != identity["audioSha256"]:
        raise ValueError("Audio transfer changed")
    if platform.system() != "Linux" or platform.machine() not in ("aarch64", "arm64"):
        raise RuntimeError("Speech worker requires the Linux ARM64 Spark runtime")
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        import soundfile as sf
        from huggingface_hub import snapshot_download
        from qwen_asr import Qwen3ASRModel, Qwen3ForcedAligner
        if not torch.cuda.is_available():
            raise RuntimeError("Spark CUDA is unavailable; refusing CPU/Mac fallback")
        snapshot = Path(snapshot_download(repo_id=identity["model"], revision=identity["revision"], local_files_only=True))
        hashes = {}
        for path in sorted(snapshot.rglob("*")):
            if path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                hashes[str(path.relative_to(snapshot))] = digest.hexdigest()
        audio, rate = sf.read(io.BytesIO(raw), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        kwargs = dict(dtype=torch.bfloat16, device_map="cuda:0")
        if identity["model"].endswith("ASR-0.6B"):
            model = Qwen3ASRModel.from_pretrained(str(snapshot), max_new_tokens=identity["maxTokens"], max_inference_batch_size=1, **kwargs)
            text = model.transcribe(audio=(audio, rate), language=identity["language"])[0].text
            words = []
        else:
            model = Qwen3ForcedAligner.from_pretrained(str(snapshot), **kwargs)
            result = model.align(audio=(audio, rate), text=identity["text"], language=identity["language"])[0]
            words = [{"text": w.text, "start": float(w.start_time), "end": float(w.end_time)} for w in result]
            text = identity["text"]
    # The caller records this alongside each audio hash and immutable model pin.
    import importlib.metadata
    json.dump({"identity": identity, "executionHost": "dgx-spark", "hostname": platform.node(), "device": "cuda", "modelFilesSha256": hashes,
               "workerSha256": hashlib.sha256(sys.argv[1].encode()).hexdigest(), "qwenAsrVersion": importlib.metadata.version("qwen-asr"), "torchVersion": torch.__version__, "text": text, "words": words}, sys.stdout)


if __name__ == "__main__":
    main()
