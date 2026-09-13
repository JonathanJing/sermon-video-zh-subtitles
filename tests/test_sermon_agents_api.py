"""Offline protocol, crash recovery and resource-boundary tests."""

import fcntl
import http.client
import io
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.sermon_agents_api import AgentsAPIClient, AgentsAPIError, _NoRedirect, run_agent_session


PAYLOAD = {"agent": {"model": "gpt-6-astra", "instructions": "Review evidence."},
           "environment": {"type": "none"}, "input": "review"}
ACTION = {"type": "function_call", "turn_id": "turn_1", "call_id": "call_1", "name": "lookup", "arguments": {"id": "one"}}


class FakeClient:
    def __init__(self, sessions=None, turns=None):
        self.sessions = sessions or [{"status": "idle", "required_actions": []}]
        self.turn_pages = turns or [[{"id": "turn_1", "subagent_id": None, "status": "completed"}]]
        self.index = -1
        self.created = 0
        self.cancelled = 0
        self.submitted = []
        self.fail_submit = False

    def create_session(self, payload):
        self.created += 1
        return {"id": "sess_1"}

    def retrieve_session(self, session_id):
        self.index += 1
        return self.sessions[min(self.index, len(self.sessions) - 1)]

    def list_turns(self, session_id):
        return self.turn_pages[min(self.index, len(self.turn_pages) - 1)]

    def list_items(self, session_id):
        return [{"id": "item_1", "type": "message"}]

    def submit_tool_result(self, session_id, action, output=None, *, error=None):
        self.submitted.append((session_id, action, output, error))
        if self.fail_submit:
            raise AgentsAPIError("transport_error")
        return {}

    def cancel(self, session_id):
        self.cancelled += 1
        return {}


