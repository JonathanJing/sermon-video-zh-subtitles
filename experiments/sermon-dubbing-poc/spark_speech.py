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
MAX_BATCH_UNITS = 8
MAX_BATCH_AUDIO_BYTES = 32 * 1024 * 1024
BATCH_SCHEMA = "spark-speech-batch-v1"

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

    def _response(self, response, identity):
        if response.get("identity") != identity or response.get("executionHost") != "dgx-spark" or response.get("device") != "cuda":
            raise ValueError("Spark speech response identity/device mismatch")
        worker_hash = hashlib.sha256(Path(__file__).with_name("spark_speech_worker.py").read_bytes()).hexdigest()
        if not response.get("modelFilesSha256") or response.get("workerSha256") != worker_hash:
            raise ValueError("Missing Spark model/code provenance")
        if not isinstance(response.get('text'), str) or not isinstance(response.get('words'), list):
            raise ValueError('Invalid Spark speech text/words')
        receipt = {k: v for k, v in response.items() if k not in ("text", "words", 'event')}
        words = response["words"]
        previous = 0
        for word in words:
            start, end = word["start"], word["end"]
            if not all(type(t) in (int, float) and math.isfinite(t) for t in (start, end)) or not previous <= start <= end or not isinstance(word["text"], str):
                raise ValueError("Invalid Spark word timing")
            previous = end
        return SimpleNamespace(text=response['text'], segments=words), receipt

    def generate(self, path, *, language, max_tokens=2048, text=None):
        request = freeze_requests([{'unitId': 0, 'path': path, 'language': language,
                                    'max_tokens': max_tokens, 'text': text}], self.model)[0]
        # The single-request protocol stays compatible with existing callers.
        request = {key: request[key] for key in ('identity', 'audio')}
        result = subprocess.run(remote_command(), input=json.dumps(request), text=True, capture_output=True, check=True,
                                timeout=timeout_seconds())
        result, self.last_receipt = self._response(json.loads(result.stdout), request['identity'])
        return result

    def generate_batch(self, requests, *, on_result=None):
        frozen = freeze_requests(requests, self.model)
        batch_hash = batch_sha256(frozen)
        request = {'schemaVersion': BATCH_SCHEMA, 'batchSha256': batch_hash, 'requests': frozen}
        self.last_receipts = []
        timeout_failure = None
        try:
            completed = subprocess.run(remote_command(), input=json.dumps(request), text=True,
                                       capture_output=True, check=False, timeout=timeout_seconds())
        except subprocess.TimeoutExpired as exc:
            timeout_failure = exc
            output = exc.stdout or ''
            if isinstance(output, bytes):
                output = output.decode()
            completed = subprocess.CompletedProcess(exc.cmd, 0, stdout=output)
        transport_failure = timeout_failure
        if timeout_failure is not None:
            timeout_failure.speechOutcomeUnknown = True
        if completed.returncode:
            transport_failure = subprocess.CalledProcessError(completed.returncode, completed.args,
                output=completed.stdout, stderr=completed.stderr)
            if completed.returncode in (-9, -11, 255):
                detail = (completed.stderr or '').lower()
                connection_failure = any(token in detail for token in (
                    'connection refused', 'no route to host', 'network is unreachable',
                    'connection timed out', 'could not resolve hostname',
                    'permission denied (', 'host key verification failed'))
                transport_failure.speechOutcomeUnknown = (completed.returncode != 255
                    or bool(completed.stdout.strip()) or not connection_failure)
        try:
            results, ended = [], False
            for line in completed.stdout.splitlines():
                response = json.loads(line)
                if ended or response.get('batchSha256') != batch_hash:
                    raise ValueError('Spark batch identity or trailing output differs')
                if response.get('event') == 'batch_complete':
                    if response.get('count') != len(frozen) or len(results) != len(frozen):
                        raise ValueError('Spark batch cardinality differs')
                    ended = True
                    continue
                index = len(results)
                if response.get('event') != 'unit_result' or index >= len(frozen) or response.get('unitId') != frozen[index]['unitId']:
                    raise ValueError('Spark batch result order/cardinality differs')
                result, receipt = self._response(response, frozen[index]['identity'])
                results.append(result)
                self.last_receipts.append(receipt)
                self.last_receipt = receipt
                if on_result is not None:
                    on_result(frozen[index]['unitId'], result, receipt)
        except Exception as exc:
            # Never let cache/callback/partial-JSON errors hide a known unknown
            # remote outcome and accidentally permit a later duplicate launch.
            if transport_failure is not None and getattr(transport_failure, 'speechOutcomeUnknown', False):
                raise transport_failure from exc
            raise
        if transport_failure is not None:
            raise transport_failure
        if not ended or len(results) != len(frozen):
            raise ValueError('Spark batch ended without complete coverage')
        return results


def timeout_seconds():
    value = float(os.environ.get('SERMON_SPARK_SPEECH_TIMEOUT', '600'))
    if not math.isfinite(value) or value <= 0 or value > 3600:
        raise ValueError('Spark speech timeout must be positive and at most 3600 seconds')
    return value


def batch_sha256(requests):
    # Hash the ordered immutable identities, not mutable filesystem paths.
    identities = [{'unitId': row['unitId'], 'identity': row['identity']} for row in requests]
    return hashlib.sha256(json.dumps(identities, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def freeze_requests(requests, model):
    if not isinstance(requests, list) or not 1 <= len(requests) <= MAX_BATCH_UNITS:
        raise ValueError('Speech batch must contain 1..8 requests')
    frozen, seen, total = [], set(), 0
    for row in requests:
        unit_id = row['unitId']
        if type(unit_id) not in (str, int) or unit_id == '' or (type(unit_id), unit_id) in seen:
            raise ValueError('Speech batch requires unique unit IDs')
        seen.add((type(unit_id), unit_id))
        language, maximum, text = row['language'], row.get('max_tokens', 2048), row.get('text')
        if not isinstance(language, str) or not language or type(maximum) is not int or not 1 <= maximum <= 2048:
            raise ValueError('Invalid speech language/token limit')
        if text is not None and not isinstance(text, str):
            raise ValueError('Invalid frozen speech text')
        if model[0].endswith('ForcedAligner-0.6B') and (not isinstance(text, str) or not text.strip()):
            raise ValueError('Forced aligner requires nonempty frozen text')
        path = Path(row['path'])
        size = path.stat().st_size
        if size <= 0 or total + size > MAX_BATCH_AUDIO_BYTES:
            raise ValueError('Speech batch exceeds 32 MiB audio bound or contains empty input')
        raw = path.read_bytes()
        total += len(raw)
        if len(raw) != size or total > MAX_BATCH_AUDIO_BYTES:
            raise ValueError('Speech input changed or exceeds audio byte bound')
        identity = {'audioSha256': hashlib.sha256(raw).hexdigest(), 'model': model[0], 'revision': model[1],
                    'language': language, 'text': text, 'maxTokens': maximum}
        if 'locale' in row:
            if not isinstance(row['locale'], str) or not row['locale']:
                raise ValueError('Invalid speech locale')
            identity['locale'] = row['locale']
        frozen.append({'unitId': unit_id, 'identity': identity, 'audio': base64.b64encode(raw).decode('ascii')})
    if len({row['identity']['maxTokens'] for row in frozen}) != 1:
        raise ValueError('A resident batch requires one frozen token limit')
    return frozen
