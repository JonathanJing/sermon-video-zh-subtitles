#!/usr/bin/env python3
"""Bounded, ephemeral browser media probe. No model, audio storage or file API."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hmac
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import signal
import statistics
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

ROOT = Path(__file__).resolve().parent
SCHEMA = "mobile-media-probe-v1"
FRAME_SAMPLES = 1600
FRAME_BYTES = 3200
HEADER = struct.Struct("!4sII")
MAGIC = b"MP01"
WIRE_BYTES = HEADER.size + FRAME_BYTES
MAX_DURATION = 120
MAX_FRAMES = MAX_DURATION * 10 + 20
MAX_RUNS = 10
MAX_SAMPLES = MAX_FRAMES
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/protocol.mjs": ("protocol.mjs", "text/javascript; charset=utf-8"),
    "/capture-worklet.js": ("capture-worklet.js", "text/javascript; charset=utf-8"),
    "/playback-worklet.js": ("playback-worklet.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "p50": None, "p95": None, "max": None}
    ordered = sorted(values)
    return {
        "count": len(ordered), "min": round(ordered[0], 3),
        "p50": round(statistics.median(ordered), 3),
        "p95": round(ordered[max(0, math.ceil(len(ordered) * .95) - 1)], 3),
        "max": round(ordered[-1], 3),
    }


def finite_number(value: Any, low: float = 0, high: float = 60000) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid_numeric_measurement")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError("numeric_measurement_out_of_range")
    return float(value)


def positive_int(value: Any, maximum: int = 2**31 - 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError("invalid_sequence")
    return value


def strict_json(raw: str) -> dict[str, Any]:
    if len(raw.encode("utf-8")) > 2048:
        raise ValueError("control_message_too_large")
    value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid_json_constant")))
    if not isinstance(value, dict):
        raise ValueError("control_object_required")
    return value


def origin_policy(port: int, public_origins: list[str]) -> tuple[set[str], set[str]]:
    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    for value in public_origins:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment or "*" in value):
            raise ValueError("public_origin_must_be_an_exact_https_origin")
        try:
            if parsed.port == 0:
                raise ValueError("invalid_origin_port")
        except ValueError:
            raise ValueError("invalid_origin_port") from None
        origins.add(f"https://{parsed.netloc}".rstrip("/"))
    return origins, {urlsplit(origin).netloc for origin in origins}


def create_token_file(path: Path) -> str:
    """Create a new, private token file. Never reuse or overwrite an old token."""
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as output:
        output.write(token + "\n")
    return token


class Bucket:
    def __init__(self, rate: float, capacity: float, clock=time.monotonic):
        self.rate, self.capacity, self.clock = rate, capacity, clock
        self.tokens, self.last = capacity, clock()

    def take(self, amount: float = 1) -> bool:
        now = self.clock()
        self.tokens = min(self.capacity, self.tokens + max(0, now - self.last) * self.rate)
        self.last = now
        if self.tokens < amount:
            return False
        self.tokens -= amount
        return True


@dataclass(eq=False)
class Peer:
    socket: Any
    role: str
    device: str
    network: str
    ready: bool = False
    outbox: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=16))
    # Loopback: 10 received + 10 played + 30 observations + 2 ping + 2 rtt = 54/s.
    # Keep headroom for finite playback status updates without an unbounded burst.
    controls: Bucket = field(default_factory=lambda: Bucket(65, 80))
    frames: Bucket = field(default_factory=lambda: Bucket(10, 5))
    ping_ids: set[int] = field(default_factory=set)

    def enqueue(self, payload: dict | bytes, *, critical: bool = False, epoch: int = 0) -> bool:
        if critical:
            self.clear()
        wire = payload if isinstance(payload, bytes) else json.dumps(payload, separators=(",", ":"), allow_nan=False)
        try:
            self.outbox.put_nowait((wire, time.monotonic(), epoch))
            return True
        except asyncio.QueueFull:
            return False

    def clear(self) -> None:
        while not self.outbox.empty():
            self.outbox.get_nowait()


@dataclass
class Run:
    run_id: str
    epoch: int
    source: Peer
    receiver: Peer
    mode: str
    duration: int
    started_at: str
    started_clock: float
    last_sequence: int = 0
    frames: dict[int, dict[str, Any]] = field(default_factory=dict)
    metrics: dict[str, list[float]] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=lambda: {
        "acceptedFrames": 0, "sourceSequenceGaps": 0, "forwardedFrames": 0,
        "receiveAcknowledgements": 0, "playbackAcknowledgements": 0,
        "transportQueueDrops": 0, "transportExpiredFrames": 0,
        "playbackQueueDrops": 0, "playbackUnderruns": 0,
    })

    def measure(self, name: str, value: float) -> None:
        samples = self.metrics.setdefault(name, [])
        if len(samples) < MAX_SAMPLES:
            samples.append(value)


class ProbeServer:
    def __init__(self, token: str, output_dir: Path, *, host_label: str = "macbook",
                 port: int = 18781, public_origins: list[str] | None = None, ttl: int = 1800):
        if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token):
            raise ValueError("token_must_be_at_least_256_bits")
        if host_label not in {"macbook", "dgx"} or not 60 <= ttl <= 3600:
            raise ValueError("invalid_probe_configuration")
        self._token = token
        self.output_dir = output_dir
        self.host_label, self.port = host_label, port
        self.origins, self.hosts = origin_policy(port, public_origins or [])
        self.deadline = time.monotonic() + ttl
        self.peers: dict[str, Peer] = {}
        self.authenticating = 0
        self.run: Run | None = None
        self.epoch = 0
        self.completed = 0
        self.last_summary: dict | None = None
        self.run_timer: asyncio.Task | None = None
        self.stopping = asyncio.Event()
        self.http_limit = Bucket(20, 40)
        self.assets = {route: ((ROOT / name).read_bytes(), mime) for route, (name, mime) in ASSETS.items()}

    def process_request(self, connection: ServerConnection, request: Request) -> Response | None:
        if not self.http_limit.take():
            return self.http_response(429, b"rate_limited")
        hosts = request.headers.get_all("Host")
        if len(hosts) != 1 or hosts[0] not in self.hosts:
            return self.http_response(421, b"unknown_host")
        if time.monotonic() >= self.deadline:
            return self.http_response(410, b"probe_expired")
        if request.path == "/ws":
            origins = request.headers.get_all("Origin")
            if len(origins) != 1 or origins[0] not in self.origins:
                return self.http_response(403, b"origin_denied")
            return None
        if request.path in self.assets:
            body, mime = self.assets[request.path]
            return self.http_response(200, body, mime)
        return self.http_response(404, b"not_found")

    def http_response(self, status: int, body: bytes, mime: str = "text/plain; charset=utf-8") -> Response:
        connect = " ".join(sorted(origin.replace("https://", "wss://").replace("http://", "ws://") for origin in self.origins))
        headers = Headers({
            "Content-Type": mime, "Content-Length": str(len(body)),
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
            "Cross-Origin-Resource-Policy": "same-origin",
            "Content-Security-Policy": f"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self' {connect}; worker-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        })
        return Response(status, HTTPStatus(status).phrase, headers, body)

    def authenticate(self, socket: Any, payload: dict[str, Any]) -> Peer:
        if (time.monotonic() >= self.deadline or payload.get("type") != "auth"
                or payload.get("schemaVersion") != SCHEMA
                or not isinstance(payload.get("token"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", payload["token"])
                or not hmac.compare_digest(payload["token"], self._token)):
            raise ValueError("authentication_failed")
        role, device, network = payload.get("role"), payload.get("device"), payload.get("network")
        if role not in {"loopback", "admin", "user"}:
            raise ValueError("invalid_role")
        if device not in {"unknown", "desktop", "phone"} or network not in {"unknown", "wifi", "cellular", "ethernet"}:
            raise ValueError("invalid_device_claim")
        if role in self.peers or (role == "loopback" and self.peers) or "loopback" in self.peers:
            raise ValueError("role_or_topology_already_in_use")
        peer = Peer(socket, role, device, network)
        self.peers[role] = peer
        peer.enqueue({"type": "authenticated", "schemaVersion": SCHEMA, "hostLabel": self.host_label,
                      "role": role, "expiresInSeconds": max(0, int(self.deadline - time.monotonic())),
                      "limits": {"durationSeconds": MAX_DURATION, "runs": MAX_RUNS, "frameRate": 10},
                      "phoneVerifiedByProbe": False})
        self.broadcast_peers()
        return peer

    def broadcast_peers(self) -> None:
        payload = {"type": "peers", "peers": [{"role": p.role, "deviceClaim": p.device,
                   "networkClaim": p.network, "playbackReady": p.ready} for p in self.peers.values()]}
        for peer in self.peers.values():
            peer.enqueue(payload)

    async def writer(self, peer: Peer) -> None:
        try:
            while True:
                wire, queued_at, epoch = await peer.outbox.get()
                if isinstance(wire, bytes):
                    if not self.run or self.run.epoch != epoch:
                        continue
                    if time.monotonic() - queued_at > .5:
                        self.run.counts["transportExpiredFrames"] += 1
                        continue
                await asyncio.wait_for(peer.socket.send(wire), timeout=1)
                if isinstance(wire, bytes) and self.run and self.run.epoch == epoch:
                    self.run.counts["forwardedFrames"] += 1
        except (ConnectionClosed, asyncio.TimeoutError):
            if self.run and peer in (self.run.source, self.run.receiver):
                await self.finish_run("slow_or_disconnected_peer")
            with contextlib.suppress(Exception):
                await peer.socket.close(1008, "peer_unavailable")

    async def handle(self, socket: ServerConnection) -> None:
        peer = None
        writer = None
        if self.authenticating >= 4:
            await socket.close(1008, "authentication_capacity")
            return
        self.authenticating += 1
        try:
            raw = await asyncio.wait_for(socket.recv(), 5)
            if not isinstance(raw, str):
                raise ValueError("authentication_required")
            peer = self.authenticate(socket, strict_json(raw))
        except (ValueError, ConnectionClosed, asyncio.TimeoutError):
            await socket.close(1008, "authentication_failed")
            return
        finally:
            self.authenticating -= 1
        try:
            writer = asyncio.create_task(self.writer(peer))
            async for raw in socket:
                if time.monotonic() >= self.deadline:
                    raise ValueError("probe_expired")
                if isinstance(raw, bytes):
                    await self.accept_frame(peer, raw)
                else:
                    if not peer.controls.take():
                        raise ValueError("control_rate_exceeded")
                    await self.control(peer, strict_json(raw))
        except ValueError:
            if self.run and peer in (self.run.source, self.run.receiver):
                await self.finish_run("protocol_or_rate_rejected")
            await socket.close(1008, "protocol_or_rate_rejected")
        except ConnectionClosed:
            pass
        finally:
            if writer:
                writer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await writer
            if self.run and peer in (self.run.source, self.run.receiver):
                await self.finish_run("peer_disconnected")
            if self.peers.get(peer.role) is peer:
                self.peers.pop(peer.role)
            self.broadcast_peers()

    async def control(self, peer: Peer, payload: dict[str, Any]) -> None:
        kind = payload.get("type")
        if kind == "ping":
            ping_id = positive_int(payload.get("id"))
            # Browser watchdog allows up to 8 s with two pings/s; retain the
            # full legitimate in-flight window while keeping a finite bound.
            if len(peer.ping_ids) >= 32:
                peer.ping_ids.clear()
            peer.ping_ids.add(ping_id)
            peer.enqueue({"type": "pong", "id": ping_id})
        elif kind == "rtt":
            ping_id = positive_int(payload.get("id"))
            if ping_id not in peer.ping_ids:
                raise ValueError("unmatched_ping")
            peer.ping_ids.remove(ping_id)
            value = finite_number(payload.get("value"))
            if self.run:
                self.run.measure(f"{peer.role}.transportRttMs", value)
        elif kind == "playback_ready":
            if peer.role not in {"user", "loopback"} or type(payload.get("ready")) is not bool:
                raise ValueError("invalid_playback_readiness")
            peer.ready = payload["ready"]
            if not peer.ready and self.run and self.run.receiver is peer:
                await self.finish_run("playback_unavailable")
            self.broadcast_peers()
        elif kind == "start":
            await self.start_run(peer, payload)
        elif kind == "stop":
            if self.run and peer in (self.run.source, self.run.receiver):
                await self.finish_run("operator_stop")
        elif kind in {"received", "played", "playback_drop"}:
            self.acknowledge(peer, payload)
        elif kind == "observation":
            self.observe(peer, payload)
        elif kind == "playback_underrun":
            if self.run and self.run.receiver is peer and payload.get("epoch") == self.run.epoch:
                self.run.counts["playbackUnderruns"] += 1
        elif kind == "summary":
            peer.enqueue({"type": "summary", "summary": self.last_summary})
        else:
            raise ValueError("unsupported_control")

    async def start_run(self, peer: Peer, payload: dict[str, Any]) -> None:
        if peer.role not in {"loopback", "admin"} or self.run or self.completed >= MAX_RUNS:
            raise ValueError("run_start_rejected")
        mode = payload.get("mode")
        duration = positive_int(payload.get("durationSeconds"), MAX_DURATION)
        if duration < 5 or mode not in {"synthetic_silent", "synthetic", "microphone"}:
            raise ValueError("invalid_run_configuration")
        receiver = peer if peer.role == "loopback" else self.peers.get("user")
        if receiver is None or not receiver.ready:
            peer.enqueue({"type": "notice", "code": "receiver_not_ready"})
            return
        self.epoch += 1
        self.run = Run(secrets.token_hex(8), self.epoch, peer, receiver, mode, duration, utc_now(), time.monotonic())
        peer.frames = Bucket(10, 5)
        start = {"type": "started", "runId": self.run.run_id, "epoch": self.epoch,
                 "mode": mode, "durationSeconds": duration, "hostLabel": self.host_label}
        for participant in set((peer, receiver)):
            participant.enqueue(start, critical=True)
        self.run_timer = asyncio.create_task(self.run_timeout(self.epoch, duration))

    async def run_timeout(self, epoch: int, duration: int) -> None:
        await asyncio.sleep(duration)
        if self.run and self.run.epoch == epoch:
            await self.finish_run("duration_limit")

    async def accept_frame(self, peer: Peer, wire: bytes) -> None:
        run = self.run
        if run is None:
            return  # In-flight frames after Stop never resurrect a run.
        if peer is not run.source or len(wire) != WIRE_BYTES:
            raise ValueError("invalid_pcm_sender_or_size")
        magic, epoch, sequence = HEADER.unpack(wire[:HEADER.size])
        if magic != MAGIC or epoch != run.epoch or sequence <= run.last_sequence or sequence > MAX_FRAMES:
            raise ValueError("invalid_pcm_header")
        if run.mode == "synthetic_silent" and any(wire[HEADER.size:]):
            raise ValueError("non_silent_pcm_in_silent_probe")
        if not peer.frames.take():
            raise ValueError("pcm_rate_exceeded")
        if time.monotonic() - run.started_clock >= run.duration:
            await self.finish_run("duration_limit")
            return
        if sequence - run.last_sequence > 21 or len(run.frames) >= MAX_FRAMES:
            raise ValueError("pcm_gap_or_count_exceeded")
        run.counts["sourceSequenceGaps"] += sequence - run.last_sequence - 1
        run.last_sequence = sequence
        run.counts["acceptedFrames"] += 1
        run.frames[sequence] = {"relayedAt": time.monotonic(), "received": False, "played": False,
                                "dropped": False, "observations": set()}
        if not run.receiver.enqueue(wire, epoch=run.epoch):
            run.counts["transportQueueDrops"] += 1

    def acknowledge(self, peer: Peer, payload: dict[str, Any]) -> None:
        run = self.run
        if run is None or payload.get("epoch") != run.epoch:
            return
        if peer is not run.receiver:
            raise ValueError("invalid_acknowledgement_role")
        sequence = positive_int(payload.get("sequence"), MAX_FRAMES)
        frame = run.frames.get(sequence)
        kind = payload["type"]
        field_name = {"received": "received", "played": "played", "playback_drop": "dropped"}[kind]
        if frame is None or frame[field_name]:
            raise ValueError("unknown_or_duplicate_acknowledgement")
        frame[field_name] = True
        if kind == "playback_drop":
            run.counts["playbackQueueDrops"] += 1
            return
        metric = "serverRelayToReceiveAckMs" if kind == "received" else "serverRelayToPlaybackAckMs"
        run.measure(metric, (time.monotonic() - frame["relayedAt"]) * 1000)
        run.counts["receiveAcknowledgements" if kind == "received" else "playbackAcknowledgements"] += 1
        if kind == "played":
            for name in ("receiveToRenderCallbackMs", "receiveToOutputEstimateMs", "baseLatencyMs", "outputLatencyMs"):
                value = payload.get(name)
                if value is not None:
                    run.measure(name, finite_number(value, -1000 if name == "receiveToOutputEstimateMs" else 0))
        run.source.enqueue({"type": "media_ack", "stage": kind, "epoch": run.epoch, "sequence": sequence})

    def observe(self, peer: Peer, payload: dict[str, Any]) -> None:
        run = self.run
        if run is None or payload.get("epoch") != run.epoch:
            return
        if peer is not run.source:
            raise ValueError("invalid_observation_role")
        sequence = positive_int(payload.get("sequence"), MAX_FRAMES)
        name = payload.get("name")
        if name not in {"mediaReceiveAckRttMs", "mediaPlaybackAckRttMs", "playbackAckMinusReceiveAckMs"}:
            raise ValueError("invalid_observation_name")
        frame = run.frames.get(sequence)
        if frame is None or name in frame["observations"]:
            raise ValueError("unknown_or_duplicate_observation")
        required = "received" if name == "mediaReceiveAckRttMs" else "played"
        if not frame[required]:
            raise ValueError("observation_before_acknowledgement")
        frame["observations"].add(name)
        run.measure(name, finite_number(payload.get("value"), -1000 if name == "playbackAckMinusReceiveAckMs" else 0))

    async def finish_run(self, reason: str) -> dict | None:
        run = self.run
        if run is None:
            return None
        self.run = None  # Reject late frames/acks before saving or notifying peers.
        if self.run_timer and self.run_timer is not asyncio.current_task():
            self.run_timer.cancel()
        self.run_timer = None
        summary = {
            "schemaVersion": "mobile-media-probe-summary-v1", "runId": run.run_id,
            "hostLabel": self.host_label, "transport": "websocket-controlled-baseline",
            "topology": "loopback" if run.source is run.receiver else "admin-user",
            "inputMode": run.mode, "startedAt": run.started_at, "endedAt": utc_now(),
            "durationSeconds": round(time.monotonic() - run.started_clock, 3),
            "requestedDurationSeconds": run.duration, "stopReason": reason,
            "format": {"encoding": "pcm_s16le", "sampleRateHz": 16000, "channels": 1,
                       "frameDurationMs": 100, "headerBytes": HEADER.size},
            "deviceClaims": [{"role": peer.role, "device": peer.device, "network": peer.network}
                             for peer in sorted(set((run.source, run.receiver)), key=lambda peer: peer.role)],
            "counts": dict(run.counts),
            "metrics": {key: stats(values) for key, values in sorted(run.metrics.items())},
            "evidence": {
                "audioWorkletPlaybackAcknowledged": run.counts["playbackAcknowledgements"] > 0,
                "phoneVerifiedByProbe": False, "microphoneInputRequested": run.mode == "microphone",
                "silentPcmValidated": run.mode == "synthetic_silent" and run.counts["acceptedFrames"] > 0,
                "audibleSignalGeneratedByProbe": run.mode == "synthetic",
                "audibleOutputValidated": False,
                "audioPersisted": False, "clockSynchronizationUsed": False,
                "crossDeviceOneWayLatencyClaimed": False, "headphoneAcousticLatencyMeasured": False,
                "modelInferenceIncluded": False, "webRtcOrSfuImplemented": False,
                "measurementsAreClientReported": True,
            },
            "measurementNotes": [
                "Transport RTT uses each browser's own performance clock.",
                "Media RTT includes relay, receiver handling or playback, and acknowledgement return travel.",
                "Media timing starts at emitPcm; it excludes the wait to accumulate the first microphone sample into a 100 ms frame.",
                "Playback ack confirms AudioWorklet output processing, not audible headphone or speaker output.",
                "Output timestamp estimates depend on the browser and audio device; missing values remain absent.",
                "Playback minus receive ack includes browser buffering and return-network jitter, not pure acoustic delay.",
                "Device and network types are operator declarations, not physical-phone verification.",
                *( ["Synthetic silent mode carries only zero-valued PCM; this run does not validate any audible input or output."]
                   if run.mode == "synthetic_silent" else [] ),
            ],
        }
        self.completed += 1
        self.last_summary = summary
        target = self.output_dir / f"{run.run_id}.json"
        temporary = self.output_dir / f".{run.run_id}.json.tmp"
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            encoded = json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            with temporary.open("x", encoding="utf-8") as output:
                output.write(encoded)
            temporary.replace(target)
            saved = True
        except OSError:
            saved = False
            with contextlib.suppress(OSError):
                temporary.unlink()
        for peer in set((run.source, run.receiver)):
            peer.enqueue({"type": "stopped", "epoch": run.epoch, "summarySaved": saved,
                          "summary": summary}, critical=True)
        return summary

    async def expire(self) -> None:
        await asyncio.sleep(max(0, self.deadline - time.monotonic()))
        await self.finish_run("token_expired")
        self.stopping.set()


async def run_server(args: argparse.Namespace) -> None:
    if not ipaddress.ip_address(args.host).is_loopback:
        raise ValueError("bind_must_remain_loopback_use_an_explicit_tls_ingress")
    # Validate all non-secret inputs before creating the token file.
    origin_policy(args.port, args.public_origin)
    token_path = Path(args.token_file).expanduser()
    token = create_token_file(token_path)
    server = ProbeServer(token, Path(args.output_dir).expanduser(), host_label=args.host_label,
                         port=args.port, public_origins=args.public_origin, ttl=args.ttl_seconds)
    logger = logging.getLogger("media_probe.websocket")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    logger.setLevel(logging.CRITICAL)
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signum, server.stopping.set)
    expiry = asyncio.create_task(server.expire())
    try:
        async with serve(server.handle, args.host, args.port, origins=list(server.origins),
                         process_request=server.process_request, compression=None, max_size=4096,
                         max_queue=4, write_limit=16384, ping_interval=20, ping_timeout=20,
                         open_timeout=5, close_timeout=2, server_header=None, logger=logger):
            print(json.dumps({"status": "ready", "hostLabel": args.host_label, "port": args.port,
                              "ttlSeconds": args.ttl_seconds, "tokenPrinted": False}), flush=True)
            await server.stopping.wait()
            await server.finish_run("server_stopped")
    finally:
        expiry.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await expiry
        with contextlib.suppress(OSError):
            token_path.unlink()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--host", default="127.0.0.1")
    result.add_argument("--port", type=int, default=18781)
    result.add_argument("--host-label", choices=("macbook", "dgx"), default="macbook")
    result.add_argument("--public-origin", action="append", default=[], help="Exact HTTPS browser origin, repeatable; no wildcard")
    result.add_argument("--ttl-seconds", type=int, choices=range(60, 3601), metavar="60..3600", default=1800)
    result.add_argument("--token-file", required=True, help="New private token file; existing files are never overwritten")
    result.add_argument("--output-dir", default=str(ROOT / "artifacts" / "summaries"))
    return result


if __name__ == "__main__":
    try:
        asyncio.run(run_server(parser().parse_args()))
    except (OSError, ValueError):
        # Exception text may contain a local path, URL or credential-bearing input.
        raise SystemExit("Media probe startup failed; check bind/origin/port and use a new token-file path.") from None
