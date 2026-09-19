"""Pinned Torch speech inference on Spark; the Mac only transfers audio/evidence.

The isolated runtime is provisioned separately. Execution is offline, fails closed,
and never loads an MLX or CPU model on the dispatcher.
"""
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
from types import SimpleNamespace

ASR = ("Qwen/Qwen3-ASR-0.6B", "5eb144179a02acc5e5ba31e748d22b0cf3e303b0")
ALIGNER = ("Qwen/Qwen3-ForcedAligner-0.6B", "c7cbfc2048c462b0d63a45797104fc9db3ad62b7")
RUNTIME = "/home/achillesjing/sermon-speech-runtime"


def remote_command():
    # Override is an explicit argv JSON, never a shell fragment. Useful for a
    # provisioned CUDA container; it still runs exclusively on the Spark host.
    python = json.loads(os.environ.get("SERMON_SPARK_SPEECH_COMMAND", json.dumps(["docker", "run", "--rm", "-i", "--entrypoint", "/runtime/venv/bin/python", "--gpus", "all", "--memory", "12g", "--cpus", "4", "-v", RUNTIME + ":/runtime", "-e", "HF_HOME=/runtime/model-cache", "-e", "HF_HUB_OFFLINE=1", "-e", "TRANSFORMERS_OFFLINE=1", "nvcr.io/nvidia/pytorch:26.06-py3"])))
    if not isinstance(python, list) or not python or any(not isinstance(x, str) for x in python):
        raise ValueError("SERMON_SPARK_SPEECH_COMMAND must be a nonempty argv JSON")
    script = Path(__file__).with_name("spark_speech_worker.py").read_text()
    remote = ["env", "HF_HOME=" + RUNTIME + "/model-cache", "HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1", *python, "-c", script, script]
    host = os.environ.get("SERMON_SPARK_HOST", "achillesjing@192.168.1.152")
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", host, shlex.join(remote)]
    bridge = os.environ.get("SERMON_SPARK_BRIDGE", "jonyopenclaw@100.73.116.52")
    if bridge:
        ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "HostKeyAlias=" + os.environ.get("SERMON_SPARK_BRIDGE_ALIAS", "jonys-mac-mini.local"), bridge, shlex.join(ssh)]
    return ssh


class SparkModel:
    def __init__(self, model):
        if model not in (ASR, ALIGNER):
            raise ValueError("Unrecognized pinned speech model")
        self.model = model
        self.last_receipt = None

    def generate(self, path, *, language, max_tokens=2048, text=None):
        raw = Path(path).read_bytes()
        identity = {"audioSha256": hashlib.sha256(raw).hexdigest(), "model": self.model[0], "revision": self.model[1], "language": language, "text": text, "maxTokens": max_tokens}
        request = {"identity": identity, "audio": base64.b64encode(raw).decode("ascii")}
        result = subprocess.run(remote_command(), input=json.dumps(request), text=True, capture_output=True, check=True,
                                timeout=float(os.environ.get("SERMON_SPARK_SPEECH_TIMEOUT", "600")))
        response = json.loads(result.stdout)
        if response.get("identity") != identity or response.get("executionHost") != "dgx-spark" or response.get("device") != "cuda":
            raise ValueError("Spark speech response identity/device mismatch")
        worker_hash = hashlib.sha256(Path(__file__).with_name("spark_speech_worker.py").read_bytes()).hexdigest()
        if not response.get("modelFilesSha256") or response.get("workerSha256") != worker_hash:
            raise ValueError("Missing Spark model/code provenance")
        self.last_receipt = {k: v for k, v in response.items() if k not in ("text", "words")}
        words = response.get("words", [])
        previous = 0
        for word in words:
            start, end = word["start"], word["end"]
            if not all(isinstance(t, (int, float)) and math.isfinite(t) for t in (start, end)) or not previous <= start <= end or not isinstance(word["text"], str):
                raise ValueError("Invalid Spark word timing")
            previous = end
        return SimpleNamespace(text=response.get("text", ""), segments=words)
