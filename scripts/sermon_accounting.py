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
import marshal
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
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from scripts.sermon_clock_evidence import clock_domain
    from scripts import sermon_dispatch_observation as dispatch_observation
    from scripts import sermon_log_profile as log_profile
except ImportError:  # Preserve direct script invocation.
    from sermon_clock_evidence import clock_domain
    import sermon_dispatch_observation as dispatch_observation
    import sermon_log_profile as log_profile

SCHEMA = "sermon-workflow-accounting-v3"
READABLE_SCHEMAS = frozenset({"sermon-workflow-accounting-v1", "sermon-workflow-accounting-v2", SCHEMA})
EXECUTOR_TYPES = frozenset({"deterministic_program", "production_model", "decision_agent",
                            "human", "external_service", "engineering_codex"})
INTERNAL_TIMING_WORKLOADS = frozenset({'timing.inline_dispatch_v1', 'timing.orchestration_v1'})
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


def _labels(values):
    """Return bounded, safe identity labels without leaking arbitrary payload text."""
    if values is None:
        return []
    if not isinstance(values, (list, tuple)) or len(values) > 64:
        raise ValueError("invalid_dependency_labels")
    result = [_label(value, None) for value in values]
    if any(value is None for value in result) or len(set(result)) != len(result):
        raise ValueError("invalid_dependency_labels")
    return result


def _safe_metadata(data):
    data = data if isinstance(data, dict) else {}
    safe = {}
    for key, value in data.items():
        if key in {"sunday", "week", "sourceServiceDate"} and isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            safe[key] = value
        elif key == "pageId" and isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", value):
            safe[key] = value
        elif key == "targetLocale" and isinstance(value, str) and re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", value):
            safe[key] = value
        elif key == "target" and value in {"dev", "production"}:
            safe[key] = value
        elif key == "ledgerIdentitySha256" and isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value):
            safe[key] = value
        elif key in {"sourceId", "videoId"} and isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            safe[key] = value
        elif key in {"jobSha256", "productionRunId", "sourceSha256", "videoSha256", "sourceVideoSha256", "sourceAudioSha256"} and isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
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
        location = {"file": str(relative), "line": lineno, "function": _label(frame.f_code.co_name)}
        # Distinct lambda/generator frames may normalize to the same safe tuple.
        # Retain first-seen provenance order while honoring schema uniqueItems;
        # never append code, exception bodies or original unsafe function names.
        if location not in frames:
            frames.append(location)
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


def safe_execution_identity(data):
    """Read-side whitelist: repository-relative code paths, never host paths."""
    data = data if isinstance(data, dict) else {}
    commit = data.get("gitCommit")
    modules = data.get("loadedProjectCodeSha256")
    safe_modules = {}
    if isinstance(modules, dict):
        for path, digest in list(modules.items())[:1024]:
            if (isinstance(path, str) and len(path) <= 256
                    and re.fullmatch(r"(?:scripts|backend|experiments)/[A-Za-z0-9_./-]+\.py", path)
                    and ".." not in Path(path).parts and isinstance(digest, str)
                    and re.fullmatch(r"[a-f0-9]{64}", digest)):
                safe_modules[path] = digest
    return {"gitCommit": commit if isinstance(commit, str) and re.fullmatch(r"[a-f0-9]{40,64}", commit) else None,
            "trackedWorkingTreeDirty": data.get("trackedWorkingTreeDirty") if type(data.get("trackedWorkingTreeDirty")) is bool else None,
            "loadedProjectCodeSha256": safe_modules,
            "pythonVersion": _label(data.get("pythonVersion"), None),
            "scope": "loaded_project_modules_at_workflow_start_not_all_or_remote_code"}


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
    if log_profile.current() is None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        log_profile.reject_downgrade(directory, run_id)
    payload = {"schemaVersion": SCHEMA, "eventId": uuid.uuid4().hex,
               "runId": run_id, "recordedAt": now(), "pid": os.getpid(),
               "threadId": threading.get_ident(),
               "workflowId": _workflow.get() or os.environ.get(WORKFLOW_ENV),
               "stage": _stage.get() or os.environ.get(ENV_KEYS[2]),
               "spanId": _span.get() or os.environ.get(ENV_KEYS[3]), **event}
    if log_profile.current() is not None:
        return log_profile.write(directory, event, payload)
    with open(path, "a+b", opener=_private_open) as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        # Profile markers are created under this same ledger lock. The early
        # check alone can race a new-profile writer waiting to append.
        log_profile.reject_downgrade(directory, run_id)
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


