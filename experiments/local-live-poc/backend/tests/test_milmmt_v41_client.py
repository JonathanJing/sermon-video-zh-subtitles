"""Local HTTP and controller fixtures; never load MLX or start the real service."""
from __future__ import annotations

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend import milmmt_v41_client as module
from backend.ollama_client import MILMMT_A0_PROMPT_VERSION, OllamaError


def health(**changes):
    return {"service": module.SERVICE, "status": "ready", "busy": False,
            "pid": 12345, "instanceId": "fixture-instance", "releaseEligible": False,
            "modelSha256": module.WEIGHTS_SHA, "packageSha256": module.MANIFEST_SHA,
            "runtimePackages": dict(module.EXPECTED_RUNTIME_PACKAGES), **changes}


def done(source="source", text="中文译文。", **changes):
    return {"type": "done", "text": text, "source": source, "finishReason": "stop",
            "promptTokens": 25, "generatedTokens": 5, "generatedTokenIdsSha256": "a" * 64,
            "elapsedMs": 123.4, "firstChineseMs": 20.0, "timingScope": module.SERVICE_TIMING_SCOPE,
            "experimental": True, "releaseEligible": False, "modelSha256": module.WEIGHTS_SHA, **changes}


def ndjson(events):
    return b"".join(json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n" for event in events)


class ClientTests(unittest.TestCase):
    def make_client(self, *, client_options=None, **configuration):
        probe = {"health": health(), "healthRequests": 0, "payloads": [], "translationStatus": 200,
                 "translationHeaders": {}, "stopped": threading.Event(), **configuration}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def response(self, content, content_type, status=200, overrides=None, chunks=None):
                self.send_response(status)
                headers = {"Content-Type": content_type, "Connection": "close"}
                if chunks is None:
                    headers["Content-Length"] = str(len(content))
                headers.update(overrides or {})
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    for part in ([content] if chunks is None else chunks):
                        if probe["stopped"].is_set():
                            break
                        self.wfile.write(part)
                        self.wfile.flush()
                        if chunks is not None:
                            probe["stopped"].wait(probe.get("chunkDelay", 0))
                except (BrokenPipeError, ConnectionResetError):
                    probe["clientDisconnected"] = True

            def do_GET(self):
                probe["healthRequests"] += 1
                self.response(json.dumps(probe["health"]).encode(), "application/json",
                              overrides=probe.get("healthHeaders"))

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                probe["payloads"].append({"path": self.path, "body": payload})
                events = probe.get("events")
                if events is None:
                    events = [{"type": "delta", "text": "中文"}, {"type": "delta", "text": "译文。"},
                              done(payload["text"])]
                content = probe.get("raw", ndjson(events))
                self.response(content, "application/x-ndjson; charset=utf-8", probe["translationStatus"],
                              probe["translationHeaders"], probe.get("chunks"))

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.005), daemon=True)
        thread.start()

        def cleanup():
            probe["stopped"].set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
        self.addCleanup(cleanup)
        client = module.MilmmtV41Client(f"http://127.0.0.1:{server.server_port}", **(client_options or {}))
        return client, probe

    def test_source_only_stream_accumulates_callbacks_and_preserves_source_bytes(self):
        client, probe = self.make_client()
        callbacks = []
        source = "  Grace saves.\nNo added context.\t"
        result = client.translate(source, {}, lambda delta, total: callbacks.append((delta, total)))
        self.assertEqual(callbacks, [("中文", "中文"), ("译文。", "中文译文。")])
        self.assertEqual(probe["payloads"], [{"path": "/api/translate", "body": {"text": source, "stream": True}}])
        self.assertEqual(probe["healthRequests"], 1)
        self.assertEqual(result["targetTextZh"], "中文译文。")
        self.assertEqual(result["model"], module.MODEL_ID)
        self.assertEqual(result["translationProvider"], module.PROVIDER_ID)
        self.assertEqual(result["promptVersion"], MILMMT_A0_PROMPT_VERSION)
        self.assertEqual(result["modelSha256"], module.WEIGHTS_SHA)
        self.assertEqual(result["packageSha256"], module.MANIFEST_SHA)
        self.assertEqual(result["generatedTokenIdsSha256"], "a" * 64)
        self.assertTrue(result["experimental"])
        self.assertFalse(result["releaseEligible"])
        self.assertEqual(result["metrics"]["evalCount"], 5)
        self.assertEqual(result["metrics"]["promptEvalCount"], 25)
        self.assertEqual(result["metrics"]["mlxWorkerElapsedMs"], 123.4)
        self.assertIn("backpressure", result["metrics"]["timingScope"])
        for name in ("evalDurationNs", "promptEvalDurationNs", "loadDurationNs", "totalDurationNs"):
            self.assertNotIn(name, result["metrics"], "MLX wall time must not impersonate Ollama phase timing")
        result["decodeContract"]["quantization"]["bits"] = 99
        self.assertEqual(client.translate("source", {})["decodeContract"]["quantization"]["bits"], 5)

    def test_no_callback_still_requests_stream_and_does_not_trim_prediction(self):
        value = " 中文 \n"
        client, probe = self.make_client(events=[{"type": "delta", "text": value}, done(text=value)])
        result = client.translate("source", {key: [] for key in module.EMPTY_CONTEXT_KEYS})
        self.assertEqual(result["targetTextZh"], value)
        self.assertTrue(probe["payloads"][0]["body"]["stream"])
        self.assertNotIn("context", probe["payloads"][0]["body"])

    def test_nonempty_or_unknown_context_is_rejected_before_any_request(self):
        client, probe = self.make_client()
        for context in ({"approvedTerms": ["grace"]}, {"reviewedAlignedReferences": ["candidate"]},
                        {"unknown": []}, {"approvedTerms": None}, {"approvedTerms": ""}, [], "context"):
            with self.subTest(context=context), self.assertRaises(OllamaError):
                client.translate("source", context)
        self.assertEqual(probe["healthRequests"], 0)
        self.assertEqual(probe["payloads"], [])

    def test_invalid_source_and_limits_fail_before_http(self):
        client, probe = self.make_client()
        for source in (None, 123, "", " \n", "x" * (module.MAX_SOURCE + 1), "bad\x00", "bad\ud800"):
            with self.subTest(source=repr(source)), self.assertRaises(OllamaError):
                client.translate(source, {})
        self.assertEqual(probe["healthRequests"], 0)

    def test_status_validates_identity_and_separates_loading_from_ready(self):
        client, probe = self.make_client()
        status = client.status()
        self.assertTrue(status["available"])
        self.assertTrue(status["ready"])
        self.assertTrue(status["configuredModelInstalled"])
        self.assertEqual(status["configuredModel"], module.MODEL_ID)
        self.assertFalse(status["busy"])
        self.assertFalse(status["startSupported"], "custom test port cannot launch the fixed real service")
        probe["health"] = health(status="loading", runtimePackages={})
        status = client.status()
        self.assertTrue(status["available"])
        self.assertFalse(status["ready"])
        self.assertFalse(status["configuredModelInstalled"])
        self.assertEqual(status["runtimeStatus"], "loading")
        probe["health"] = health(status="failed", error="PRIVATE SOURCE SHOULD NOT LEAK")
        status = client.status()
        self.assertFalse(status["ready"])
        self.assertTrue(status["configuredModelInstalled"])
        self.assertNotIn("PRIVATE", json.dumps(status))

    def test_health_identity_types_and_package_drift_fail_closed(self):
        client, probe = self.make_client()
        changes = {"service": "mlx-server", "schemaVersion": "other-v2", "modelSha256": "wrong",
                   "packageSha256": "wrong", "releaseEligible": 0, "busy": 0, "pid": True,
                   "instanceId": "", "status": [], "runtimePackages": {"mlx": "0.99"}}
        for field, value in changes.items():
            with self.subTest(field=field):
                probe["health"] = health(**{field: value})
                status = client.status()
                self.assertFalse(status["available"])
                self.assertFalse(status["ready"])
                self.assertIsNone(status["modelSha256"])
                self.assertIsNone(status["packageSha256"])
                with self.assertRaises(OllamaError):
                    client.translate("source", {})
        self.assertEqual(probe["payloads"], [])
        probe["health"] = health(runtimePackages={})
        self.assertFalse(client.status()["ready"])

    def test_loading_busy_and_failed_never_send_translation(self):
        client, probe = self.make_client()
        for change in ({"status": "loading", "runtimePackages": {}}, {"status": "failed"}, {"busy": True}):
            probe["health"] = health(**change)
            with self.assertRaises(OllamaError):
                client.translate("source", {})
        self.assertEqual(probe["payloads"], [])

    def test_http_errors_and_redirects_are_not_followed_or_echoed(self):
        client, probe = self.make_client(raw=b"PRIVATE TEXT bearer SECRET")
        for code in (302, 400, 413, 429, 500, 503):
            probe["translationStatus"] = code
            probe["translationHeaders"] = {"Location": "http://remote.invalid/private?token=SECRET"}
            with self.subTest(code=code), self.assertRaises(OllamaError) as caught:
                client.translate("source", {})
            self.assertIn(str(code), str(caught.exception))
            self.assertNotIn("PRIVATE", str(caught.exception))
            self.assertNotIn("SECRET", str(caught.exception))
        self.assertEqual(len(probe["payloads"]), 6)

    def test_protocol_errors_do_not_return_or_echo_untrusted_error_text(self):
        client, probe = self.make_client()
        cases = [b"not json\n", b"[]\n", b'{"type":"delta","type":"done","text":"secret"}\n',
                 b'{"type":"delta","text":"PRIVATE","x":NaN}\n',
                 b'{"type":"delta","text":"\\ud800"}\n',
                 ndjson([{"type": "unknown"}]), ndjson([{"type": "delta", "text": 123}]),
                 ndjson([{"type": "delta", "text": ""}]),
                 ndjson([{"type": "error", "error": "PRIVATE SECRET", "status": 503}]),
                 ndjson([{"type": "delta", "text": "unfinished"}]), b""]
        for raw in cases:
            probe["raw"] = raw
            with self.subTest(raw=raw), self.assertRaises(OllamaError) as caught:
                client.translate("source", {})
            self.assertNotIn("PRIVATE", str(caught.exception))
            self.assertNotIn("SECRET", str(caught.exception))

    def test_done_binds_source_model_counts_decode_and_exact_delta_text(self):
        client, probe = self.make_client()
        changes = [("source", "other"), ("text", "different"), ("finishReason", "length"),
                   ("modelSha256", "other"), ("experimental", 1), ("releaseEligible", 0),
                   ("generatedTokenIdsSha256", None), ("generatedTokenIdsSha256", "z" * 64),
                   ("generatedTokens", True), ("generatedTokens", 513), ("promptTokens", 0),
                   ("promptTokens", 1025), ("elapsedMs", -1), ("elapsedMs", True),
                   ("firstChineseMs", 999), ("timingScope", "Ollama decode duration")]
        for field, value in changes:
            probe["events"] = [{"type": "delta", "text": "中文译文。"}, done(**{field: value})]
            with self.subTest(field=field, value=value), self.assertRaises(OllamaError):
                client.translate("source", {})
        for required in ("source", "text", "generatedTokenIdsSha256", "experimental", "releaseEligible", "modelSha256"):
            final = done()
            final.pop(required)
            probe["events"] = [{"type": "delta", "text": "中文译文。"}, final]
            with self.subTest(missing=required), self.assertRaises(OllamaError):
                client.translate("source", {})

    def test_done_must_be_unique_terminal_frame_followed_by_clean_eof(self):
        client, probe = self.make_client()
        prefix = [{"type": "delta", "text": "中文译文。"}, done()]
        for trailing in (done(), {"type": "delta", "text": "extra"}, {"type": "error"}):
            probe["events"] = [*prefix, trailing]
            with self.subTest(trailing=trailing), self.assertRaises(OllamaError):
                client.translate("source", {})
        probe["raw"] = ndjson(prefix).rstrip(b"\n")
        with self.assertRaisesRegex(OllamaError, "unterminated"):
            client.translate("source", {})
        probe["raw"] = ndjson(prefix)
        probe["translationHeaders"] = {"Content-Length": str(len(probe["raw"]) + 5)}
        with self.assertRaises(OllamaError):
            client.translate("source", {})

    def test_response_content_encoding_framing_and_size_are_bounded(self):
        client, probe = self.make_client(client_options={"max_response_bytes": 2048, "max_line_bytes": 1024})
        for headers in ({"Content-Type": "text/plain"}, {"Content-Encoding": "gzip"},
                        {"Content-Length": "99999999"}, {"Content-Length": "-1"},
                        {"Transfer-Encoding": "chunked"}):
            probe["translationHeaders"] = headers
            with self.subTest(headers=headers), self.assertRaises(OllamaError):
                client.translate("source", {})
        probe["translationHeaders"] = {}
        probe["raw"] = b" " * 2049
        with self.assertRaises(OllamaError):
            client.translate("source", {})
        probe["raw"] = b" " * 1025 + b"\n"
        with self.assertRaisesRegex(OllamaError, "record exceeds"):
            client.translate("source", {})

    def test_utf8_and_ndjson_may_span_arbitrary_socket_chunks(self):
        events = [{"type": "delta", "text": "中文译文。"}, done()]
        raw = ndjson(events)
        client, _ = self.make_client(chunks=[raw[i:i + 1] for i in range(len(raw))])
        self.assertEqual(client.translate("source", {})["targetTextZh"], "中文译文。")

    def test_whole_deadline_stops_a_trickling_unterminated_line(self):
        client, _ = self.make_client(chunks=[b" "] * 100, chunkDelay=.015,
                                    client_options={"translation_timeout": .15, "io_timeout": 1})
        started = time.monotonic()
        with self.assertRaises(OllamaError):
            client.translate("source", {})
        self.assertLess(time.monotonic() - started, .8, "idle timeouts must not permit an endless trickle")

    def test_fixed_event_count_prevents_unbounded_empty_protocol_chatter(self):
        client, _ = self.make_client(events=[{"type": "delta", "text": "a"}] * (module.MAX_STREAM_EVENTS + 1))
        with self.assertRaisesRegex(OllamaError, "event limit"):
            client.translate("source", {})

    def test_callback_failure_closes_translation_with_compatible_error(self):
        client, _ = self.make_client()
        def broken(_delta, _total):
            raise RuntimeError("PRIVATE delivery detail")
        with self.assertRaisesRegex(OllamaError, "partial delivery failed") as caught:
            client.translate("source", {}, broken)
        self.assertNotIn("PRIVATE", str(caught.exception))

    def test_proxy_environment_cannot_intercept_loopback_requests(self):
        client, _ = self.make_client()
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "http_proxy": "http://127.0.0.1:1",
                                     "HTTPS_PROXY": "http://127.0.0.1:1", "ALL_PROXY": "http://127.0.0.1:1", "NO_PROXY": "", "no_proxy": ""}):
            self.assertTrue(client.status()["ready"])
            self.assertEqual(client.translate("source", {})["targetTextZh"], "中文译文。")


