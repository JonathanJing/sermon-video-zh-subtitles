"""Local Jaeger/OTLP runtime and durable, opt-in accounting delivery.

Jaeger v2 is an OpenTelemetry Collector distribution. This deployment binds
loopback only and stores spans in Badger. The original ledger stays authoritative.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.export_sermon_trace import export
from scripts.sermon_execution_harness import atomic_json, utc_now, work_lock

VERSION = "2.20.0"
ARCHIVE = f"jaeger-{VERSION}-darwin-arm64.tar.gz"
ARCHIVE_SHA256 = "b2d21051b27f06535c288dd63e15a42d5aae653d0113695014d7e6b502736e5d"
DOWNLOAD = f"https://github.com/jaegertracing/jaeger/releases/download/v{VERSION}/{ARCHIVE}"
DEFAULT_RUNTIME = ROOT / "artifacts/observability"
HTTP_PORT, GRPC_PORT, QUERY_PORT, QUERY_GRPC_PORT, HEALTH_PORT = 14318, 14317, 16686, 16685, 14333


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_get(url, *, timeout=5):
    with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect).open(url, timeout=timeout) as response:
        return json.load(response)


def binary(runtime):
    return runtime / "runtime" / f"jaeger-{VERSION}-darwin-arm64" / "jaeger"


def install(runtime):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("This pinned installer supports macOS arm64; use a verified platform-specific release elsewhere")
    receipt = runtime / "runtime/install.json"
    executable = binary(runtime)
    if receipt.exists() and executable.exists():
        saved = json.loads(receipt.read_text())
        if saved.get("version") != VERSION or saved.get("binarySha256") != sha(executable):
            raise ValueError("Installed runtime changed; preserve and inspect before reinstalling")
        return saved
    archive = runtime / "runtime" / ARCHIVE
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        temporary = archive.with_suffix(".download")
        with urllib.request.urlopen(DOWNLOAD, timeout=60) as source, temporary.open("wb") as target:
            while block := source.read(1024 * 1024):
                target.write(block)
        temporary.replace(archive)
    if sha(archive) != ARCHIVE_SHA256:
        raise ValueError("Release archive checksum mismatch")
    member_name = f"jaeger-{VERSION}-darwin-arm64/jaeger"
    with tarfile.open(archive, "r:gz") as archive_file:
        member = archive_file.getmember(member_name)
        if not member.isfile():
            raise ValueError("Expected one regular executable in release archive")
        executable.parent.mkdir(parents=True, exist_ok=True)
        with archive_file.extractfile(member) as source, executable.open("wb") as target:
            while block := source.read(1024 * 1024):
                target.write(block)
    executable.chmod(0o755)
    saved = {"version": VERSION, "download": DOWNLOAD, "archiveSha256": ARCHIVE_SHA256,
             "binarySha256": sha(executable), "installedAt": utc_now()}
    atomic_json(receipt, saved)
    return saved


def configuration(runtime):
    store = str((runtime / "badger").resolve())
    return {
        "service": {"extensions": ["jaeger_storage", "jaeger_query", "healthcheckv2"],
            "pipelines": {"traces": {"receivers": ["otlp"], "processors": ["batch"],
                                     "exporters": ["jaeger_storage_exporter"]}},
            "telemetry": {"metrics": {"level": "none"}, "logs": {"level": "warn"}}},
        "extensions": {
            "healthcheckv2": {"use_v2": True, "http": {"endpoint": f"127.0.0.1:{HEALTH_PORT}"}},
            "jaeger_query": {"storage": {"traces": "sermon"}, "max_clock_skew_adjust": "0s",
                "http": {"endpoint": f"127.0.0.1:{QUERY_PORT}"},
                "grpc": {"endpoint": f"127.0.0.1:{QUERY_GRPC_PORT}"}},
            "jaeger_storage": {"backends": {"sermon": {"badger": {
                "directories": {"keys": store + "/keys", "values": store + "/values"},
                "ephemeral": False, "ttl": {"spans": "87600h"}}}}}},
        "receivers": {"otlp": {"protocols": {
            "http": {"endpoint": f"127.0.0.1:{HTTP_PORT}"},
            "grpc": {"endpoint": f"127.0.0.1:{GRPC_PORT}"}}}},
        "processors": {"batch": {"timeout": "200ms"}},
        "exporters": {"jaeger_storage_exporter": {"trace_storage": "sermon"}},
    }


def process_identity(pid):
    result = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "lstart=", "-o", "command="],
                            capture_output=True, text=True, timeout=5)
    return result.stdout.strip() if result.returncode == 0 else None


def managed(runtime):
    path = runtime / "service.json"
    if not path.exists():
        return None
    saved = json.loads(path.read_text())
    pid = saved.get("pid")
    if type(pid) is not int or pid <= 1 or saved.get("identity") != process_identity(pid):
        return None
    expected = str(binary(runtime))
    if expected not in saved["identity"] or str(runtime / "config.json") not in saved["identity"]:
        return None
    return saved


def status(runtime):
    current = managed(runtime)
    healthy = False
    if current:
        try:
            json_get(f"http://127.0.0.1:{QUERY_PORT}/api/services")
            healthy = True
        except (OSError, ValueError):
            pass
    return {"status": "running" if healthy else "unhealthy" if current else "stopped",
            "pid": current["pid"] if current else None,
            "ui": f"http://127.0.0.1:{QUERY_PORT}", "otlp": f"http://127.0.0.1:{HTTP_PORT}/v1/traces",
            "storage": "persistent_badger", "runtime": str(runtime)}


def start(runtime):
    with work_lock(runtime / "service-control"):
        if managed(runtime):
            return status(runtime)
        install(runtime)
        for port in (HTTP_PORT, GRPC_PORT, QUERY_PORT, QUERY_GRPC_PORT, HEALTH_PORT):
            with socket.socket() as check:
                # Match server bind semantics: TIME_WAIT after our clean stop is
                # not an active listener and must not prevent an immediate restart.
                check.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                check.bind(("127.0.0.1", port))
        for name in ("keys", "values"):
            (runtime / "badger" / name).mkdir(parents=True, exist_ok=True)
        config = runtime / "config.json"
        atomic_json(config, configuration(runtime))  # JSON is also valid YAML.
        with (runtime / "jaeger.log").open("ab") as log:
            process = subprocess.Popen([str(binary(runtime)), "--config", str(config)],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
                env={**os.environ, "OTEL_SDK_DISABLED": "true", "OTEL_TRACES_EXPORTER": "none", "OTEL_METRICS_EXPORTER": "none"})
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Jaeger exited during startup; inspect its local log")
            identity = process_identity(process.pid)
            if identity and str(binary(runtime)) in identity:
                atomic_json(runtime / "service.json", {"pid": process.pid, "identity": identity, "startedAt": utc_now()})
                try:
                    json_get(f"http://127.0.0.1:{QUERY_PORT}/api/services")
                    return status(runtime)
                except (OSError, ValueError):
                    pass
            time.sleep(.1)
        raise RuntimeError("Jaeger did not become healthy; retained process identity and log")


def stop(runtime):
    with work_lock(runtime / "service-control"):
        current = managed(runtime)
        if not current:
            return status(runtime)
        pid = current["pid"]
        if os.getpgid(pid) != pid:
            raise ValueError("Managed process no longer owns its group")
        os.killpg(pid, signal.SIGTERM)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process_identity(pid) != current["identity"]:
                return status(runtime)
            time.sleep(.1)
        raise RuntimeError("Jaeger still stopping; preserve Badger and inspect before retrying")


def local_endpoint(value):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path != "/v1/traces" or not parsed.port):
        raise ValueError("Delivery requires an explicit loopback OTLP HTTP endpoint")
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "OTLP redirects are disabled", headers, fp)


def deliver(directory, *, endpoint=f"http://127.0.0.1:{HTTP_PORT}/v1/traces", site="macbook"):
    local_endpoint(endpoint)
    if site not in {"macbook", "spark", "cloud", "test"}:
        raise ValueError("Unknown execution site")
    directory = Path(directory).resolve()
    payload, diagnostics = export(directory)
    for resource in payload["resourceSpans"]:
        if site == "test":
            for attribute in resource["resource"]["attributes"]:
                if attribute["key"] == "service.name":
                    attribute["value"] = {"stringValue": "sermon-harness-verification"}
        resource["resource"]["attributes"].append({"key": "sermon.execution.site", "value": {"stringValue": site}})
    spans = [span for r in payload["resourceSpans"] for s in r["scopeSpans"] for span in s["spans"]]
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    receipt = {"schemaVersion": "sermon-otlp-delivery-v1", "checkedAt": utc_now(), "status": "pending",
               "payloadSha256": hashlib.sha256(body).hexdigest(), "spans": len(spans),
               "traceIds": sorted({span["traceId"] for span in spans}),
               "sourceStatus": diagnostics["status"], "diagnosticCount": len(diagnostics["diagnostics"]),
               "site": site, "approvalGranted": False}
    folder = directory / "telemetry"
    atomic_json(folder / "payload.json", payload)
    atomic_json(folder / "diagnostics.json", diagnostics)
    atomic_json(folder / "delivery.json", receipt)
    if not spans:
        receipt["status"] = "nothing_completed_to_send"
        atomic_json(folder / "delivery.json", receipt)
        return receipt
    try:
        request = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect).open(request, timeout=10) as response:
            result = json.loads(response.read() or b"{}")
        if not isinstance(result, dict) or not isinstance(result.get("partialSuccess", {}), dict):
            raise ValueError("Invalid OTLP acceptance response")
        partial = result.get("partialSuccess", {})
        if int(partial.get("rejectedSpans", 0)) != 0 or partial.get("errorMessage"):
            raise ValueError("Collector reported partial acceptance")
    except (OSError, ValueError, TypeError) as exc:
        receipt.update(status="delivery_failed", errorType=type(exc).__name__)
    else:
        receipt["status"] = "collector_accepted"
    atomic_json(folder / "delivery.json", receipt)
    return receipt


def watch_cycle(directories, previous, *, endpoint, site):
    results = []
    for directory in directories:
        source = directory / "events.jsonl"
        try:
            if not source.exists():
                continue
            digest = sha(source)
            if previous.get(str(directory)) == digest:
                continue
            receipt = deliver(directory, endpoint=endpoint, site=site)
            if receipt["status"] in {"collector_accepted", "nothing_completed_to_send"}:
                previous[str(directory)] = digest
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            receipt = {"status": "source_failed", "errorType": type(exc).__name__,
                       "sourceSha256": hashlib.sha256(str(directory).encode()).hexdigest()}
        results.append(receipt)
    return results


def watch(directories, *, scan_roots=(), interval=2, endpoint=f"http://127.0.0.1:{HTTP_PORT}/v1/traces", site="macbook", ready_file=None):
    if not math.isfinite(interval) or interval < .5 or interval > 60:
        raise ValueError("Watch interval must be between 0.5 and 60 seconds")
    local_endpoint(endpoint)
    if ready_file is not None:
        atomic_json(ready_file, {"pid": os.getpid(), "identity": process_identity(os.getpid()), "readyAt": utc_now()})
    previous = {}
    while True:
        found = set(directories)
        for root in scan_roots:
            try:
                found.update(path.parent for path in root.glob("**/accounting/events.jsonl"))
            except OSError as exc:
                print(json.dumps({"status": "scan_failed", "errorType": type(exc).__name__}), flush=True)
        for receipt in watch_cycle(sorted(found), previous, endpoint=endpoint, site=site):
            print(json.dumps(receipt), flush=True)
        time.sleep(interval)


def observer_managed(runtime):
    path = runtime / "observer.json"
    if not path.exists():
        return None
    saved = json.loads(path.read_text())
    pid = saved.get("pid")
    if (type(pid) is not int or pid <= 1 or saved.get("identity") != process_identity(pid)
            or str(Path(__file__).resolve()) + " watch " not in saved.get("identity", "")):
        return None
    return saved


def observer_status(runtime):
    saved = observer_managed(runtime)
    return {"status": "running" if saved else "stopped", "pid": saved["pid"] if saved else None,
            "configuration": saved.get("configuration") if saved else None}


def observer_start(runtime, directories, scan_roots, *, endpoint, site, interval):
    local_endpoint(endpoint)
    if not math.isfinite(interval) or not .5 <= interval <= 60:
        raise ValueError("Observer interval must be between 0.5 and 60 seconds")
    configuration = {"accountingDirectories": [str(p.resolve()) for p in directories],
                     "scanRoots": [str(p.resolve()) for p in scan_roots], "endpoint": endpoint, "site": site}
    with work_lock(runtime / "observer-control"):
        existing = observer_managed(runtime)
        if existing:
            if existing.get("configuration") != configuration:
                raise ValueError("Observer configuration differs; stop the managed observer before changing it")
            return observer_status(runtime)
        command = [sys.executable, str(Path(__file__).resolve()), "watch", "--endpoint", endpoint,
                   "--site", site, "--interval", str(interval)]
        ready = runtime / ("observer-ready-" + uuid.uuid4().hex + ".json")
        command += ["--ready-file", str(ready)]
        for option, paths in (("--accounting-dir", directories), ("--scan-root", scan_roots)):
            for path in paths:
                command += [option, str(path.resolve())]
        runtime.mkdir(parents=True, exist_ok=True)
        with (runtime / "observer.log").open("ab") as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Observer exited; inspect retained observer log")
            handshake = json.loads(ready.read_text()) if ready.exists() else {}
            identity = process_identity(process.pid)
            if (handshake.get("pid") == process.pid and handshake.get("identity") == identity
                    and identity and str(Path(__file__).resolve()) + " watch " in identity):
                atomic_json(runtime / "observer.json", {"pid": process.pid, "identity": identity,
                    "configuration": configuration, "startedAt": utc_now()})
                return observer_status(runtime)
            time.sleep(.1)
        raise RuntimeError("Observer process identity could not be verified")


def observer_stop(runtime):
    with work_lock(runtime / "observer-control"):
        saved = observer_managed(runtime)
        if not saved:
            return observer_status(runtime)
        if os.getpgid(saved["pid"]) != saved["pid"]:
            raise ValueError("Observer does not own its process group")
        os.killpg(saved["pid"], signal.SIGTERM)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and observer_managed(runtime):
            time.sleep(.1)
        if observer_managed(runtime):
            raise RuntimeError("Observer still stopping; inspect its local process")
        return observer_status(runtime)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "start", "stop", "status", "send", "watch", "observer-start", "observer-stop", "observer-status"))
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--accounting-dir", type=Path, action="append", default=[])
    parser.add_argument("--scan-root", type=Path, action="append", default=[])
    parser.add_argument("--ready-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--site", choices=("macbook", "spark", "cloud", "test"), default="macbook")
    parser.add_argument("--endpoint", default=f"http://127.0.0.1:{HTTP_PORT}/v1/traces")
    parser.add_argument("--interval", type=float, default=2)
    args = parser.parse_args(argv)
    try:
        if args.action in {"observer-start", "observer-stop", "observer-status"}:
            runtime = args.runtime.resolve()
            if args.action == "observer-start":
                if not args.accounting_dir and not args.scan_root:
                    raise ValueError("Observer requires explicit accounting directories or scan roots")
                result = observer_start(runtime, args.accounting_dir, args.scan_root,
                    endpoint=args.endpoint, site=args.site, interval=args.interval)
            else:
                result = observer_stop(runtime) if args.action == "observer-stop" else observer_status(runtime)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.action in {"send", "watch"}:
            if not args.accounting_dir and not (args.action == "watch" and args.scan_root):
                raise ValueError("At least one explicit accounting directory is required")
            if args.action == "watch":
                watch(args.accounting_dir, scan_roots=args.scan_root, interval=args.interval, endpoint=args.endpoint, site=args.site, ready_file=args.ready_file)
                return 0
            result = [deliver(path, endpoint=args.endpoint, site=args.site) for path in args.accounting_dir]
            print(json.dumps(result, ensure_ascii=False))
            return int(any(r["status"] == "delivery_failed" for r in result))
        result = {"install": install, "start": start, "stop": stop, "status": status}[args.action](args.runtime.resolve())
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "failed", "errorType": type(exc).__name__, "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
