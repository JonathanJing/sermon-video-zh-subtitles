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
