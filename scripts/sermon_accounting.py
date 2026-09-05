"""Append-only, process-safe workflow timing and provider usage receipts.

No prompts, credentials or exception bodies are persisted. Costs are list-price
estimates, never invoices. A missing receipt is unknown, not free usage.
"""
from __future__ import annotations

import argparse
import contextvars
import csv
import fcntl
import hashlib
import json
import os
import platform
import re
import resource
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "sermon-workflow-accounting-v2"
PRICE_SOURCE = "https://developers.openai.com/api/docs/pricing"
PRICE_DATE = "2026-09-05"
_stage = contextvars.ContextVar("sermon_accounting_stage", default=None)
_span = contextvars.ContextVar("sermon_accounting_span", default=None)
_identity = contextvars.ContextVar("sermon_accounting_identity", default=None)
_workflow = contextvars.ContextVar("sermon_accounting_workflow", default=None)
ENV_KEYS = ("SERMON_ACCOUNTING_DIR", "SERMON_ACCOUNTING_RUN_ID", "SERMON_ACCOUNTING_STAGE", "SERMON_ACCOUNTING_SPAN")
WORKFLOW_ENV = "SERMON_ACCOUNTING_WORKFLOW_ID"


class AccountingWriteError(OSError):
    """A ledger failure must never trigger a fresh paid model request."""


def _label(value, default="unknown"):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", value) else default


def _safe_metadata(data):
    data = data if isinstance(data, dict) else {}
    safe = {}
    for key, value in data.items():
        if key in {"sunday", "week", "sourceServiceDate"} and isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            safe[key] = value
        elif key in {"sourceId", "videoId"} and isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            safe[key] = value
        elif key in {"jobSha256", "sourceSha256", "videoSha256", "sourceVideoSha256", "sourceAudioSha256"} and isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
            safe[key] = value
        elif key == "mode" and isinstance(value, str) and value in {"shadow", "execute", "inspect", "dry_run"}:
            safe[key] = value
    return safe


def _safe_settings(data):
    data = data if isinstance(data, dict) else {}
    safe = {}
    for key, value in data.items():
        if key in {"reasoning_effort", "service_tier"} and isinstance(value, str) and value in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "auto", "default", "standard", "priority", "fast", "batch", "flex"}:
            safe[key] = value
        elif key in {"temperature", "max_tokens", "max_completion_tokens", "max_output_tokens"} and _number(value) is not None:
            safe[key] = value
        elif key == "requestPayloadSha256" and isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
            safe[key] = value
    return safe


def error_location(exc):
    """Code location only: never exception messages, source lines or locals."""
    root = Path(__file__).resolve().parents[1]
    frames = []
    for frame, lineno in traceback.walk_tb(exc.__traceback__):
        try:
            relative = Path(frame.f_code.co_filename).resolve().relative_to(root)
        except (OSError, ValueError):
            continue
        if relative.parts[0] not in {"scripts", "backend", "experiments", "tests"}:
            continue
        frames.append({"file": str(relative), "line": lineno, "function": _label(frame.f_code.co_name)})
    return {"errorType": _label(type(exc).__name__), "frames": frames[-12:]}


def record_log(code, *, level="INFO", fields=None, exception=None):
    """Write a fixed event code with typed metadata, never free-form messages."""
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("invalid_log_level")
    safe = {}
    for key, value in (fields or {}).items():
        if key in {"exitCode", "count", "attempt", "httpStatus", "elapsedSeconds"} and _number(value) is not None:
            safe[key] = value
        elif key == "cacheHit" and isinstance(value, bool):
            safe[key] = value
        elif key in {"status", "reasonCode"} and isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", value):
            safe[key] = value
    event = {"event": "log", "code": _label(code), "level": level, "fields": safe}
    if exception is not None:
        event["error"] = error_location(exception)
    _emit(event)


def _finalize(action, original_error):
    try:
        return action()
    except Exception as exc:
        # Do not hide a failed write or replace the original business failure.
        print("SERMON_LOGGING_WRITE_FAILED errorType=" + _label(type(exc).__name__), file=sys.stderr)
        if original_error is None:
            raise
        original_error.sermon_logging_failed = True


def _private_open(path, flags):
    return os.open(path, flags, 0o600)


