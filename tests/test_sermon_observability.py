"""Real loopback HTTP delivery, retry isolation and managed-process ownership."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts import sermon_observability as observer
from scripts.sermon_accounting import accounting_session, stage


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.accounting = self.root / "accounting"
        with patch("scripts.sermon_accounting.execution_identity", return_value={"gitCommit": None}):
            with accounting_session(self.accounting, "weekly_dubbing"):
                with stage("render", billing="local", cache_hit=True):
                    pass
        self.original = (self.accounting / "events.jsonl").read_bytes()
        self.requests = []
        self.response = {}
        self.redirect = None
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                owner.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(307 if owner.redirect else 200)
                if owner.redirect:
                    self.send_header("Location", owner.redirect)
                self.end_headers()
                self.wfile.write(json.dumps(owner.response).encode())
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/v1/traces"

    def test_actual_http_receipt_preserves_ledger_and_disables_environment_proxy(self):
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "http_proxy": "http://127.0.0.1:1", "NO_PROXY": "", "no_proxy": ""}):
            result = observer.deliver(self.accounting, endpoint=self.endpoint, site="test")
        self.assertEqual(result["status"], "collector_accepted")
        self.assertGreater(result["spans"], 0)
        self.assertFalse(result["approvalGranted"])
        self.assertEqual(len(self.requests), 1)
        self.assertEqual((self.accounting / "events.jsonl").read_bytes(), self.original)
        self.assertEqual(json.loads((self.accounting / "telemetry/delivery.json").read_text()), result)

    def test_partial_and_malformed_acceptance_remain_retryable(self):
        for response in ([], None, {"partialSuccess": None}, {"partialSuccess": {"rejectedSpans": "1"}}):
            with self.subTest(response=response):
                self.response = response
                result = observer.deliver(self.accounting, endpoint=self.endpoint)
                self.assertEqual(result["status"], "delivery_failed")
                self.assertTrue((self.accounting / "telemetry/payload.json").exists())
        self.response = {}
        self.assertEqual(observer.deliver(self.accounting, endpoint=self.endpoint)["status"], "collector_accepted")

    def test_redirect_cannot_send_payload_to_a_second_destination(self):
        self.redirect = self.endpoint
        result = observer.deliver(self.accounting, endpoint=self.endpoint)
        self.assertEqual(result["status"], "delivery_failed")
        self.assertEqual(len(self.requests), 1)

    def test_unapproved_endpoint_fails_before_writing_telemetry(self):
        for endpoint in ("http://example.com:4318/v1/traces", "http://user:pass@127.0.0.1:4318/v1/traces",
                         "https://127.0.0.1:4318/v1/traces", self.endpoint + "?token=private"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                observer.deliver(self.accounting, endpoint=endpoint)
        self.assertFalse((self.accounting / "telemetry").exists())

    def test_one_bad_ledger_does_not_stop_other_deliveries_or_mark_failure_sent(self):
        bad = self.root / "bad"
        bad.mkdir()
        (bad / "events.jsonl").write_text("broken fixture")
        original = observer.deliver
        def deliver(path, **kwargs):
            if path == bad:
                raise PermissionError("fixture-private-message")
            return original(path, **kwargs)
        previous = {}
        with patch.object(observer, "deliver", side_effect=deliver):
            results = observer.watch_cycle([bad, self.accounting], previous, endpoint=self.endpoint, site="test")
        self.assertEqual([r["status"] for r in results], ["source_failed", "collector_accepted"])
        self.assertNotIn(str(bad), previous)
        self.assertIn(str(self.accounting), previous)
        self.assertNotIn("fixture-private-message", json.dumps(results))

    def test_stale_pid_cannot_signal_another_process(self):
        runtime = self.root / "runtime"
        runtime.mkdir()
        (runtime / "service.json").write_text(json.dumps({"pid": 12345, "identity": "old-start old-command"}))
        with patch.object(observer, "process_identity", return_value="new-start another-command"), patch.object(observer.os, "killpg") as kill:
            self.assertEqual(observer.stop(runtime)["status"], "stopped")
        kill.assert_not_called()

    def test_config_uses_only_loopback_and_persistent_storage(self):
        config = observer.configuration(self.root)
        self.assertFalse(config["extensions"]["jaeger_storage"]["backends"]["sermon"]["badger"]["ephemeral"])
        text = json.dumps(config)
        self.assertNotIn("0.0.0.0", text)
        self.assertNotIn("localhost", text)
        self.assertIn("127.0.0.1:14318", text)


if __name__ == "__main__":
    unittest.main()
