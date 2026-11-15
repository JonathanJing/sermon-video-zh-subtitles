#!/usr/bin/env python3
"""Capture a translate.pastors.ai listener feed to timestamped text and audio.

Why this exists
---------------
A Sunday service with a live speaker cannot be pre-produced.  The
translate.pastors.ai player already exposes two useful listener feeds:

  lang=captions  the source-language (English) transcript, no audio
  lang=zh        the Mandarin translated audio + Mandarin captions

This script joins both feeds as a listener, timestamps every message on
arrival, writes the audio as 24 kHz mono PCM/WAV and the captions as JSONL,
and stops by itself at a configured wall-clock deadline.  It is a capture
tool only: no ASR, no translation, no publication.

Wire protocol (observed 2026-11-08 and 2026-11-14)
--------------------------------------------------
wss://translate.pastors.ai/ws/listen?room=<room>&lang=<code>&v=2[&since=<seq>][&lid=<uuid>]

  binary frame : 4-byte big-endian sequence + int16 little-endian mono PCM
                 24 000 Hz, 250 ms (12 000 bytes) per frame
  text frame   : JSON status / caption / heartbeat / health / resumed / handoff

Audio and caption messages share one sequence space.  On reconnect we send
``since=<last seq>``; the server replays captions and a short audio window.

Output layout (one directory per service)
-----------------------------------------
  capture.json              manifest: window, streams, hashes, warnings
  capture.log               operator log
  events.jsonl              status / connect / stall / resumed / errors
  status.jsonl              one snapshot every 30 s (the first one immediately)
  english.captions.jsonl    every English caption message (partial + final)
  english.finals.jsonl      final English lines only
  english.txt               final English lines as plain text
  mandarin.captions.jsonl   every Mandarin caption message
  mandarin.finals.jsonl     final Mandarin lines only
  mandarin.txt              final Mandarin lines as plain text
  mandarin.audio.wav        received audio, WAV container (24 kHz mono s16le)
  mandarin.audio.pcm        raw s16le; kept on failure, deleted after a verified WAV
                            unless --keep-pcm is passed
  mandarin.frames.jsonl     one line per audio frame (offset, seq, arrival time)

The audio is the Mandarin translated voice from the page, not the original
English microphone feed: the service does not publish a source-audio channel.
If the original English audio is needed, record it separately (venue
microphone or the church live stream) and bind it to this capture by time.

Usage
-----
  .venv/bin/python experiments/live-translate-capture/capture.py \
      --room mariners-north-irvine \
      --start-at 10:00 --stop-at 11:20

  # short live check against a broadcasting room
  ... --room mariners-irvine-outdoor --start-at now --duration 2m

The script needs the ``websockets`` package (already present in the repo venv).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import platform
import re
import signal
import sys
import time
import uuid
import wave
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

try:
    import websockets
    from websockets.exceptions import ConnectionClosed, InvalidStatus
except ImportError as exc:  # pragma: no cover - operator-facing message
    raise SystemExit(
        "missing dependency: websockets; run `.venv/bin/python -m pip install 'websockets>=13'`"
    ) from exc

SCHEMA = "live-translate-capture/v1"
SAMPLE_RATE = 24_000
FRAME_SECONDS = 0.25
STALL_SECONDS = 12.0
STABLE_SECONDS = 5.0
MAX_PAD_MS = 30 * 60 * 1000
DEFAULT_TIMEZONE = "America/Los_Angeles"
DEFAULT_BASE_WS = "wss://translate.pastors.ai"
DEFAULT_ROOM_URL = "https://translate.pastors.ai/play/{room}/"
LOG = logging.getLogger("live-capture")


# ---------------------------------------------------------------------------
# small helpers


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def room_ever_broadcast(timeline: list[dict[str, Any]]) -> bool:
    """True if any status event reported broadcasting, not just the last one."""
    return any(bool(event.get("broadcasting")) for event in timeline)


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def jsonl(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


def parse_when(value: str, tz: ZoneInfo, *, now: datetime | None = None) -> datetime:
    """Parse ``HH:MM`` (today in tz), ``now`` or an ISO-8601 timestamp."""
    text = value.strip()
    moment = (now or datetime.now(tz)).astimezone(tz)
    if text.lower() == "now":
        return moment.astimezone(timezone.utc)
    if re.fullmatch(r"\d{1,2}:\d{2}", text):
        hour, minute = (int(part) for part in text.split(":"))
        return datetime.combine(moment.date(), dtime(hour, minute), tz).astimezone(timezone.utc)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(timezone.utc)


def parse_duration(value: str) -> float:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smh]?)\s*", value)
    if not match:
        raise argparse.ArgumentTypeError("duration must look like 90s, 10m or 1.5h")
    amount = float(match.group(1))
    unit = match.group(2) or "s"
    return amount * {"s": 1, "m": 60, "h": 3600}[unit]


@dataclass
class Window:
    requested_start: datetime
    requested_stop: datetime
    start: datetime
    stop: datetime
    late_start: bool

    @property
    def duration_s(self) -> float:
        return (self.stop - self.start).total_seconds()


def resolve_window(
    start_arg: str | None,
    stop_arg: str | None,
    duration_s: float | None,
    tz_name: str,
    *,
    now: datetime | None = None,
) -> Window:
    tz = ZoneInfo(tz_name)
    current = now or datetime.now(timezone.utc)
    requested_start = parse_when(start_arg, tz, now=current) if start_arg else current
    if stop_arg and duration_s is not None:
        raise SystemExit("pass --stop-at or --duration, not both")
    if stop_arg:
        requested_stop = parse_when(stop_arg, tz, now=current)
    else:
        requested_stop = requested_start + timedelta(seconds=duration_s or 80 * 60)
    if requested_stop <= current:
        raise SystemExit(f"stop time {iso_utc(requested_stop)} is already in the past")
    late = requested_start < current
    start = current if late else requested_start
    if requested_stop <= start:
        raise SystemExit(f"stop time {iso_utc(requested_stop)} is not after start {iso_utc(start)}")
    if (requested_stop - start).total_seconds() > 6 * 3600:
        raise SystemExit("refusing a window longer than 6 hours")
    return Window(requested_start, requested_stop, start, requested_stop, late)


def make_run_dir(root: Path, room: str, start_local: datetime, explicit: Path | None) -> Path:
    base = explicit if explicit else root / room / start_local.strftime("%Y-%m-%d")
    path = base
    if explicit is not None:
        path.mkdir(parents=True, exist_ok=True)
        return path
    if path.exists() and any(path.iterdir()):
        index = 2
        while True:
            candidate = base.with_name(f"{base.name}-{index}")
            if not candidate.exists():
                path = candidate
                break
            index += 1
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# writers


class EventLog:
    def __init__(self, path: Path, t0_mono: float):
        self._handle = path.open("a", encoding="utf-8", buffering=1)
        self._t0 = t0_mono

    def add(self, event: str, **fields: Any) -> None:
        record = {
            "received_at": iso_utc(now_utc()),
            "t_ms": round((time.monotonic() - self._t0) * 1000),
            "event": event,
        }
        record.update(fields)
        self._handle.write(jsonl(record))

    def close(self) -> None:
        self._handle.close()


class CaptionSink:
    """Append-only caption log plus a de-duplicated final-lines view."""

    def __init__(self, run_dir: Path, name: str):
        self.name = name
        self.raw_path = run_dir / f"{name}.captions.jsonl"
        self.finals_path = run_dir / f"{name}.finals.jsonl"
        self.text_path = run_dir / f"{name}.txt"
        self._raw = self.raw_path.open("a", encoding="utf-8", buffering=1)
        self._finals = self.finals_path.open("a", encoding="utf-8", buffering=1)
        self._text = self.text_path.open("a", encoding="utf-8", buffering=1)
        self._seen_finals: set[tuple[Any, str]] = set()
        self.messages = 0
        self.partials = 0
        self.finals = 0
        self.duplicate_finals = 0
        self.chars = 0
        self.first_final_at: datetime | None = None
        self.last_final_at: datetime | None = None
        self.last_seq: int | None = None
        self.closed = False

    def on_caption(self, message: dict[str, Any], wall: datetime, t_ms: int) -> None:
        seq = message.get("seq")
        final = bool(message.get("final"))
        record: dict[str, Any] = {
            "received_at": iso_utc(wall),
            "t_ms": t_ms,
            "seq": seq,
            "final": final,
        }
        if final:
            text = str(message.get("text") or "")
            record["text"] = text
        else:
            text = str(message.get("partial") or "")
            record["partial"] = text
        self._raw.write(jsonl(record))
        self.messages += 1
        if isinstance(seq, int):
            self.last_seq = seq
        if not final:
            self.partials += 1
            return

        key = (seq, text)
        if key in self._seen_finals:
            self.duplicate_finals += 1
            return
        self._seen_finals.add(key)
        self.finals += 1
        self.chars += len(text)
        if self.first_final_at is None:
            self.first_final_at = wall
        self.last_final_at = wall
        self._finals.write(
            jsonl(
                {
                    "received_at": iso_utc(wall),
                    "t_ms": t_ms,
                    "seq": seq,
                    "text": text,
                }
            )
        )
        self._text.write(text + "\n")

    def stats(self, *, include_hashes: bool = True) -> dict[str, Any]:
        return {
            "present": self.messages > 0,
            "messages": self.messages,
            "partials": self.partials,
            "finals": self.finals,
            "duplicate_finals": self.duplicate_finals,
            "chars": self.chars,
            "first_final_at": iso_utc(self.first_final_at) if self.first_final_at else None,
            "last_final_at": iso_utc(self.last_final_at) if self.last_final_at else None,
            "last_seq": self.last_seq,
            "files": {
                "raw": str(self.raw_path),
                "finals": str(self.finals_path),
                "text": str(self.text_path),
            },
            "sha256": (
                {
                    "raw": sha256_file(self.raw_path),
                    "finals": sha256_file(self.finals_path),
                    "text": sha256_file(self.text_path),
                }
                if include_hashes
                else None
            ),
        }

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for handle in (self._raw, self._finals, self._text):
            handle.close()


class AudioSink:
    """Append-only PCM writer with explicit silence for server-declared skips."""

    def __init__(self, run_dir: Path, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self.pcm_path = run_dir / "mandarin.audio.pcm"
        self.frames_path = run_dir / "mandarin.frames.jsonl"
        self._pcm = self.pcm_path.open("wb", buffering=0)
        self._frames = self.frames_path.open("a", encoding="utf-8", buffering=1)
        self.frames = 0
        self.samples = 0
        self.pad_ms = 0
        self.duplicate_frames = 0
        self.pads: list[dict[str, Any]] = []
        self.arrival_gaps: list[dict[str, Any]] = []
        self.seen_seq: set[int] = set()
        self.first_frame_at: datetime | None = None
        self.last_frame_at: datetime | None = None
        self.first_seq: int | None = None
        self.last_seq: int | None = None
        self.max_arrival_gap_s = 0.0
        self._last_mono: float | None = None
        self.closed = False

    def on_frame(
        self,
        seq: int,
        pcm: bytes,
        wall: datetime,
        mono: float,
        t_ms: int,
    ) -> None:
        if seq in self.seen_seq:
            self.duplicate_frames += 1
            return
        self.seen_seq.add(seq)
        if len(pcm) % 2:
            pcm = pcm[:-1]
        if self.first_frame_at is None:
            self.first_frame_at = wall
            self.first_seq = seq
        if self._last_mono is not None:
            gap = mono - self._last_mono
            if gap > self.max_arrival_gap_s:
                self.max_arrival_gap_s = gap
            if gap > 1.0:
                self.arrival_gaps.append({"at_ms": t_ms, "gap_s": round(gap, 3)})
        self._last_mono = mono
        offset_samples = self.samples
        self._pcm.write(pcm)
        self.samples += len(pcm) // 2
        self.frames += 1
        self.last_seq = seq
        self.last_frame_at = wall
        self._frames.write(
            jsonl(
                {
                    "received_at": iso_utc(wall),
                    "t_ms": t_ms,
                    "seq": seq,
                    "offset_samples": offset_samples,
                    "samples": len(pcm) // 2,
                    "bytes": len(pcm),
                }
            )
        )

    def pad(self, milliseconds: int, reason: str, detail: dict[str, Any], t_ms: int) -> None:
        milliseconds = int(milliseconds)
        if milliseconds <= 0:
            return
        samples = int(round(milliseconds * self.sample_rate / 1000))
        self._pcm.write(b"\x00" * (samples * 2))
        self.samples += samples
        self.pad_ms += milliseconds
        self.pads.append({"at_ms": t_ms, "ms": milliseconds, "reason": reason, "detail": detail})

    def on_resumed(self, message: dict[str, Any], t_ms: int) -> None:
        skipped = int(message.get("audioSkippedMs") or 0)
        if skipped <= 0:
            return
        capped = min(skipped, MAX_PAD_MS)
        self.pad(
            capped,
            "server_audio_skipped",
            {
                "audio_skipped_ms": skipped,
                "audio_replayed_ms": int(message.get("audioMs") or 0),
                "since": message.get("since"),
            },
            t_ms,
        )

    def stats(self, *, include_hashes: bool = True) -> dict[str, Any]:
        return {
            "present": self.frames > 0,
            "sample_rate_hz": self.sample_rate,
            "channels": 1,
            "format": "pcm_s16le",
            "frames": self.frames,
            "samples": self.samples,
            "total_duration_s": round(self.samples / self.sample_rate, 3),
            "received_audio_s": round(
                (self.samples - int(round(self.pad_ms * self.sample_rate / 1000))) / self.sample_rate, 3
            ),
            "pad_ms": self.pad_ms,
            "pads": self.pads,
            "arrival_gaps": self.arrival_gaps,
            "max_arrival_gap_s": round(self.max_arrival_gap_s, 3),
            "duplicate_frames": self.duplicate_frames,
            "first_frame_at": iso_utc(self.first_frame_at) if self.first_frame_at else None,
            "last_frame_at": iso_utc(self.last_frame_at) if self.last_frame_at else None,
            "first_seq": self.first_seq,
            "last_seq": self.last_seq,
            "files": {"pcm": str(self.pcm_path), "frames": str(self.frames_path)},
            "sha256": (
                {"pcm": sha256_file(self.pcm_path), "frames": sha256_file(self.frames_path)}
                if include_hashes
                else None
            ),
        }

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._pcm.close()
        self._frames.close()


def pcm_to_wav(pcm_path: Path, wav_path: Path, sample_rate: int = SAMPLE_RATE) -> None:
    with wave.open(str(wav_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        with pcm_path.open("rb") as source:
            for chunk in iter(lambda: source.read(1 << 20), b""):
                output.writeframes(chunk)


# ---------------------------------------------------------------------------
# protocol client


class StreamClient:
    """One listener socket.  Reconnects with ``since`` until the capture stops."""

    def __init__(
        self,
        capture: "Capture",
        name: str,
        lang: str,
        caption_sink: CaptionSink | None,
        audio_sink: AudioSink | None,
    ):
        self.capture = capture
        self.name = name
        self.lang = lang
        self.caption_sink = caption_sink
        self.audio_sink = audio_sink
        self.last_seq: int | None = None
        self.last_rx = 0.0
        self.connections = 0
        self.reconnects = 0
        self.errors = 0
        self.captions = 0
        self.heartbeats = 0
        self.resumed = 0
        self.audio_frames = 0
        self.ignored_audio_bytes = 0
        self.broadcasting: bool | None = None
        self.opened_at: float | None = None
        self.started = False

    async def run(self) -> None:
        backoff = 1.0
        while not self.capture.stop.is_set():
            self.opened_at = time.monotonic()
            try:
                await self._one_session()
            except asyncio.CancelledError:
                raise
            except InvalidStatus as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                self.errors += 1
                self.capture.record(
                    "handshake_rejected",
                    language=self.name,
                    lang=self.lang,
                    http_status=status,
                )
                LOG.warning("%s: handshake rejected (HTTP %s), retrying", self.name, status)
                await self._sleep(30.0 if status == 400 else backoff)
                backoff = min(max(backoff * 2, 1.0), 30.0)
                continue
            except (ConnectionClosed, OSError, asyncio.TimeoutError, ValueError) as exc:
                self.errors += 1
                self.capture.record(
                    "connection_lost",
                    language=self.name,
                    error=type(exc).__name__,
                    detail=str(exc)[:300],
                )
                LOG.warning("%s: connection ended (%s: %s)", self.name, type(exc).__name__, exc)
            if self.capture.stop.is_set():
                break
            stable = self.opened_at is not None and time.monotonic() - self.opened_at > STABLE_SECONDS
            if stable:
                self.reconnects += 1
                delay = 0.0
                backoff = 1.0
            else:
                delay = backoff
                backoff = min(backoff * 2, 10.0)
            if delay:
                self.capture.record("reconnect_wait", language=self.name, seconds=delay)
                await self._sleep(delay)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.capture.stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    def _url(self) -> str:
        params: dict[str, Any] = {
            "room": self.capture.settings.room,
            "lang": self.lang,
            "v": "2",
            "lid": self.capture.listener_id,
        }
        if self.last_seq is not None:
            params["since"] = self.last_seq
        base = self.capture.settings.base_ws.rstrip("/")
        return f"{base}/ws/listen?{urlencode(params)}"

    async def _one_session(self) -> None:
        url = self._url()
        self.capture.record("connect", language=self.name, lang=self.lang, since=self.last_seq)
        async with websockets.connect(
            url,
            max_size=1 << 20,
            ping_interval=None,
            open_timeout=15,
            close_timeout=5,
        ) as socket:
            self.connections += 1
            self.started = True
            self.opened_at = time.monotonic()
            self.last_rx = self.opened_at
            self.capture.record("connected", language=self.name, lang=self.lang)
            LOG.info("%s: connected (lang=%s, since=%s)", self.name, self.lang, self.last_seq)
            while not self.capture.stop.is_set():
                try:
                    message = await asyncio.wait_for(socket.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    silence = time.monotonic() - self.last_rx
                    if silence > STALL_SECONDS:
                        self.capture.record("stall", language=self.name, seconds=round(silence, 1))
                        LOG.warning("%s: %.0fs of silence, reconnecting", self.name, silence)
                        raise ConnectionError("stalled socket")
                    continue
                self.last_rx = time.monotonic()
                if isinstance(message, bytes):
                    self._on_binary(message)
                else:
                    self._on_text(message)

    def _on_binary(self, message: bytes) -> None:
        if len(message) < 4:
            self.capture.record("bad_audio_frame", language=self.name, bytes=len(message))
            return
        seq = int.from_bytes(message[:4], "big")
        if self.last_seq is None or seq > self.last_seq:
            self.last_seq = seq
        if self.audio_sink is None:
            self.ignored_audio_bytes += len(message) - 4
            return
        wall, mono, t_ms = self.capture.clock()
        self.audio_frames += 1
        self.audio_sink.on_frame(seq, message[4:], wall, mono, t_ms)

    def _on_text(self, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            self.capture.record("bad_json", language=self.name, bytes=len(message))
            return
        seq = data.get("seq")
        if isinstance(seq, int) and (self.last_seq is None or seq > self.last_seq):
            self.last_seq = seq
        wall, _, t_ms = self.capture.clock()
        kind = data.get("type")
        if kind == "caption":
            self.captions += 1
            if self.caption_sink is not None:
                self.caption_sink.on_caption(data, wall, t_ms)
        elif kind == "status":
            value = bool(data.get("broadcasting"))
            if value != self.broadcasting:
                self.broadcasting = value
                self.capture.on_broadcast_status(self.name, value)
        elif kind == "resumed":
            self.resumed += 1
            if self.audio_sink is not None:
                self.audio_sink.on_resumed(data, t_ms)
            self.capture.record(
                "resumed",
                language=self.name,
                since=data.get("since"),
                captions=data.get("captions"),
                audio_ms=data.get("audioMs"),
                skipped_ms=data.get("audioSkippedMs"),
            )
        elif kind == "health":
            self.capture.record(
                "health",
                language=self.name,
                dropped_frames=data.get("droppedFrames"),
            )
        elif kind == "handoff":
            self.capture.record("handoff", language=self.name, phase=data.get("phase"), payload=data)
        elif kind == "heartbeat":
            self.heartbeats += 1
        else:
            self.capture.record("unknown_message", language=self.name, payload=data)

    def summary(self) -> dict[str, Any]:
        return {
            "lang": self.lang,
            "connected": self.started,
            "connections": self.connections,
            "reconnects": self.reconnects,
            "errors": self.errors,
            "captions": self.captions,
            "heartbeats": self.heartbeats,
            "resumed": self.resumed,
            "audio_frames": self.audio_frames,
            "ignored_audio_bytes": self.ignored_audio_bytes,
            "last_seq": self.last_seq,
            "broadcasting": self.broadcasting,
        }


# ---------------------------------------------------------------------------
# capture orchestration


@dataclass
class Settings:
    room: str
    english_lang: str
    mandarin_lang: str
    base_ws: str
    timezone: str
    window: Window
    out_dir: Path | None
    out_root: Path
    capture_english: bool
    capture_mandarin: bool
    keep_pcm: bool
    verbose: bool


class Capture:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.tz = ZoneInfo(settings.timezone)
        self.listener_id = str(uuid.uuid4())
        self.stop = asyncio.Event()
        self.events: EventLog | None = None
        self.t0_mono = 0.0
        self.t0_wall: datetime | None = None
        self.run_dir: Path | None = None
        self.status_path: Path | None = None
        self.warnings: list[str] = []
        self.notes: list[str] = []
        self.broadcast_state: dict[str, bool | None] = {}
        self.broadcast_timeline: list[dict[str, Any]] = []
        self.english_client: StreamClient | None = None
        self.mandarin_client: StreamClient | None = None
        self.english_sink: CaptionSink | None = None
        self.mandarin_sink: CaptionSink | None = None
        self.audio_sink: AudioSink | None = None
        self._stop_reason = "deadline"
        self._status_task: asyncio.Task | None = None
        self._deadline_task: asyncio.Task | None = None

    # -- clock and logging -------------------------------------------------

    def clock(self) -> tuple[datetime, float, int]:
        wall = now_utc()
        mono = time.monotonic()
        return wall, mono, round((mono - self.t0_mono) * 1000)

    def record(self, event: str, **fields: Any) -> None:
        if self.events is not None:
            self.events.add(event, **fields)
        LOG.debug("event %s %s", event, fields)

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        LOG.warning("%s", message)

    def on_broadcast_status(self, language: str, broadcasting: bool) -> None:
        previous = self.broadcast_state.get(language)
        self.broadcast_state[language] = broadcasting
        if previous is broadcasting:
            return
        wall, _, t_ms = self.clock()
        self.broadcast_timeline.append(
            {
                "received_at": iso_utc(wall),
                "t_ms": t_ms,
                "language": language,
                "broadcasting": broadcasting,
            }
        )
        self.record("broadcast_status", language=language, broadcasting=broadcasting)
        LOG.info("%s: broadcasting=%s", language, broadcasting)

    # -- main path ---------------------------------------------------------

    async def run(self) -> dict[str, Any]:
        started = await self._wait_until_start()
        if not started:
            return {"status": "stopped_before_start", "run_dir": str(self.run_dir)}
        self.t0_mono = time.monotonic()
        self.t0_wall = now_utc()
        assert self.run_dir is not None
        self.events = EventLog(self.run_dir / "events.jsonl", self.t0_mono)
        self.status_path = self.run_dir / "status.jsonl"
        self.record(
            "capture_start",
            room=self.settings.room,
            english_lang=self.settings.english_lang,
            mandarin_lang=self.settings.mandarin_lang,
            requested_start=iso_utc(self.settings.window.requested_start),
            requested_stop=iso_utc(self.settings.window.requested_stop),
            actual_start=iso_utc(self.settings.window.start),
            late_start=self.settings.window.late_start,
            listener_id=self.listener_id,
        )
        if self.settings.window.late_start:
            self.warn("capture started late; first moments of the service may be missing")

        self._open_sinks()
        clients: list[StreamClient] = []
        if self.english_client is not None:
            clients.append(self.english_client)
        if self.mandarin_client is not None:
            clients.append(self.mandarin_client)
        if not clients:
            self.warn("no streams enabled")
            return self._finalize()

        self._deadline_task = asyncio.create_task(self._deadline())
        self._status_task = asyncio.create_task(self._status_loop())
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._on_signal, sig)
            except NotImplementedError:
                pass

        LOG.info(
            "capturing room=%s english=%s mandarin=%s until %s",
            self.settings.room,
            self.settings.english_lang if self.settings.capture_english else "off",
            self.settings.mandarin_lang if self.settings.capture_mandarin else "off",
            iso_utc(self.settings.window.stop),
        )
        results = await asyncio.gather(*(client.run() for client in clients), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                self.warn(f"stream task failed: {type(result).__name__}: {result}")
        self.stop.set()
        await self._cancel_tasks()
        return self._finalize()

    async def _wait_until_start(self) -> bool:
        self.run_dir = make_run_dir(
            self.settings.out_root,
            self.settings.room,
            self.settings.window.start.astimezone(self.tz),
            self.settings.out_dir,
        )
        setup_logging(self.run_dir, self.settings.verbose)
        LOG.info("run directory: %s", self.run_dir)
        while not self.stop.is_set():
            remaining = (self.settings.window.start - now_utc()).total_seconds()
            if remaining <= 0:
                return True
            LOG.info("waiting %.0f s for the capture window", remaining)
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=min(remaining, 30.0))
            except asyncio.TimeoutError:
                continue
        return False

    def _on_signal(self, signum: signal.Signals) -> None:
        self._stop_reason = f"signal:{signum.name}"
        LOG.warning("received %s; finishing the capture", signum.name)
        self.stop.set()

    def _open_sinks(self) -> None:
        assert self.run_dir is not None
        if self.settings.capture_english:
            self.english_sink = CaptionSink(self.run_dir, "english")
            self.english_client = StreamClient(
                self,
                "english",
                self.settings.english_lang,
                self.english_sink,
                None,
            )
        if self.settings.capture_mandarin:
            self.mandarin_sink = CaptionSink(self.run_dir, "mandarin")
            self.audio_sink = AudioSink(self.run_dir)
            self.mandarin_client = StreamClient(
                self,
                "mandarin",
                self.settings.mandarin_lang,
                self.mandarin_sink,
                self.audio_sink,
            )

    async def _deadline(self) -> None:
        while not self.stop.is_set():
            remaining = (self.settings.window.stop - now_utc()).total_seconds()
            if remaining <= 0:
                self._stop_reason = "deadline"
                LOG.info("capture deadline reached")
                self.stop.set()
                return
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=min(remaining, 30.0))
            except asyncio.TimeoutError:
                continue

    async def _status_loop(self) -> None:
        assert self.status_path is not None
        handle = self.status_path.open("a", encoding="utf-8", buffering=1)
        first = True
        try:
            while True:
                if not first:
                    try:
                        await asyncio.wait_for(self.stop.wait(), timeout=30.0)
                        return
                    except asyncio.TimeoutError:
                        pass
                first = False
                wall, _, t_ms = self.clock()
                snapshot = self._snapshot(wall, t_ms)
                handle.write(jsonl(snapshot))
                LOG.info(
                    "status: audio=%ss english=%d finals mandarin=%d finals broadcasting=%s",
                    snapshot["audio_received_s"],
                    snapshot["english_finals"],
                    snapshot["mandarin_finals"],
                    snapshot["broadcasting"],
                )
        finally:
            handle.close()

    def _snapshot(self, wall: datetime, t_ms: int) -> dict[str, Any]:
        audio = self.audio_sink.stats(include_hashes=False) if self.audio_sink else None
        return {
            "received_at": iso_utc(wall),
            "t_ms": t_ms,
            "audio_received_s": audio["received_audio_s"] if audio else 0,
            "audio_frames": audio["frames"] if audio else 0,
            "english_finals": self.english_sink.finals if self.english_sink else 0,
            "english_messages": self.english_sink.messages if self.english_sink else 0,
            "mandarin_finals": self.mandarin_sink.finals if self.mandarin_sink else 0,
            "mandarin_messages": self.mandarin_sink.messages if self.mandarin_sink else 0,
            "broadcasting": dict(self.broadcast_state),
            "connections": {
                client.name: client.connections
                for client in (self.english_client, self.mandarin_client)
                if client is not None
            },
        }

    async def _cancel_tasks(self) -> None:
        tasks = [task for task in (self._deadline_task, self._status_task) if task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # -- finalize ----------------------------------------------------------

    def _finalize(self) -> dict[str, Any]:
        assert self.run_dir is not None
        stopped_at = now_utc()
        audio_stats = None
        if self.audio_sink is not None:
            audio_stats = self.audio_sink.stats()
        for sink in (self.english_sink, self.mandarin_sink, self.audio_sink):
            if sink is not None:
                sink.close()

        wav_path = self.run_dir / "mandarin.audio.wav"
        if audio_stats and audio_stats["present"] and audio_stats["samples"] > 0:
            pcm_path = self.run_dir / "mandarin.audio.pcm"
            wav_frames = None
            try:
                pcm_to_wav(pcm_path, wav_path)
                with wave.open(str(wav_path), "rb") as handle:
                    wav_frames = handle.getnframes()
            except Exception as exc:  # keep the PCM if the WAV could not be verified
                self.warn(f"WAV finalize failed ({type(exc).__name__}: {exc}); keeping PCM")
                wav_path.unlink(missing_ok=True)
            if wav_frames is None:
                audio_stats["files"]["wav"] = None
                audio_stats["sha256"]["wav"] = None
            else:
                if wav_frames != audio_stats["samples"]:
                    self.warn(
                        f"WAV frame count {wav_frames} != PCM sample count {audio_stats['samples']}; keeping PCM"
                    )
                audio_stats["files"]["wav"] = str(wav_path)
                audio_stats["sha256"]["wav"] = sha256_file(wav_path)
                audio_stats["wav_duration_s"] = round(audio_stats["samples"] / SAMPLE_RATE, 3)
                audio_stats["wav_frames"] = wav_frames
                if not self.settings.keep_pcm and wav_frames == audio_stats["samples"]:
                    audio_stats["files"]["pcm_sha256"] = audio_stats["sha256"].get("pcm")
                    audio_stats["files"]["pcm"] = None
                    audio_stats["files"]["pcm_removed"] = True
                    pcm_path.unlink(missing_ok=True)
        elif audio_stats:
            self.warn("no Mandarin audio frames were received")
            audio_stats["files"]["wav"] = None
            audio_stats["sha256"]["wav"] = None

        english_stats = self.english_sink.stats() if self.english_sink else None
        mandarin_stats = self.mandarin_sink.stats() if self.mandarin_sink else None
        if english_stats is not None and english_stats["finals"] == 0:
            self.warn("no final English caption lines were received")
        if mandarin_stats is not None and mandarin_stats["messages"] == 0:
            self.warn("no Mandarin caption messages were received")
        elif mandarin_stats is not None and mandarin_stats["finals"] == 0:
            self.notes.append(
                "Mandarin captions were partial-only during this window; "
                "mandarin.captions.jsonl is the comparison source."
            )
        if not room_ever_broadcast(self.broadcast_timeline):
            self.warn("room never reported broadcasting during the capture window")

        duration_s = (stopped_at - (self.t0_wall or stopped_at)).total_seconds()
        manifest = {
            "schema": SCHEMA,
            "generated_at": iso_utc(now_utc()),
            "status": (
                "captured"
                if (
                    (english_stats and english_stats["finals"] > 0)
                    or (mandarin_stats and mandarin_stats["finals"] > 0)
                    or (audio_stats and audio_stats["frames"] > 0)
                )
                else "empty"
            ),
            "room": self.settings.room,
            "source": {
                "base_ws": self.settings.base_ws,
                "room_url": DEFAULT_ROOM_URL.format(room=self.settings.room),
                "english_lang": self.settings.english_lang,
                "mandarin_lang": self.settings.mandarin_lang,
                "capture_english": self.settings.capture_english,
                "capture_mandarin": self.settings.capture_mandarin,
                "note": "Mandarin audio is the service's translated voice, not the original English microphone feed.",
            },
            "window": {
                "requested_start": iso_utc(self.settings.window.requested_start),
                "requested_stop": iso_utc(self.settings.window.requested_stop),
                "actual_start": iso_utc(self.t0_wall) if self.t0_wall else None,
                "actual_stop": iso_utc(stopped_at),
                "duration_s": round(duration_s, 3),
                "late_start": self.settings.window.late_start,
                "stop_reason": self._stop_reason,
            },
            "listener_id": self.listener_id,
            "streams": {
                "english": self.english_client.summary() if self.english_client else None,
                "mandarin": self.mandarin_client.summary() if self.mandarin_client else None,
            },
            "text": {"english": english_stats, "mandarin": mandarin_stats},
            "audio": audio_stats,
            "broadcast_timeline": self.broadcast_timeline,
            "notes": self.notes,
            "warnings": self.warnings,
            "host": {
                "hostname": platform.node(),
                "platform": platform.platform(),
                "python": sys.version.split()[0],
                "timezone": self.settings.timezone,
            },
            "script": {
                "path": str(Path(__file__).resolve()),
                "sha256": sha256_file(Path(__file__).resolve()),
            },
        }
        write_json(self.run_dir / "capture.json", manifest)
        if self.events is not None:
            self.record("capture_stop", stop_reason=self._stop_reason)
            self.events.close()
        LOG.info("capture finished: %s", self.run_dir / "capture.json")
        return manifest


# ---------------------------------------------------------------------------
# CLI


def setup_logging(run_dir: Path, verbose: bool) -> None:
    if LOG.handlers:
        return
    LOG.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    logfile = logging.FileHandler(run_dir / "capture.log", encoding="utf-8")
    logfile.setFormatter(formatter)
    LOG.addHandler(stream)
    LOG.addHandler(logfile)
    LOG.propagate = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture translate.pastors.ai English captions and Mandarin audio/captions.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--room", default="mariners-north-irvine")
    parser.add_argument("--english-lang", default="captions")
    parser.add_argument("--mandarin-lang", default="zh")
    parser.add_argument("--base-ws", default=DEFAULT_BASE_WS)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--start-at", default=None, help="HH:MM (local) or ISO-8601; default now")
    parser.add_argument("--stop-at", default=None, help="HH:MM (local) or ISO-8601")
    parser.add_argument("--duration", type=parse_duration, default=None, help="alternative to --stop-at")
    parser.add_argument("--out-root", type=Path, default=Path("artifacts/live-capture"))
    parser.add_argument("--out", type=Path, default=None, help="explicit run directory")
    parser.add_argument("--no-english", action="store_true", help="do not join the source caption feed")
    parser.add_argument("--no-mandarin", action="store_true", help="do not join the Mandarin feed")
    parser.add_argument("--keep-pcm", action="store_true", help="keep the raw PCM after a verified WAV")
    parser.add_argument("--verbose", action="store_true")
    return parser


def settings_from_args(args: argparse.Namespace) -> Settings:
    if args.no_english and args.no_mandarin:
        raise SystemExit("nothing to capture: both English and Mandarin feeds are disabled")
    window = resolve_window(args.start_at, args.stop_at, args.duration, args.timezone)
    return Settings(
        room=args.room,
        english_lang=args.english_lang,
        mandarin_lang=args.mandarin_lang,
        base_ws=args.base_ws,
        timezone=args.timezone,
        window=window,
        out_dir=args.out,
        out_root=args.out_root,
        capture_english=not args.no_english,
        capture_mandarin=not args.no_mandarin,
        keep_pcm=args.keep_pcm,
        verbose=args.verbose,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = settings_from_args(args)
    capture = Capture(settings)
    try:
        manifest = asyncio.run(capture.run())
    except KeyboardInterrupt:
        LOG.warning("interrupted")
        return 130
    except Exception as exc:  # keep the operator log useful
        LOG.exception("capture failed: %s", exc)
        return 2
    status = manifest.get("status") if isinstance(manifest, dict) else None
    return 0 if status in {"captured", "empty", "stopped_before_start"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
