#!/usr/bin/env python3
"""The local service behind the review pages: serves apps/review-web and accepts decisions.

    python3 tools/ops/review_gate_server.py serve --work-root <checkout that holds artifacts/> --port 8444

It listens on the loopback address only. Other devices reach it through Tailscale Serve, which
adds tailnet-only HTTPS and tells this service who is asking:

    tailscale serve --bg --https=8444 http://127.0.0.1:8444

  GET  /api/gates?production=NAME          the steps of one production (newest when NAME is absent)
  GET  /api/gate?production=NAME&gate=ID   one step: what the page shows and the hashes it binds
  GET  /files/NAME/ID/<path>               that step's media, with Range support
  POST /api/decisions                      one decision; written once, never rewritten

A decision is accepted only for the open revision and only when it echoes that revision's
hashes. Accepting it writes no receipt and approves nothing: the driver (weekly_auto.py) checks
the hashes against the files and then acts. The reviewer is the Tailscale identity that Serve
puts in the request headers; a request that did not come through Serve is recorded as local.

Requests whose Host is not this Mac's loopback or tailnet name are refused, so a web page
elsewhere cannot reach this service through the reviewer's browser. Standard library only.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_gates  # noqa: E402
from review_gates import GateError  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "apps" / "review-web"
MAX_BODY = 2 * 1024 * 1024
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".mjs": "text/javascript; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8"}
MEDIA_TYPES = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "video/mp4", ".png": "image/png"}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "media-src 'self' blob:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
TAILSCALE_PATHS = ("/Applications/Tailscale.app/Contents/MacOS/Tailscale", "/opt/homebrew/bin/tailscale", "/usr/local/bin/tailscale")


def tailnet_name() -> str | None:
    """This Mac's tailnet DNS name, or None when Tailscale is not there."""
    for binary in TAILSCALE_PATHS:
        if not Path(binary).exists():
            continue
        try:
            done = subprocess.run([binary, "status", "--json"], capture_output=True, text=True, timeout=10, check=False)
            name = json.loads(done.stdout)["Self"]["DNSName"].rstrip(".")
            return name or None
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            return None
    return None


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """(first, last) for a single bytes range, None when there is no usable Range header."""
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", (header or "").strip())
    if not match or (not match.group(1) and not match.group(2)):
        return None
    if not match.group(1):                                   # suffix: the last N bytes
        length = int(match.group(2))
        return (max(0, size - length), size - 1) if length else None
    first = int(match.group(1))
    last = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
    return (first, last) if first <= last and first < size else (-1, -1)


