"""Deterministic, versioned payloads; no filesystem or SDK imports."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
import re

REQUEST_SCHEMA = "sermon-temporal-request-v1"
STATE_SCHEMA = "sermon-temporal-state-v1"
OBSERVATION_SCHEMA = "sermon-temporal-observation-v1"
SIGNAL_SCHEMA = "sermon-temporal-resume-v1"
QUEUE_PREFIX = "sermon-saturday-v1-"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


OPERATOR_SCHEMA_V1 = "sermon-temporal-operator-v1"
OPERATOR_SCHEMA_V2 = "sermon-temporal-operator-v2"


def operator_harness_argv(config: dict) -> list[str]:
    """Resolve backend from immutable config bytes, never the harness default.

    Existing v1 requests omitted the backend when agents-api was the default.
    Keep that interpretation on activity retries without migrating their hash.
    """
    schema = config.get("schemaVersion")
    if schema not in (OPERATOR_SCHEMA_V1, OPERATOR_SCHEMA_V2):
        raise ValueError("Unsupported Temporal operator configuration schema")
    argv = config.get("harnessArgv")
    if not isinstance(argv, list) or any(not isinstance(item, str) for item in argv):
        raise ValueError("Temporal operator harnessArgv must be a list of strings")
    backend_values = []
    for index, token in enumerate(argv):
        flag = token.split("=", 1)[0]
        if flag.startswith("--") and "--agent-backend".startswith(flag) and flag != "--agent-backend":
            # v1 bytes predate the full-option rule; the harness parser accepts
            # unambiguous abbreviations ("--ag" onward; "--a" also matches --api-key-secret).
            if schema != OPERATOR_SCHEMA_V1 or len(flag) < len("--ag"):
                raise ValueError("Temporal backend pin must use the full --agent-backend option")
        if flag.startswith("--ag") and "--agent-backend".startswith(flag):
            value = token.split("=", 1)[1] if "=" in token else (argv[index + 1] if index + 1 < len(argv) else "")
            backend_values.append(value)
    if len(backend_values) > 1:
        raise ValueError("Temporal backend pin must occur exactly once")
    if backend_values and backend_values[0] not in ("codex-cli", "agents-api", "sdk"):
        raise ValueError("Unsupported Temporal backend pin")
    if schema == OPERATOR_SCHEMA_V2 and not backend_values:
        raise ValueError("Temporal operator-v2 requires an explicit --agent-backend pin")
    if schema == OPERATOR_SCHEMA_V2 and backend_values != ["codex-cli"]:
        raise ValueError("New Temporal operator-v2 configurations require --agent-backend codex-cli")
    return list(argv) if backend_values else [*argv, "--agent-backend", "agents-api"]


def validate_configuration_profile(config: dict, profile: str) -> None:
    if profile == "fixture" and config.get("schemaVersion") == "sermon-temporal-fixture-v1":
        return
    if profile == "production" and config.get("schemaVersion") in (OPERATOR_SCHEMA_V1, OPERATOR_SCHEMA_V2):
        operator_harness_argv(config)
        return
    raise ValueError("Client profile does not match configuration schema")


@dataclass(frozen=True)
class Request:
    schema_version: str
    profile: str
    sunday: str
    source_key: str
    config_path: str
    config_sha256: str
    allow_execute: bool = False
    activity_timeout_seconds: float = 25260
    heartbeat_timeout_seconds: float = 20

    def validate(self):
        if self.schema_version != REQUEST_SCHEMA or self.profile not in ("fixture", "production"):
            raise ValueError("Unsupported Temporal request schema/profile")
        date.fromisoformat(self.sunday)
        if not self.source_key or len(self.source_key) > 512:
            raise ValueError("Explicit bounded source key is required")
        if not self.config_path.startswith("/") or not re.fullmatch(r"[0-9a-f]{64}", self.config_sha256):
            raise ValueError("Absolute configuration path and SHA-256 are required")
        if type(self.allow_execute) is not bool:
            raise ValueError("allow_execute must be a boolean")
        if any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0
               for value in (self.activity_timeout_seconds, self.heartbeat_timeout_seconds)):
            raise ValueError("Positive finite activity/heartbeat deadlines are required")
        if self.heartbeat_timeout_seconds >= min(self.activity_timeout_seconds, 300):
            raise ValueError("Heartbeat deadline must be shorter than both activity and 300-second inspection deadlines")

    def workflow_id(self) -> str:
        # File location, permission and timeout changes never create a second
        # execution identity for the same fixed config/source.
        return f"sermon-saturday-v1-{self.sunday}-{digest([self.profile, self.source_key, self.config_sha256])[:24]}"

    def task_queue(self) -> str:
        return QUEUE_PREFIX + self.profile


@dataclass(frozen=True)
class ActivityInput:
    request: Request
    expected_binding: str = ""


@dataclass(frozen=True)
class ResumeSignal:
    schema_version: str
    signal_id: str
    expected_binding: str
    reason: str
    recovery_epoch: int = 0


@dataclass
class Observation:
    schema_version: str = OBSERVATION_SCHEMA
    status: str = "not_observed"
    source_binding: str = ""
    action_token: str = ""
    executable: bool = False
    terminal: bool = False
    terminal_scope: str = ""
    approval_valid: bool = False
    runtime_busy: bool = False
    original_action: str = ""
    evidence_path: str = ""
    reason: str = ""

    def validate(self):
        if self.schema_version != OBSERVATION_SCHEMA or not re.fullmatch(r"[0-9a-f]{64}", self.source_binding):
            raise ValueError("Malformed observation or missing source binding")
        if self.terminal_scope not in ("", "candidate_handoff_only", "fixture_only"):
            raise ValueError("Temporal cannot grant a new production completion scope")
        if self.terminal and not self.terminal_scope:
            raise ValueError("Terminal observation must explicitly identify its limited scope")
