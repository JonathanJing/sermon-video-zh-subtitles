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
import subprocess
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
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, EXPERIMENT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


mark_window = load_module("live_capture_mark_window_under_test", "mark_window.py")
extract_sermon = load_module("live_capture_extract_under_test", "extract_sermon.py")
build_reading_pdf = load_module("live_capture_build_reading_under_test", "build_reading_pdf.py")

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


class WindowMarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.temp.name)
        (self.run_dir / "capture.json").write_text(
            json.dumps(
                {
                    "schema": "live-translate-capture/v1",
                    "window": {
                        "actual_start": "2026-11-15T18:00:00.000Z",  # 10:00 PST
                        "actual_stop": "2026-11-15T19:20:00.000Z",   # 11:20 PST
                    },
                    "host": {"timezone": "America/Los_Angeles"},
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_records_offset_window_and_checks_binding(self):
        payload = mark_window.record_window(
            self.run_dir,
            start="10:29:35",
            end="11:02:10",
            approved_by="Jony (chat)",
            evidence="reviewed the full service",
        )
        window = payload["sermon_window"]
        self.assertEqual(window["start"], "2026-11-15T18:29:35.000Z")
        self.assertEqual(window["end"], "2026-11-15T19:02:10.000Z")
        self.assertAlmostEqual(window["start_offset_s"], 1775.0, places=3)
        self.assertAlmostEqual(window["end_offset_s"], 3730.0, places=3)
        self.assertAlmostEqual(window["duration_s"], 1955.0, places=3)
        checked = mark_window.check_window(self.run_dir)
        self.assertTrue(checked["ok"])
        self.assertEqual(checked["approved_by"], "Jony (chat)")

        # Same values are idempotent; changed values need --force.
        again = mark_window.record_window(
            self.run_dir,
            start="10:29:35",
            end="11:02:10",
            approved_by="Jony (chat)",
            evidence="reviewed the full service",
        )
        self.assertEqual(again["sermon_window"], window)
        with self.assertRaises(ValueError):
            mark_window.record_window(
                self.run_dir,
                start="10:30:00",
                end="11:02:10",
                approved_by="Jony (chat)",
                evidence="changed",
            )
        replaced = mark_window.record_window(
            self.run_dir,
            start="10:30:00",
            end="11:02:10",
            approved_by="Jony (chat)",
            evidence="changed",
            force=True,
        )
        self.assertEqual(replaced["sermon_window"]["start_offset_s"], 1800.0)

    def test_offset_mode_and_bounds(self):
        payload = mark_window.record_window(
            self.run_dir,
            start_offset="60",
            end_offset="120",
            approved_by="Jony (chat)",
            evidence="offset review",
        )
        self.assertAlmostEqual(payload["sermon_window"]["start_offset_s"], 60.0, places=3)
        self.assertAlmostEqual(payload["sermon_window"]["end_offset_s"], 120.0, places=3)
        with self.assertRaises(ValueError):
            mark_window.record_window(
                self.run_dir,
                start="09:50:00",
                end="11:02:10",
                approved_by="Jony (chat)",
                evidence="outside",
                force=True,
            )
        with self.assertRaises(ValueError):
            mark_window.record_window(
                self.run_dir,
                start="10:30:00",
                end="10:30:30",
                approved_by="Jony (chat)",
                evidence="too short",
                force=True,
            )

    def test_capture_hash_mismatch_is_rejected(self):
        mark_window.record_window(
            self.run_dir,
            start="10:29:35",
            end="11:02:10",
            approved_by="Jony (chat)",
            evidence="reviewed",
        )
        manifest_path = self.run_dir / "capture.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["notes"] = ["capture edited after the window was recorded"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ValueError):
            mark_window.check_window(self.run_dir)


class ExtractSermonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.temp.name)
        (self.run_dir / "capture.json").write_text(
            json.dumps(
                {
                    "schema": "live-translate-capture/v1",
                    "window": {
                        "actual_start": "2026-11-15T18:00:00.000Z",
                        "actual_stop": "2026-11-15T19:20:00.000Z",
                    },
                    "host": {"timezone": "America/Los_Angeles"},
                }
            ),
            encoding="utf-8",
        )
        self.write_jsonl(
            "session.english.jsonl",
            [
                {"ts": "2026-11-15T17:58:00.000Z", "text": "before the window"},
                {"ts": "2026-11-15T18:05:00.000Z", "text": "first sermon line."},
                {"ts": "2026-11-15T18:10:00.000Z", "text": "second sermon line."},
                {"ts": "2026-11-15T18:30:00.000Z", "text": "after the window"},
            ],
        )
        self.write_jsonl(
            "session.mandarin.jsonl",
            [
                {"ts": "2026-11-15T18:05:00.000Z", "text": "第一句。"},
                {"ts": "2026-11-15T18:10:00.000Z", "text": "第二句。"},
            ],
        )
        mark_window.record_window(
            self.run_dir,
            start="10:04:00",
            end="10:11:00",
            approved_by="test operator",
            evidence="test window",
        )

    def tearDown(self):
        self.temp.cleanup()

    def write_jsonl(self, name: str, rows: list[dict]) -> None:
        (self.run_dir / name).write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )

    def test_extracts_session_lines_inside_the_window(self):
        manifest = extract_sermon.extract(self.run_dir)
        rows = [json.loads(line) for line in (self.run_dir / "sermon.english.jsonl").read_text().splitlines()]
        self.assertEqual([row["text"] for row in rows], ["first sermon line.", "second sermon line."])
        self.assertEqual(manifest["english"]["lines"], 2)
        self.assertEqual(manifest["source"]["english"]["kind"], "session")
        self.assertEqual(manifest["mandarin"]["lines"], 2)
        self.assertTrue(manifest["mandarin"]["comparison_only"])
        timed = (self.run_dir / "sermon.english.timed.txt").read_text(encoding="utf-8")
        self.assertIn("[00:05:00.000] first sermon line.", timed)
        self.assertTrue((self.run_dir / "sermon.manifest.json").exists())

    def test_falls_back_to_live_arrival_times(self):
        (self.run_dir / "session.english.jsonl").unlink()
        self.write_jsonl(
            "english.finals.jsonl",
            [
                {"received_at": "2026-11-15T18:05:00.000Z", "t_ms": 300000, "text": "live first."},
                {"received_at": "2026-11-15T18:05:00.000Z", "t_ms": 600000, "text": "live second."},
                {"received_at": "2026-11-15T18:20:00.000Z", "t_ms": 1200000, "text": "live after."},
            ],
        )
        manifest = extract_sermon.extract(self.run_dir)
        rows = [json.loads(line) for line in (self.run_dir / "sermon.english.jsonl").read_text().splitlines()]
        self.assertEqual([row["text"] for row in rows], ["live first.", "live second."])
        self.assertEqual(manifest["source"]["english"]["kind"], "live")

    def test_falls_back_when_the_session_file_is_empty(self):
        (self.run_dir / "session.english.jsonl").write_text("", encoding="utf-8")
        self.write_jsonl(
            "english.finals.jsonl",
            [{"received_at": "2026-11-15T18:05:00.000Z", "t_ms": 300000, "text": "live fallback."}],
        )
        manifest = extract_sermon.extract(self.run_dir)
        self.assertEqual(manifest["source"]["english"]["kind"], "live")
        self.assertEqual(manifest["english"]["lines"], 1)

    def test_requires_a_recorded_window(self):
        (self.run_dir / "sermon.window.json").unlink()
        with self.assertRaises(ValueError):
            extract_sermon.extract(self.run_dir)


class BuildReadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.temp.name)
        (self.run_dir / "capture.json").write_text(
            json.dumps(
                {
                    "schema": "live-translate-capture/v1",
                    "window": {
                        "actual_start": "2026-11-15T18:00:00.000Z",
                        "actual_stop": "2026-11-15T19:20:00.000Z",
                    },
                    "host": {"timezone": "America/Los_Angeles"},
                }
            ),
            encoding="utf-8",
        )
        rows = []
        for minute, text in [
            (5, "The first sentence of the sermon is here."),
            (6, "The second sentence continues the same thought."),
            (7, "The third sentence adds a little more context."),
            (8, "The fourth sentence names Jesus and the church."),
            (9, "The fifth sentence closes the opening paragraph."),
            (10, "The sixth sentence begins the next paragraph."),
        ]:
            rows.append({"ts": f"2026-11-15T18:{minute:02d}:00.000Z", "text": text})
        (self.run_dir / "session.english.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
        )
        mark_window.record_window(
            self.run_dir,
            start="10:04:00",
            end="10:11:00",
            approved_by="test operator",
            evidence="test window",
        )
        extract_sermon.extract(self.run_dir)
        self.settings = build_reading_pdf.BuildSettings(
            capture_dir=self.run_dir,
            outdir=self.run_dir / "reading",
            title="Test Sermon",
            sermon_date="2026-11-15",
            speaker=None,
            glossary=None,
            en_model="test-en",
            zh_model="test-zh",
            reading_model="test-reading",
            reasoning_effort="high",
            translation_workers=1,
            no_english_cleanup=False,
            hide_timecodes=False,
            max_segments=100,
            max_chars=100000,
            allow_large=False,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_plan_builds_raw_segments_without_paid_calls(self):
        plan = build_reading_pdf.make_plan(self.settings)
        self.assertEqual(plan["status"], "planned")
        self.assertGreater(plan["source"]["reading_segments"], 0)
        self.assertTrue((self.run_dir / "reading" / "segments_timed_en_raw.json").exists())
        self.assertTrue((self.run_dir / "reading" / "reading.plan.json").exists())
        commands = plan["commands"]
        self.assertIn("build_sermon_reading_edition_with_openai.py", commands["readingEdition"][1])
        self.assertIn("workflows.dual_pdf.mobile_pdf", commands["pdf"])

    def test_execute_writes_manifest_pdf_and_qa(self):
        calls = []

        def correct(api_key, segments, *args, **kwargs):
            return [{**segment, "text": segment["text"] + " corrected"} for segment in segments]

        def translate(api_key, segments, *args, **kwargs):
            return [{**segment, "zh": f"译文{segment['id']}"} for segment in segments]

        def qa(english, chinese, glossary):
            return {"hardFailures": {}}

        def runner(command, check=False):
            calls.append(command)
            if "build_sermon_reading_edition_with_openai.py" in command[1]:
                outdir = Path(command[command.index("--outdir") + 1])
                outdir.mkdir(parents=True, exist_ok=True)
                (outdir / "sermon_zh_reading_revised.srt").write_text(
                    "1\n00:00:00,000 --> 00:00:05,000\n译文\n", encoding="utf-8"
                )
                (outdir / "sermon_en_reading_revised.srt").write_text(
                    "1\n00:00:00,000 --> 00:00:05,000\nEnglish\n", encoding="utf-8"
                )
                (outdir / "reading_quality_report.json").write_text(
                    json.dumps({"status": "pass"}), encoding="utf-8"
                )
            elif "workflows.dual_pdf.mobile_pdf" in command:
                out = Path(command[command.index("--out") + 1])
                out.write_bytes(b"%PDF-1.4 test")
            return subprocess.CompletedProcess(command, 0)

        manifest = build_reading_pdf.execute_plan(
            self.settings,
            correct_fn=correct,
            translate_fn=translate,
            qa_fn=qa,
            runner=runner,
            route_check=lambda: None,
            api_key="test-key",
        )
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(len(calls), 2)
        self.assertTrue((self.run_dir / "reading" / "sermon_zh_en_reading.pdf").exists())
        self.assertTrue((self.run_dir / "reading" / "reading.manifest.json").exists())
        self.assertEqual(manifest["readingQuality"]["status"], "pass")
        self.assertIn("pdf_sha256", manifest["outputs"])


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