RUNNING = [{"id": "turn_1", "subagent_id": None, "status": "running"}]
COMPLETED = [{"id": "turn_1", "subagent_id": None, "status": "completed"}]


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = AgentsAPIClient("test-secret-do-not-print")

    def test_request_origin_headers_and_tool_protocol(self):
        response = io.BytesIO(b'{"id":"sess_1"}')
        self.client._opener = Mock()
        self.client._opener.open.return_value = response
        self.client.create_session(PAYLOAD)
        req = self.client._opener.open.call_args.args[0]
        self.assertEqual(req.full_url, "https://api.openai.com/v1/agents/sessions")
        self.assertEqual(req.get_header("Openai-beta"), "agents=v1")
        self.assertEqual(req.get_header("Authorization"), "Bearer test-secret-do-not-print")
        self.assertEqual(json.loads(req.data), PAYLOAD)
        with patch.object(self.client, "_request", return_value={}) as request:
            self.client.submit_tool_result("sess_1", ACTION, {"answer": 42})
            event = request.call_args.args[2]["events"][0]
            self.assertEqual(event, {"type": "agent.session.input.tool_result", "turn_id": "turn_1",
                                    "call_id": "call_1", "success": True, "output": '{"answer": 42}'})
            self.client.submit_tool_result("sess_1", ACTION, error="lookup_failed")
            self.assertFalse(request.call_args.args[2]["events"][0]["success"])
            self.client.cancel("sess_1")
            self.assertEqual(request.call_args.args[2], {"events": [{"type": "agent.session.input.cancel"}]})

    def test_no_environment_requires_initial_input_before_request(self):
        with patch.object(self.client, "_request") as request:
            with self.assertRaisesRegex(AgentsAPIError, "initial_input_required"):
                self.client.create_session({"environment": {"type": "none"}})
            request.assert_not_called()

    def test_wire_input_string_is_accepted_and_initial_input_is_not_a_field(self):
        with patch.object(self.client, "_request", return_value={"id": "sess_1"}) as request:
            self.assertEqual(self.client.create_session(PAYLOAD), {"id": "sess_1"})
            self.assertEqual(request.call_args.args[2]["input"], "review")
            request.reset_mock()
            with self.assertRaisesRegex(AgentsAPIError, "initial_input_required"):
                self.client.create_session({"environment": {"type": "none"}, "initial_input": "review"})
            request.assert_not_called()

    def test_event_submission_accepts_empty_success_acknowledgement(self):
        for status in (200, 202, 204):
            with self.subTest(status=status):
                response = io.BytesIO(b"")
                response.status = status
                self.client._opener = Mock()
                self.client._opener.open.return_value = response
                self.assertEqual(self.client.submit_tool_result("sess_1", ACTION, {"ok": True}), {})
        response = io.BytesIO(b"")
        response.status = 204
        self.client._opener.open.return_value = response
        self.assertEqual(self.client.cancel("sess_1"), {})

    def test_empty_session_body_remains_invalid(self):
        self.client._opener = Mock()
        self.client._opener.open.return_value = io.BytesIO(b"")
        with self.assertRaisesRegex(AgentsAPIError, "invalid_response"):
            self.client.create_session(PAYLOAD)

    def test_both_collections_walk_all_pages_in_order(self):
        for method in (self.client.list_turns, self.client.list_items):
            with self.subTest(method=method.__name__):
                pages = [{"data": [{"id": "a"}], "has_more": True, "last_id": "a"},
                         {"data": [{"id": "b"}], "has_more": False, "last_id": "b"}]
                with patch.object(self.client, "_request", side_effect=pages) as request:
                    self.assertEqual(method("sess_1"), [{"id": "a"}, {"id": "b"}])
                    self.assertIn("order=asc&limit=100", request.call_args_list[0].args[1])
                    self.assertIn("after=a", request.call_args_list[1].args[1])

    def test_repeated_cursor_fails_instead_of_looping(self):
        page = {"data": [{"id": "a"}], "has_more": True, "last_id": "a"}
        with patch.object(self.client, "_request", return_value=page) as request:
            with self.assertRaisesRegex(AgentsAPIError, "invalid_pagination_cursor"):
                self.client.list_items("sess_1")
            self.assertEqual(request.call_count, 2)

    def test_http_and_transport_diagnostics_do_not_include_secrets(self):
        errors = [urllib.error.HTTPError("https://secret.invalid", 401, "test-secret-do-not-print",
                                        {"Authorization": "secret"}, io.BytesIO(b"private body")),
                  urllib.error.URLError("test-secret-do-not-print"),
                  http.client.BadStatusLine("test-secret-do-not-print")]
        for error in errors:
            self.client._opener = Mock()
            self.client._opener.open.side_effect = error
            with self.assertRaises(AgentsAPIError) as raised:
                self.client.retrieve_session("sess_1")
            diagnostic = str(raised.exception)
            for forbidden in ("test-secret", "private body", "secret.invalid", "Authorization"):
                self.assertNotIn(forbidden, diagnostic)
            self.assertIsNone(raised.exception.__cause__)

    def test_redirect_handler_never_forwards_authorization(self):
        handler = _NoRedirect()
        req = urllib.request.Request("https://api.openai.com/v1/agents/sessions", headers={"Authorization": "secret"})
        self.assertIsNone(handler.redirect_request(req, None, 302, "redirect", {}, "https://evil.invalid"))
        installed = [h for h in self.client._opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
        self.assertEqual(len(installed), 1)
        self.assertIsInstance(installed[0], _NoRedirect)
        self.client._opener = Mock()
        self.client._opener.open.side_effect = urllib.error.HTTPError(req.full_url, 302, "secret", {}, io.BytesIO(b"secret"))
        with self.assertRaises(AgentsAPIError) as raised:
            self.client.retrieve_session("sess_1")
        self.assertEqual(raised.exception.status, 302)
        self.assertEqual(self.client._opener.open.call_count, 1)

    def test_invalid_identifier_cannot_change_request_origin(self):
        with patch.object(self.client, "_request") as request:
            with self.assertRaisesRegex(AgentsAPIError, "invalid_identifier"):
                self.client.retrieve_session("../private?key=secret")
            request.assert_not_called()

    def test_environment_proxies_are_disabled(self):
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://private-proxy.invalid:8080"}):
            client = AgentsAPIClient("test-secret")
        self.assertFalse(any(isinstance(handler, urllib.request.ProxyHandler)
                             for handler in client._opener.handlers))

    def test_request_timeout_is_capped_by_remaining_deadline(self):
        self.client.set_deadline(103)
        self.client._opener = Mock()
        self.client._opener.open.return_value = io.BytesIO(b'{"id":"sess_1"}')
        with patch("scripts.sermon_agents_api.time.time", return_value=100):
            self.client.retrieve_session("sess_1")
        self.assertEqual(self.client._opener.open.call_args.kwargs["timeout"], 3)
        self.client._opener.open.reset_mock()
        with patch("scripts.sermon_agents_api.time.time", return_value=104):
            with self.assertRaisesRegex(AgentsAPIError, "deadline_exceeded"):
                self.client.retrieve_session("sess_1")
        self.client._opener.open.assert_not_called()

    def test_pagination_stops_at_deadline_between_pages(self):
        self.client.set_deadline(101)
        page = {"data": [{"id": "a"}], "has_more": True, "last_id": "a"}
        with patch("scripts.sermon_agents_api.time.time", side_effect=[100, 102]):
            with patch.object(self.client, "_request", return_value=page) as request:
                with self.assertRaisesRegex(AgentsAPIError, "deadline_exceeded"):
                    self.client.list_items("sess_1")
        self.assertEqual(request.call_count, 1)

    def test_pagination_has_a_small_finite_page_cap(self):
        counter = iter(range(200))
        def page(*args):
            cursor = str(next(counter))
            return {"data": [{"id": cursor}], "has_more": True, "last_id": cursor}
        with patch.object(self.client, "_request", side_effect=page) as request:
            with self.assertRaisesRegex(AgentsAPIError, "pagination_limit_exceeded"):
                self.client.list_turns("sess_1")
        self.assertEqual(request.call_count, 100)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name) / "run"
        self.handler = Mock(return_value={"found": True})

    def run_session(self, client, **kwargs):
        return run_agent_session(client, self.run_dir, PAYLOAD, self.handler, poll_seconds=0, **kwargs)

    def test_completed_is_saved_and_usage_unknown_is_null(self):
        client = FakeClient()
        result = self.run_session(client)
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(result["usage"])
        self.assertEqual(json.loads((self.run_dir / "state.json").read_text())["session_id"], "sess_1")
        self.assertEqual(self.run_session(client, resume=True), result)
        self.assertEqual(client.created, 1)
        with self.assertRaisesRegex(AgentsAPIError, "run_directory_not_empty"):
            self.run_session(client)

    def test_failed_and_cancelled_root_are_not_success(self):
        for status in ("failed", "cancelled"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                client = FakeClient(turns=[[{"id": "turn_1", "subagent_id": None, "status": status}]])
                result = run_agent_session(client, Path(tmp), PAYLOAD, self.handler)
                self.assertEqual(result["status"], status)

    def test_idle_and_subagent_completed_do_not_establish_root_success(self):
        client = FakeClient(turns=[[{"id": "child", "subagent_id": "sub_1", "status": "completed"}]])
        with patch("scripts.sermon_agents_api.time.time", side_effect=[100, 102, 102]):
            result = self.run_session(client, max_seconds=1)
        self.assertEqual(result["status"], "timed_out")
        self.assertEqual(client.cancelled, 1)
        self.assertTrue(result["cancel_requested"])

    def test_duplicate_required_action_replays_saved_output_once(self):
        pending = {"required_actions": [ACTION]}
        client = FakeClient(sessions=[pending, pending, {}], turns=[RUNNING, RUNNING, COMPLETED])
        result = self.run_session(client)
        self.assertEqual(result["status"], "completed")
        self.handler.assert_called_once_with("lookup", {"id": "one"})
        self.assertEqual(len(client.submitted), 2)
        self.assertEqual(result["tool_calls"], 1)

    def test_lost_tool_submission_response_resume_does_not_rerun_handler(self):
        client = FakeClient(sessions=[{"required_actions": [ACTION]}], turns=[RUNNING])
        client.fail_submit = True
        with self.assertRaisesRegex(AgentsAPIError, "transport_error"):
            self.run_session(client)
        self.handler.assert_called_once()
        resumed = FakeClient(sessions=[{"required_actions": [ACTION]}, {}], turns=[RUNNING, COMPLETED])
        result = self.run_session(resumed, resume=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(resumed.created, 0)
        self.handler.assert_called_once()
        self.assertEqual(resumed.submitted[0][2], {"found": True})

    def test_crash_during_handler_never_reexecutes_uncertain_side_effect(self):
        client = FakeClient(sessions=[{"required_actions": [ACTION]}], turns=[RUNNING])
        self.handler.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_session(client)
        self.handler.side_effect = None
        result = self.run_session(client, resume=True)
        self.assertEqual(result["status"], "tool_outcome_unknown")
        self.handler.assert_called_once()
        self.assertEqual(client.cancelled, 1)

    def test_creation_unknown_is_persisted_and_cannot_create_on_resume(self):
        client = FakeClient()
        client.create_session = Mock(side_effect=RuntimeError("secret in transport"))
        with self.assertRaisesRegex(AgentsAPIError, "creation_outcome_unknown") as raised:
            self.run_session(client)
        self.assertNotIn("secret", str(raised.exception))
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["status"], "creation_outcome_unknown")
        self.assertIsNone(state["session_id"])
        with self.assertRaisesRegex(AgentsAPIError, "creation_outcome_unknown"):
            self.run_session(client, resume=True)
        client.create_session.assert_called_once()

    def test_resume_payload_hash_is_bound_even_after_completion(self):
        client = FakeClient()
        self.run_session(client)
        with self.assertRaisesRegex(AgentsAPIError, "resume_payload_mismatch"):
            run_agent_session(client, self.run_dir, {**PAYLOAD, "changed": True}, self.handler, resume=True)

    def test_pending_action_over_budget_cancels_without_executing(self):
        client = FakeClient(sessions=[{"required_actions": [ACTION]}], turns=[RUNNING])
        result = self.run_session(client, max_tool_calls=0)
        self.assertEqual(result["status"], "tool_budget_exceeded")
        self.assertEqual(client.cancelled, 1)
        self.handler.assert_not_called()

    def test_reused_call_id_with_changed_arguments_is_rejected(self):
        changed = {**ACTION, "arguments": {"id": "different"}}
        client = FakeClient(sessions=[{"required_actions": [ACTION]}, {"required_actions": [changed]}],
                            turns=[RUNNING])
        result = self.run_session(client)
        self.assertEqual(result["status"], "tool_call_identity_conflict")
        self.handler.assert_called_once()
        self.assertEqual(client.cancelled, 1)

    def test_reported_usage_is_retained_without_manufacturing_totals(self):
        reported = {"input_tokens": 12, "output_tokens": 5}
        client = FakeClient(turns=[[{**COMPLETED[0], "usage": reported}]])
        result = self.run_session(client)
        self.assertEqual(result["usage"], {"turns": [{"turn_id": "turn_1", "subagent_id": None, "usage": reported}]})

    def test_cancel_failure_does_not_claim_remote_cancellation(self):
        client = FakeClient(turns=[RUNNING])
        client.cancel = Mock(side_effect=RuntimeError("private secret"))
        with patch("scripts.sermon_agents_api.time.time", side_effect=[100, 102, 102]):
            result = self.run_session(client, max_seconds=1)
        self.assertEqual(result["status"], "timed_out")
        self.assertFalse(result["cancel_requested"])
        self.assertEqual(result["cancel_error_code"], "cancel_request_failed")
        self.assertNotIn("private secret", json.dumps(result))

    def test_handler_error_is_sanitized_for_remote_agent(self):
        self.handler.side_effect = ValueError("OPENAI_API_KEY=private")
        client = FakeClient(sessions=[{"required_actions": [ACTION]}, {}], turns=[RUNNING, COMPLETED])
        self.run_session(client)
        self.assertEqual(client.submitted[0][3], "tool_execution_failed")
        self.assertNotIn("private", next((self.run_dir / "tool-results").glob("*.json")).read_text())

    def test_lock_prevents_concurrent_same_directory_run(self):
        self.run_dir.mkdir()
        with (self.run_dir / ".run.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(AgentsAPIError, "run_already_locked"):
                self.run_session(FakeClient())

    def test_poll_failure_saves_recoverable_state_and_requests_cancel(self):
        client = FakeClient(turns=[RUNNING])
        client.retrieve_session = Mock(side_effect=AgentsAPIError("transport_error"))
        with self.assertRaisesRegex(AgentsAPIError, "transport_error"):
            self.run_session(client)
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["status"], "interrupted")
        self.assertEqual(state["session_id"], "sess_1")
        self.assertTrue(state["cancel_attempted"])
        self.assertTrue(state["cancel_requested"])
        self.assertFalse(state["cancellation_observed"])
        self.assertFalse((self.run_dir / "result.json").exists())
        resumed = FakeClient()
        self.assertEqual(self.run_session(resumed, resume=True)["status"], "completed")
        self.assertEqual(resumed.created, 0)

    def test_cancel_ack_is_distinct_from_observed_root_cancellation(self):
        for remote_status in ("running", "cancelled"):
            with self.subTest(remote_status=remote_status), tempfile.TemporaryDirectory() as tmp:
                client = FakeClient(turns=[[{**RUNNING[0], "status": remote_status}]])
                with patch("scripts.sermon_agents_api.time.time", side_effect=[100, 102, 102]):
                    result = run_agent_session(client, Path(tmp), PAYLOAD, self.handler, max_seconds=1)
                self.assertTrue(result["cancel_requested"])
                self.assertEqual(result["cancellation_observed"], remote_status == "cancelled")
                self.assertEqual(result["status"], "timed_out")

    def test_handler_output_is_durable_before_expired_run_is_cancelled(self):
        now = [100]
        def handler(*args):
            now[0] += 3600
            return {"artifact": "completed locally"}
        self.handler.side_effect = handler
        client = FakeClient(sessions=[{"required_actions": [ACTION]}], turns=[RUNNING])
        with patch("scripts.sermon_agents_api.time.time", side_effect=lambda: now[0]):
            result = self.run_session(client, max_seconds=60)
        self.assertEqual(result["status"], "timed_out")
        self.assertEqual(client.submitted, [])
        cache = json.loads(next((self.run_dir / "tool-results").glob("*.json")).read_text())
        self.assertEqual(cache["status"], "completed")
        self.assertEqual(cache["output"], {"artifact": "completed locally"})

    def test_six_hour_budget_accepts_a_long_production_handler(self):
        now = [100]
        def handler(*args):
            now[0] += 3600
            return {"artifact": "complete"}
        self.handler.side_effect = handler
        client = FakeClient(sessions=[{"required_actions": [ACTION]}, {}], turns=[RUNNING, COMPLETED])
        client.set_deadline = Mock()
        with patch("scripts.sermon_agents_api.time.time", side_effect=lambda: now[0]):
            result = self.run_session(client, max_seconds=6 * 3600)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(client.submitted), 1)
        self.assertEqual(client.set_deadline.call_args.args, (None,))


if __name__ == "__main__":
    unittest.main()