class ConfigurationAndStartupTests(unittest.TestCase):
    def test_only_explicit_loopback_http_origins_are_accepted(self):
        for value in ("http://127.0.0.1:18771", "http://localhost:18771/", "http://127.0.0.1:12345"):
            with self.subTest(value=value):
                client = module.MilmmtV41Client(value)
                self.assertTrue(client.base_url.startswith("http://127.0.0.1:"))
        for value in ("https://127.0.0.1:18771", "http://127.0.0.1", "http://127.0.0.1:0", "http://127.0.0.1:99999",
                      "http://0.0.0.0:18771", "http://192.168.1.1:18771", "http://localhost.evil:18771",
                      "http://user:secret@127.0.0.1:18771", "http://127.0.0.1:18771/api",
                      "http://127.0.0.1:18771?", "http://127.0.0.1:18771#", "http://127.0.0.1:18771?token=secret",
                      "http://127.0.0.1:18771/#secret", " http://127.0.0.1:18771", "http://127.0.0.1:\t18771",
                      "http://127.1:18771", "http://2130706433:18771", "http://127.0.0.1:18771\\anything"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.MilmmtV41Client(value)

    def test_model_is_fixed_and_constructor_bounds_cannot_be_disabled(self):
        client = module.MilmmtV41Client()
        self.assertEqual(client.model, module.MODEL_ID)
        with self.assertRaises(AttributeError):
            client.model = "another-model"
        for options in ({"translation_timeout": 0}, {"translation_timeout": 101}, {"io_timeout": float("inf")},
                        {"health_timeout": True}, {"max_line_bytes": 0}, {"max_response_bytes": module.MAX_RESPONSE_BYTES + 1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                module.MilmmtV41Client(**options)

    def launcher_client(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        python = root / "fake-python"
        python.write_text("not executed")
        python.chmod(0o700)
        runner = root / "runner.py"
        runner.write_text("not executed")
        client = module.MilmmtV41Client(python_path=python, runtime_script=runner,
                                        model_path=root / "model", state_dir=root / "state")
        return client

    def test_start_supported_requires_local_fixed_endpoint_and_executable_python(self):
        client = self.launcher_client()
        self.assertTrue(client.start_supported)
        client.python_path.chmod(0o600)
        self.assertFalse(client.start_supported)
        client.python_path.chmod(0o700)
        client.runtime_script.unlink()
        self.assertFalse(client.start_supported)

    def test_same_package_ready_service_is_reused_without_any_subprocess(self):
        client = module.MilmmtV41Client()
        ready = client._status(health())
        with patch.object(client, "status", return_value=ready), patch.object(module.subprocess, "run") as run:
            self.assertEqual(client.start_runtime(), ready)
        run.assert_not_called()

    def test_fixed_launcher_argv_timeout_and_verified_ready_postcondition(self):
        client = self.launcher_client()
        before, after = client._status(error="unavailable"), client._status(health())
        with patch.object(client, "status", side_effect=[before, after]), \
                patch.object(module.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(client.start_runtime(), after)
        run.assert_called_once_with([str(client.python_path), str(client.runtime_script), "start", "--port", "18771",
                                    "--model", str(client.model_path), "--state-dir", str(client.state_dir)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=100, check=False)

    def test_launcher_preserves_venv_python_symlink_instead_of_resolving_base_interpreter(self):
        original = self.launcher_client()
        link = original.python_path.parent / "venv" / "bin" / "python"
        link.parent.mkdir(parents=True)
        link.symlink_to(original.python_path)
        client = module.MilmmtV41Client(python_path=link, runtime_script=original.runtime_script,
                                        model_path=original.model_path, state_dir=original.state_dir)
        self.assertEqual(client.python_path, link.absolute())
        self.assertNotEqual(client.python_path, link.resolve())
        self.assertTrue(client.start_supported)
        with patch.object(client, "status", side_effect=[client._status(error="unavailable"), client._status(health())]), \
                patch.object(module.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            client.start_runtime()
        self.assertEqual(run.call_args.args[0][0], str(link.absolute()))

    def test_failed_timeout_or_unready_start_raises_compatible_error_without_logs(self):
        client = self.launcher_client()
        unavailable = client._status(error="unavailable")
        for behavior in (SimpleNamespace(returncode=1), SimpleNamespace(returncode=0),
                         subprocess.TimeoutExpired(["private"], 100, output="SECRET"), OSError("SECRET")):
            with self.subTest(behavior=type(behavior).__name__), patch.object(client, "status", return_value=unavailable), \
                    patch.object(module.subprocess, "run", **({"side_effect": behavior} if isinstance(behavior, Exception) else {"return_value": behavior})):
                with self.assertRaises(OllamaError) as caught:
                    client.start_runtime()
                self.assertNotIn("SECRET", str(caught.exception))
        client.runtime_script.unlink()
        with patch.object(client, "status", return_value=unavailable), patch.object(module.subprocess, "run") as run:
            with self.assertRaises(OllamaError):
                client.start_runtime()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
