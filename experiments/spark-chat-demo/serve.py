#!/usr/bin/env python3
"""Tiny LAN-facing chat front end for the throwaway Qwen3.8 demo.

Serves one static page and proxies the OpenAI-compatible chat endpoint to the
llama-server instance on loopback, streaming the SSE body straight through.
Standard library only: nothing to install, nothing to uninstall.
"""
from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
STATE = HERE.parent / "state" / "install.json"


def load_model_info() -> dict:
    try:
        return json.loads(STATE.read_text())["model"]
    except Exception:
        return {"name": "qwen3.8-demo", "path": "unknown", "sha256": ""}


class Handler(BaseHTTPRequestHandler):
    upstream = "http://127.0.0.1:8080"
    model = load_model_info()
    log_path: Path | None = None
    server_version = "spark-chat-demo/1"
    protocol_version = "HTTP/1.1"

    # ---------------------------------------------------------------- helpers
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _journal(self, entry: dict) -> None:
        if self.log_path is None:
            return
        try:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def log_message(self, fmt: str, *args) -> None:  # quieter than the default
        sys.stderr.write("%s %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    # ---------------------------------------------------------------- routes
    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            page = (HERE / "index.html").read_bytes()
            self._send(200, page, "text/html; charset=utf-8")
            return
        if self.path == "/healthz":
            payload = {"status": "ok", "model": self.model.get("name"),
                       "sha256": self.model.get("sha256", "")[:16],
                       "upstream": self.upstream}
            self._send(200, json.dumps(payload).encode())
            return
        if self.path.startswith("/v1/models"):
            self._proxy("GET", b"")
            return
        self._send(404, b'{"error":"not_found"}')

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/v1/"):
            self._send(404, b'{"error":"not_found"}')
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self._proxy("POST", body)

    # ---------------------------------------------------------------- proxy
    def _proxy(self, method: str, body: bytes) -> None:
        started = time.time()
        request = urllib.request.Request(
            self.upstream + self.path, data=body if method == "POST" else None, method=method,
            headers={"Content-Type": "application/json", "Accept": self.headers.get("Accept", "*/*")})
        try:
            with urllib.request.urlopen(request, timeout=600) as upstream:
                ctype = upstream.headers.get("Content-Type", "application/json")
                streaming = _wants_stream(body) or "text/event-stream" in ctype
                if streaming:
                    self.send_response(200)
                    self.send_header("Content-Type", ctype or "text/event-stream")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    self._relay(upstream, started, body)
                else:
                    payload = upstream.read()
                    self._send(200, payload, ctype)
                    self._journal({"at": time.time(), "path": self.path, "mode": "buffered",
                                   "seconds": round(time.time() - started, 3), "bytes": len(payload),
                                   "request": _request_summary(body)})
        except urllib.error.HTTPError as error:
            payload = error.read()
            self._send(error.code, payload, error.headers.get("Content-Type", "application/json"))
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            self._send(502, json.dumps({"error": "upstream_unavailable", "detail": str(error)}).encode())

    def _relay(self, upstream, started: float, body: bytes) -> None:
        """Copy the SSE stream through as HTTP/1.1 chunks and journal the run."""
        events = 0
        total = 0
        first_byte_at = None
        try:
            while True:
                line = upstream.readline()
                if not line:
                    break
                if first_byte_at is None:
                    first_byte_at = time.time()
                total += len(line)
                if line.startswith(b"data:"):
                    events += 1
                self.wfile.write(b"%x\r\n%s\r\n" % (len(line), line))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except OSError:
                pass
            self._journal({"at": time.time(), "path": self.path, "mode": "stream",
                           "seconds": round(time.time() - started, 3),
                           "ttftSeconds": round((first_byte_at - started), 3) if first_byte_at else None,
                           "events": events, "bytes": total, "request": _request_summary(body)})


def _wants_stream(body: bytes) -> bool:
    try:
        return bool(json.loads(body or b"{}").get("stream"))
    except Exception:
        return b'"stream":true' in body.replace(b" ", b"")


def _request_summary(body: bytes) -> dict:
    try:
        data = json.loads(body or b"{}")
    except Exception:
        return {}
    messages = data.get("messages") or []
    return {"turns": len(messages), "thinking": (data.get("chat_template_kwargs") or {}).get("enable_thinking", True),
            "lastChars": len(messages[-1].get("content", "")) if messages else 0,
            "maxTokens": data.get("max_tokens")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--upstream", default="http://127.0.0.1:8080")
    parser.add_argument("--log", default=str(HERE.parent / "logs" / "chat.jsonl"))
    args = parser.parse_args()

    Handler.upstream = args.upstream.rstrip("/")
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    Handler.log_path = log_path

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(json.dumps({"status": "listening", "url": f"http://{args.host}:{args.port}/",
                      "upstream": Handler.upstream, "log": str(log_path)}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