def subprocess_environment():
    """Snapshot child-process attribution without mutating the process-wide environment.

    Worker stages deliberately only change ContextVars. Pass this mapping as
    subprocess env so concurrently launched children inherit their own span.
    """
    env = os.environ.copy()
    identity = _identity.get()
    if identity:
        env[ENV_KEYS[0]], env[ENV_KEYS[1]] = map(str, identity)
    for key, value in ((ENV_KEYS[2], _stage.get()), (ENV_KEYS[3], _span.get()),
                       (WORKFLOW_ENV, _workflow.get())):
        if value is not None:
            env[key] = str(value)
    return log_profile.child_environment(env)


@contextmanager
def stage(name, *, cache_hit=False, billing="local", executor_type=None,
          depends_on=None, blocked_by=None, work_unit_id=None, attempt_id=None,
          dependency_ready_at=None, queued_at=None, decision_id=None):
    """Legacy auto-completing stage; yield its string span identity."""
    with _stage_context(name, cache_hit=cache_hit, billing=billing, executor_type=executor_type,
            depends_on=depends_on, blocked_by=blocked_by, work_unit_id=work_unit_id,
            attempt_id=attempt_id, dependency_ready_at=dependency_ready_at,
            queued_at=queued_at, decision_id=decision_id) as result:
        yield result.span_id


class StageOutcome:
    """An explicit observation endpoint, captured before logging may block.

    A terminal is emitted once on context exit. Capturing an outcome does not
    permit changing an already durable terminal or reopening an old attempt.
    """
    def __init__(self, span_id):
        self.span_id = span_id
        self._outcome = None
        self._artifact_sha256 = None

    def finish(self, status, *, error=None, artifact_sha256=None):
        if not isinstance(status, str) or status not in {'completed', 'failed', 'outcome_unknown', 'cancelled'}:
            raise ValueError('invalid_stage_outcome')
        if error is not None and (not isinstance(error, BaseException) or status == 'completed'):
            raise ValueError('invalid_stage_outcome_error')
        if self._outcome is not None:
            raise ValueError('stage_outcome_already_captured')
        if artifact_sha256 is not None and (status != 'completed' or not isinstance(artifact_sha256, str)
                or re.fullmatch(r'[a-f0-9]{64}', artifact_sha256) is None):
            raise ValueError('invalid_stage_artifact_hash')
        self._artifact_sha256 = artifact_sha256
        self._outcome = (status, error, time.monotonic_ns(), now())
        return self.span_id


@contextmanager
def stage_outcome(name, **kwargs):
    """Yield an explicit outcome writer; omitted finish fails closed.

    Call ``outcome.finish(status)`` at the observed endpoint. A later exception
    wins over an uncommitted success; the original exception is propagated.
    Observing a worker timeout must use its own attempt, not the worker attempt.
    """
    with _stage_context(name, explicit_outcome=True, **kwargs) as result:
        yield result