class Handler(BaseHTTPRequestHandler):
    server_version = "ReviewGate/1"
    protocol_version = "HTTP/1.1"

    # ---- plumbing
    def log_message(self, fmt, *args):                       # method, path and status only: no bodies, no identities
        sys.stderr.write(f"{self.log_date_time_string()} {fmt % args}\n")

    def _headers(self, status: int, content_type: str, length: int, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()

    def _json(self, status: int, value) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        if self.command != "HEAD":
            self.wfile.write(body)

    def _fail(self, error: GateError) -> None:
        self.close_connection = True                         # a refused POST may leave its body unread
        self._json(error.status, {"code": error.code, "message": error.message})

    def _host_allowed(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        return host in self.server.allowed_hosts

    def viewer(self) -> dict:
        login = self.headers.get("Tailscale-User-Login")
        if login:
            return {"login": login, "name": self.headers.get("Tailscale-User-Name") or login, "source": "tailscale"}
        return {"login": f"local:{self.server.local_user}", "name": self.server.local_user, "source": "local"}

    def _file(self, path: Path, content_type: str) -> None:
        size = path.stat().st_size
        span = parse_range(self.headers.get("Range"), size)
        if span == (-1, -1):
            self._headers(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, content_type, 0, {"Content-Range": f"bytes */{size}"})
            return
        first, last = span if span else (0, size - 1)
        length = max(0, last - first + 1)
        extra = {"Accept-Ranges": "bytes"}
        if span:
            extra["Content-Range"] = f"bytes {first}-{last}/{size}"
        self._headers(HTTPStatus.PARTIAL_CONTENT if span else HTTPStatus.OK, content_type, length, extra)
        if self.command == "HEAD":
            return
        with path.open("rb") as handle:
            handle.seek(first)
            remaining = length
            while remaining > 0:
                block = handle.read(min(1 << 16, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)

    # ---- routes
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            if not self._host_allowed():
                raise GateError(403, "forbidden_host", "不认识的主机名")
            url = urlsplit(self.path)
            query = {name: values[0] for name, values in parse_qs(url.query).items()}
            path = unquote(url.path)
            store = self.server.store
            if path == "/api/gates":
                production = query.get("production") or (store.productions() or [None])[0]
                if not production:
                    raise GateError(404, "no_production", "还没有生产")
                return self._json(200, store.index(production))
            if path == "/api/gate":
                return self._json(200, store.descriptor(query.get("production", ""), query.get("gate", ""), self.viewer()))
            if path.startswith("/files/"):
                parts = path.split("/", 4)
                if len(parts) < 5:
                    raise GateError(404, "unknown_asset", "没有这个文件")
                asset = store.asset(parts[2], parts[3], parts[4])
                content_type = MEDIA_TYPES.get(asset.suffix.lower())
                if not content_type:
                    raise GateError(404, "unknown_asset", "没有这个文件")
                return self._file(asset, content_type)
            relative = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (self.server.web_root / relative).resolve()
            if (not target.is_relative_to(self.server.web_root) or not target.is_file()
                    or target.suffix not in STATIC_TYPES or target.name.startswith(".")):
                raise GateError(404, "not_found", "没有这个页面")
            return self._file(target, STATIC_TYPES[target.suffix])
        except GateError as error:
            self._fail(error)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        try:
            if not self._host_allowed():
                raise GateError(403, "forbidden_host", "不认识的主机名")
            origin = self.headers.get("Origin")
            if origin and (urlsplit(origin).hostname or "").lower() not in self.server.allowed_hosts:
                raise GateError(403, "forbidden_origin", "不接受来自其他网站的提交")
            if urlsplit(self.path).path != "/api/decisions":
                raise GateError(404, "not_found", "没有这个接口")
            if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
                raise GateError(415, "unsupported_type", "只接受 JSON")
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= MAX_BODY:
                raise GateError(413, "too_large", "提交内容为空或太大")
            try:
                decision = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise GateError(400, "invalid_json", "不是合法的 JSON") from exc
            viewer = self.viewer()
            allowed = self.server.allowed_logins
            if allowed and viewer["login"] not in allowed:
                raise GateError(403, "not_a_reviewer", "这个身份不能提交决定")
            if not isinstance(decision, dict):
                raise GateError(400, "invalid_decision", "决定必须是一个 JSON 对象")
            record = self.server.store.record_decision(decision, viewer)
            self._json(202, {"decisionId": record["decisionId"], "reviewer": record["reviewer"]["name"], "outcome": "queued"})
            if self.server.on_decision:
                self.server.on_decision(record["decision"]["production"])
        except GateError as error:
            self._fail(error)
        except (BrokenPipeError, ConnectionResetError):
            pass


def make_server(work_root: Path, *, port: int, bind: str = "127.0.0.1", web_root: Path = WEB_ROOT,
                allowed_hosts: set[str] | None = None, allowed_logins: set[str] | None = None,
                on_decision=None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((bind, port), Handler)
    server.daemon_threads = True
    server.store = review_gates.Store(work_root)
    server.web_root = Path(web_root).resolve()
    server.allowed_hosts = {"127.0.0.1", "localhost", "::1"} | {host.lower() for host in (allowed_hosts or set())}
    server.allowed_logins = set(allowed_logins or ())
    server.local_user = getpass.getuser()
    server.on_decision = on_decision
    return server


def spawn_apply(work_root: Path):
    """After a decision is stored, start the driver for that production and return at once."""
    driver = Path(__file__).resolve().with_name("weekly_auto.py")

    def run(production: str) -> None:
        log = (review_gates.Store(work_root).production_dir(production) / "driver.log").open("ab")
        subprocess.Popen([sys.executable, str(driver), "--work-root", str(work_root), "apply", "--production", production],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, cwd=str(ROOT))
    return run


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="serve the review pages and accept decisions")
    serve.add_argument("--work-root", type=Path, default=ROOT, help="the checkout whose artifacts/ holds the productions")
    serve.add_argument("--port", type=int, default=8444)
    serve.add_argument("--bind", default="127.0.0.1")
    serve.add_argument("--allow-non-loopback", action="store_true", help="needed to bind anything but the loopback address")
    serve.add_argument("--allow-host", action="append", default=[], help="extra Host name to accept (the tailnet name is added by itself)")
    serve.add_argument("--allow-login", action="append", default=[], help="only these identities may submit decisions")
    serve.add_argument("--no-apply", action="store_true", help="store decisions but do not start the driver")
    args = parser.parse_args(argv)
    if args.bind not in ("127.0.0.1", "::1", "localhost") and not args.allow_non_loopback:
        raise SystemExit("refusing to listen beyond the loopback address; put Tailscale Serve in front instead")
    hosts = set(args.allow_host)
    name = tailnet_name()
    if name:
        hosts.add(name)
    server = make_server(args.work_root, port=args.port, bind=args.bind, allowed_hosts=hosts,
                         allowed_logins=set(args.allow_login), on_decision=None if args.no_apply else spawn_apply(args.work_root))
    print(json.dumps({"listening": f"http://{args.bind}:{args.port}", "workRoot": str(Path(args.work_root).resolve()),
                      "tailnetName": bool(name), "pid": os.getpid()}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