def execution_identity():
    root = Path(__file__).resolve().parents[1]
    def git(*args):
        try:
            return subprocess.run(["git", "--no-optional-locks", "-C", str(root), *args], capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired, TypeError):
            return None
    head, dirty = git("rev-parse", "HEAD"), git("status", "--porcelain", "--untracked-files=no")
    modules = {}
    for module in list(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if not name: continue
        try:
            path = Path(name).resolve()
            relative = path.relative_to(root)
            if relative.parts[0] not in {"scripts", "backend", "experiments"} or path.suffix != ".py": continue
            modules[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
        except (ValueError, OSError):
            continue
    commit = head.stdout.strip() if head and head.returncode == 0 and isinstance(head.stdout, str) else None
    return {"gitCommit": commit if commit and re.fullmatch(r"[0-9a-f]{40,64}", commit) else None,
            "trackedWorkingTreeDirty": bool(dirty.stdout) if dirty and dirty.returncode == 0 and isinstance(dirty.stdout, str) else None,
            "loadedProjectCodeSha256": modules, "pythonVersion": platform.python_version(),
            "platform": sys.platform, "architecture": platform.machine(),
            "scope": "Loaded project Python modules at workflow start; unimported modules and remote code require their own receipts."}


def resource_snapshot(directory):
    own, children = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        free = shutil.disk_usage(directory).free
    except OSError:
        free = None
    return {"processPeakRssBytes": int(own.ru_maxrss * (1 if sys.platform == "darwin" else 1024)),
            "processUserCpuSeconds": own.ru_utime, "processSystemCpuSeconds": own.ru_stime,
            "finishedChildUserCpuSeconds": children.ru_utime, "finishedChildSystemCpuSeconds": children.ru_stime,
            "diskFreeBytes": free, "gpuPeakBytes": None,
            "scope": "Process-lifetime RSS high-water mark and CPU counters; child CPU includes finished children only. GPU allocation not exposed by this local collector."}


def record_workload(name, metrics):
    safe = {}
    for key, value in metrics.items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", key): continue
        if value is None or isinstance(value, bool) or _number(value) is not None:
            safe[key] = value
        elif isinstance(value, str) and key.endswith("Sha256") and re.fullmatch(r"[0-9a-f]{64}", value):
            safe[key] = value
        elif key in {"timingScope", "evidenceScope", "countStatus"} and value in {
            "after_model_load", "existing_report", "current_execution", "verified_receipts", "unknown", "partial"}:
            safe[key] = value
    _emit({"event": "workload", "stage": _label(name), "metrics": safe})


def request_metadata(payload):
    """Only selected request settings and a digest; never include prompt text."""
    allowed = {k: payload[k] for k in ("reasoning_effort", "service_tier", "temperature", "max_tokens", "max_completion_tokens", "max_output_tokens") if k in payload and isinstance(payload[k], (str, int, float, bool))}
    reasoning = payload.get("reasoning")
    if isinstance(reasoning, dict) and isinstance(reasoning.get("effort"), str): allowed["reasoning_effort"] = reasoning["effort"]
    allowed["requestPayloadSha256"] = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return _safe_settings(allowed)


def now():
    return datetime.now(timezone.utc).isoformat()


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 and value < float("inf") else None


def normalize_usage(usage):
    usage = usage if isinstance(usage, dict) else {}
    inp = usage.get("input_tokens_details", usage.get("prompt_tokens_details")) or {}
    out = usage.get("output_tokens_details", usage.get("completion_tokens_details")) or {}
    inp = inp if isinstance(inp, dict) else {}
    out = out if isinstance(out, dict) else {}
    return {
        "inputTokens": _number(usage.get("input_tokens", usage.get("prompt_tokens"))),
        "outputTokens": _number(usage.get("output_tokens", usage.get("completion_tokens"))),
        "cachedInputTokens": _number(inp.get("cached_tokens")),
        "cacheWriteTokens": _number(inp.get("cache_write_tokens")),
        "reasoningTokens": _number(out.get("reasoning_tokens")),
        "totalTokens": _number(usage.get("total_tokens")),
        "audioSeconds": _number(usage.get("seconds")),
    }


def estimate_cost(model, usage, service_tier="default", audio_seconds=None):
    """Freeze verified direct-OpenAI rates; unknown models/details stay unknown."""
    u = normalize_usage(usage)
    base = {"currency": "USD", "status": "unknown", "estimatedUsd": None,
            "priceSource": PRICE_SOURCE, "priceVerifiedAt": PRICE_DATE,
            "invoiceVerified": False, "serviceTier": service_tier}
    if model == "gpt-transcribe":
        seconds = u["audioSeconds"] if u["audioSeconds"] is not None else audio_seconds
        if _number(seconds) is None:
            return {**base, "reason": "audio_duration_missing"}
        return {**base, "status": "estimated", "estimatedUsd": round(seconds / 60 * .0045, 9),
                "audioSeconds": seconds, "usdPerMinute": .0045}
    match = re.fullmatch(r"(gpt-6-astra|gpt-5\.6-sol|gpt-5\.6-terra|gpt-5\.6-luna)(?:-\d{4}-\d{2}-\d{2})?", model or "")
    if not match:
        return {**base, "reason": "model_price_unverified"}
    if any(u[k] is None for k in ("inputTokens", "outputTokens", "cachedInputTokens", "cacheWriteTokens")):
        return {**base, "reason": "usage_or_cache_details_missing"}
    i, o, c, w = (u[k] for k in ("inputTokens", "outputTokens", "cachedInputTokens", "cacheWriteTokens"))
    if c + w > i:
        return {**base, "reason": "inconsistent_usage"}
    multiplier = {"default": 1, "standard": 1, "priority": 2, "fast": 2, "batch": .5, "flex": .5}.get(service_tier)
    if multiplier is None:
        return {**base, "reason": "service_tier_unverified"}
    input_rate, output_rate = {"gpt-6-astra": (10, 50), "gpt-5.6-sol": (4, 20),
                               "gpt-5.6-terra": (2, 12), "gpt-5.6-luna": (.2, 1.2)}[match[1]]
    # Only Astra's long-context threshold has been verified in this snapshot.
    if i > 272000 and match[1] != "gpt-6-astra":
        return {**base, "reason": "long_context_threshold_unverified"}
    long = i > 272000
    input_rate *= multiplier * (2 if long else 1)
    output_rate *= multiplier * (1.5 if long else 1)
    cost = ((i-c-w) * input_rate + c * input_rate * .1 + w * input_rate * 1.25 + o * output_rate) / 1_000_000
    return {**base, "status": "estimated", "estimatedUsd": round(cost, 9),
            "contextTier": "long" if long else "short", "ratesPerMillion": {
                "input": input_rate, "cachedInput": input_rate*.1,
                "cacheWrite": input_rate*1.25, "output": output_rate},
            "reasoningIncludedInOutput": True}


def _emit(event):
    try:
        return _write_event(event)
    except Exception as exc:
        raise AccountingWriteError("structured_logging_write_failed") from exc


def _write_event(event):
    directory, run_id = _identity.get() or tuple(os.environ.get(k) for k in ENV_KEYS[:2])
    if not directory or not run_id:
        return
    path = Path(directory) / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {"schemaVersion": SCHEMA, "eventId": uuid.uuid4().hex,
               "runId": run_id, "recordedAt": now(), "pid": os.getpid(),
               "threadId": threading.get_ident(),
               "workflowId": _workflow.get() or os.environ.get(WORKFLOW_ENV),
               "stage": _stage.get() or os.environ.get(ENV_KEYS[2]),
               "spanId": _span.get() or os.environ.get(ENV_KEYS[3]), **event}
    with open(path, "a+b", opener=_private_open) as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        # Preserve a killed writer's partial bytes, but never concatenate the
        # next valid event onto its damaged line. The summary reports the gap.
        stream.seek(0, os.SEEK_END)
        if stream.tell():
            stream.seek(-1, os.SEEK_END)
            if stream.read(1) != b"\n":
                stream.write(b"\n")
        stream.write((json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def stage(name, *, cache_hit=False, billing="local"):
    name = _label(name)
    span_id = uuid.uuid4().hex
    parent = _span.get() or os.environ.get("SERMON_ACCOUNTING_SPAN")
    base = {"stage": name, "spanId": span_id, "parentSpanId": parent,
            "cacheHit": bool(cache_hit), "billing": billing}
    started = time.monotonic()
    _emit({**base, "event": "stage_started", "startedAt": now()})
    tokens = (_stage.set(name), _span.set(span_id))
    old = {k: os.environ.get(k) for k in ENV_KEYS[2:]}
    main_thread = threading.current_thread() is threading.main_thread()
    if main_thread:
        os.environ.update(SERMON_ACCOUNTING_STAGE=name, SERMON_ACCOUNTING_SPAN=span_id)
    outcome = "completed"
    error = None
    try:
        yield
    except BaseException as exc:
        outcome, error = "failed", exc
        raise
    finally:
        try:
            _finalize(lambda: _emit({**base, "event": "stage_finished", "status": outcome,
                "level": "ERROR" if error else "INFO",
                "elapsedSeconds": round(time.monotonic()-started, 6),
                "errorType": _label(type(error).__name__) if error else None,
                "error": error_location(error) if error else None}), error)
        finally:
            _stage.reset(tokens[0]); _span.reset(tokens[1])
            if main_thread:
                for k, val in old.items():
                    if val is None: os.environ.pop(k, None)
                    else: os.environ[k] = val


@contextmanager
def accounting_session(directory, workflow, metadata=None, *, evidence_directory=None):
    evidence_directory = Path(evidence_directory).absolute() if evidence_directory is not None else Path(directory).absolute().parent
    workflow = _label(workflow)
    metadata = _safe_metadata(metadata)
    workflow_id = uuid.uuid4().hex
    parent_workflow = _workflow.get() or os.environ.get(WORKFLOW_ENV)
    identity = _identity.get() or tuple(os.environ.get(k) for k in ENV_KEYS[:2])
    inherited = bool(all(identity))
    if not inherited:
        identity = (str(Path(directory).absolute()), uuid.uuid4().hex)
    directory = Path(identity[0])
    old = {k: os.environ.get(k) for k in (*ENV_KEYS, WORKFLOW_ENV)}
    main_thread = threading.current_thread() is threading.main_thread()
    tokens = (_identity.set(identity), _workflow.set(workflow_id))
    session = {"runId": identity[1], "workflowId": workflow_id, "directory": str(directory),
               "events": str(directory / "events.jsonl"), "summary": str(directory / "summary.json")}
    original_error = None
    began = False
    try:
        if main_thread:
            os.environ.update(SERMON_ACCOUNTING_DIR=identity[0], SERMON_ACCOUNTING_RUN_ID=identity[1])
            os.environ[WORKFLOW_ENV] = workflow_id
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not inherited:
            _emit({"event": "run_started", "workflow": workflow, "metadata": metadata})
        began = True
        _emit({"event": "workflow_started", "workflow": workflow, "parentWorkflowId": parent_workflow,
               "metadata": metadata, "executionIdentity": execution_identity(), "resources": resource_snapshot(directory)})
        _emit({"event": "workflow_evidence", "workflow": workflow, "phase": "before",
               "evidence": _workflow_evidence(evidence_directory, workflow)})
        with stage(workflow, billing="orchestrator"):
            yield session
    except BaseException as exc:
        original_error = exc
        raise
    finally:
        try:
            if began:
                outcome = "failed" if original_error else "completed"
                def finish():
                    _emit({"event": "workflow_evidence", "workflow": workflow, "phase": "after",
                           "evidence": _workflow_evidence(evidence_directory, workflow)})
                    _emit({"event": "workflow_finished", "workflow": workflow, "status": outcome,
                           "resources": resource_snapshot(directory)})
                    if not inherited:
                        _emit({"event": "run_finished", "workflow": workflow, "status": outcome})
                        summarize(directory)
                _finalize(finish, original_error)
        finally:
            _identity.reset(tokens[0]); _workflow.reset(tokens[1])
            if main_thread:
                for key, value in old.items():
                    if value is None: os.environ.pop(key, None)
                    else: os.environ[key] = value


def _workflow_evidence(directory, workflow):
    try:
        from scripts.sermon_workflow_evidence import collect_workflow_evidence
        return collect_workflow_evidence(directory, workflow)
    except Exception as exc:
        return {"status": "unavailable", "errorType": type(exc).__name__, "currentRunExecutionProven": False}


def record_api_started(model, settings=None):
    attempt_id = uuid.uuid4().hex
    _emit({"event": "api_attempt_started", "attemptId": attempt_id, "model": _label(model), "settings": _safe_settings(settings),
           "stage": _stage.get() or os.environ.get(ENV_KEYS[2], "unattributed_api"),
           "spanId": _span.get() or os.environ.get(ENV_KEYS[3])})
    return attempt_id


def record_api_attempt(model, response, elapsed_seconds, status="completed", error_type=None, *, audio_seconds=None, attempt_id=None, http_status=None):
    response = response if isinstance(response, dict) else {}
    usage = response.get("usage")
    actual_model = _label(response.get("model") or model)
    tier = _safe_settings({"service_tier": response.get("service_tier") or "default"}).get("service_tier", "unknown")
    cost = estimate_cost(actual_model, usage, tier, audio_seconds) if status == "completed" else {
        "status": "unknown", "estimatedUsd": None, "currency": "USD", "reason": "failed_attempt_billing_unknown"}
    _emit({"event": "api_attempt", "attemptId": attempt_id or uuid.uuid4().hex,
           "stage": _stage.get() or os.environ.get(ENV_KEYS[2], "unattributed_api"),
           "spanId": _span.get() or os.environ.get(ENV_KEYS[3]),
           "status": _label(status), "errorType": _label(error_type) if error_type else None,
           "httpStatus": _number(http_status), "elapsedSeconds": _number(elapsed_seconds),
           "requestedModel": _label(model), "model": actual_model, "responseId": _label(response.get("id"), None),
           "usage": normalize_usage(usage), "cost": cost})


@contextmanager
def sdk_invocation(model):
    """Record SDK-reported aggregate usage without inventing HTTP receipts."""
    invocation_id = uuid.uuid4().hex
    base = {"invocationId": invocation_id, "model": _label(model),
            "measurementScope": "sdk_aggregate_including_tools",
            "estimatedUsd": None, "costStatus": "unknown",
            "costReason": "sdk_aggregate_not_provider_receipts",
            "httpAttemptsKnown": False}
    receipt = {}
    started = time.monotonic()
    original_error = None
    _emit({**base, "event": "sdk_call_started"})
    try:
        yield receipt
    except BaseException as exc:
        original_error = exc
        raise
    finally:
        usage = receipt.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        safe = {key: _number(usage.get(key)) for key in ("requests", "input_tokens", "output_tokens", "total_tokens")}
        _finalize(lambda: _emit({**base, "event": "sdk_call_finished", "usage": safe,
            "status": "failed" if original_error else "completed",
            "level": "ERROR" if original_error else "INFO",
            "elapsedSeconds": round(time.monotonic() - started, 6),
            "error": error_location(original_error) if original_error else None}), original_error)


def summarize(directory):
    directory = Path(directory)
    # Serialize snapshot + both outputs, preventing an old snapshot replacing a new one.
    with open(directory / ".summary.lock", "a", opener=_private_open) as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return _summarize_locked(directory)


def _percentile(values, fraction):
    if not values: return None
    values = sorted(values)
    index = (len(values)-1) * fraction
    lo = int(index)
    hi = min(lo+1, len(values)-1)
    return round(values[lo] + (values[hi]-values[lo]) * (index-lo), 6)


def _valid_event(value):
    if not isinstance(value, dict) or any(not isinstance(value.get(k), str) or not value[k] for k in ("event", "eventId", "runId", "recordedAt")):
        return False
    if datetime.fromisoformat(value["recordedAt"]).tzinfo is None:
        return False
    required = {
        "run_started": {"workflow": str}, "run_finished": {"workflow": str, "status": str},
        "workflow_started": {"workflow": str},
        "workflow_finished": {"workflow": str, "status": str},
        "workflow_evidence": {"phase": str, "evidence": dict},
        "stage_started": {"stage": str, "spanId": str, "startedAt": str},
        "stage_finished": {"stage": str, "spanId": str, "status": str, "cacheHit": bool, "billing": str},
        "api_attempt_started": {"attemptId": str, "stage": str},
        "api_attempt": {"stage": str, "status": str, "usage": dict, "cost": dict},
        "workload": {"stage": str, "metrics": dict},
        "log": {"code": str, "level": str, "fields": dict},
        "sdk_call_started": {"invocationId": str, "model": str},
        "sdk_call_finished": {"invocationId": str, "model": str, "status": str, "usage": dict},
    }.get(value["event"])
    if required is None or any(not isinstance(value.get(k), kind) for k, kind in required.items()):
        return False
    for key in ("workflowId", "spanId", "attemptId", "responseId", "invocationId"):
        if value.get(key) is not None and not isinstance(value[key], str):
            return False
    if value["event"] == "stage_finished" and _number(value.get("elapsedSeconds")) is None:
        return False
    if value["event"] == "api_attempt":
        usage = value["usage"]
        for key in ("inputTokens", "outputTokens", "cachedInputTokens", "cacheWriteTokens", "reasoningTokens"):
            if key not in usage or (usage[key] is not None and _number(usage[key]) is None): return False
        for number in (value.get("elapsedSeconds"), value["cost"].get("estimatedUsd")):
            if number is not None and _number(number) is None: return False
    return True


def read_events(directory):
    """Read a locked snapshot without changing the ledger or its projections."""
    events, damaged = [], []
    with (Path(directory) / "events.jsonl").open("rb") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
        for index, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                if not _valid_event(value):
                    raise ValueError("invalid_event_identity")
            except (ValueError, UnicodeError):
                damaged.append({"line": index, "bytes": len(line), "sha256": hashlib.sha256(line).hexdigest(),
                                "reason": "invalid_or_incomplete_event", "runAttribution": "unknown"})
                continue
            events.append(value)
    return events, damaged


def diagnostic_event(event):
    """A small, terminal-safe view; no legacy free-text fields are forwarded."""
    result = {key: _label(event.get(key), None) for key in
              ("runId", "workflowId", "stage", "spanId", "attemptId", "invocationId", "status")}
    result.update(recordedAt=event["recordedAt"], event=_label(event["event"]),
                  code=_label(event.get("code") or event["event"]),
                  level=event.get("level") if event.get("level") in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else
                  ("ERROR" if event.get("status") == "failed" else "INFO"))
    for key in ("elapsedSeconds", "httpStatus"):
        if _number(event.get(key)) is not None: result[key] = event[key]
    if event.get("cacheHit") is True: result["cacheHit"] = True
    if event.get("errorType"): result["errorType"] = _label(event["errorType"])
    fields = event.get("fields")
    if isinstance(fields, dict):
        for key in ("status", "reasonCode"):
            if key in fields: result[key] = _label(fields[key])
        if _number(fields.get("exitCode")) is not None: result["exitCode"] = fields["exitCode"]
    error = event.get("error")
    if isinstance(error, dict):
        result["errorType"] = _label(error.get("errorType"))
        frames = error.get("frames")
        if isinstance(frames, list):
            safe = []
            for frame in frames[-12:]:
                if not isinstance(frame, dict): continue
                path = frame.get("file")
                if not isinstance(path, str) or not re.fullmatch(r"(?:scripts|backend|experiments|tests)/[A-Za-z0-9_./-]+\.py", path) or ".." in Path(path).parts: continue
                if not isinstance(frame.get("line"), int) or frame["line"] < 1: continue
                safe.append({"file": path, "line": frame["line"], "function": _label(frame.get("function"))})
            result["frames"] = safe
    return result


def format_diagnostic(event):
    parts = [event["recordedAt"], event["level"], "run=" + (event.get("runId") or "?"), event["code"]]
    for key in ("workflowId", "stage", "spanId", "attemptId", "invocationId", "status", "exitCode", "httpStatus", "elapsedSeconds", "cacheHit", "errorType", "reasonCode"):
        if event.get(key) is not None: parts.append(f"{key}={event[key]}")
    if event.get("frames"):
        last = event["frames"][-1]
        parts.append(f"at={last['file']}:{last['line']}")
    return " ".join(parts)


def _summarize_locked(directory):
    events, damaged = read_events(directory)
    completed_attempts = {e.get("attemptId") for e in events if e["event"] == "api_attempt"}
    unfinished_api = [e for e in events if e["event"] == "api_attempt_started" and e["attemptId"] not in completed_attempts]
    # A process can disappear after sending a billable request. Preserve uncertainty.
    events.extend({**e, "event": "api_attempt", "status": "interrupted_or_running",
                   "elapsedSeconds": None, "usage": normalize_usage(None),
                   "cost": {"estimatedUsd": None, "status": "unknown"}}
                  for e in unfinished_api)
    runs, groups, seen = {}, {}, set()
    latencies, workflows = {}, {}
    sdk_calls = {}
    token_fields = ("inputTokens", "outputTokens", "cachedInputTokens", "cacheWriteTokens", "reasoningTokens")
    started_spans = {e["spanId"]: e for e in events if e["event"] == "stage_started"}
    ended_spans = {e["spanId"] for e in events if e["event"] == "stage_finished"}
    for event in events:
        rid = event["runId"]
        run = runs.setdefault(rid, {"runId": rid, "status": "interrupted_or_running"})
        if event["event"] == "run_started":
            run.update(workflow=event["workflow"], startedAt=event["recordedAt"], metadata=event.get("metadata", {}))
        elif event["event"] == "run_finished":
            run.update(status=event["status"], completedAt=event["recordedAt"])
            if run.get("startedAt"):
                run["wallSeconds"] = (datetime.fromisoformat(event["recordedAt"])-datetime.fromisoformat(run["startedAt"])).total_seconds()
        elif event["event"] == "workflow_started":
            wid = event.get("workflowId", event["eventId"])
            workflows[wid] = {"workflowId": wid, "runId": rid, "workflow": event["workflow"],
                "parentWorkflowId": event.get("parentWorkflowId"),
                "status": "interrupted_or_running", "startedAt": event["recordedAt"], "completedAt": None,
                "metadata": event.get("metadata", {}), "executionIdentity": event.get("executionIdentity"),
                "resourcesBefore": event.get("resources"), "resourcesAfter": None,
                "evidenceBefore": None, "evidenceAfter": None}
        elif event["event"] in {"workflow_finished", "workflow_evidence"} and event.get("workflowId") in workflows:
            w = workflows[event["workflowId"]]
            if event["event"] == "workflow_finished":
                w["resourcesAfter"] = event.get("resources")
                w["status"] = event["status"]
                w["completedAt"] = event["recordedAt"]
            else:
                w["evidenceBefore" if event["phase"] == "before" else "evidenceAfter"] = event["evidence"]
        elif event["event"] == "workload":
            run.setdefault("workloads", []).append({"stage": event["stage"], "metrics": event["metrics"]})
        elif event["event"] in {"sdk_call_started", "sdk_call_finished"}:
            key = (rid, event["invocationId"])
            call = sdk_calls.setdefault(key, {"runId": rid, "invocationId": event["invocationId"],
                "model": _label(event["model"]), "status": "interrupted_or_running", "elapsedSeconds": None,
                "usage": {key: None for key in ("requests", "input_tokens", "output_tokens", "total_tokens")},
                "measurementScope": "sdk_aggregate_including_tools", "estimatedUsd": None,
                "costStatus": "unknown", "httpAttemptsKnown": False})
            if event["event"] == "sdk_call_finished":
                call.update(status=_label(event["status"]), elapsedSeconds=_number(event.get("elapsedSeconds")),
                            usage={key: _number(event["usage"].get(key)) for key in call["usage"]})
        if diagnostic_event(event)["level"] in {"WARNING", "ERROR", "CRITICAL"}:
            run.setdefault("diagnostics", []).append(diagnostic_event(event))
        if event["event"] not in {"stage_finished", "api_attempt"}: continue
        key = (rid, event["stage"])
        row = groups.setdefault(key, {"runId": rid, "stage": event["stage"], "stageAttempts": 0,
            "failedStages": 0, "cacheHits": 0, "elapsedSeconds": 0.0, "apiAttempts": 0,
            "inputTokens": 0, "outputTokens": 0, "cachedInputTokens": 0, "cacheWriteTokens": 0,
            "reasoningTokens": 0, "usageMissingAttempts": 0, "knownEstimatedUsd": 0.0,
            "unknownCostAttempts": 0, "billing": event.get("billing", "api"),
            "apiLatencySeconds": 0.0, "missingLatencyAttempts": 0,
            "unfinishedStageAttempts": 0, "usageReceipts": 0, "completedApiAttempts": 0,
            "failedApiAttempts": 0, "missingTokenFields": {k: 0 for k in token_fields}})
        if event["event"] == "stage_finished":
            row["stageAttempts"] += 1; row["elapsedSeconds"] += event["elapsedSeconds"]
            row["cacheHits"] += int(event["cacheHit"]); row["failedStages"] += int(event["status"] == "failed")
            row["billing"] = event["billing"]
        else:
            # Duplicate imports of the same provider response are not new spend.
            identity = event.get("responseId") or event.get("attemptId") or event["eventId"]
            if identity in seen: continue
            seen.add(identity); row["apiAttempts"] += 1
            row["completedApiAttempts"] += int(event["status"] == "completed")
            row["failedApiAttempts"] += int(event["status"] == "failed")
            row["missingLatencyAttempts"] += int(event.get("elapsedSeconds") is None)
            row["apiLatencySeconds"] += event.get("elapsedSeconds") or 0
            if event.get("elapsedSeconds") is not None:
                latencies.setdefault(key, []).append(event["elapsedSeconds"])
            u = event["usage"]
            row["usageReceipts"] += int((u["inputTokens"] is not None and u["outputTokens"] is not None) or u.get("audioSeconds") is not None)
            row["usageMissingAttempts"] += int(u["inputTokens"] is None or u["outputTokens"] is None)
            for k in token_fields:
                row["missingTokenFields"][k] += int(u[k] is None)
                row[k] += u[k] or 0
            cost = event["cost"].get("estimatedUsd")
            if cost is None: row["unknownCostAttempts"] += 1
            else: row["knownEstimatedUsd"] += cost
    for row in groups.values():
        row["unfinishedStageAttempts"] = sum(1 for sid, e in started_spans.items()
            if sid not in ended_spans and e["runId"] == row["runId"] and e["stage"] == row["stage"])
        row["elapsedSeconds"] = round(row["elapsedSeconds"], 6)
        row["apiLatencySeconds"] = round(row["apiLatencySeconds"], 6)
        row["elapsedStatus"] = "known_subtotal" if row["unfinishedStageAttempts"] else "measured"
        if not row["stageAttempts"]:
            row["elapsedSeconds"] = None
            row["elapsedStatus"] = "not_recorded"
        if not row["apiAttempts"] or row["missingLatencyAttempts"] == row["apiAttempts"]:
            row["apiLatencySeconds"] = None
        row["knownEstimatedUsd"] = round(row["knownEstimatedUsd"], 9)
        row["tokenStatus"] = "known_subtotal" if row["apiAttempts"] else ("not_applicable" if row["billing"] == "local" or row["cacheHits"] else "not_recorded")
        for k in token_fields:
            if not row["apiAttempts"] or row["missingTokenFields"][k] == row["apiAttempts"]:
                row[k] = None
        row["costStatus"] = "partial" if row["unknownCostAttempts"] else ("estimated_api_only" if row["apiAttempts"] else "no_api_receipts")
        samples = latencies.get((row["runId"], row["stage"]), [])
        row["apiLatencySampleCount"] = len(samples)
        row["apiLatencyP50Seconds"] = _percentile(samples, .5)
        row["apiLatencyP95Seconds"] = _percentile(samples, .95)
        row["usageReceiptCoverage"] = row["usageReceipts"] / row["apiAttempts"] if row["apiAttempts"] else None
    for rid, run in runs.items():
        rows = [r for r in groups.values() if r["runId"] == rid]
        run["knownEstimatedUsd"] = round(sum(r["knownEstimatedUsd"] for r in rows), 9)
        run["unknownCostAttempts"] = sum(r["unknownCostAttempts"] for r in rows)
        run["apiAttempts"] = sum(r["apiAttempts"] for r in rows)
        run["usageReceipts"] = sum(r["usageReceipts"] for r in rows)
        run["usageReceiptCoverage"] = run["usageReceipts"] / run["apiAttempts"] if run["apiAttempts"] else None
        run["completedApiAttempts"] = sum(r["completedApiAttempts"] for r in rows)
        run["failedApiAttempts"] = sum(r["failedApiAttempts"] for r in rows)
        run["workflows"] = [w for w in workflows.values() if w["runId"] == rid]
        run["sdkCalls"] = [call for (run_id, _), call in sdk_calls.items() if run_id == rid]
        run["unpricedSdkInvocations"] = len(run["sdkCalls"])
        run["overallCostStatus"] = "partial" if run["unknownCostAttempts"] or run["sdkCalls"] or damaged else "recorded_api_only"
    result = {"schemaVersion": SCHEMA, "generatedAt": now(), "runs": list(runs.values()), "stages": list(groups.values()),
              "ledgerIntegrity": {"status": "incomplete_corrupt_events" if damaged else "readable",
                                  "damagedEvents": damaged, "unattributedCostUnknown": bool(damaged),
                                  "originalBytesPreserved": True},
              "unfinishedApiAttempts": [{"runId": e["runId"], "stage": e["stage"], "attemptId": e["attemptId"],
                                         "startedAt": e["recordedAt"], "costStatus": "unknown"} for e in unfinished_api],
              "unfinishedStages": [{"runId": e["runId"], "stage": e["stage"], "spanId": sid,
                                    "startedAt": e["startedAt"], "elapsedSeconds": None}
                                   for sid, e in started_spans.items() if sid not in ended_spans],
              "notes": ["Parent and child elapsed times overlap: do not sum all stages as wall time.",
                        "Known USD is an API list-price estimate, not an invoice or complete project cost.",
                        "Local compute, storage, network and in-conversation Codex costs are not allocated.",
                        "Missing usage/cost remains unknown; caches do not re-bill old responses."]}
    temp = directory / (".summary-" + uuid.uuid4().hex + ".json")
    with open(temp, "w", opener=_private_open) as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    temp.replace(directory / "summary.json")
    csv_temp = directory / (".stages-" + uuid.uuid4().hex + ".csv")
    with open(csv_temp, "w", newline="", encoding="utf-8-sig", opener=_private_open) as stream:
        if result["stages"]:
            writer = csv.DictWriter(stream, fieldnames=list(result["stages"][0]))
            writer.writeheader(); writer.writerows(result["stages"])
    csv_temp.replace(directory / "stages.csv")
    log_temp = directory / (".operations-" + uuid.uuid4().hex + ".log")
    with open(log_temp, "w", opener=_private_open) as stream:
        for event in events:
            stream.write(format_diagnostic(diagnostic_event(event)) + "\n")
    log_temp.replace(directory / "operations.log")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = summarize(args.directory)
    print(json.dumps({"runs": len(result["runs"]), "stages": len(result["stages"]), "summary": str(args.directory / "summary.json")}))