@contextmanager
def _stage_context(name, *, cache_hit=False, billing="local", executor_type=None,
          depends_on=None, blocked_by=None, work_unit_id=None, attempt_id=None,
          dependency_ready_at=None, queued_at=None, decision_id=None, explicit_outcome=False):
    """Record one stage attempt with dependency-aware v3 trace identity.

    Callers provide stable stage/work-unit identities; ``spanId`` remains unique
    to this execution attempt. Explicit queue timestamps remain authoritative.
    Otherwise capture synchronous dispatch-to-entry; external readiness stays
    unknown and these observations never claim a resource queue measurement.
    """
    name = _label(name)
    span_id = uuid.uuid4().hex
    parent = _span.get() or os.environ.get("SERMON_ACCOUNTING_SPAN")
    if executor_type is None:
        executor_type = {"api": "production_model", "cloud": "external_service",
                         "codex": "production_model"}.get(billing, "deterministic_program")
    if not isinstance(executor_type, str) or executor_type not in EXECUTOR_TYPES:
        raise ValueError("invalid_executor_type")
    identities = {
        "workUnitId": _label(work_unit_id, None) if work_unit_id is not None else None,
        "attemptId": _label(attempt_id, None) if attempt_id is not None else uuid.uuid4().hex,
        "decisionId": _label(decision_id, None) if decision_id is not None else None,
    }
    if ((work_unit_id is not None and identities["workUnitId"] is None) or
            (attempt_id is not None and identities["attemptId"] is None) or
            (decision_id is not None and identities["decisionId"] is None)):
        raise ValueError("invalid_stage_identity")
    for value in (dependency_ready_at, queued_at):
        if value is not None and (not isinstance(value, str) or len(value) > 40 or datetime.fromisoformat(value).tzinfo is None):
            raise ValueError("invalid_queue_timestamp")
    dispatch_identity = _identity.get() or tuple(os.environ.get(k) for k in ENV_KEYS[:2])
    automatic_dispatch = dependency_ready_at is None and queued_at is None
    if automatic_dispatch:
        observed_ready, observed_dispatch = dispatch_observation.observe(dispatch_identity, depends_on, now)
        dependency_ready_at, queued_at = observed_ready, observed_dispatch
    base = {"stage": name, "spanId": span_id, "parentSpanId": parent,
            "cacheHit": bool(cache_hit), "billing": billing,
            "executorType": executor_type, "dependsOn": None if depends_on is None else _labels(depends_on),
            "blockedBy": _labels(blocked_by), "dependencyReadyAt": dependency_ready_at,
            "queuedAt": queued_at, **identities}
    started_ns = time.monotonic_ns()
    base.update(clockDomainId=clock_domain(), monotonicStartNs=str(started_ns))
    _emit({**base, "event": "stage_started", "startedAt": now()})
    profile_context = log_profile.context(executorType=executor_type,
        workUnitId=identities['workUnitId'] or (log_profile.current() or {}).get('workUnitId'),
        attemptId=identities['attemptId'], parentSpanId=parent) if log_profile.current() is not None else nullcontext()
    profile_context.__enter__()
    tokens = (_stage.set(name), _span.set(span_id))
    old = {k: os.environ.get(k) for k in ENV_KEYS[2:]}
    main_thread = threading.current_thread() is threading.main_thread()
    if main_thread:
        os.environ.update(SERMON_ACCOUNTING_STAGE=name, SERMON_ACCOUNTING_SPAN=span_id)
    result = StageOutcome(span_id)
    error = None
    try:
        if automatic_dispatch:
            _emit({'event': 'workload', 'stage': 'timing.inline_dispatch_v1', 'metrics': {
                'dispatchObserved': True, 'dependencyReadyObserved': dependency_ready_at is not None,
                'resourceQueueObserved': False}})
        yield result
        if result._outcome is None:
            if explicit_outcome:
                result.finish('outcome_unknown')
                raise ValueError('stage_outcome_required')
            result.finish('completed')
    except BaseException as exc:
        error = exc
        if result._outcome is None or result._outcome[0] == 'completed':
            # This candidate has not yet been written; never amend a ledger fact.
            result._outcome = ('failed', exc, time.monotonic_ns(), now())
            result._artifact_sha256 = None
        raise
    finally:
        try:
            outcome, outcome_error, finished_ns, completed_at = result._outcome
            def finish_event():
                _emit({**base, "event": "stage_finished", "status": outcome,
                    "completedAt": completed_at,
                    "monotonicEndNs": str(finished_ns),
                    "level": "ERROR" if outcome == 'failed' else "INFO",
                    "elapsedSeconds": round((finished_ns-started_ns)/1_000_000_000, 6),
                    "errorType": _label(type(outcome_error).__name__) if outcome_error else None,
                    "error": error_location(outcome_error) if outcome_error else None,
                    **({'artifactSha256': result._artifact_sha256} if result._artifact_sha256 else {})})
                dispatch_observation.finished(dispatch_identity, span_id)
            _finalize(finish_event, error)
        finally:
            _stage.reset(tokens[0]); _span.reset(tokens[1])
            profile_context.__exit__(None, None, None)
            if main_thread:
                for k, val in old.items():
                    if val is None: os.environ.pop(k, None)
                    else: os.environ[k] = val


def bounded_dependencies(name, dependencies, *, work_unit_id):
    """Join completed leaves without widening the 64-edge event contract.

    Each emitted deterministic barrier depends on at most 64 predecessors.
    Larger fan-ins form a tree, retaining reachability of every original leaf.
    Consumers must call this only after all supplied predecessors have finished.
    """
    if not isinstance(dependencies, (list, tuple)):
        raise ValueError('invalid_dependency_labels')
    pending = list(dependencies)
    if any(_label(value, None) is None for value in pending) or len(set(pending)) != len(pending):
        raise ValueError('invalid_dependency_labels')
    level = 0
    while len(pending) > 64:
        joined = []
        for index in range(0, len(pending), 64):
            suffix = f'.{level}.{index // 64}'
            with stage(name + suffix, depends_on=pending[index:index + 64],
                       executor_type='deterministic_program', work_unit_id=work_unit_id + suffix) as span:
                # This is the actual completed-group fan-in barrier. It neither
                # reruns work nor assigns model/token usage to the join.
                joined.append(span)
        pending = joined
        level += 1
    return pending


@contextmanager
def orchestration(name, *, depends_on=None, work_unit_id=None):
    """Measure explicitly selected program bookkeeping; no wrapper-gap inference."""
    with stage(name, depends_on=depends_on, executor_type='deterministic_program',
               work_unit_id=work_unit_id) as span:
        _emit({'event': 'workload', 'stage': 'timing.orchestration_v1',
               'metrics': {'orchestrationWorkObserved': True}})
        yield span


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


