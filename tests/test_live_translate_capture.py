"""Tests for the live translate capture experiment.

The integration test uses a local WebSocket server that speaks the same wire
contract as translate.pastors.ai (status/caption/heartbeat + 4-byte sequence
plus int16 PCM), drops the first connection and accepts a ``since`` reconnect.
It does not touch the live service.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
import unittest
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import websockets
    HAVE_WEBSOCKETS = True
except ImportError:  # CI installs requirements-test.txt, which does not pin websockets
    websockets = None
    HAVE_WEBSOCKETS = False

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "live-translate-capture"


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, EXPERIMENT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


if HAVE_WEBSOCKETS:
    capture = load_module("live_capture_under_test", "capture.py")
    fetch_session = load_module("live_capture_session_under_test", "fetch_session.py")
else:
    capture = None
    fetch_session = None


@unittest.skipUnless(HAVE_WEBSOCKETS, "websockets not installed")
class WindowTests(unittest.TestCase):
    def test_hh_mm_uses_local_date_across_utc_midnight(self):
        # 00:44Z = 16:44 in Los Angeles; "16:45" is the same local day, 27 s later.
        now = datetime(2026, 11, 15, 0, 44, 33, tzinfo=timezone.utc)
        window = capture.resolve_window("now", "16:45", None, "America/Los_Angeles", now=now)
        self.assertAlmostEqual(window.duration_s, 27.0, places=3)
        self.assertFalse(window.late_start)

    def test_sunday_window(self):
        now = datetime(2026, 11, 14, 17, 55, tzinfo=timezone.utc)  # 09:55 PST
        window = capture.resolve_window("10:00", "11:20", None, "America/Los_Angeles", now=now)
        self.assertEqual(window.start, datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc))
        self.assertEqual(window.stop, datetime(2026, 11, 14, 19, 20, tzinfo=timezone.utc))
        self.assertFalse(window.late_start)

    def test_late_start_clamps_to_now(self):
        now = datetime(2026, 11, 14, 18, 5, tzinfo=timezone.utc)  # 10:05 PST
        window = capture.resolve_window("10:00", "11:20", None, "America/Los_Angeles", now=now)
        self.assertEqual(window.start, now)
        self.assertTrue(window.late_start)

    def test_past_window_is_rejected(self):
        now = datetime(2026, 11, 14, 20, 0, tzinfo=timezone.utc)
        with self.assertRaises(SystemExit):
            capture.resolve_window("10:00", "11:20", None, "America/Los_Angeles", now=now)


@unittest.skipUnless(HAVE_WEBSOCKETS, "websockets not installed")
class SinkTests(unittest.TestCase):
    def test_caption_sink_dedupes_replayed_finals(self):
        with tempfile.TemporaryDirectory() as raw:
            sink = capture.CaptionSink(Path(raw), "english")
            when = datetime(2026, 11, 15, 1, 0, tzinfo=timezone.utc)
            message = {"type": "caption", "seq": 7, "final": True, "text": "Grace and peace."}
            sink.on_caption(message, when, 1000)
            sink.on_caption(message, when, 1001)  # replay after reconnect
            sink.on_caption({"type": "caption", "seq": 8, "partial": "Grace"}, when, 1002)
            stats = sink.stats()
            sink.close()
            self.assertEqual(stats["finals"], 1)
            self.assertEqual(stats["duplicate_finals"], 1)
            self.assertEqual(stats["messages"], 3)
            self.assertEqual(Path(stats["files"]["text"]).read_text(encoding="utf-8"), "Grace and peace.\n")

    def test_audio_sink_pads_server_skips_and_writes_wav(self):
        with tempfile.TemporaryDirectory() as raw:
            run_dir = Path(raw)
            sink = capture.AudioSink(run_dir)
            when = datetime(2026, 11, 15, 1, 0, tzinfo=timezone.utc)
            for seq in (10, 11):
                sink.on_frame(seq, b"\x01\x00" * 6000, when, 0.0 + seq, seq * 250)
            sink.on_resumed({"type": "resumed", "audioSkippedMs": 500, "audioMs": 0}, 1000)
            sink.on_frame(12, b"\x01\x00" * 6000, when, 20.0, 1500)
            stats = sink.stats()
            sink.close()
            self.assertEqual(stats["frames"], 3)
            self.assertEqual(stats["pad_ms"], 500)
            self.assertAlmostEqual(stats["total_duration_s"], 1.25, places=3)
            wav_path = run_dir / "out.wav"
            capture.pcm_to_wav(run_dir / "mandarin.audio.pcm", wav_path)
            with wave.open(str(wav_path), "rb") as handle:
                self.assertEqual(handle.getframerate(), 24000)
                self.assertEqual(handle.getnchannels(), 1)
                self.assertEqual(handle.getsampwidth(), 2)
                self.assertAlmostEqual(handle.getnframes() / 24000, 1.25, places=3)


@unittest.skipUnless(HAVE_WEBSOCKETS, "websockets not installed")
class SessionTests(unittest.TestCase):
    def test_choose_session_prefers_overlap(self):
        now = datetime(2026, 11, 15, 1, 0, tzinfo=timezone.utc)
        sessions = [
            {"sessionId": "early", "startedAt": "2026-11-14T16:00:00Z", "endedAt": "2026-11-14T17:00:00Z"},
            {"sessionId": "target", "startedAt": "2026-11-14T17:55:00Z", "endedAt": "2026-11-14T19:30:00Z"},
            {"sessionId": "late", "startedAt": "2026-11-14T19:40:00Z", "endedAt": "2026-11-14T21:00:00Z"},
        ]
        chosen = fetch_session.choose_session(
            sessions,
            datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc),
            datetime(2026, 11, 14, 19, 20, tzinfo=timezone.utc),
            now=now,
        )
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["sessionId"], "target")

    def test_redact_summary_drops_listener_data_and_ingest_url(self):
        summary = {
            "sessionId": "s1",
            "room": "r",
            "source": "ingest:rtmp://10.0.0.1/stream/secret",
            "provider": "gemini-live-translate",
            "listenerTelemetry": {"es": [{"listenerId": "abc"}]},
            "listenerSocket": {"es": {"connections": 1}},
            "peakListeners": {"es": 1},
        }
        redacted = fetch_session.redact_summary(summary)
        self.assertNotIn("listenerTelemetry", redacted)
        self.assertNotIn("listenerSocket", redacted)
        self.assertEqual(redacted["source"], "ingest:rtmp (redacted)")
        self.assertEqual(redacted["peakListeners"], {"es": 1})


class LocalWireServer:
    def __init__(self):
        self.connections: dict[str, int] = {}
        self.since: dict[str, list[str | None]] = {}
        self.server = None

    async def start(self):
        self.server = await websockets.serve(self.handler, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        return port

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()

    async def handler(self, websocket):
        query = parse_qs(urlparse(websocket.request.path).query)
        lang = (query.get("lang") or ["unknown"])[0]
        since = (query.get("since") or [None])[0]
        self.connections[lang] = self.connections.get(lang, 0) + 1
        self.since.setdefault(lang, []).append(since)
        attempt = self.connections[lang]
        await websocket.send(json.dumps({"type": "status", "broadcasting": True}))
        if lang == "captions":
            await websocket.send(json.dumps({"type": "caption", "seq": 1, "partial": "Grace"}))
            await websocket.send(
                json.dumps({"type": "caption", "seq": 2, "final": True, "text": "Grace and peace be with you."})
            )
            await asyncio.sleep(0.35)
            await websocket.send(
                json.dumps({"type": "caption", "seq": 3, "final": True, "text": "We are glad you are here."})
            )
            await asyncio.sleep(0.2)
            if attempt == 1:
                await websocket.close()
                return
            await websocket.send(
                json.dumps({"type": "caption", "seq": 4, "final": True, "text": "This is the day."})
            )
        else:
            await websocket.send(json.dumps({"type": "caption", "seq": 10, "partial": "愿恩惠"}))
            for index in range(4):
                payload = (100 + index).to_bytes(4, "big") + b"\x01\x00" * 6000
                await websocket.send(payload)
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.25)
            if attempt == 1:
                await websocket.close()
                return
            await websocket.send(json.dumps({"type": "resumed", "since": since, "captions": 0, "audioMs": 500, "audioSkippedMs": 500}))
            for index in range(4):
                payload = (200 + index).to_bytes(4, "big") + b"\x02\x00" * 6000
                await websocket.send(payload)
                await asyncio.sleep(0.05)
        try:
            await websocket.wait_closed()
        except Exception:  # noqa: BLE001 - the client closing is the normal end
            pass


@unittest.skipUnless(HAVE_WEBSOCKETS, "websockets not installed")
class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        capture.LOG.handlers.clear()
        self.wire = LocalWireServer()
        self.port = await self.wire.start()

    async def asyncTearDown(self):
        await self.wire.stop()
        capture.LOG.handlers.clear()

    async def test_capture_reconnects_and_keeps_both_feeds(self):
        with tempfile.TemporaryDirectory() as raw:
            now = datetime.now(timezone.utc)
            settings = capture.Settings(
                room="test-room",
                english_lang="captions",
                mandarin_lang="zh",
                base_ws=f"ws://127.0.0.1:{self.port}",
                timezone="America/Los_Angeles",
                window=capture.Window(
                    requested_start=now,
                    requested_stop=now.replace(microsecond=0),
                    start=now,
                    stop=now,
                    late_start=False,
                ),
                out_dir=Path(raw),
                out_root=Path(raw),
                capture_english=True,
                capture_mandarin=True,
                keep_pcm=True,
                verbose=False,
            )
            # 4 s window: first connection drops at ~0.6 s, reconnect after ~1 s.
            settings.window = capture.Window(
                requested_start=now,
                requested_stop=now,
                start=now,
                stop=now,
                late_start=False,
            )
            runner = capture.Capture(settings)
            runner.settings.window.stop = now + timedelta(seconds=4)
            runner.settings.window.requested_stop = runner.settings.window.stop
            manifest = await runner.run()
            self.assertEqual(manifest["status"], "captured")
            self.assertTrue((Path(raw) / "capture.json").exists())
            self.assertGreaterEqual(runner.english_client.connections, 2)
            self.assertGreaterEqual(runner.mandarin_client.connections, 2)
            self.assertGreaterEqual(runner.english_sink.finals, 2)
            self.assertGreaterEqual(runner.audio_sink.frames, 4)
            self.assertEqual(runner.audio_sink.pad_ms, 500)
            self.assertEqual(self.wire.since["captions"][1], "3")
            self.assertIsNotNone(manifest["text"]["english"]["sha256"]["finals"])


if __name__ == "__main__":
    unittest.main()
