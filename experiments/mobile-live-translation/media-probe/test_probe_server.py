from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import time
import unittest

from websockets.datastructures import Headers
from websockets.http11 import Request

from probe_server import (Bucket, FRAME_BYTES, HEADER, MAGIC, MAX_RUNS, Peer, ProbeServer, ROOT,
                          SCHEMA, create_token_file, finite_number, origin_policy, stats, strict_json)

TOKEN = "test_token_" + "a" * 40


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.closed = []

    async def send(self, payload):
        self.sent.append(payload)

    async def close(self, code=1000, reason=""):
        self.closed.append((code, reason))


def auth(role="loopback", token=TOKEN, device="desktop"):
    return {"type": "auth", "schemaVersion": SCHEMA, "token": token,
            "role": role, "device": device, "network": "wifi"}


def frame(epoch, sequence, pcm=None):
    return HEADER.pack(MAGIC, epoch, sequence) + (pcm if pcm is not None else bytes(FRAME_BYTES))


class ConfigurationTests(unittest.TestCase):
    def test_origin_allowlist_is_exact_and_https_only_for_remote(self):
        origins, hosts = origin_policy(18781, ["https://probe.example.org"])
        self.assertIn("https://probe.example.org", origins)
        self.assertIn("probe.example.org", hosts)
        self.assertNotIn("probe.example.org.evil.test", hosts)
        for invalid in ("http://example.org", "https://*.example.org", "https://u:p@example.org",
                        "https://example.org/path", "https://example.org?token=x", "https://example.org/#x"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                origin_policy(18781, [invalid])

    def test_nonfinite_and_boolean_measurements_are_rejected(self):
        for invalid in (True, False, "10", math.inf, math.nan, -1, 60001):
            with self.subTest(value=repr(invalid)), self.assertRaises(ValueError):
                finite_number(invalid)
        self.assertEqual(finite_number(12.3), 12.3)
        for invalid in ('{"value":NaN}', '[1]', '"text"', '{"data":"' + 'x' * 3000 + '"}'):
            with self.assertRaises(ValueError):
                strict_json(invalid)

    def test_bucket_burst_is_bounded_and_recovers_with_elapsed_time(self):
        clock = [0.0]
        bucket = Bucket(10, 5, clock=lambda: clock[0])
        self.assertTrue(all(bucket.take() for _ in range(5)))
        self.assertFalse(bucket.take())
        clock[0] += .1
        self.assertTrue(bucket.take())
        self.assertFalse(bucket.take())

    def test_loopback_control_budget_supports_54_per_second_for_120_seconds(self):
        # Exercise the actual Peer default, with a virtual clock and no network/sleep.
        peer = Peer(FakeSocket(), "loopback", "desktop", "wifi")
        clock = [0.0]
        peer.controls.clock = lambda: clock[0]
        peer.controls.last = 0.0
        self.assertEqual(peer.controls.rate, 65)
        self.assertEqual(peer.controls.capacity, 80)
        for index in range(54 * 120):
            clock[0] = index / 54
            self.assertTrue(peer.controls.take(), f"legal loopback rejected at t={clock[0]}")

        # Even after a long legitimate run, a sustained over-budget client is rejected.
        began = clock[0]
        rejected = []
        for index in range(100 * 5):
            clock[0] = began + (index + 1) / 100
            if not peer.controls.take():
                rejected.append(index)
        self.assertTrue(rejected)
        self.assertLess(rejected[0], 300)

    def test_control_budget_keeps_an_exact_finite_instantaneous_burst(self):
        peer = Peer(FakeSocket(), "loopback", "desktop", "wifi")
        peer.controls.clock = lambda: 0.0
        peer.controls.last = 0.0
        self.assertTrue(all(peer.controls.take() for _ in range(80)))
        self.assertFalse(peer.controls.take())

    def test_summary_percentiles_preserve_missing_evidence(self):
        self.assertIsNone(stats([])["p50"])
        self.assertEqual(stats([3, 1, 2, 4]), {"count": 4, "min": 1, "p50": 2.5, "p95": 4, "max": 4})


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_root = ROOT / ".test-tmp"
        self.temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.temp_root)
        self.directory = Path(self.temp.name)
        self.server = ProbeServer(TOKEN, self.directory / "summaries", public_origins=["https://probe.example.org"])

    async def asyncTearDown(self):
        await self.server.finish_run("unit_test_cleanup")
        self.temp.cleanup()
        try:
            self.temp_root.rmdir()
        except OSError:
            pass

    def peer(self, role="loopback", **overrides):
        payload = auth(role)
        payload.update(overrides)
        return self.server.authenticate(FakeSocket(), payload)

    async def start(self, role="loopback", mode="synthetic"):
        source = self.peer(role)
        receiver = source if role == "loopback" else self.peer("user")
        await self.server.control(receiver, {"type": "playback_ready", "ready": True})
        await self.server.start_run(source, {"mode": mode, "durationSeconds": 30})
        return source, receiver, self.server.run

    def test_private_token_file_is_new_and_never_overwritten(self):
        path = self.directory / "new.token"
        token = create_token_file(path)
        self.assertGreaterEqual(len(token), 43)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            create_token_file(path)
        self.assertEqual(path.read_text().strip(), token)

    def test_host_origin_query_and_file_routes_fail_closed(self):
        def request(path, host="probe.example.org", origin="https://probe.example.org"):
            headers = Headers({"Host": host})
            if origin is not None:
                headers["Origin"] = origin
            return self.server.process_request(None, Request(path, headers))
        self.assertIsNone(request("/ws"))
        self.assertEqual(request("/ws", origin="https://evil.test").status_code, 403)
        self.assertEqual(request("/ws", origin=None).status_code, 403)
        self.assertEqual(request("/", host="probe.example.org.evil.test").status_code, 421)
        self.assertEqual(request("/ws?token=not-supported").status_code, 404)
        for path in ("/api/health", "/api/runtime/restart", "/../probe_server.py", "/summaries/run.json", "/token"):
            self.assertEqual(request(path).status_code, 404)
        shell = request("/")
        self.assertEqual(shell.status_code, 200)
        self.assertNotIn(TOKEN.encode(), shell.body)
        self.assertEqual(shell.headers["Referrer-Policy"], "no-referrer")
        self.assertIn("frame-ancestors 'none'", shell.headers["Content-Security-Policy"])
        duplicate = Headers([("Host", "probe.example.org"), ("Host", "evil.test")])
        self.assertEqual(self.server.process_request(None, Request("/", duplicate)).status_code, 421)

    def test_auth_rejects_bad_token_expiry_and_role_collision(self):
        for token in ("wrong", "b" * 50, "中文" * 30):
            with self.assertRaises(ValueError):
                self.peer(token=token)
        self.peer()
        with self.assertRaises(ValueError):
            self.peer()
        with self.assertRaises(ValueError):
            self.peer("user")
        self.server.peers.clear()
        self.server.deadline = time.monotonic() - 1
        with self.assertRaises(ValueError):
            self.peer()

    async def test_user_cannot_start_or_send_admin_audio(self):
        source, receiver, run = await self.start("admin")
        with self.assertRaises(ValueError):
            await self.server.start_run(receiver, {"mode": "synthetic", "durationSeconds": 20})
        with self.assertRaises(ValueError):
            await self.server.accept_frame(receiver, frame(run.epoch, 1))
        await self.server.accept_frame(source, frame(run.epoch, 1))
        self.assertEqual(run.counts["acceptedFrames"], 1)

    async def test_silent_mode_requires_zero_pcm_and_preserves_non_audible_evidence(self):
        source, receiver, run = await self.start(mode="synthetic_silent")
        await self.server.accept_frame(source, frame(run.epoch, 1))
        with self.assertRaises(ValueError):
            await self.server.accept_frame(source, frame(run.epoch, 2, b"\x01" + bytes(FRAME_BYTES - 1)))
        self.server.acknowledge(receiver, {"type": "received", "epoch": run.epoch, "sequence": 1})
        self.server.acknowledge(receiver, {"type": "played", "epoch": run.epoch, "sequence": 1,
            "receiveToRenderCallbackMs": 100})
        summary = await self.server.finish_run("operator_stop")
        self.assertEqual(summary["inputMode"], "synthetic_silent")
        self.assertTrue(summary["evidence"]["silentPcmValidated"])
        self.assertTrue(summary["evidence"]["audioWorkletPlaybackAcknowledged"])
        self.assertFalse(summary["evidence"]["audibleSignalGeneratedByProbe"])
        self.assertFalse(summary["evidence"]["audibleOutputValidated"])
        self.assertFalse(summary["evidence"]["microphoneInputRequested"])
        self.assertTrue(any("zero-valued PCM" in note for note in summary["measurementNotes"]))

    async def test_start_waits_for_playback_and_enforces_run_duration_and_count(self):
        source = self.peer()
        await self.server.start_run(source, {"mode": "synthetic", "durationSeconds": 20})
        self.assertIsNone(self.server.run)
        source.ready = True
        for duration in (0, 4, 121, True):
            with self.assertRaises(ValueError):
                await self.server.start_run(source, {"mode": "synthetic", "durationSeconds": duration})
        self.server.completed = MAX_RUNS
        with self.assertRaises(ValueError):
            await self.server.start_run(source, {"mode": "synthetic", "durationSeconds": 20})

    async def test_pcm_requires_exact_header_size_epoch_and_monotonic_sequence(self):
        source, _, run = await self.start()
        for invalid in (b"audio", frame(run.epoch, 1) + b"x", frame(run.epoch + 1, 1),
                        b"BAD!" + frame(run.epoch, 1)[4:]):
            with self.assertRaises(ValueError):
                await self.server.accept_frame(source, invalid)
        await self.server.accept_frame(source, frame(run.epoch, 1))
        await self.server.accept_frame(source, frame(run.epoch, 3))
        self.assertEqual(run.counts["sourceSequenceGaps"], 1)
        with self.assertRaises(ValueError):
            await self.server.accept_frame(source, frame(run.epoch, 3))

    async def test_pcm_burst_limit_and_outbound_queue_bound(self):
        source, receiver, run = await self.start()
        for sequence in range(1, 6):
            await self.server.accept_frame(source, frame(run.epoch, sequence))
        with self.assertRaises(ValueError):
            await self.server.accept_frame(source, frame(run.epoch, 6))
        receiver.clear()
        for _ in range(16):
            self.assertTrue(receiver.enqueue(b"queued", epoch=run.epoch))
        source.frames = Bucket(10, 5)
        await self.server.accept_frame(source, frame(run.epoch, 6))
        self.assertEqual(receiver.outbox.qsize(), 16)
        self.assertEqual(run.counts["transportQueueDrops"], 1)

    async def test_playback_receipts_and_source_rtt_are_distinct_measurements(self):
        source, receiver, run = await self.start("admin")
        await self.server.accept_frame(source, frame(run.epoch, 1))
        self.server.acknowledge(receiver, {"type": "received", "epoch": run.epoch, "sequence": 1})
        self.server.acknowledge(receiver, {"type": "played", "epoch": run.epoch, "sequence": 1,
            "receiveToRenderCallbackMs": 108, "receiveToOutputEstimateMs": None})
        self.server.observe(source, {"type": "observation", "epoch": run.epoch, "sequence": 1,
            "name": "mediaReceiveAckRttMs", "value": 30})
        self.server.observe(source, {"type": "observation", "epoch": run.epoch, "sequence": 1,
            "name": "mediaPlaybackAckRttMs", "value": 140})
        self.assertEqual(run.metrics["mediaReceiveAckRttMs"], [30])
        self.assertEqual(run.metrics["mediaPlaybackAckRttMs"], [140])
        self.assertNotIn("receiveToOutputEstimateMs", run.metrics)
        with self.assertRaises(ValueError):
            self.server.acknowledge(receiver, {"type": "received", "epoch": run.epoch, "sequence": 1})

    async def test_observations_require_acknowledged_known_frames(self):
        source, _, run = await self.start()
        await self.server.accept_frame(source, frame(run.epoch, 1))
        with self.assertRaises(ValueError):
            self.server.observe(source, {"epoch": run.epoch, "sequence": 1, "name": "mediaPlaybackAckRttMs", "value": 5})
        with self.assertRaises(ValueError):
            self.server.observe(source, {"epoch": run.epoch, "sequence": 999, "name": "mediaReceiveAckRttMs", "value": 5})

    async def test_ping_identity_window_covers_eight_seconds_of_legitimate_traffic(self):
        peer = self.peer()
        # Two pings/s can be outstanding for up to the frontend's 8-second watchdog.
        for ping_id in range(1, 17):
            await self.server.control(peer, {"type": "ping", "id": ping_id})
            peer.clear()  # Simulate normal outbound delivery.
        for ping_id in range(1, 17):
            await self.server.control(peer, {"type": "rtt", "id": ping_id, "value": 7500})
        self.assertEqual(peer.ping_ids, set())

    async def test_stop_clears_media_and_saves_only_bounded_summary_without_audio_or_token(self):
        source, receiver, run = await self.start(mode="microphone")
        marker = b"private_audio_bytes"
        pcm = (marker * (FRAME_BYTES // len(marker))).ljust(FRAME_BYTES, b"\0")
        self.assertEqual(len(pcm), FRAME_BYTES)
        await self.server.accept_frame(source, frame(run.epoch, 1, pcm))
        summary = await self.server.finish_run("operator_stop")
        self.assertIsNone(self.server.run)
        queued = [receiver.outbox.get_nowait()[0] for _ in range(receiver.outbox.qsize())]
        self.assertTrue(all(isinstance(item, str) for item in queued))
        self.assertEqual(json.loads(queued[-1])["type"], "stopped")
        await self.server.accept_frame(source, frame(run.epoch, 2, pcm))
        self.server.acknowledge(receiver, {"type": "played", "epoch": run.epoch, "sequence": 1})
        self.assertEqual(summary["counts"]["playbackAcknowledgements"], 0)
        files = list((self.directory / "summaries").iterdir())
        self.assertEqual(len(files), 1)
        stored = files[0].read_text()
        self.assertNotIn(TOKEN, stored)
        self.assertNotIn("private_audio_bytes", stored)
        self.assertFalse(summary["evidence"]["audioPersisted"])
        self.assertFalse(summary["evidence"]["phoneVerifiedByProbe"])
        self.assertFalse(summary["evidence"]["headphoneAcousticLatencyMeasured"])
        self.assertFalse(summary["evidence"]["crossDeviceOneWayLatencyClaimed"])

    async def test_writer_discards_stale_queued_media(self):
        source, receiver, run = await self.start()
        receiver.clear()
        await self.server.accept_frame(source, frame(run.epoch, 1))
        wire, _, epoch = receiver.outbox.get_nowait()
        receiver.outbox.put_nowait((wire, time.monotonic() - 1, epoch))
        writer = asyncio.create_task(self.server.writer(receiver))
        await asyncio.sleep(.01)
        writer.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await writer
        self.assertEqual(receiver.socket.sent, [])
        self.assertEqual(run.counts["transportExpiredFrames"], 1)

    async def test_expiry_ends_active_run_without_reusing_token(self):
        await self.start()
        self.server.deadline = time.monotonic() - 1
        await self.server.expire()
        self.assertTrue(self.server.stopping.is_set())
        self.assertIsNone(self.server.run)
        self.assertEqual(self.server.last_summary["stopReason"], "token_expired")


if __name__ == "__main__":
    unittest.main()