def record_api_attempt(model, response, elapsed_seconds, status="completed", error_type=None, *, audio_seconds=None, attempt_id=None, http_status=None, not_dispatched_reason=None):
    # Reuse contract-v1's bounded extension slots instead of silently extending
    # the schema. No arbitrary exception text or provider error body is accepted.
    if not_dispatched_reason is not None:
        from scripts.sermon_pipeline import PRE_DISPATCH_REASONS
        if (type(not_dispatched_reason) is not str or not_dispatched_reason not in PRE_DISPATCH_REASONS
                or status != "failed" or response is not None or http_status is not None):
            raise ValueError("invalid_not_dispatched_evidence")
    response = response if isinstance(response, dict) else {}
    usage = response.get("usage")
    actual_model = _label(response.get("model"), None) if log_profile.current() is not None else _label(response.get("model") or model)
    tier = _safe_settings({"service_tier": response.get("service_tier") or "default"}).get("service_tier", "unknown")
    cost = estimate_cost(actual_model, usage, tier, audio_seconds) if status == "completed" else {
        "status": "unknown", "estimatedUsd": None, "currency": "USD", "reason": "failed_attempt_billing_unknown"}
    if not_dispatched_reason is not None:
        cost = {"status": "not_incurred", "estimatedUsd": 0, "currency": "USD",
                "reason": "transport_not_dispatched", "invoiceVerified": False}
    evidence = ({"metrics": {"dispatched": False}, "reasonCode": not_dispatched_reason}
                if not_dispatched_reason is not None else {})
    _emit({"event": "api_attempt", "attemptId": attempt_id or uuid.uuid4().hex,
           "stage": _stage.get() or os.environ.get(ENV_KEYS[2], "unattributed_api"),
           "spanId": _span.get() or os.environ.get(ENV_KEYS[3]),
           "status": _label(status), "errorType": _label(error_type) if error_type else None,
           "httpStatus": _number(http_status), "elapsedSeconds": _number(elapsed_seconds),
           "requestedModel": _label(model), "model": actual_model, "responseId": _label(response.get("id"), None),
           "usage": normalize_usage(usage), "cost": cost, **evidence})


