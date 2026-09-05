"""Behavior checks for the experimental local server; no MLX/model loading."""
from argparse import Namespace
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import serve_milmmt_v41_local as server


class FakeEngine:
    def __init__(self, probe):
        self.probe = probe
        self.packages = {"fake-engine": "unit-test"}
        probe["factoryThread"] = threading.get_ident()
        if probe.get("initializationFailure"):
            raise ValueError("test initialization failure")

    def translate(self, source, emit, cancelled):
        self.probe["calls"].append((source, threading.get_ident()))
        if source == server.WARMUP:
            self.probe["warming"].set()
            if self.probe.get("warmupFailure"):
                raise ValueError("test warmup failure")
            if self.probe.get("holdWarmup"):
                if not self.probe["release"].wait(2):
                    raise RuntimeError("test did not release warmup")
            return {"text": "预热。"}
        if source == "blocked":
            self.probe["entered"].set()
            while not self.probe["release"].wait(0.01):
                if cancelled.is_set():
                    raise server.RequestError("test cancelled", 499)
        if source == "internal-error":
            raise RuntimeError("test engine fault")
        emit({"type": "delta", "text": "中文"})
        if source == "request-error":
            raise server.RequestError("test request rejected", 422)
        emit({"type": "delta", "text": "译文。"})
        return {"text": "中文译文。", "source": source, "finishReason": "stop",
                "experimental": True, "releaseEligible": False}


class RuntimeFixture(unittest.TestCase):
    def wait_for(self, predicate, message="condition did not become true"):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if predicate():
                return
            threading.Event().wait(0.005)
        self.fail(message)

    def make_runtime(self, *, wait_status="ready", **options):
        probe = {"calls": [], "warming": threading.Event(), "entered": threading.Event(),
                 "release": threading.Event(), **options}
        runtime = server.Runtime(Path("unused-fake-model"), "unit-test-instance",
                                 engine_factory=lambda _: FakeEngine(probe))
        runtime.worker.start()
        self.addCleanup(runtime.stop)
        self.addCleanup(probe["release"].set)
        if wait_status:
            self.wait_for(lambda: runtime.health()["status"] == wait_status, f"runtime did not reach {wait_status}")
        return runtime, probe

    def assert_request_status(self, status, function, *args):
        with self.assertRaises(server.RequestError) as caught:
            function(*args)
        self.assertEqual(caught.exception.status, status)


class RequestContractTests(unittest.TestCase):
    def test_self_contained_official_prompt_keeps_frozen_source_bytes(self):
        source = "  Grace saves.\nHe is faithful.\t"
        expected = "Translate this from English to Chinese (Simplified):\nEnglish: " + source + "\nChinese (Simplified):"
        self.assertEqual(server.official_prompt(source).encode(), expected.encode())

    def test_valid_source_is_preserved_and_stream_is_explicit_boolean(self):
        text = "  English source.\nA second line.\t\r"
        self.assertEqual(server.validate_request({"text": text}), (text, False))
        self.assertEqual(server.validate_request({"text": text, "stream": True}), (text, True))
        self.assertEqual(server.validate_request({"text": "x" * server.MAX_SOURCE})[0], "x" * server.MAX_SOURCE)

    def test_decode_or_model_overrides_are_rejected(self):
        for name in ("temperature", "top_p", "max_tokens", "model", "eos_token_id", "prompt", "systemPrompt", "generationConfig"):
            with self.subTest(name=name), self.assertRaises(server.RequestError) as caught:
                server.validate_request({"text": "Hello", name: "override"})
            self.assertEqual(caught.exception.status, 400)

    def test_missing_wrong_types_control_characters_and_limits(self):
        invalid = [None, [], "hello", {}, {"text": None}, {"text": 123}, {"text": True},
                   {"text": ""}, {"text": " \n\t"}, {"text": "hello", "stream": 0},
                   {"text": "hello", "stream": "true"}, {"text": "hello", "stream": None}]
        invalid.extend({"text": "bad" + character} for character in ("\x00", "\x1f", "\ud800", "\udfff"))
        for value in invalid:
            with self.subTest(value=repr(value)), self.assertRaises(server.RequestError) as caught:
                server.validate_request(value)
            self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(server.RequestError) as caught:
            server.validate_request({"text": "x" * (server.MAX_SOURCE + 1)})
        self.assertEqual(caught.exception.status, 413)


