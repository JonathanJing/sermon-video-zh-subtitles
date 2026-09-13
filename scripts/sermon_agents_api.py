"""Bounded Agents API sessions with local, crash-aware function result replay.

Only the remote root turn establishes completion. Function handlers return JSON
objects and own their execution timeout. An interrupted handler is never retried: its
side effects may already have happened, so that session requires investigation.
No API key, request headers, or remote error body is included in diagnostics.
"""

from __future__ import annotations

import fcntl
import hashlib
import http.client
import json
import math
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping


class AgentsAPIError(RuntimeError):
    def __init__(self, code: str, status: int | None = None, error_type: str | None = None):
        self.code = code
        self.status = status
        self.error_type = error_type
        super().__init__(json.dumps({"code": code, "status": status, "type": error_type}))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
        raise AgentsAPIError("invalid_identifier")
    return value


def _json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError):
        raise AgentsAPIError("invalid_json_value") from None


class AgentsAPIClient:
    """Fixed origin, no redirects, environment proxies or automatic retries.

    ``deadline_at`` bounds requests and pagination; use one client per runner.
    """

    max_pages = 100

    def __init__(self, api_key: str | None = None, timeout: float = 30.0):
        key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
        if not isinstance(key, str) or not key.strip() or "\n" in key or "\r" in key:
            raise AgentsAPIError("missing_or_invalid_api_key")
        if not math.isfinite(timeout) or timeout <= 0:
            raise AgentsAPIError("invalid_timeout")
        self._api_key = key
        self.timeout = timeout
        self.deadline_at: float | None = None
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def set_deadline(self, deadline_at: float | None) -> None:
        if deadline_at is not None and not math.isfinite(deadline_at):
            raise AgentsAPIError("invalid_deadline")
        self.deadline_at = deadline_at

    def _remaining_timeout(self) -> float:
        if self.deadline_at is None:
            return self.timeout
        remaining = self.deadline_at - time.time()
        if remaining <= 0:
            raise AgentsAPIError("deadline_exceeded")
        return min(self.timeout, remaining)

    def _request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        timeout = self._remaining_timeout()
        request = urllib.request.Request(
            "https://api.openai.com/v1" + path,
            data=_json_bytes(payload) if payload is not None else None,
            method=method,
            headers={"Authorization": "Bearer " + self._api_key,
                     "OpenAI-Beta": "agents=v1", "Content-Type": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                status = getattr(response, "status", 200)
                raw = response.read(16 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            raise AgentsAPIError("http_error", status=status, error_type="http") from None
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
            raise AgentsAPIError("transport_error", error_type="transport") from None
        self._remaining_timeout()
        if len(raw) > 16 * 1024 * 1024:
            raise AgentsAPIError("response_too_large")
        # Input-event submission can acknowledge with an empty 2xx response.
        # Creation/retrieval/listing still require their JSON resource body.
        if method == "POST" and path.endswith("/events") and 200 <= status < 300 and not raw.strip():
            return {}
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise AgentsAPIError("invalid_response") from None
        if not isinstance(value, dict):
            raise AgentsAPIError("invalid_response")
        return value

    def create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise AgentsAPIError("invalid_payload")
        environment = payload.get("environment")
        # The wire field is `input`; "initial input" in the guide is prose.
        if isinstance(environment, dict) and environment.get("type") == "none" and not payload.get("input"):
            raise AgentsAPIError("initial_input_required")
        return self._request("POST", "/agents/sessions", payload)

    def retrieve_session(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/agents/sessions/{_identifier(session_id)}")

    def _list(self, session_id: str, resource: str) -> list[dict[str, Any]]:
        path = f"/agents/sessions/{_identifier(session_id)}/{resource}"
        result: list[dict[str, Any]] = []
        cursors: set[str] = set()
        after: str | None = None
        for _page in range(self.max_pages):
            self._remaining_timeout()
            query: dict[str, Any] = {"order": "asc", "limit": 100}
            if after is not None:
                query["after"] = after
            page = self._request("GET", path + "?" + urllib.parse.urlencode(query))
            data = page.get("data")
            if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                raise AgentsAPIError("invalid_page")
            result.extend(data)
            if page.get("has_more") is False:
                return result
            if page.get("has_more") is not True:
                raise AgentsAPIError("invalid_page")
            cursor = page.get("last_id")
            if not data or not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise AgentsAPIError("invalid_pagination_cursor")
            cursors.add(cursor)
            after = cursor
        raise AgentsAPIError("pagination_limit_exceeded")

    def list_turns(self, session_id: str) -> list[dict[str, Any]]:
        return self._list(session_id, "turns")

    def list_items(self, session_id: str) -> list[dict[str, Any]]:
        return self._list(session_id, "items")

    def submit_tool_result(self, session_id: str, action: Mapping[str, Any], output: Any = None,
                           *, error: str | None = None) -> dict[str, Any]:
        event: dict[str, Any] = {"type": "agent.session.input.tool_result",
            "turn_id": _identifier(action.get("turn_id")), "call_id": _identifier(action.get("call_id")),
            "success": error is None}
        if error is None:
            event["output"] = _json_bytes(output).decode("utf-8")
        else:
            if output is not None:
                raise AgentsAPIError("ambiguous_tool_result")
            event["error"] = error
        return self._request("POST", f"/agents/sessions/{_identifier(session_id)}/events", {"events": [event]})

    def cancel(self, session_id: str) -> dict[str, Any]:
        return self._request("POST", f"/agents/sessions/{_identifier(session_id)}/events",
                             {"events": [{"type": "agent.session.input.cancel"}]})


def _write_json(path: Path, value: Any) -> None:
    data = _json_bytes(value) + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink():
            raise ValueError()
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError):
        raise AgentsAPIError("invalid_saved_state") from None


def run_agent_session(client: AgentsAPIClient, run_dir: Path, payload: dict[str, Any],
                      handler: Callable[[str, dict[str, Any]], dict[str, Any]], *,
                      max_seconds: float = 600, max_tool_calls: int = 30,
                      poll_seconds: float = 2, resume: bool = False) -> dict[str, Any]:
    """Run one initial root turn, retaining outcomes for explicit safe resume.

    Deadlines include downtime. HTTP timeouts use the remaining run budget.
    A synchronous production handler owns its timeout and is never forcibly
    stopped; its durable result is saved before checking the deadline again.
    Cancellation and final artifact collection have a separate 10-second budget.
    ``usage`` preserves reported per-turn counters without inventing totals.
    """
    if (not math.isfinite(max_seconds) or max_seconds <= 0
            or not math.isfinite(poll_seconds) or poll_seconds < 0
            or not isinstance(max_tool_calls, int) or isinstance(max_tool_calls, bool) or max_tool_calls < 0):
        raise AgentsAPIError("invalid_run_limits")
    if not isinstance(payload, dict):
        raise AgentsAPIError("invalid_payload")
    payload_hash = hashlib.sha256(_json_bytes(payload)).hexdigest()
    run_dir = Path(run_dir)
    if run_dir.is_symlink():
        raise AgentsAPIError("invalid_run_directory")
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_fd = os.open(run_dir / ".run.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AgentsAPIError("run_already_locked") from None
        return _run_locked(client, run_dir, payload, payload_hash, handler,
                           max_seconds, max_tool_calls, poll_seconds, resume)
    finally:
        if callable(getattr(client, "set_deadline", None)):
            client.set_deadline(None)
        os.close(lock_fd)


def _run_locked(client, run_dir, payload, payload_hash, handler,
                max_seconds, max_tool_calls, poll_seconds, resume):
    state_path = run_dir / "state.json"

    def set_deadline(deadline_at):
        if callable(getattr(client, "set_deadline", None)):
            client.set_deadline(deadline_at)

    if resume:
        state = _read_json(state_path)
        if state.get("payload_sha256") != payload_hash:
            raise AgentsAPIError("resume_payload_mismatch")
        if not state.get("session_id"):
            raise AgentsAPIError("creation_outcome_unknown")
        session_id = _identifier(state["session_id"])
        if (run_dir / "result.json").exists():
            result = _read_json(run_dir / "result.json")
            if result.get("session_id") != session_id:
                raise AgentsAPIError("invalid_saved_state")
            return result
    else:
        if any(path.name != ".run.lock" for path in run_dir.iterdir()):
            raise AgentsAPIError("run_directory_not_empty")
        state = {"schema_version": "agents.session-run.v1", "payload_sha256": payload_hash,
                 "session_id": None, "status": "creation_outcome_unknown",
                 "deadline_at": time.time() + max_seconds,
                 "max_tool_calls": max_tool_calls, "tool_calls": 0}
        # Persist uncertainty BEFORE the request. A crash or lost response must
        # never cause a duplicate paid session on restart.
        _write_json(state_path, state)
        set_deadline(state["deadline_at"])
        try:
            session = client.create_session(payload)
            session_id = _identifier(session.get("id"))
        except Exception as exc:
            raise AgentsAPIError("creation_outcome_unknown",
                                 status=exc.status if isinstance(exc, AgentsAPIError) else None) from None
        state.update(session_id=session_id, status="running")
        _write_json(state_path, state)

    set_deadline(state["deadline_at"])
    tools_dir = run_dir / "tool-results"
    tools_dir.mkdir(exist_ok=True, mode=0o700)
    turns: list[dict[str, Any]] = []
    session: dict[str, Any] = {}

    def save():
        _write_json(state_path, state)

    def request_cancel():
        # An event ACK is not evidence that the root turn stopped.
        state.update(cancel_attempted=True, cancel_requested=False, cancellation_observed=False)
        for key in ("cancel_error_code", "cancel_observation_error_code", "observed_root_status"):
            state.pop(key, None)
        save()
        try:
            client.cancel(session_id)
            state["cancel_requested"] = True
        except Exception:
            state["cancel_error_code"] = "cancel_request_failed"
        save()
        try:
            observed_turns = client.list_turns(session_id)
            roots = [turn for turn in observed_turns if "subagent_id" in turn and turn["subagent_id"] is None]
            root_id = state.get("root_turn_id") or (roots[0].get("id") if roots else None)
            root = next((turn for turn in roots if turn.get("id") == root_id), None)
            if root:
                state["observed_root_status"] = root.get("status")
                state["cancellation_observed"] = root.get("status") == "cancelled"
        except Exception:
            state["cancel_observation_error_code"] = "cancel_observation_unavailable"
        save()

    def finish(status, *, cancel=False):
        state["status"] = status
        set_deadline(time.time() + 10)
        if cancel:
            request_cancel()
        save()
        artifact_errors = []
        try:
            items = client.list_items(session_id)
        except Exception:
            items = []
            artifact_errors.append("items_unavailable")
        reported = [{"turn_id": turn.get("id"), "subagent_id": turn.get("subagent_id"),
                     "usage": turn["usage"]} for turn in turns if isinstance(turn.get("usage"), dict)]
        usage = session.get("usage") if isinstance(session.get("usage"), dict) else (
            {"turns": reported} if reported else None)
        result = {"session_id": session_id, "status": status, "turns": turns,
                  "items": items, "usage": usage, "tool_calls": state["tool_calls"],
                  "artifact_errors": artifact_errors}
        for key in ("cancel_attempted", "cancel_requested", "cancellation_observed", "cancel_error_code",
                    "observed_root_status", "cancel_observation_error_code"):
            if key in state:
                result[key] = state[key]
        _write_json(run_dir / "result.json", result)
        return result

    try:
        while True:
            if time.time() >= state["deadline_at"]:
                return finish("timed_out", cancel=True)
            session = client.retrieve_session(session_id)
            turns = client.list_turns(session_id)
            root_turns = [turn for turn in turns if "subagent_id" in turn and turn["subagent_id"] is None]
            if not state.get("root_turn_id") and root_turns:
                state["root_turn_id"] = _identifier(root_turns[0].get("id"))
                save()
            root = next((turn for turn in root_turns if turn.get("id") == state.get("root_turn_id")), None)
            if root and root.get("status") in {"completed", "failed", "cancelled"}:
                return finish(root["status"])
            if time.time() >= state["deadline_at"]:
                return finish("timed_out", cancel=True)
            actions = session.get("required_actions", [])
            if not isinstance(actions, list):
                return finish("invalid_required_actions", cancel=True)
            for action in actions:
                if time.time() >= state["deadline_at"]:
                    return finish("timed_out", cancel=True)
                if not isinstance(action, dict) or action.get("type") != "function_call":
                    return finish("unsupported_required_action", cancel=True)
                turn_id = _identifier(action.get("turn_id"))
                call_id = _identifier(action.get("call_id"))
                cache_key = hashlib.sha256(_json_bytes([session_id, turn_id, call_id])).hexdigest()
                cache_path = tools_dir / (cache_key + ".json")
                action_hash = hashlib.sha256(_json_bytes({key: action.get(key) for key in
                    ("type", "turn_id", "call_id", "name", "arguments")})).hexdigest()
                if cache_path.exists():
                    record = _read_json(cache_path)
                    if record.get("action_sha256") != action_hash:
                        return finish("tool_call_identity_conflict", cancel=True)
                    if record.get("status") != "completed":
                        return finish("tool_outcome_unknown", cancel=True)
                else:
                    if state["tool_calls"] >= min(max_tool_calls, state["max_tool_calls"]):
                        return finish("tool_budget_exceeded", cancel=True)
                    record = {"session_id": session_id, "turn_id": turn_id, "call_id": call_id,
                              "action_sha256": action_hash, "status": "executing"}
                    _write_json(cache_path, record)
                    state["tool_calls"] += 1
                    save()
                    try:
                        name, arguments = action.get("name"), action.get("arguments")
                        if not isinstance(name, str) or not name or not isinstance(arguments, dict):
                            raise AgentsAPIError("invalid_tool_arguments")
                        output = handler(name, arguments)
                        if not isinstance(output, dict):
                            raise AgentsAPIError("invalid_tool_output")
                        _json_bytes(output)
                        record.update(status="completed", output=output, error=None)
                    except Exception:
                        record.update(status="completed", output=None, error="tool_execution_failed")
                    _write_json(cache_path, record)
                if time.time() >= state["deadline_at"]:
                    return finish("timed_out", cancel=True)
                client.submit_tool_result(session_id, action, record["output"], error=record["error"])
            remaining = state["deadline_at"] - time.time()
            if remaining > 0 and poll_seconds:
                time.sleep(min(poll_seconds, remaining))
    except Exception as exc:
        if isinstance(exc, AgentsAPIError) and exc.code == "deadline_exceeded":
            return finish("timed_out", cancel=True)
        state["status"] = "interrupted"
        state["error_code"] = exc.code if isinstance(exc, AgentsAPIError) else "session_run_error"
        save()
        set_deadline(time.time() + 10)
        request_cancel()
        if isinstance(exc, AgentsAPIError):
            raise
        raise AgentsAPIError("session_run_error") from None