@contextmanager
def sdk_invocation(model, *, backend="sdk"):
    """Record SDK-reported aggregate usage without inventing HTTP receipts."""
    invocation_id = uuid.uuid4().hex
    base = {"invocationId": invocation_id, "model": _label(model), "agentBackend": backend,
            "measurementScope": "agents_api_session_including_tools" if backend == "agents-api" else "sdk_aggregate_including_tools",
            "estimatedUsd": None, "costStatus": "unknown",
            "costReason": "agents_api_best_effort_not_invoice" if backend == "agents-api" else "sdk_aggregate_not_provider_receipts",
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
    return _with_summary_snapshot(directory, lambda events, damaged, digest, replay, summary: summary)


def _with_report_snapshot(directory, project):
    """One private, operation-local read; never accept reusable caller authority.

    Rows belong only to this call. The callback is an internal pure projector,
    not an API for accepting externally prevalidated rows. Exact typed bytes
    guard accidental mutation; current schema identity must remain unchanged
    for the operation. Later calls always reread/revalidate the actual ledger.
    """
    events, damaged, digest = read_event_snapshot(directory)
    contract = log_profile.contract
    has_profile = any('contractVersion' in row for row in events)
    with contract._schema_snapshot_lock:
        schema = (contract.VERSION, contract._schema_snapshot()[0]) if has_profile else None
        replay = profile_integrity(events)
        frozen = marshal.dumps((events, damaged), 2)
        result = project(events, damaged, digest, replay)
        if marshal.dumps((events, damaged), 2) != frozen:
            raise ValueError('report_snapshot_mutated')
        if has_profile and (contract.VERSION, contract._schema_snapshot()[0]) != schema:
            raise ValueError('report_schema_changed')
    return result


def _with_summary_snapshot(directory, project):
    """Preserve summarize's serialized output writes while sharing its read."""
    directory = Path(directory)
    with open(directory / '.summary.lock', 'a', opener=_private_open) as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        def build(events, damaged, digest, replay):
            summary, projected = _summarize_events(events, damaged, digest, replay)
            result = project(events, damaged, digest, replay, summary)
            return result, summary, projected
        result, summary, projected = _with_report_snapshot(directory, build)
        _write_summary(directory, summary, projected)
        return result


def _percentile(values, fraction):
    if not values: return None
    values = sorted(values)
    index = (len(values)-1) * fraction
    lo = int(index)
    hi = min(lo+1, len(values)-1)
    return round(values[lo] + (values[hi]-values[lo]) * (index-lo), 6)


def _valid_event(value):
    if isinstance(value, dict) and 'contractVersion' in value:
        try:
            from scripts.sermon_log_contract import valid_event
        except ImportError:
            from sermon_log_contract import valid_event
        return valid_event(value)
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
    if value.get('code') == 'model_call_observation':
        from scripts.sermon_model_call_observation import safe_observation
        try:
            safe_observation(value['fields'])
        except (ValueError, KeyError, TypeError):
            return False
    for key in ("workflowId", "spanId", "attemptId", "responseId", "invocationId"):
        if value.get(key) is not None and not isinstance(value[key], str):
            return False
    if value["event"] == "stage_finished" and _number(value.get("elapsedSeconds")) is None:
        return False
    # Validate extension fields on every schema: legacy rows must not smuggle
    # unchecked labels into exporters either. Missing legacy fields stay unknown.
    if value["event"] in {"stage_started", "stage_finished"}:
        if value.get("executorType") is not None and (not isinstance(value["executorType"], str) or value["executorType"] not in EXECUTOR_TYPES):
            return False
        for key in ("workUnitId", "attemptId", "decisionId"):
            if value.get(key) is not None and _label(value[key], None) is None:
                return False
        for key in ("dependsOn", "blockedBy"):
            if value.get(key) is not None:
                if not isinstance(value[key], list):
                    return False
                try:
                    _labels(value[key])
                except ValueError:
                    return False
        for key in ("dependencyReadyAt", "queuedAt"):
            timestamp = value.get(key)
            if timestamp is not None:
                if (not isinstance(timestamp, str) or len(timestamp) > 40 or
                        datetime.fromisoformat(timestamp).tzinfo is None):
                    return False
    for key in ('clockDomainId', 'monotonicStartNs', 'monotonicEndNs'):
        if key in value:
            pattern = r'[a-f0-9]{32}' if key == 'clockDomainId' else r'[0-9]{1,20}'
            if not isinstance(value[key], str) or not re.fullmatch(pattern, value[key]): return False
    if value["event"] == "api_attempt":
        usage = value["usage"]
        for key in ("inputTokens", "outputTokens", "cachedInputTokens", "cacheWriteTokens", "reasoningTokens"):
            if key not in usage or (usage[key] is not None and _number(usage[key]) is None): return False
        for number in (value.get("elapsedSeconds"), value["cost"].get("estimatedUsd")):
            if number is not None and _number(number) is None: return False
    return True


def read_events(directory):
    """Read a locked snapshot without changing the ledger or its projections."""
    events, damaged, _ = read_event_snapshot(directory)
    return events, damaged


def read_event_snapshot(directory):
    """Parse and hash the exact same locked byte snapshot, including blank lines."""
    events, damaged, digest = [], [], hashlib.sha256()
    with (Path(directory) / "events.jsonl").open("rb") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
        for index, line in enumerate(stream, 1):
            digest.update(line)
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                # Keep syntactically valid unknown-schema rows visible so
                # consumers can diagnose rather than silently erase them.
                if not _valid_event(value):
                    raise ValueError("invalid_event_identity")
            except (ValueError, UnicodeError):
                damaged.append({"line": index, "bytes": len(line), "sha256": hashlib.sha256(line).hexdigest(),
                                "reason": "invalid_or_incomplete_event", "runAttribution": "unknown"})
                continue
            events.append(value)
    return events, damaged, digest.hexdigest()


def diagnostic_event(event):
    """A small, terminal-safe view; no legacy free-text fields are forwarded."""
    result = {key: _label(event.get(key), None) for key in
              ("runId", "workflowId", "stage", "spanId", "attemptId", "invocationId", "status")}
    result.update(recordedAt=event["recordedAt"], event=_label(event["event"]),
                  code=_label(event.get("code") or event["event"]),
                  level=event.get("level") if event.get("level") in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else
                  ("ERROR" if event.get("status") in {"failed","cancelled","outcome_unknown"} else "INFO"))
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


def profile_integrity(events):
    if not any('contractVersion' in e for e in events):
        return {'status': 'consistent', 'diagnostics': [], 'profileEventCount': 0,
                'equivalentDuplicatesIgnored': 0, 'executionAuthority': 'none',
                '_excluded': set(), '_selected': set()}
    try:
        from scripts.sermon_log_contract import replay_integrity
    except ImportError:
        from sermon_log_contract import replay_integrity
    return replay_integrity(events)


def receipt_integrity(events, *, event_integrity=None):
    """Compare all imported facts before choosing a stable representative.

    Returned event object IDs are internal selection keys, never serialized.
    Conflicts contain hashes and safe attribution only, not provider payloads.
    """
    def encoded(value):
        # Hash even legacy non-finite extension values; numeric output still
        # goes through _number, and no raw fact is forwarded in diagnostics.
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=True)
    def digest(value):
        return hashlib.sha256(encoded(value).encode()).hexdigest()
    replay = event_integrity if event_integrity is not None else profile_integrity(events)
    event_facts = {}
    for event in events:
        identity = (event['runId'], event['eventId'])
        event_facts.setdefault(identity, set()).add(digest(event))
    ambiguous_events = {key for key, facts in event_facts.items() if len(facts) > 1}
    executors = {}
    for event in events:
        if event['event'] in {'stage_started', 'stage_finished'}:
            key = (event['runId'], event.get('spanId'))
            executors.setdefault(key, set()).add(event.get('executorType'))
    groups = {}
    for event in events:
        kind = event['event']
        if kind not in {'api_attempt', 'sdk_call_finished'}:
            continue
        if kind == 'api_attempt':
            if event.get('contractVersion'):
                # An unknown provider account must not collapse independent calls.
                scope = event.get('providerScopeKey') or ['unknown_scope', event['runId'], event['modelCallId']]
                identity = ['provider', event.get('provider'), scope,
                            event.get('providerResponseId') or event['modelCallId']]
            else:
                identity = ['provider', event.get('provider'),
                            event.get('responseId') or event.get('attemptId') or event['eventId']]
            fact = {key: event.get(key) for key in
                    ('status', 'usage', 'cost', 'model', 'requestedModel', 'elapsedSeconds')}
        else:
            identity = ['sdk', event['invocationId']]
            fact = {key: event.get(key) for key in ('status', 'usage', 'model', 'elapsedSeconds', 'measurementScope')}
        key = digest(identity)
        group = groups.setdefault(key, {'kind': identity[0], 'variants': {}, 'events': []})
        group['events'].append(event)
        # Conflicting stage classifications cannot silently choose the last row.
        for executor in executors.get((event['runId'], event.get('spanId')), {None}):
            variant = {**fact, 'executorType': executor}
            group['variants'][digest(variant)] = variant
    selected, conflicts, affected, sdk_conflicts = set(), [], {}, set()
    duplicates = 0
    for key, group in sorted(groups.items()):
        rows = group['events']
        if (len(group['variants']) != 1 or any(id(e) in replay['_excluded'] for e in rows)
                or any((e['runId'], e['eventId']) in ambiguous_events for e in rows)):
            conflicts.append({'kind': group['kind'], 'identitySha256': key,
                              'variantSha256': sorted(group['variants']),
                              'runIds': sorted({_label(e['runId']) for e in rows})})
            for event in rows:
                affected.setdefault((event['runId'], event.get('stage')), set()).add(key)
                if group['kind'] == 'sdk':
                    sdk_conflicts.add((event['runId'], event['invocationId']))
        else:
            # Stable across line reordering, including equivalent cross-run imports.
            chosen = min(rows, key=lambda e: (e['recordedAt'], e['runId'],
                                              e.get('stage') or '', e['eventId'], digest(e)))
            selected.add(id(chosen))
            duplicates += len(rows) - 1
    return {'status': 'conflicted' if conflicts else 'consistent', 'conflicts': conflicts,
            'equivalentDuplicatesIgnored': duplicates,
            '_selected': selected, '_affected': affected, '_sdkConflicts': sdk_conflicts}