class RuntimeTests(RuntimeFixture):
    def test_loading_is_not_ready_until_warmup_finishes(self):
        runtime, probe = self.make_runtime(wait_status=None, holdWarmup=True)
        self.assertTrue(probe["warming"].wait(1))
        self.assertEqual(runtime.health()["status"], "loading")
        self.assert_request_status(503, runtime.submit, "source")
        probe["release"].set()
        self.wait_for(lambda: runtime.health()["status"] == "ready")
        self.assertEqual(runtime.health()["runtimePackages"], {"fake-engine": "unit-test"})
        self.assertFalse(runtime.health()["releaseEligible"])

    def test_initialization_and_warmup_failure_never_accept_jobs(self):
        for option in ("initializationFailure", "warmupFailure"):
            with self.subTest(option=option):
                runtime, _ = self.make_runtime(wait_status="failed", **{option: True})
                self.assert_request_status(503, runtime.submit, "source")
                self.assertFalse(runtime.health()["busy"])

    def test_concurrent_submits_claim_one_worker_and_busy_429(self):
        runtime, probe = self.make_runtime()
        barrier = threading.Barrier(3)
        accepted, rejected = [], []

        def submit():
            barrier.wait()
            try:
                accepted.append(runtime.submit("blocked"))
            except server.RequestError as error:
                rejected.append(error.status)

        threads = [threading.Thread(target=submit) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=1)
        for thread in threads:
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(accepted), 1)
        self.assertEqual(rejected, [429])
        self.assertTrue(probe["entered"].wait(1))
        self.assertTrue(runtime.health()["busy"])
        probe["release"].set()
        self.assertEqual(accepted[0].result.result(timeout=1)["text"], "中文译文。")
        self.wait_for(lambda: not runtime.health()["busy"])
        runtime.submit("second").result.result(timeout=1)
        self.assertEqual({thread_id for _, thread_id in probe["calls"]}, {runtime.worker.ident})
        self.assertEqual(probe["factoryThread"], runtime.worker.ident)
        self.assertEqual([source for source, _ in probe["calls"]], [server.WARMUP, "blocked", "second"])

    def test_request_error_releases_busy_and_runtime_recovers(self):
        runtime, _ = self.make_runtime()
        job = runtime.submit("request-error")
        self.assert_request_status(422, job.result.result, 1)
        self.wait_for(lambda: not runtime.health()["busy"])
        self.assertEqual(runtime.health()["status"], "ready")
        self.assertEqual(runtime.submit("retry").result.result(timeout=1)["source"], "retry")

    def test_internal_error_fails_runtime_and_prevents_later_inference(self):
        runtime, probe = self.make_runtime()
        job = runtime.submit("internal-error")
        self.assert_request_status(503, job.result.result, 1)
        self.wait_for(lambda: not runtime.health()["busy"])
        self.assertEqual(runtime.health()["status"], "failed")
        self.assert_request_status(503, runtime.submit, "retry")
        self.assertEqual([source for source, _ in probe["calls"]], [server.WARMUP, "internal-error"])


