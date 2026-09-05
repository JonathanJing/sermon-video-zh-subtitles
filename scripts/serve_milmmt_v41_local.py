#!/usr/bin/env python3
"""Independent, loopback-only v4.1 experimental translation service and launcher."""
from __future__ import annotations

import argparse
from concurrent.futures import Future
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.metadata
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser

def official_prompt(source: str) -> str:
    """Frozen source-only MiLMMT A0 prompt; never apply a chat template."""
    return ("Translate this from English to Chinese (Simplified):\n"
            f"English: {source}\nChinese (Simplified):")

SERVICE = "milmmt-v41-local-experimental-v1"
MANIFEST_SHA = "5f313eadf8951eb3251056686fee965feae3d189b2a6cbe844118982d0d27179"
WEIGHTS_SHA = "6057e793922b8aa0c30c5180b490d8e5cac14a3dcd1a000b1b906d0da8fa6987"
MODEL = Path.home() / "Models/milmmt-sermon-v41-experimental-mlx-q5"
STATE_DIR = Path.home() / "Library/Caches/sermon-video-zh-subtitles/milmmt-v41-local"
PAGE = Path(__file__).resolve().parents[1] / "experiments/milmmt-v41-local/index.html"
MAX_SOURCE = 2048
MAX_PROMPT_TOKENS = 1024
MAX_BODY = 16384
MAX_SECONDS = 90
WARMUP = "God loves us, and he calls us to love one another."


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verify_package(model):
    """Bind the service to the exact previously tested package, before loading."""
    if digest(model / "EXPERIMENTAL.json") != MANIFEST_SHA:
        raise ValueError("experimental package identity differs from tested v4.1")
    manifest = json.loads((model / "EXPERIMENTAL.json").read_text())
    for record in manifest["coreFiles"]:
        path = model / record["name"]
        if path.stat().st_size != record["bytes"] or digest(path) != record["sha256"]:
            raise ValueError(f"model package checksum failed: {record['name']}")
    if {p.name for p in model.glob("*.safetensors")} != {"model.safetensors"}:
        raise ValueError("unexpected additional model or adapter weights")
    packages = {name: importlib.metadata.version(name) for name in manifest["runtimePackages"]}
    if packages != manifest["runtimePackages"]:
        raise ValueError("runtime versions differ from the tested package")
    return packages


class RequestError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def validate_request(value):
    if not isinstance(value, dict) or set(value) - {"text", "stream"}:
        raise RequestError("请求只接受 text 和可选的 stream。")
    source = value.get("text")
    if not isinstance(source, str) or not source.strip():
        raise RequestError("请输入英文原文。")
    if len(source) > MAX_SOURCE:
        raise RequestError(f"请每次输入不超过 {MAX_SOURCE} 个字符。", 413)
    if any(ord(c) < 32 and c not in "\n\r\t" for c in source) or any(0xD800 <= ord(c) <= 0xDFFF for c in source):
        raise RequestError("原文包含不支持的控制字符。")
    if not isinstance(value.get("stream", False), bool):
        raise RequestError("stream 必须为布尔值。")
    return source, value.get("stream", False)