def _summarize_locked(directory):
    # Retained private compatibility entry for callers already holding the lock.
    result, events = _with_report_snapshot(directory, _summarize_events)
    _write_summary(Path(directory), result, events)
    return result


def _summarize_events(events, damaged, ledger_hash, replay):
    # Reconcile all raw receipts below, but aggregate one representative of
    # every equivalent profile fact, including stage/review/start events.
    projected = [e for e in events if 'contractVersion' not in e or id(e) in replay['_selected']]
    completed_attempts = {(e['runId'], e.get('attemptId')) for e in projected if e['event'] == 'api_attempt'}
    unfinished_api = [e for e in projected if e['event'] == 'api_attempt_started'
                      and (e['runId'], e['attemptId']) not in completed_attempts]
    # A process can disappear after sending a billable request. Preserve uncertainty.
    unresolved = [{**e, "event": "api_attempt", "eventId": hashlib.sha256((e["eventId"] + ":unresolved_projection").encode()).hexdigest()[:32],
                   "status": "interrupted_or_running",
                   "elapsedSeconds": None, "usage": normalize_usage(None),
                   "cost": {"estimatedUsd": None, "status": "unknown"}}
                  for e in unfinished_api]
    integrity = receipt_integrity(events + unresolved, event_integrity=replay)
    events = projected + unresolved
    selected_receipts = integrity.pop("_selected")
    affected_receipts = integrity.pop("_affected")
    sdk_conflicts = integrity.pop("_sdkConflicts")
    sdk_finished = {(e['runId'], e['invocationId']) for e in events if e['event'] == 'sdk_call_finished'}
    sdk_selected = {(e['runId'], e['invocationId']) for e in events
                    if e['event'] == 'sdk_call_finished' and id(e) in selected_receipts}
    sdk_duplicates = sdk_finished - sdk_selected - sdk_conflicts
    runs, groups = {}, {}
    latencies, workflows = {}, {}
    sdk_calls = {}
    token_fields = ("inputTokens", "outputTokens", "cachedInputTokens", "cacheWriteTokens", "reasoningTokens")
    started_spans = {e["spanId"]: e for e in events if e["event"] == "stage_started"}
    finished_spans = {e["spanId"]: e for e in events if e["event"] == "stage_finished"}
    ended_spans = set(finished_spans)
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
            # Preserve the business-workload projection and its existing order.
            # These exact versioned internal observations remain in the raw
            # ledger and are projected separately by weekly telemetryEvidence.
            if event["stage"] not in INTERNAL_TIMING_WORKLOADS:
                run.setdefault("workloads", []).append({"stage": event["stage"], "metrics": event["metrics"]})
        elif event["event"] in {"sdk_call_started", "sdk_call_finished"}:
            key = (rid, event["invocationId"])
            call = sdk_calls.setdefault(key, {"runId": rid, "invocationId": event["invocationId"],
                "model": _label(event["model"]), "status": "interrupted_or_running", "elapsedSeconds": None,
                "usage": {key: None for key in ("requests", "input_tokens", "output_tokens", "total_tokens")},
                "measurementScope": "sdk_aggregate_including_tools", "estimatedUsd": None,
                "costStatus": "unknown", "httpAttemptsKnown": False})
            if event["event"] == "sdk_call_finished" and id(event) in selected_receipts:
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
            if id(event) not in selected_receipts: continue
            row["apiAttempts"] += 1
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
    for key, call in sdk_calls.items():
        if key in sdk_conflicts:
            call.update(status='usage_conflict', model=None, elapsedSeconds=None,
                        usage={field: None for field in call['usage']}, costStatus='conflicted')
        elif key in sdk_duplicates:
            call.update(status='duplicate_import', elapsedSeconds=None,
                        usage={field: None for field in call['usage']})
    for row in groups.values():
        conflict_ids = sorted(affected_receipts.get((row['runId'], row['stage']), ()))
        row['receiptConflictSha256'] = conflict_ids
        row['knownNonconflictingEstimatedUsd'] = row['knownEstimatedUsd']
        if conflict_ids:
            row.update(tokenStatus='conflicted', costStatus='conflicted', knownEstimatedUsd=None,
                       apiLatencySeconds=None, apiLatencyP50Seconds=None, apiLatencyP95Seconds=None,
                       usageReceiptCoverage=None)
            for field in token_fields:
                row[field] = None
    for rid, run in runs.items():
        rows = [r for r in groups.values() if r["runId"] == rid]
        run["knownEstimatedUsd"] = round(sum(r["knownNonconflictingEstimatedUsd"] for r in rows), 9)
        run["unknownCostAttempts"] = sum(r["unknownCostAttempts"] for r in rows)
        run["apiAttempts"] = sum(r["apiAttempts"] for r in rows)
        run["usageReceipts"] = sum(r["usageReceipts"] for r in rows)
        run["usageReceiptCoverage"] = run["usageReceipts"] / run["apiAttempts"] if run["apiAttempts"] else None
        run["completedApiAttempts"] = sum(r["completedApiAttempts"] for r in rows)
        run["failedApiAttempts"] = sum(r["failedApiAttempts"] for r in rows)
        run["workflows"] = [w for w in workflows.values() if w["runId"] == rid]
        run["sdkCalls"] = [call for (run_id, _), call in sdk_calls.items() if run_id == rid]
        run["duplicateSdkInvocations"] = sum(call["status"] == "duplicate_import" for call in run["sdkCalls"])
        run["unpricedSdkInvocations"] = len(run["sdkCalls"]) - run["duplicateSdkInvocations"]
        run["overallCostStatus"] = "partial" if run["unknownCostAttempts"] or run["sdkCalls"] or damaged else "recorded_api_only"
        run['receiptConflictSha256'] = sorted({key for (run_id, _), keys in affected_receipts.items()
                                               if run_id == rid for key in keys})
        run['knownNonconflictingEstimatedUsd'] = run['knownEstimatedUsd']
        if run['receiptConflictSha256']:
            run['knownNonconflictingApiAttempts'] = run['apiAttempts']
            run.update(knownEstimatedUsd=None, overallCostStatus='conflicted', usageReceiptCoverage=None,
                       apiAttempts=None, completedApiAttempts=None, failedApiAttempts=None)
    # Run aggregation above consumes only consistent receipts. Do not expose a
    # conflict-excluding call count under the old unqualified total field.
    for row in groups.values():
        row['knownNonconflictingApiAttempts'] = row['apiAttempts']
        if row['receiptConflictSha256']:
            row.update(apiAttempts=None, completedApiAttempts=None, failedApiAttempts=None)
    from scripts.sermon_review_observation import observations as review_observations
    result = {"schemaVersion": SCHEMA, **({"sourceLedgerSha256": ledger_hash} if replay["profileEventCount"] else {}), "generatedAt": now(), "runs": list(runs.values()), "stages": list(groups.values()),
              "ledgerIntegrity": {"status": "incomplete_corrupt_events" if damaged else "conflicting_receipts" if integrity["conflicts"] else "readable",
                                  "damagedEvents": damaged, "unattributedCostUnknown": bool(damaged or integrity["conflicts"]),
                                  "originalBytesPreserved": True},
              "receiptIntegrity": integrity,
              **({"reviewObservations": review_observations(events)} if any(e["event"] == "rqc_observation" for e in events) else {}),
              **({"eventIntegrity": {k: v for k, v in replay.items() if not k.startswith("_")}} if replay["profileEventCount"] else {}),
              "unfinishedApiAttempts": [{"runId": e["runId"], "stage": e["stage"], "attemptId": e["attemptId"],
                                         "startedAt": e["recordedAt"], "costStatus": "unknown"} for e in unfinished_api],
              "unfinishedStages": [{"runId": e["runId"], "stage": e["stage"], "spanId": sid,
                                    "startedAt": e["startedAt"], "elapsedSeconds": None}
                                   for sid, e in started_spans.items() if sid not in ended_spans],
              "notes": ["Parent and child elapsed times overlap: do not sum all stages as wall time.",
                        "Known USD is an API list-price estimate, not an invoice or complete project cost.",
                        "Local compute, storage, network and in-conversation Codex costs are not allocated.",
                        "Missing usage/cost remains unknown; caches do not re-bill old responses."]}
    from scripts.sermon_model_call_report import report as model_call_report
    result['modelCallReport'] = model_call_report(events)
    # One row per attempt, including a killed process with no finish event. The
    # grouped stages.csv intentionally remains an aggregate for old consumers.
    attempts = []
    for span_id, start in started_spans.items():
        finish = finished_spans.get(span_id)
        attempts.append({"runId": start["runId"], "workflowId": start.get("workflowId"),
                         "stage": start["stage"], "spanId": span_id,
                         "parentSpanId": start.get("parentSpanId"),
                         "startedAt": start["startedAt"],
                         "finishedAt": finish["recordedAt"] if finish else None,
                         "status": finish["status"] if finish else "interrupted_or_running",
                         "elapsedSeconds": finish["elapsedSeconds"] if finish else None,
                         "cacheHit": finish["cacheHit"] if finish else start.get("cacheHit"),
                         "billing": finish["billing"] if finish else start.get("billing")})
    result["stageAttempts"] = attempts
    return result, events


def _write_summary(directory, result, events):
    attempts = result['stageAttempts']
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
    attempts_temp = directory / (".stage-attempts-" + uuid.uuid4().hex + ".csv")
    with open(attempts_temp, "w", newline="", encoding="utf-8-sig", opener=_private_open) as stream:
        writer = csv.DictWriter(stream, fieldnames=("runId", "workflowId", "stage", "spanId",
            "parentSpanId", "startedAt", "finishedAt", "status", "elapsedSeconds",
            "cacheHit", "billing"))
        writer.writeheader(); writer.writerows(attempts)
    attempts_temp.replace(directory / "stage-attempts.csv")
    calls_temp = directory / ('.model-calls-' + uuid.uuid4().hex + '.csv')
    calls = result['modelCallReport']['calls']
    with open(calls_temp, 'w', newline='', encoding='utf-8-sig', opener=_private_open) as stream:
        if calls:
            # Nested numeric usage/rates retain their fields as JSON cells.
            keys = sorted({key for call in calls for key in call})
            writer = csv.DictWriter(stream, fieldnames=keys)
            writer.writeheader()
            writer.writerows({key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
                             for key, value in call.items()} for call in calls)
    calls_temp.replace(directory / 'model-calls.csv')
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