class HttpTests(RuntimeFixture):
    def make_server(self, **runtime_options):
        runtime, probe = self.make_runtime(**runtime_options)
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        httpd.daemon_threads = True
        httpd.runtime = runtime
        thread = threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()

        def cleanup():
            probe["release"].set()
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=1)

        self.addCleanup(cleanup)
        return httpd, runtime, probe

    def request(self, httpd, body=None, *, method="POST", path="/api/translate", headers=None, content_type="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=True).encode()
        actual_headers = {} if content_type is None else {"Content-Type": content_type}
        actual_headers.update(headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=2)
        try:
            connection.request(method, path, body=body, headers=actual_headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_health_host_and_origin_allow_only_local_entry(self):
        httpd, _, probe = self.make_server()
        port = httpd.server_port
        for headers, status in (({}, 200), ({"Host": f"localhost:{port}", "Origin": f"http://localhost:{port}"}, 200),
                ({"Origin": f"http://127.0.0.1:{port}"}, 200), ({"Host": "evil.example"}, 403),
                ({"Host": "127.0.0.1"}, 403), ({"Origin": "https://evil.example"}, 403),
                ({"Origin": "null"}, 403), ({"Origin": f"https://localhost:{port}"}, 403),
                ({"Origin": f"http://127.0.0.1:{port + 1}"}, 403)):
            with self.subTest(headers=headers):
                actual, response_headers, raw = self.request(httpd, method="GET", path="/api/health", headers=headers)
                self.assertEqual(actual, status)
                self.assertEqual(response_headers["Cache-Control"], "no-store")
                if status == 200:
                    self.assertEqual(json.loads(raw)["service"], server.SERVICE)
        self.assertEqual([source for source, _ in probe["calls"]], [server.WARMUP])

    def test_post_host_origin_and_json_contract_rejections_do_not_reach_engine(self):
        httpd, _, probe = self.make_server()
        cases = [({"text": "hello"}, {"headers": {"Host": "evil.example"}}, 403),
                 ({"text": "hello"}, {"headers": {"Origin": "https://evil.example"}}, 403),
                 ({"text": "hello"}, {"path": "/api/other"}, 404),
                 ({"text": "hello"}, {"content_type": "text/plain"}, 415),
                 ({"text": "hello"}, {"content_type": None}, 415),
                 (b"{", {}, 400), (b"\xff", {}, 400), ([], {}, 400),
                 ({"text": " "}, {}, 400), ({"text": "hello", "temperature": 0.5}, {}, 400),
                 ({"text": "hello", "stream": 1}, {}, 400),
                 ({"text": "x" * (server.MAX_SOURCE + 1)}, {}, 413),
                 (b"{}", {"headers": {"Content-Length": str(server.MAX_BODY + 1)}}, 413),
                 (b"{}", {"headers": {"Content-Length": "-1"}}, 413),
                 (b"{}", {"headers": {"Content-Length": "not-a-number"}}, 400),
                 (b"{}", {"headers": {"Transfer-Encoding": "chunked"}}, 400),
                 (None, {}, 413)]
        for body, options, expected in cases:
            with self.subTest(options=options, expected=expected):
                status, _, raw = self.request(httpd, body, **options)
                self.assertEqual(status, expected)
                self.assertFalse(json.loads(raw)["complete"])
        self.assertEqual([source for source, _ in probe["calls"]], [server.WARMUP])

    def test_nonstream_success_and_request_error_recovery(self):
        httpd, runtime, _ = self.make_server()
        status, headers, raw = self.request(httpd, {"text": "first"})
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        self.assertEqual(json.loads(raw)["text"], "中文译文。")
        self.wait_for(lambda: not runtime.health()["busy"])
        status, _, raw = self.request(httpd, {"text": "request-error"})
        self.assertEqual(status, 422)
        self.assertFalse(json.loads(raw)["complete"])
        self.wait_for(lambda: not runtime.health()["busy"])
        self.assertEqual(self.request(httpd, {"text": "retry"})[0], 200)

    def test_stream_done_follows_all_deltas(self):
        httpd, _, _ = self.make_server()
        status, headers, raw = self.request(httpd, {"text": "source", "stream": True})
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("application/x-ndjson"))
        events = [json.loads(line) for line in raw.splitlines()]
        self.assertEqual([event["type"] for event in events], ["delta", "delta", "done"])
        self.assertEqual("".join(event["text"] for event in events[:-1]), events[-1]["text"])
        self.assertFalse(events[-1]["releaseEligible"])

    def test_stream_request_error_is_terminal_without_done(self):
        httpd, runtime, _ = self.make_server()
        status, _, raw = self.request(httpd, {"text": "request-error", "stream": True})
        self.assertEqual(status, 200)
        events = [json.loads(line) for line in raw.splitlines()]
        self.assertEqual([event["type"] for event in events], ["delta", "error"])
        self.assertEqual(events[-1]["status"], 422)
        self.assertFalse(events[-1]["complete"])
        self.wait_for(lambda: not runtime.health()["busy"])
        self.assertEqual(runtime.health()["status"], "ready")

    def test_stream_internal_error_fails_closed_for_future_http_requests(self):
        httpd, runtime, _ = self.make_server()
        status, _, raw = self.request(httpd, {"text": "internal-error", "stream": True})
        self.assertEqual(status, 200)
        events = [json.loads(line) for line in raw.splitlines()]
        self.assertEqual([event["type"] for event in events], ["error"])
        self.assertEqual(events[0]["status"], 503)
        self.assertFalse(events[0]["complete"])
        self.assertEqual(runtime.health()["status"], "failed")
        self.assertEqual(self.request(httpd, {"text": "retry"})[0], 503)

    def test_http_busy_is_429_while_first_request_runs_on_single_worker(self):
        httpd, runtime, probe = self.make_server()
        result, errors = [], []

        def first_request():
            try:
                result.append(self.request(httpd, {"text": "blocked"}))
            except Exception as error:
                errors.append(error)

        first = threading.Thread(target=first_request)
        first.start()
        self.assertTrue(probe["entered"].wait(1))
        self.assertEqual(self.request(httpd, {"text": "second"})[0], 429)
        probe["release"].set()
        first.join(timeout=2)
        self.assertFalse(first.is_alive())
        self.assertFalse(errors)
        self.assertEqual(result[0][0], 200)
        self.assertEqual({thread_id for _, thread_id in probe["calls"]}, {runtime.worker.ident})
        self.assertNotIn("second", [source for source, _ in probe["calls"]])

    def test_http_loading_and_initialization_failure_return_503(self):
        httpd, _, probe = self.make_server(wait_status=None, holdWarmup=True)
        self.assertTrue(probe["warming"].wait(1))
        self.assertEqual(self.request(httpd, {"text": "hello"})[0], 503)
        probe["release"].set()
        failed, _, _ = self.make_server(wait_status="failed", initializationFailure=True)
        self.assertEqual(self.request(failed, {"text": "hello"})[0], 503)


class LauncherIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state_dir = self.root / "original-state"
        self.state_dir.mkdir()
        self.args = Namespace(state_dir=self.state_dir, port=18771, model=self.root / "fake-model", open=False)
        self.state = {"pid": 123456, "instanceId": "original-instance", "port": self.args.port,
                      "model": str(self.args.model), "script": str(Path(server.__file__).resolve())}
        self.state_path = self.state_dir / "service.json"
        self.state_path.write_text(json.dumps(self.state))
        self.original_state_bytes = self.state_path.read_bytes()
        self.health = {"service": server.SERVICE, "packageSha256": server.MANIFEST_SHA,
                       "instanceId": self.state["instanceId"], "pid": self.state["pid"], "status": "ready"}

    def test_start_same_state_and_ready_instance_is_idempotent_without_spawn(self):
        with patch.object(server, "fetch_health", return_value=self.health) as health, \
                patch.object(server.subprocess, "Popen", side_effect=AssertionError("must not spawn")) as spawn, \
                patch.object(server.os, "kill", side_effect=AssertionError("must not kill")) as kill, \
                patch.object(server.webbrowser, "open") as browser:
            server.start(self.args)
            server.start(self.args)
        spawn.assert_not_called()
        kill.assert_not_called()
        browser.assert_not_called()
        self.assertTrue(health.call_args_list)
        self.assertTrue(all(call.args == (self.args.port,) for call in health.call_args_list))
        self.assertEqual(self.state_path.read_bytes(), self.original_state_bytes)
        self.assertFalse((self.state_dir / "server.log").exists())

    def test_start_same_state_with_changed_port_refuses_without_spawn(self):
        changed = Namespace(**{**vars(self.args), "port": self.args.port + 1})
        with patch.object(server, "fetch_health", return_value=self.health) as health, \
                patch.object(server.subprocess, "Popen", side_effect=AssertionError("must not spawn")) as spawn, \
                patch.object(server.os, "kill", side_effect=AssertionError("must not kill")) as kill:
            with self.assertRaises(RuntimeError):
                server.start(changed)
        health.assert_called_once_with(self.state["port"])
        spawn.assert_not_called()
        kill.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), self.original_state_bytes)
        self.assertFalse((self.state_dir / "server.log").exists())

    def test_start_different_state_cannot_adopt_existing_service_on_same_port(self):
        other_dir = self.root / "different-state"
        other_dir.mkdir()
        other = Namespace(**{**vars(self.args), "state_dir": other_dir})
        with patch.object(server, "fetch_health", return_value=self.health), \
                patch.object(server.subprocess, "Popen", side_effect=AssertionError("must not spawn")) as spawn, \
                patch.object(server.os, "kill", side_effect=AssertionError("must not kill")) as kill:
            with self.assertRaises(RuntimeError):
                server.start(other)
        spawn.assert_not_called()
        kill.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), self.original_state_bytes)
        self.assertEqual(list(other_dir.iterdir()), [])

    def test_stop_instance_or_pid_mismatch_preserves_state_and_never_kills(self):
        for mismatch in ({"instanceId": "replacement-instance"}, {"pid": self.state["pid"] + 1}):
            with self.subTest(mismatch=mismatch), \
                    patch.object(server, "fetch_health", return_value={**self.health, **mismatch}) as health, \
                    patch.object(server.os, "kill", side_effect=AssertionError("must not kill")) as kill, \
                    patch.object(server.subprocess, "Popen", side_effect=AssertionError("must not spawn")) as spawn:
                with self.assertRaises(RuntimeError):
                    server.stop(self.args)
            health.assert_called_once_with(self.state["port"])
            kill.assert_not_called()
            spawn.assert_not_called()
            self.assertEqual(self.state_path.read_bytes(), self.original_state_bytes)


if __name__ == "__main__":
    unittest.main()