class MLXEngine:
    """All MLX imports, model loading and generation stay on one worker thread."""
    def __init__(self, model):
        self.packages = verify_package(model)
        import mlx.core as mx
        from mlx_lm import load, stream_generate
        from mlx_lm.sample_utils import make_sampler
        self.mx, self.stream_generate = mx, stream_generate
        self.sampler = make_sampler(temp=0)
        self.model, self.tokenizer = load(str(model), lazy=False,
                                         tokenizer_config={"trust_remote_code": False})
        if set(self.tokenizer.eos_token_ids) != {1, 106}:
            raise ValueError("unexpected EOS configuration")

    def translate(self, source, emit, cancelled):
        started = time.perf_counter()
        prompt = self.tokenizer.encode(official_prompt(source), add_special_tokens=False)
        if len(prompt) > MAX_PROMPT_TOKENS:
            raise RequestError("原文分词后过长，请拆成更短的段落。", 413)
        self.mx.random.seed(42)
        last, first_chinese, parts, token_ids = None, None, [], []
        generator = self.stream_generate(self.model, self.tokenizer, prompt,
                                        max_tokens=512, sampler=self.sampler, prompt_cache=None)
        try:
            for response in generator:
                if cancelled.is_set():
                    raise RequestError("翻译已取消。", 499)
                elapsed = time.perf_counter() - started
                if elapsed > MAX_SECONDS:
                    raise RequestError("翻译超时，请缩短原文后重试。", 504)
                parts.append(response.text)
                token_ids.append(int(response.token))
                if first_chinese is None and any("\u3400" <= c <= "\u9fff" for c in response.text):
                    first_chinese = elapsed * 1000
                if response.text:
                    emit({"type": "delta", "text": response.text})
                last = response
        finally:
            generator.close()
            self.mx.synchronize()
        if last is None or last.finish_reason != "stop" or not "".join(parts).strip():
            raise RequestError("输出未完整结束，请缩短原文后重试。", 422)
        return {"text": "".join(parts), "source": source, "finishReason": "stop",
                "promptTokens": len(prompt), "generatedTokens": last.generation_tokens,
                "generatedTokenIdsSha256": hashlib.sha256(json.dumps(token_ids, separators=(",", ":")).encode()).hexdigest(),
                "firstChineseMs": first_chinese, "elapsedMs": (time.perf_counter() - started) * 1000,
                "timingScope": "worker tokenization through synchronized generation; includes stream backpressure, excludes request transit and UI paint",
                "experimental": True, "releaseEligible": False, "modelSha256": WEIGHTS_SHA}


class Job:
    def __init__(self, source):
        self.source = source
        self.events = queue.Queue(maxsize=64)
        self.cancelled = threading.Event()
        self.result = Future()

    def emit(self, event):
        while not self.cancelled.is_set():
            try:
                self.events.put(event, timeout=0.1)
                return
            except queue.Full:
                continue
        raise RequestError("连接已断开。", 499)


