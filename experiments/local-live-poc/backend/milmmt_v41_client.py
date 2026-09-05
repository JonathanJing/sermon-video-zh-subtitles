"""Fixed, source-only adapter for the separately hosted experimental MLX v4.1.

This client never changes the default Ollama runtime, accepts model parameters,
or sends Saturday context. Failure uses OllamaError so recording can continue.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import http.client
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from .ollama_client import MILMMT_A0_PROMPT_VERSION, OllamaError


PROVIDER_ID = "milmmt-v41-mlx"
MODEL_ID = "milmmt-sermon-v41-experimental-mlx-q5"
SERVICE = "milmmt-v41-local-experimental-v1"
WEIGHTS_SHA = "6057e793922b8aa0c30c5180b490d8e5cac14a3dcd1a000b1b906d0da8fa6987"
MANIFEST_SHA = "5f313eadf8951eb3251056686fee965feae3d189b2a6cbe844118982d0d27179"
EXPECTED_RUNTIME_PACKAGES = {
    "mlx": "0.32.2", "mlx-lm": "0.31.3", "safetensors": "0.8.0",
    "tokenizers": "0.23.2", "transformers": "5.16.1",
}
DEFAULT_BASE_URL = "http://127.0.0.1:18771"
ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PYTHON = Path.home() / ".local/share/uv/tools/mlx-lm/bin/python"
DEFAULT_SCRIPT = ROOT / "scripts/serve_milmmt_v41_local.py"
DEFAULT_MODEL = Path.home() / "Models" / MODEL_ID
DEFAULT_STATE_DIR = Path.home() / "Library/Caches/sermon-video-zh-subtitles/milmmt-v41-local"
MAX_SOURCE = 2048
MAX_PROMPT_TOKENS = 1024
MAX_NEW_TOKENS = 512
MAX_HEALTH_BYTES = 16384
MAX_RESPONSE_BYTES = 512 * 1024
MAX_LINE_BYTES = 64 * 1024
MAX_STREAM_EVENTS = MAX_NEW_TOKENS + 1
SERVICE_TIMING_SCOPE = (
    "worker tokenization through synchronized generation; includes stream backpressure, "
    "excludes request transit and UI paint"
)
EMPTY_CONTEXT_KEYS = {
    "approvedTerms", "verifiedScriptureRefs", "reviewedExactExamples", "reviewedAlignedReferences",
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DECODE_CONTRACT = {
    "schemaVersion": "milmmt-mlx-q5-source-only-v1", "runtime": "mlx",
    "quantization": {"bits": 5, "group_size": 64, "mode": "affine"},
    "promptVersion": MILMMT_A0_PROMPT_VERSION,
    "addSpecialTokens": False, "chatTemplateApplied": False,
    "sampler": "make_sampler(temp=0)", "temperature": 0,
    "maxNewTokens": MAX_NEW_TOKENS, "eosTokenIds": [1, 106],
    "promptCache": "new_per_request", "contextPolicy": "none", "postprocessing": "none",
}


def _loopback_url(value: str) -> tuple[str, str, int]:
    """Canonicalize localhost to the explicit IPv4 loopback used by the service."""
    if (not isinstance(value, str) or value != value.strip() or not value
            or any(ord(c) <= 32 or ord(c) >= 127 for c in value)
            or "?" in value or "#" in value or "\\" in value):
        raise ValueError("MiLMMT v4.1 endpoint must be an explicit HTTP loopback origin")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("MiLMMT v4.1 endpoint has an invalid loopback origin") from None
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or port is None or not 1 <= port <= 65535):
        raise ValueError("MiLMMT v4.1 endpoint must be HTTP localhost/127.0.0.1 with an explicit port and no credentials or path")
    return f"http://127.0.0.1:{port}", "127.0.0.1", port


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _reject_constant(_value):
    raise ValueError("non-finite JSON number")


def _json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
        if not isinstance(value, dict):
            raise ValueError("expected object")
        return value
    except (ValueError, UnicodeError):
        raise OllamaError("MiLMMT v4.1 returned an invalid JSON protocol object") from None


def _source_and_context(source: str, context: dict[str, Any] | None) -> None:
    if (not isinstance(source, str) or not source.strip() or len(source) > MAX_SOURCE
            or any(ord(c) < 32 and c not in "\n\r\t" for c in source)
            or any(0xD800 <= ord(c) <= 0xDFFF for c in source)):
        raise OllamaError("MiLMMT v4.1 requires nonempty English text within the fixed input limit")
    # prompt_context(policy='none') has these four empty lists; it is still A0.
    if context is not None and (not isinstance(context, dict) or
            set(context) - EMPTY_CONTEXT_KEYS or any(value != [] for value in context.values())):
        raise OllamaError("MiLMMT v4.1 experimental mode does not accept translation context")


class MilmmtV41Client:
    def __init__(
        self, base_url: str = DEFAULT_BASE_URL, *,
        python_path: Path | str | None = None, runtime_script: Path | str | None = None,
        model_path: Path | str | None = None, state_dir: Path | str | None = None,
        translation_timeout: float = 100.0, health_timeout: float = 2.0,
        io_timeout: float = 15.0, max_response_bytes: int = MAX_RESPONSE_BYTES,
        max_line_bytes: int = MAX_LINE_BYTES,
    ) -> None:
        self.base_url, self._host, self._port = _loopback_url(base_url)
        # Retain the venv's invocation path. Resolving its python symlink can
        # select the underlying uv interpreter without the installed MLX env.
        self.python_path = Path(DEFAULT_PYTHON if python_path is None else python_path).expanduser().absolute()
        self.runtime_script = Path(DEFAULT_SCRIPT if runtime_script is None else runtime_script).expanduser().resolve()
        self.model_path = Path(DEFAULT_MODEL if model_path is None else model_path).expanduser().resolve()
        self.state_dir = Path(DEFAULT_STATE_DIR if state_dir is None else state_dir).expanduser().resolve()
        for name, value, maximum in (("translation_timeout", translation_timeout, 100),
                                     ("health_timeout", health_timeout, 5), ("io_timeout", io_timeout, 15)):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
                raise ValueError(f"{name} must be positive and within the service bound")
        for name, value, maximum in (("max_response_bytes", max_response_bytes, MAX_RESPONSE_BYTES),
                                     ("max_line_bytes", max_line_bytes, MAX_LINE_BYTES)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be a positive bounded integer")
        self.translation_timeout = float(translation_timeout)
        self.health_timeout = float(health_timeout)
        self.io_timeout = float(io_timeout)
        self.max_response_bytes, self.max_line_bytes = max_response_bytes, max_line_bytes

    @property
    def model(self) -> str:
        return MODEL_ID

    @property
    def start_supported(self) -> bool:
        return (self.base_url == DEFAULT_BASE_URL and self.python_path.is_file()
                and os.access(self.python_path, os.X_OK) and self.runtime_script.is_file()
                and os.access(self.runtime_script, os.R_OK))

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise OllamaError("MiLMMT v4.1 request deadline exceeded")
        return min(self.io_timeout, remaining)

    @contextmanager
    def _response(self, method: str, path: str, payload: dict | None, deadline: float):
        # HTTPConnection connects directly. It never consults proxy environment
        # variables, follows redirects, sends credentials, or resolves localhost.
        connection = http.client.HTTPConnection(self._host, self._port, timeout=self._remaining(deadline))
        response = timer = None
        try:
            connection.connect()
            sock = connection.sock
            if sock is None:
                raise OllamaError("MiLMMT v4.1 connection did not open")
            # A socket idle timeout alone does not bound a peer trickling headers
            # or bytes forever. Shutdown wakes blocked reads at the whole deadline.
            def expire():
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            timer = threading.Timer(max(0, deadline - time.monotonic()), expire)
            timer.daemon = True
            timer.start()
            data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            connection.request(method, path, body=data, headers={
                "Content-Type": "application/json", "Accept": "application/json" if method == "GET" else "application/x-ndjson",
                "Connection": "close",
            })
            response = connection.getresponse()
            self._remaining(deadline)
            if response.status != 200:
                raise OllamaError(f"MiLMMT v4.1 returned HTTP {response.status}")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise OllamaError("MiLMMT v4.1 returned unsupported response encoding")
            yield response, sock
        except OllamaError:
            raise
        except (OSError, http.client.HTTPException, ValueError, UnicodeError):
            if time.monotonic() >= deadline:
                raise OllamaError("MiLMMT v4.1 request deadline exceeded") from None
            raise OllamaError("MiLMMT v4.1 local connection failed or stream was interrupted") from None
        finally:
            if timer is not None:
                timer.cancel()
            if response is not None:
                response.close()
            connection.close()

    def _chunks(self, response, sock, deadline: float, limit: int) -> Iterator[bytes]:
        total = 0
        expected = response.getheader("Content-Length")
        transfer = response.getheader("Transfer-Encoding")
        if transfer and (transfer.lower() != "chunked" or expected is not None):
            raise OllamaError("MiLMMT v4.1 returned ambiguous response framing")
        if expected is not None:
            try:
                if not expected.isdecimal() or not 0 <= int(expected) <= limit:
                    raise ValueError("invalid response length")
                expected = int(expected)
            except (ValueError, AttributeError):
                raise OllamaError("MiLMMT v4.1 response exceeds the size limit or has invalid framing") from None
        while True:
            sock.settimeout(self._remaining(deadline))
            # read1 returns after one socket read; an incomplete line cannot hide
            # the total deadline or grow an unbounded readline buffer.
            raw = response.read1(min(4096, limit - total + 1))
            self._remaining(deadline)
            if not raw:
                if expected is not None and total != expected:
                    raise OllamaError("MiLMMT v4.1 response ended before its declared length")
                return
            total += len(raw)
            if total > limit:
                raise OllamaError("MiLMMT v4.1 response exceeds the size limit")
            yield raw
            # HTTPResponse closes the socket-backed file as soon as a declared
            # Content-Length is fully consumed. Do not set a timeout on that
            # already-closed socket for an unnecessary EOF read.
            if expected is not None and total == expected:
                return

    def _health(self, deadline: float | None = None) -> dict[str, Any]:
        deadline = min(deadline or float("inf"), time.monotonic() + self.health_timeout)
        with self._response("GET", "/api/health", None, deadline) as (response, sock):
            if response.getheader("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise OllamaError("MiLMMT v4.1 health response has an invalid content type")
            health = _json(b"".join(self._chunks(response, sock, deadline, MAX_HEALTH_BYTES)))
        packages = health.get("runtimePackages")
        state = health.get("status")
        if (health.get("service") != SERVICE or health.get("modelSha256") != WEIGHTS_SHA
                or health.get("packageSha256") != MANIFEST_SHA or health.get("releaseEligible") is not False
                or not isinstance(state, str) or state not in {"loading", "ready", "failed", "stopping"}
                or type(health.get("busy")) is not bool or type(health.get("pid")) is not int
                or health["pid"] <= 0 or not isinstance(health.get("instanceId"), str) or not health["instanceId"]
                or not isinstance(packages, dict)
                or packages not in ({}, EXPECTED_RUNTIME_PACKAGES)
                or (state == "ready" and packages != EXPECTED_RUNTIME_PACKAGES)):
            raise OllamaError("MiLMMT v4.1 service identity, runtime versions, or health schema mismatch")
        # Older v1 services identify the protocol through their versioned service
        # name. If a separate schema is supplied it must agree, not redefine v1.
        if "schemaVersion" in health and health["schemaVersion"] != SERVICE:
            raise OllamaError("MiLMMT v4.1 health schema version mismatch")
        return health

    def _status(self, health: dict | None = None, error: str | None = None) -> dict[str, Any]:
        ready = health is not None and health["status"] == "ready"
        result = {
            "available": health is not None, "configuredModel": MODEL_ID,
            "configuredModelInstalled": bool(health and health["runtimePackages"] == EXPECTED_RUNTIME_PACKAGES),
            "ready": ready, "busy": bool(health and health["busy"]),
            "experimental": True, "releaseEligible": False,
            "modelSha256": WEIGHTS_SHA if health is not None else None,
            "packageSha256": MANIFEST_SHA if health is not None else None,
            "runtimePackages": dict(health["runtimePackages"]) if health is not None else {},
            "startSupported": self.start_supported,
            "runtimeStatus": health["status"] if health is not None else "unavailable",
        }
        if health is not None:
            result.update({"service": SERVICE, "instanceId": health["instanceId"], "pid": health["pid"]})
        if error is not None:
            result["error"] = error
        elif health is not None and not ready:
            result["error"] = f"MiLMMT v4.1 runtime is not ready ({health['status']})"
        return result

    def status(self) -> dict[str, Any]:
        try:
            return self._status(self._health())
        except OllamaError as error:
            return self._status(error=str(error))

    def _events(self, payload: dict, deadline: float) -> Iterator[dict[str, Any]]:
        with self._response("POST", "/api/translate", payload, deadline) as (response, sock):
            if response.getheader("Content-Type", "").split(";", 1)[0].strip().lower() != "application/x-ndjson":
                raise OllamaError("MiLMMT v4.1 translation response must be NDJSON")
            pending, count = b"", 0
            for raw in self._chunks(response, sock, deadline, self.max_response_bytes):
                pending += raw
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    if len(line) > self.max_line_bytes:
                        raise OllamaError("MiLMMT v4.1 stream record exceeds the size limit")
                    if line.strip():
                        count += 1
                        if count > MAX_STREAM_EVENTS:
                            raise OllamaError("MiLMMT v4.1 stream exceeds the fixed generation event limit")
                        yield _json(line)
                if len(pending) > self.max_line_bytes:
                    raise OllamaError("MiLMMT v4.1 stream record exceeds the size limit")
            if pending.strip():
                raise OllamaError("MiLMMT v4.1 stream ended with an unterminated record")

    @staticmethod
    def _validate_done(done: dict, source: str, total: str) -> None:
        valid_number = lambda value: type(value) in (int, float) and math.isfinite(value) and value >= 0
        token_hash = done.get("generatedTokenIdsSha256")
        elapsed = done.get("elapsedMs")
        first = done.get("firstChineseMs")
        if (done.get("finishReason") != "stop" or done.get("source") != source
                or not isinstance(done.get("text"), str) or not done["text"].strip()
                or done["text"] != total or done.get("modelSha256") != WEIGHTS_SHA
                or done.get("experimental") is not True or done.get("releaseEligible") is not False
                or not isinstance(token_hash, str) or SHA256.fullmatch(token_hash) is None
                or type(done.get("promptTokens")) is not int or not 1 <= done["promptTokens"] <= MAX_PROMPT_TOKENS
                or type(done.get("generatedTokens")) is not int or not 1 <= done["generatedTokens"] <= MAX_NEW_TOKENS
                or not valid_number(elapsed) or done.get("timingScope") != SERVICE_TIMING_SCOPE
                or (first is not None and (not valid_number(first) or first > elapsed))):
            raise OllamaError("MiLMMT v4.1 terminal result does not match the source, stream, model or decode contract")

    def translate(
        self, source_text_en: str, context: dict[str, Any] | None = None,
        on_partial: Callable[[str, str], None] | None = None,
    ) -> dict[str, Any]:
        _source_and_context(source_text_en, context)
        started = time.monotonic()
        deadline = started + self.translation_timeout
        health = self._health(deadline)
        if health["status"] != "ready":
            raise OllamaError("MiLMMT v4.1 model is not ready; recording should continue")
        if health["busy"]:
            raise OllamaError("MiLMMT v4.1 model is busy; recording should continue")
        total, done = "", None
        events = self._events({"text": source_text_en, "stream": True}, deadline)
        try:
            for event in events:
                if done is not None:
                    raise OllamaError("MiLMMT v4.1 stream contained data after its terminal result")
                kind = event.get("type")
                if kind == "error":
                    code = event.get("status")
                    detail = f" ({code})" if type(code) is int and 400 <= code <= 599 else ""
                    raise OllamaError("MiLMMT v4.1 runtime rejected or interrupted translation" + detail)
                if kind == "delta":
                    delta = event.get("text")
                    if not isinstance(delta, str) or not delta:
                        raise OllamaError("MiLMMT v4.1 returned an invalid text delta")
                    try:
                        delta.encode("utf-8")
                    except UnicodeError:
                        raise OllamaError("MiLMMT v4.1 returned invalid Unicode text") from None
                    total += delta
                    if on_partial is not None:
                        try:
                            on_partial(delta, total)
                        except Exception:
                            raise OllamaError("MiLMMT v4.1 partial delivery failed") from None
                elif kind == "done":
                    self._validate_done(event, source_text_en, total)
                    done = event
                else:
                    raise OllamaError("MiLMMT v4.1 returned an unknown stream event")
        finally:
            events.close()
        if done is None:
            raise OllamaError("MiLMMT v4.1 stream ended without a complete terminal result")
        return {
            "targetTextZh": total, "model": MODEL_ID, "promptVersion": MILMMT_A0_PROMPT_VERSION,
            "translationProvider": PROVIDER_ID, "experimental": True, "releaseEligible": False,
            "modelSha256": WEIGHTS_SHA, "packageSha256": MANIFEST_SHA,
            "generatedTokenIdsSha256": done["generatedTokenIdsSha256"],
            "decodeContract": json.loads(json.dumps(DECODE_CONTRACT)),
            "metrics": {"promptEvalCount": done["promptTokens"], "evalCount": done["generatedTokens"],
                        "generatedTokenCountIncludesEos": True,
                        "mlxWorkerElapsedMs": done["elapsedMs"], "firstChineseMs": done.get("firstChineseMs"),
                        "clientElapsedMs": (time.monotonic() - started) * 1000,
                        "timingScope": SERVICE_TIMING_SCOPE,
                        "clientTimingScope": "health validation and complete local HTTP stream receipt, including callbacks",
                        "durationSemantics": "MLX wall time; no Ollama load/prompt-eval/decode duration is claimed"},
        }

    def start_runtime(self) -> dict[str, Any]:
        before = self.status()
        if before["ready"]:
            return before  # Existing same-package service remains untouched.
        if not self.start_supported:
            raise OllamaError("MiLMMT v4.1 fixed local launcher or MLX Python is unavailable for this endpoint")
        command = [str(self.python_path), str(self.runtime_script), "start", "--port", "18771",
                   "--model", str(self.model_path), "--state-dir", str(self.state_dir)]
        try:
            process = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, timeout=100, check=False)
        except subprocess.TimeoutExpired:
            after = self.status()
            if after["ready"]:
                return after
            raise OllamaError("MiLMMT v4.1 startup wait timed out; check local runtime status") from None
        except OSError:
            raise OllamaError("MiLMMT v4.1 fixed local launcher could not be executed") from None
        after = self.status()
        if not after["ready"]:
            raise OllamaError("MiLMMT v4.1 local launcher failed; existing services were not stopped"
                              if process.returncode else "MiLMMT v4.1 launcher returned before the verified model was ready")
        return after
