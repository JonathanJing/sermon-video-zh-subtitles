from __future__ import annotations

import json
import queue
import re
import secrets
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse


SAFE_EVENT_TYPES = {
    "stream.ready",
    "asr.final",
    "translation.partial",
    "translation.final",
    "translation.failed",
    "translation.skipped",
    "caption.display",
    "stream.closed",
}
SAFE_FIELDS = {
    "type",
    "at",
    "sequence",
    "segmentId",
    "sourceTextEn",
    "targetTextZh",
    "displayKind",
    "phase",
}


@dataclass
class ViewerSession:
    session_id: str
    token: str
    created_at: float
    active: bool = True
    ended_at: float | None = None
    snapshot: dict[str, Any] = field(default_factory=lambda: {
        "type": "caption.snapshot",
        "previousFinal": None,
        "active": {
            "segmentId": "",
            "sourceTextEn": "",
            "targetTextZh": "等待现场字幕…",
            "phase": "listening",
        },
        "sessionActive": True,
    })
    subscribers: set[queue.Queue[dict[str, Any]]] = field(default_factory=set)


class CaptionHub:
    """In-memory, read-only caption fan-out. It never stores audio or control access."""

    def __init__(self, retention_seconds: int = 900) -> None:
        self.retention_seconds = retention_seconds
        self._lock = threading.Lock()
        self._by_token: dict[str, ViewerSession] = {}
        self._token_by_session: dict[str, str] = {}

    def start_session(self, session_id: str, token: str | None = None) -> str:
        with self._lock:
            self._purge_locked()
            existing = self._token_by_session.get(session_id)
            if existing and existing in self._by_token:
                self._by_token[existing].active = True
                self._by_token[existing].ended_at = None
                self._by_token[existing].snapshot["sessionActive"] = True
                return existing
            token = token or secrets.token_urlsafe(18)
            if not re.fullmatch(r"[A-Za-z0-9_-]{24}", token) or token in self._by_token:
                raise ValueError("invalid or conflicting viewer token")
            self._by_token[token] = ViewerSession(session_id, token, time.time())
            self._token_by_session[session_id] = token
            return token

    def publish(self, session_id: str, payload: dict[str, Any]) -> None:
        safe = self._project(payload)
        if not safe:
            return
        with self._lock:
            token = self._token_by_session.get(session_id)
            session = self._by_token.get(token or "")
            if not session:
                return
            session.snapshot = self._update_snapshot(session.snapshot, safe, session.active)
            subscribers = tuple(session.subscribers)
        for subscriber in subscribers:
            self._offer(subscriber, safe)

    def end_session(self, session_id: str) -> None:
        with self._lock:
            token = self._token_by_session.get(session_id)
            session = self._by_token.get(token or "")
            if not session:
                return
            session.active = False
            session.ended_at = time.time()
            session.snapshot = {**session.snapshot, "sessionActive": False}
            subscribers = tuple(session.subscribers)
        for subscriber in subscribers:
            self._offer(subscriber, {"type": "stream.closed"})

    def snapshot(self, token: str) -> dict[str, Any] | None:
        with self._lock:
            self._purge_locked()
            session = self._by_token.get(token)
            return None if not session else dict(session.snapshot)

    def subscribe(self, token: str) -> queue.Queue[dict[str, Any]] | None:
        with self._lock:
            self._purge_locked()
            session = self._by_token.get(token)
            if not session:
                return None
            subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=16)
            session.subscribers.add(subscriber)
            subscriber.put_nowait(dict(session.snapshot))
            return subscriber

    def unsubscribe(self, token: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            session = self._by_token.get(token)
            if session:
                session.subscribers.discard(subscriber)

    @staticmethod
    def _project(payload: dict[str, Any]) -> dict[str, Any] | None:
        if payload.get("displayEligible") is False:
            return None
        if payload.get("type") not in SAFE_EVENT_TYPES:
            return None
        return {key: payload[key] for key in SAFE_FIELDS if key in payload}

    @staticmethod
    def _offer(subscriber: queue.Queue[dict[str, Any]], payload: dict[str, Any]) -> None:
        try:
            subscriber.put_nowait(payload)
        except queue.Full:
            try:
                subscriber.get_nowait()
            except queue.Empty:
                pass
            try:
                subscriber.put_nowait(payload)
            except queue.Full:
                pass

    @staticmethod
    def _update_snapshot(
        snapshot: dict[str, Any],
        event: dict[str, Any],
        session_active: bool,
    ) -> dict[str, Any]:
        previous = snapshot.get("previousFinal")
        active = dict(snapshot.get("active") or {})
        event_type = event["type"]
        if event_type == "asr.final":
            if active.get("phase") == "final" and active.get("sourceTextEn") and active.get("targetTextZh"):
                previous = {
                    "segmentId": active.get("segmentId", ""),
                    "sourceTextEn": active["sourceTextEn"],
                    "targetTextZh": active["targetTextZh"],
                }
            active = {
                "segmentId": event.get("segmentId", ""),
                "sourceTextEn": event.get("sourceTextEn", ""),
                "targetTextZh": "",
                "phase": "requesting",
            }
        elif event_type == "caption.display":
            is_new_segment = bool(
                event.get("segmentId")
                and active.get("segmentId")
                and event["segmentId"] != active["segmentId"]
            )
            if (
                is_new_segment
                and active.get("phase") == "final"
                and active.get("sourceTextEn")
                and active.get("targetTextZh")
            ):
                previous = {
                    "segmentId": active.get("segmentId", ""),
                    "sourceTextEn": active["sourceTextEn"],
                    "targetTextZh": active["targetTextZh"],
                }
            active = {
                "segmentId": event.get("segmentId", active.get("segmentId", "")),
                "sourceTextEn": event.get("sourceTextEn", active.get("sourceTextEn", "")),
                "targetTextZh": event.get("targetTextZh", active.get("targetTextZh", "")),
                "phase": event.get("phase")
                or ("final" if event.get("displayKind") == "final" else "streaming"),
            }
        elif event_type in {"translation.partial", "translation.final", "translation.failed", "translation.skipped"}:
            if event.get("segmentId") and active.get("segmentId") and event["segmentId"] != active["segmentId"]:
                return snapshot
            fallback = {
                "translation.failed": "翻译暂时不可用，请查看英文原文。",
                "translation.skipped": "翻译积压，暂时显示英文原文。",
                "translation.final": "翻译结果为空。",
            }.get(event_type, active.get("targetTextZh", ""))
            active.update({
                "segmentId": event.get("segmentId", active.get("segmentId", "")),
                "sourceTextEn": event.get("sourceTextEn", active.get("sourceTextEn", "")),
                "targetTextZh": event.get("targetTextZh") or fallback,
                "phase": "streaming" if event_type == "translation.partial"
                else "final" if event_type == "translation.final" else "error",
            })
        return {
            "type": "caption.snapshot",
            "previousFinal": previous,
            "active": active,
            "sessionActive": session_active,
        }

    def _purge_locked(self) -> None:
        now = time.time()
        expired = [
            token for token, session in self._by_token.items()
            if not session.active and session.ended_at is not None
            and now - session.ended_at > self.retention_seconds
        ]
        for token in expired:
            session = self._by_token.pop(token)
            self._token_by_session.pop(session.session_id, None)


def local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        address = probe.getsockname()[0]
        if not address.startswith(("127.", "169.254.")):
            addresses.add(address)
    except OSError:
        pass
    finally:
        probe.close()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = item[4][0]
            if not address.startswith(("127.", "169.254.")):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


def viewer_urls(token: str, port: int) -> list[str]:
    return [f"http://{address}:{port}/view/{token}" for address in local_ipv4_addresses()]


VIEWER_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark"><title>现场中文字幕</title>
<style>
:root{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;color:#fff;background:#071827}
*{box-sizing:border-box}body{margin:0;min-height:100dvh;display:grid;grid-template-rows:auto 1fr auto;background:#071827}
header,footer{padding:14px 18px;color:#a9c0cf;font-size:13px}header{display:flex;justify-content:space-between;border-bottom:1px solid #294456}
main{min-height:0;display:grid;grid-template-rows:minmax(96px,.3fr) 1px minmax(0,1fr);text-align:center;padding:2vh 5vw}.previous{align-self:end;padding:1vh 0 3vh}.previous[hidden],.divider[hidden]{display:none}.previous-zh,.previous-en,.zh,.en{margin:0 auto;text-wrap:balance}.previous-zh{max-width:28em;color:#71849e;font-size:clamp(25px,7.4vw,48px);font-weight:700;line-height:1.18}.previous-en{max-width:58ch;margin-top:8px;color:#6f8198;font-size:clamp(14px,4vw,22px);line-height:1.4}.divider{width:min(82%,940px);height:1px;margin:auto;background:#294456}.current{min-height:0;display:flex;flex-direction:column;justify-content:center;padding:3vh 0 5vh}.zh{font-size:clamp(48px,13vw,104px);font-weight:800;line-height:1.15}.en{margin-top:24px;max-width:55ch;color:#a9c0cf;font-size:clamp(17px,4vw,25px);line-height:1.45}
.ok{color:#8dd6ba}.waiting{color:#f0cc83}button{min-width:44px;min-height:44px;border:1px solid #70839a;border-radius:999px;background:transparent;color:#fff;font-size:20px}
footer{display:flex;justify-content:space-between;align-items:center;border-top:1px solid #294456}.controls{display:flex;gap:10px}
@media(orientation:landscape) and (max-height:560px){header,footer{padding-block:8px}main{grid-template-rows:minmax(58px,.24fr) 1px minmax(0,1fr);padding-block:1vh}.previous{padding-bottom:8px}.previous-zh{font-size:clamp(20px,4vw,32px)}.previous-en{font-size:14px}.current{padding:8px 0}.zh{font-size:clamp(40px,8.5vw,76px)}.en{margin-top:10px}}
</style></head><body><header><strong>现场中文字幕</strong><span id="status" class="waiting">正在连接…</span></header>
<main><section id="previous" class="previous" hidden><p id="previous-zh" class="previous-zh"></p><p id="previous-en" class="previous-en"></p></section><div id="divider" class="divider" hidden></div><section id="current" class="current"><p id="zh" class="zh">等待现场字幕…</p><p id="en" class="en"></p></section></main>
<footer><span>只读 · 同一 Wi-Fi</span><span class="controls"><button id="minus" aria-label="缩小字号">−</button><button id="plus" aria-label="放大字号">＋</button></span></footer>
<script>
const token=__TOKEN__,zh=document.querySelector('#zh'),en=document.querySelector('#en'),previous=document.querySelector('#previous'),previousZh=document.querySelector('#previous-zh'),previousEn=document.querySelector('#previous-en'),divider=document.querySelector('#divider'),current=document.querySelector('#current'),status=document.querySelector('#status');let scale=1,state={previousFinal:null,active:{segmentId:'',sourceTextEn:'',targetTextZh:'等待现场字幕…',phase:'listening'},sessionActive:true};
function draw(){const old=state.previousFinal;previous.hidden=!old;divider.hidden=!old;if(old){previousZh.textContent=old.targetTextZh||'';previousEn.textContent=old.sourceTextEn||''}zh.textContent=state.active.targetTextZh||'正在翻译…';en.textContent=state.active.sourceTextEn||'';if(state.sessionActive===false){status.textContent='本场已结束';status.className='waiting'}else{status.textContent='字幕连接正常';status.className='ok'}}
function render(event){if(event.displayEligible===false)return;if(event.type==='caption.snapshot'){state=event;draw();return}if(event.type==='stream.ready'){state.sessionActive=true;draw();return}if(event.type==='asr.final'){const active=state.active;if(active.phase==='final'&&active.sourceTextEn&&active.targetTextZh)state.previousFinal={segmentId:active.segmentId,sourceTextEn:active.sourceTextEn,targetTextZh:active.targetTextZh};state.active={segmentId:event.segmentId||'',sourceTextEn:event.sourceTextEn||'',targetTextZh:'',phase:'requesting'}}else if(event.type==='caption.display'){const active=state.active,isNew=event.segmentId&&active.segmentId&&event.segmentId!==active.segmentId;if(isNew&&active.phase==='final'&&active.sourceTextEn&&active.targetTextZh)state.previousFinal={segmentId:active.segmentId,sourceTextEn:active.sourceTextEn,targetTextZh:active.targetTextZh};state.active={segmentId:event.segmentId||active.segmentId,sourceTextEn:event.sourceTextEn??active.sourceTextEn,targetTextZh:event.targetTextZh||active.targetTextZh,phase:event.phase||(event.displayKind==='final'?'final':'streaming')}}else if(['translation.partial','translation.final','translation.failed','translation.skipped'].includes(event.type)){if(event.segmentId&&state.active.segmentId&&event.segmentId!==state.active.segmentId)return;state.active={segmentId:event.segmentId||state.active.segmentId,sourceTextEn:event.sourceTextEn??state.active.sourceTextEn,targetTextZh:event.targetTextZh||state.active.targetTextZh,phase:event.type==='translation.partial'?'streaming':event.type==='translation.final'?'final':'error'}}else if(event.type==='stream.closed')state.sessionActive=false;draw()}
const source=new EventSource('/api/view/'+encodeURIComponent(token)+'/events');source.onopen=()=>{status.textContent='字幕连接正常';status.className='ok'};source.onmessage=e=>render(JSON.parse(e.data));source.onerror=()=>{status.textContent='正在重新连接…';status.className='waiting'};
function resize(delta){scale=Math.min(1.35,Math.max(.75,scale+delta));current.style.transform='scale('+scale+')'}document.querySelector('#minus').onclick=()=>resize(-.1);document.querySelector('#plus').onclick=()=>resize(.1);
</script></body></html>"""


class ViewerServer(ThreadingHTTPServer):
    hub: CaptionHub

    def handle_error(self, request: Any, client_address: Any) -> None:
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


class ViewerHandler(BaseHTTPRequestHandler):
    server: ViewerServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _headers(self, status: HTTPStatus, content_type: str, length: int | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        parts = [part for part in path.split("/") if part]
        if path == "/health":
            self._json(HTTPStatus.OK, {"service": "caption-viewer", "status": "ready"})
            return
        if len(parts) == 2 and parts[0] == "view":
            token = parts[1]
            if self.server.hub.snapshot(token) is None:
                self._not_found()
                return
            body = VIEWER_HTML.replace("__TOKEN__", json.dumps(token)).encode("utf-8")
            self._headers(HTTPStatus.OK, "text/html; charset=utf-8", len(body))
            self.wfile.write(body)
            return
        if len(parts) == 4 and parts[:2] == ["api", "view"] and parts[3] == "snapshot":
            snapshot = self.server.hub.snapshot(parts[2])
            if snapshot is None:
                self._not_found()
            else:
                self._json(HTTPStatus.OK, snapshot)
            return
        if len(parts) == 4 and parts[:2] == ["api", "view"] and parts[3] == "events":
            self._events(parts[2])
            return
        self._not_found()

    def do_POST(self) -> None:
        self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "read_only"})

    def _events(self, token: str) -> None:
        subscriber = self.server.hub.subscribe(token)
        if subscriber is None:
            self._not_found()
            return
        self._headers(HTTPStatus.OK, "text/event-stream; charset=utf-8")
        event_id = 0
        try:
            while True:
                try:
                    payload = subscriber.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                event_id += 1
                data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                self.wfile.write(f"id: {event_id}\ndata: {data}\n\n".encode("utf-8"))
                self.wfile.flush()
                if payload.get("type") == "stream.closed":
                    return
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.server.hub.unsubscribe(token, subscriber)

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _not_found(self) -> None:
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found_or_expired"})


class ViewerService:
    def __init__(self, hub: CaptionHub, host: str = "0.0.0.0", port: int = 8780) -> None:
        self.server = ViewerServer((host, port), ViewerHandler)
        self.server.hub = hub
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self.server.server_port

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