class Runtime:
    def __init__(self, model, instance, engine_factory=MLXEngine):
        self.model, self.instance, self.engine_factory = model, instance, engine_factory
        self.lock = threading.Lock()
        self.jobs = queue.Queue(maxsize=1)
        self.stopping = threading.Event()
        self.status, self.busy, self.packages, self.error = "loading", False, {}, None
        self.active = None
        self.started = datetime.now(timezone.utc).isoformat()
        self.worker = threading.Thread(target=self.run, name="v41-mlx-worker", daemon=True)

    def health(self):
        with self.lock:
            return {"service": SERVICE, "instanceId": self.instance, "pid": os.getpid(),
                    "status": self.status, "busy": self.busy, "startedAt": self.started,
                    "model": "MiLMMT v4.1 · MLX Q5 · experimental", "modelSha256": WEIGHTS_SHA,
                    "packageSha256": MANIFEST_SHA, "runtimePackages": self.packages,
                    "releaseEligible": False, "error": self.error}

    def submit(self, source):
        with self.lock:
            if self.status != "ready":
                raise RequestError("模型尚未就绪，请稍后重试；失败时重新启动。", 503)
            if self.busy:
                raise RequestError("模型正在翻译，请完成后再试。", 429)
            job = Job(source)
            self.busy, self.active = True, job
            self.jobs.put_nowait(job)
            return job

    def run(self):
        try:
            engine = self.engine_factory(self.model)
            engine.translate(WARMUP, lambda _: None, self.stopping)
            with self.lock:
                self.packages, self.status = engine.packages, "ready"
            print("v4.1 package verified; model loaded and warmup finished.", flush=True)
        except Exception as exc:
            with self.lock:
                self.status, self.error = "failed", "模型校验、加载或预热失败，请检查本地日志。"
            print(f"Model initialization failed: {type(exc).__name__}: {exc}", flush=True)
            return
        while not self.stopping.is_set():
            try:
                job = self.jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                result = engine.translate(job.source, job.emit, job.cancelled)
                job.result.set_result(result)
            except RequestError as exc:
                job.result.set_exception(exc)
            except Exception as exc:
                with self.lock:
                    self.status, self.error = "failed", "模型运行失败，请重新启动本地服务。"
                print(f"Generation failed: {type(exc).__name__}", flush=True)
                job.result.set_exception(RequestError(self.error, 503))
            finally:
                with self.lock:
                    self.busy, self.active = False, None

    def stop(self):
        self.stopping.set()
        with self.lock:
            self.status = "stopping"
            if self.active:
                self.active.cancelled.set()
        self.worker.join(timeout=15)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Never log user source text, output, request bodies or query strings.

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def allowed(self):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        return (self.headers.get("Host") in hosts and
                (not self.headers.get("Origin") or self.headers["Origin"] in {"http://" + h for h in hosts}))

    def send_headers(self, status, content_type, length=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Connection", "close")
        self.end_headers()

    def json_response(self, status, value):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_headers(status, "application/json; charset=utf-8", len(data))
        self.wfile.write(data)

    def do_GET(self):
        if not self.allowed():
            return self.json_response(403, {"error": "仅允许本机入口访问。"})
        if self.path == "/api/health":
            return self.json_response(200, self.server.runtime.health())
        if self.path == "/":
            data = PAGE.read_bytes()
            self.send_headers(200, "text/html; charset=utf-8", len(data))
            return self.wfile.write(data)
        self.json_response(404, {"error": "未找到。"})

    def do_POST(self):
        job, streaming_started = None, False
        try:
            if not self.allowed():
                raise RequestError("仅允许本机入口访问。", 403)
            if self.path != "/api/translate":
                raise RequestError("未找到。", 404)
            if self.headers.get_content_type() != "application/json":
                raise RequestError("请发送 application/json。", 415)
            if self.headers.get("Transfer-Encoding"):
                raise RequestError("不支持 Transfer-Encoding。")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise RequestError("Content-Length 无效。")
            if length <= 0 or length > MAX_BODY:
                raise RequestError("请求大小超出限制。", 413)
            try:
                body = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeError):
                raise RequestError("JSON 格式无效。")
            source, stream = validate_request(body)
            job = self.server.runtime.submit(source)
            if stream:
                self.send_headers(200, "application/x-ndjson; charset=utf-8")
                streaming_started = True
            deadline = time.monotonic() + MAX_SECONDS + 10
            while True:
                try:
                    event = job.events.get(timeout=0.05)
                    if stream:
                        self.write_event(event)
                except queue.Empty:
                    pass
                if job.result.done() and job.events.empty():
                    result = job.result.result()
                    if stream:
                        self.write_event({"type": "done", **result})
                    else:
                        self.json_response(200, result)
                    return
                if time.monotonic() > deadline:
                    raise RequestError("翻译等待超时，请重试。", 504)
        except RequestError as exc:
            if streaming_started:
                self.write_event({"type": "error", "error": str(exc), "status": exc.status, "complete": False})
            else:
                self.json_response(exc.status, {"error": str(exc), "complete": False})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        finally:
            if job:
                job.cancelled.set()

    def write_event(self, value):
        self.wfile.write((json.dumps(value, ensure_ascii=False) + "\n").encode())
        self.wfile.flush()


def fetch_health(port):
    try:
        # Local requests must never go through a configured HTTP proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
            return json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return None


def is_ours(health):
    return isinstance(health, dict) and health.get("service") == SERVICE and health.get("packageSha256") == MANIFEST_SHA


