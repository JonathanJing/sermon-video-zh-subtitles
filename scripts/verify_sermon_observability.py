"""Verify local Jaeger persistence, retry identity, and a real zero-model observer.

This intentionally stops and restarts only the Jaeger owned by --runtime. It
copies the input ledger unchanged under runtime/verification before delivery;
the original accounting directory is read only. The managed Jaeger remains
running on exit. No model, source-media, or public publishing calls are made.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import sermon_accounting as accounting
from scripts import sermon_observability as observer
from scripts.sermon_execution_harness import atomic_json, utc_now, work_lock

DEFAULT_ACCOUNTING = ROOT / "artifacts/sermon-dubbing/2026-09-06-live-fallback-v3-numbers/accounting"


class VerificationFailure(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise VerificationFailure(code)


def identities(payload):
    return Counter((span["traceId"], span["spanId"])
                   for resource in payload["resourceSpans"]
                   for scope in resource["scopeSpans"] for span in scope["spans"])


def restore_service(runtime, *, timeout=45):
    """Bounded recovery for a recently stopped socket; never kill a port owner."""
    deadline = time.monotonic() + timeout
    retries = 0
    while True:
        try:
            return {**observer.start(runtime), "recoveryRetries": retries}
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE or time.monotonic() >= deadline:
                raise
            retries += 1
            time.sleep(.5)


def query_exact(expected, *, timeout=20):
    """Wait for exact ID multiplicity, detecting both omissions and duplicates."""
    deadline = time.monotonic() + timeout
    trace_ids = sorted({trace for trace, _ in expected})
    while True:
        actual = Counter()
        traces = []
        try:
            for trace_id in trace_ids:
                response = observer.json_get(
                    f"http://127.0.0.1:{observer.QUERY_PORT}/api/traces/{trace_id}")
                require(isinstance(response, dict) and not response.get("errors"), "query_response_error")
                for trace in response.get("data") or []:
                    spans = trace.get("spans") or []
                    actual.update((span["traceID"], span["spanID"]) for span in spans)
                    traces.append({"traceId": trace["traceID"], "spanCount": len(spans),
                                   "spanIds": sorted(span["spanID"] for span in spans)})
            if actual == expected:
                return {"queriedAt": utc_now(), "spanCount": sum(actual.values()),
                        "traceCount": len(traces), "exactIdentityMultiplicity": True,
                        "traces": traces}
        except (OSError, ValueError, KeyError, TypeError, VerificationFailure):
            pass
        if time.monotonic() >= deadline:
            raise VerificationFailure("query_exact_span_identity_timeout")
        time.sleep(.2)


@contextmanager
def isolated_accounting_environment():
    # A caller's inherited session must never redirect this fixture to its ledger.
    keys = (*accounting.ENV_KEYS, accounting.WORKFLOW_ENV)
    saved = {key: os.environ.pop(key, None) for key in keys}
    try:
        require(accounting._identity.get() is None, "existing_accounting_context")
        yield
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)


def run(runtime, source_directory, expected_span_count):
    runtime, source_directory = runtime.resolve(), source_directory.resolve()
    verification = runtime / "verification"
    source = source_directory / "events.jsonl"
    run_id = utc_now().replace(":", "").replace("+", "_") + "-" + uuid.uuid4().hex[:8]
    output = verification / run_id
    output.mkdir(parents=True, mode=0o700)
    receipt_path = output / "receipt.json"
    receipt = {"schemaVersion": "sermon-observability-verification-v1", "status": "running",
               "startedAt": utc_now(), "runtime": str(runtime), "sourceAccounting": str(source_directory),
               "evidenceScope": "real_ledger_replay_and_zero_model_observer_fixture",
               "humanGoldClaimed": False, "modelCalls": 0, "steps": [],
               "implementationSha256": {str(path.relative_to(ROOT)): observer.sha(path)
                    for path in (Path(__file__), Path(observer.__file__),
                                 ROOT / "scripts/export_sermon_trace.py", Path(accounting.__file__))}}
    atomic_json(receipt_path, receipt)
    test_runtime = verification / "observer-control"
    observer_identity = None
    source_hash = None
    service_touched = False

    def record(name, **details):
        receipt["steps"].append({"step": name, "status": "passed", "checkedAt": utc_now(), **details})
        atomic_json(receipt_path, receipt)
        print(json.dumps({"step": name, "status": "passed"}), flush=True)

    try:
        with source.open("rb") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
            source_bytes = stream.read()
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        ledger = output / "real-ledger" / "accounting"
        ledger.mkdir(parents=True, mode=0o700)
        copied = ledger / "events.jsonl"
        copied.write_bytes(source_bytes)
        copied.chmod(0o600)
        payload, diagnostics = observer.export(ledger)
        expected = identities(payload)
        require(diagnostics["status"] == "exported", "real_ledger_export_not_complete")
        require(sum(expected.values()) == expected_span_count, "unexpected_real_span_count")
        require(all(count == 1 for count in expected.values()), "duplicate_exported_ids")
        receipt["sourceEventsSha256"] = source_hash
        record("real_ledger_snapshot", sha256=source_hash, byteIdentical=observer.sha(copied) == source_hash,
               snapshot=str(copied), spans=sum(expected.values()), diagnostics=diagnostics)

        require(observer.observer_managed(runtime) is None, "stop_formal_observer_before_verification")
        require(observer.observer_managed(test_runtime) is None, "verification_observer_already_running")
        initial = observer.start(runtime)
        service_touched = True
        require(initial["status"] == "running", "jaeger_start_unhealthy")
        record("jaeger_running", service=initial)

        accepted = observer.deliver(ledger, site="macbook")
        require(accepted["status"] == "collector_accepted", "initial_delivery_not_accepted")
        record("initial_delivery", delivery=accepted, query=query_exact(expected))
        retained_payload_hash = observer.sha(ledger / "telemetry/payload.json")
        owner = observer.managed(runtime)
        require(owner and owner["pid"] == initial["pid"], "jaeger_owner_changed")
        stopped = observer.stop(runtime)
        require(stopped["status"] == "stopped", "jaeger_not_stopped")
        record("managed_jaeger_stopped", service=stopped)

        failed = observer.deliver(ledger, site="macbook")
        require(failed["status"] == "delivery_failed", "offline_delivery_did_not_fail")
        require(observer.sha(ledger / "telemetry/payload.json") == retained_payload_hash,
                "offline_payload_changed")
        require(failed["payloadSha256"] == accepted["payloadSha256"], "offline_request_identity_changed")
        record("offline_delivery_retained", delivery=failed, payloadFileSha256=retained_payload_hash)

        restarted = observer.start(runtime)
        require(restarted["status"] == "running", "jaeger_restart_unhealthy")
        # No resend occurs between restart and this query: this is storage proof.
        persisted = query_exact(expected)
        record("badger_persisted_before_resend", service=restarted, query=persisted,
               resentBeforeQuery=False, startupRetries=0)

        retried = observer.deliver(ledger, site="macbook")
        require(retried["status"] == "collector_accepted", "retry_not_accepted")
        require(retried["payloadSha256"] == accepted["payloadSha256"], "retry_request_identity_changed")
        # Wait past the configured batch interval before testing duplicate IDs.
        time.sleep(1)
        record("retry_preserves_exact_ids", delivery=retried, query=query_exact(expected))

        fixture = output / "observer-fixture" / "accounting"
        observed = observer.observer_start(test_runtime, [fixture], [],
                    endpoint=f"http://127.0.0.1:{observer.HTTP_PORT}/v1/traces", site="test", interval=.5)
        receipt["observerStartAttempt"] = observed
        observer_identity = observer.observer_managed(test_runtime)
        require(observed["status"] == "running" and observer_identity, "observer_not_running")
        record("fixture_observer_started", service=observed)
        # The observer is already running when this real ledger is created.
        with isolated_accounting_environment():
            with accounting.accounting_session(fixture, "pipeline", evidence_directory=fixture.parent):
                with accounting.stage("source_metadata"):
                    sum(range(1000))
        fixture_payload, fixture_diagnostics = observer.export(fixture)
        fixture_expected = identities(fixture_payload)
        require(fixture_diagnostics["status"] == "exported" and sum(fixture_expected.values()) == 4,
                "fixture_export_not_four_complete_spans")
        require(not (set(fixture_expected) & set(expected)), "fixture_ids_overlap_real_ledger")
        automatic = query_exact(fixture_expected)
        delivered = json.loads((fixture / "telemetry/delivery.json").read_text())
        require(delivered["status"] == "collector_accepted" and delivered["site"] == "test",
                "fixture_automatic_delivery_not_accepted")
        record("fixture_automatically_delivered", fixtureEventsSha256=observer.sha(fixture / "events.jsonl"),
               query=automatic, delivery=delivered, manualDeliveryCalled=False)
        current = observer.observer_managed(test_runtime)
        require(current and current["identity"] == observer_identity["identity"], "fixture_observer_owner_changed")
        stopped_observer = observer.observer_stop(test_runtime)
        require(stopped_observer["status"] == "stopped", "fixture_observer_not_stopped")
        observer_identity = None
        record("fixture_observer_stopped", service=stopped_observer)
        require(observer.sha(source) == source_hash, "original_ledger_changed")
        record("original_ledger_unchanged", sha256=source_hash)
        receipt["status"] = "passed"
    except Exception as exc:
        receipt.update(status="failed", errorType=type(exc).__name__)
        if isinstance(exc, OSError):
            receipt["errorNumber"] = exc.errno
        if isinstance(exc, VerificationFailure):
            receipt["failureCode"] = str(exc)
    finally:
        if observer_identity is not None:
            try:
                current = observer.observer_managed(test_runtime)
                if current and current["identity"] == observer_identity["identity"]:
                    receipt["observerCleanup"] = observer.observer_stop(test_runtime)
                elif current:
                    receipt.update(status="failed", cleanupFailure="observer_owner_changed")
            except Exception as exc:
                receipt.update(status="failed", cleanupErrorType=type(exc).__name__)
        if service_touched:
            try:
                receipt["finalJaeger"] = restore_service(runtime)
                if receipt["finalJaeger"]["status"] != "running":
                    receipt.update(status="failed", cleanupFailure="jaeger_not_running")
            except Exception as exc:
                receipt.update(status="failed", cleanupErrorType=type(exc).__name__)
        if source_hash is not None:
            try:
                receipt["sourceUnchanged"] = observer.sha(source) == source_hash
                if not receipt["sourceUnchanged"]:
                    receipt.update(status="failed", failureCode="original_ledger_changed")
            except OSError as exc:
                receipt.update(status="failed", sourceCheckErrorType=type(exc).__name__)
        receipt["finishedAt"] = utc_now()
        atomic_json(receipt_path, receipt)
        atomic_json(verification / "latest-verification.json", {
            "status": receipt["status"], "receipt": str(receipt_path),
            "receiptSha256": observer.sha(receipt_path), "finishedAt": receipt["finishedAt"]})
    return receipt, receipt_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=observer.DEFAULT_RUNTIME)
    parser.add_argument("--accounting-dir", type=Path, default=DEFAULT_ACCOUNTING)
    parser.add_argument("--expected-span-count", type=int, default=18)
    args = parser.parse_args(argv)
    try:
        require(args.expected_span_count > 0, "expected_span_count_must_be_positive")
        with work_lock(args.runtime.resolve() / "verification/control"):
            receipt, path = run(args.runtime, args.accounting_dir, args.expected_span_count)
        print(json.dumps({"status": receipt["status"], "receipt": str(path)}))
        return 0 if receipt["status"] == "passed" else 1
    except Exception as exc:
        print(json.dumps({"status": "failed", "errorType": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