def write_state(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def serve(args):
    # Held for the entire process lifetime, including model loading and shutdown.
    lifetime_lock = (args.state_dir / "service.lock").open("a")
    try:
        fcntl.flock(lifetime_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lifetime_lock.close()
        raise RuntimeError("此运行目录已有服务，请先停止或使用独立 --state-dir。")
    runtime = Runtime(args.model, args.instance_id)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.runtime = runtime
    state_path = args.state_dir / "service.json"
    write_state(state_path, {"pid": os.getpid(), "instanceId": args.instance_id, "port": args.port,
                            "script": str(Path(__file__).resolve()), "model": str(args.model)})
    def shutdown(*_):
        runtime.stopping.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    runtime.worker.start()
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        runtime.stop()
        server.server_close()
        if state_path.exists() and json.loads(state_path.read_text()).get("instanceId") == args.instance_id:
            state_path.unlink()
        lifetime_lock.close()


@contextmanager
def control_lock(state_dir):
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state_dir / "control.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def start(args):
    state_path = args.state_dir / "service.json"
    state = None
    if state_path.exists():
        state = json.loads(state_path.read_text())
        recorded = fetch_health(state["port"])
        if is_ours(recorded) and recorded["instanceId"] == state["instanceId"]:
            if state["port"] != args.port or state["model"] != str(args.model):
                raise RuntimeError("此运行目录已有不同配置的服务；先停止，或使用独立 --state-dir。")
    health = fetch_health(args.port)
    if health and not is_ours(health):
        raise RuntimeError("指定端口有其他服务；未改动该服务。")
    if is_ours(health) and (not state or state.get("instanceId") != health.get("instanceId") or state.get("pid") != health.get("pid")):
        raise RuntimeError("指定端口属于另一个运行目录，未接管该服务；请使用其原启动入口。")
    if not health:
        instance = str(uuid.uuid4())
        log_path = args.state_dir / "server.log"
        with log_path.open("a") as log:
            log_path.chmod(0o600)
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "serve",
                                        "--port", str(args.port), "--model", str(args.model),
                                        "--state-dir", str(args.state_dir), "--instance-id", instance],
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       start_new_session=True, close_fds=True)
        for _ in range(300):
            health = fetch_health(args.port)
            if process.poll() is not None:
                raise RuntimeError(f"服务启动失败，请查看 {log_path}")
            if is_ours(health) and health["instanceId"] == instance and health["status"] in {"ready", "failed"}:
                break
            time.sleep(0.2)
    if not is_ours(health) or health["status"] != "ready":
        raise RuntimeError(f"模型尚未就绪，请查看 {args.state_dir / 'server.log'}；可用 status 检查、stop 停止。")
    url = f"http://127.0.0.1:{args.port}"
    print(f"v4.1 实验翻译已就绪：{url} （PID {health['pid']}）")
    if args.open:
        webbrowser.open(url)


def stop(args):
    state_path = args.state_dir / "service.json"
    if not state_path.exists():
        print("此入口没有运行中的服务记录。")
        return
    state = json.loads(state_path.read_text())
    health = fetch_health(state["port"])
    if (not is_ours(health) or health["instanceId"] != state["instanceId"] or health["pid"] != state["pid"]):
        raise RuntimeError("无法确认服务进程身份；没有停止任何进程。")
    os.kill(state["pid"], signal.SIGTERM)
    for _ in range(100):
        if not state_path.exists():
            print("v4.1 实验服务已停止。")
            return
        time.sleep(0.2)
    raise RuntimeError("服务仍在关闭中，请稍后检查 status。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status", "serve"])
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--port", type=int, default=18771)
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    parser.add_argument("--instance-id", default=str(uuid.uuid4()))
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    args.model, args.state_dir = args.model.resolve(), args.state_dir.resolve()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    try:
        if args.action == "serve":
            args.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            serve(args)
        elif args.action == "status":
            health = fetch_health(args.port)
            print(json.dumps(health or {"status": "stopped"}, ensure_ascii=False, indent=2))
            return 0 if is_ours(health) and health["status"] == "ready" else 1
        else:
            with control_lock(args.state_dir):
                {"start": start, "stop": stop}[args.action](args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
