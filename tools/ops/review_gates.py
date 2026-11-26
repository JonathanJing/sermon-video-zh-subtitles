#!/usr/bin/env python3
"""Where the steps that wait for a person live on disk, and what happens to a decision.

    artifacts/weekly-auto/<production>/
      production.json                       the production record (written by weekly_auto.py)
      gates/<gateId>/gate.json              the current revision: kind, bindings, state
      gates/<gateId>/data.json              what the page shows for this revision
      gates/<gateId>/decisions/<id>.json    every accepted decision, never rewritten
      gates/<gateId>/outcomes/<id>.json     what the driver did with it

The review server (review_gate_server.py) writes decisions; the driver (weekly_auto.py) opens
gates and writes outcomes. A decision is accepted only for the open revision and only when it
echoes that revision's bindings; the driver checks the bindings against the files again before
it writes any receipt. Nothing here is a receipt, and nothing here sets humanApproval.

The shapes the pages see are schemas/sermon-review-gate-v1, -decision-v1 and -index-v1.
Standard library only.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path

ROOT_NAME = Path("artifacts") / "weekly-auto"
PRODUCTION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}")
GATE_ID = re.compile(r"l[0-9]\.[A-Za-z0-9.-]{1,60}")
KINDS = ("decisions", "english", "speakers", "track", "study", "publish", "confirm")
ORDER = ("l0.decisions", "l1.english-review", "l1.speakers", "l3.review.", "l4.study", "l4.publish.authorization", "l4.device-confirm")
VERDICTS = ("approved", "changes_requested")
MAX_NOTE = 4000


class GateError(Exception):
    """A request the store refuses. `status` is the HTTP status the server answers with."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _order(gate_id: str) -> tuple[int, str]:
    for index, prefix in enumerate(ORDER):
        if gate_id == prefix or (prefix.endswith(".") and gate_id.startswith(prefix)):
            return index, gate_id
    return len(ORDER), gate_id


def validate_decision(gate: dict, decision) -> None:
    """Shape, and that the decision is about the revision and the hashes the gate has now."""
    def bad(message: str, status: int = 400, code: str = "invalid_decision"):
        raise GateError(status, code, message)

    if not isinstance(decision, dict):
        bad("决定必须是一个 JSON 对象")
    if decision.get("schemaVersion") != "sermon-review-decision-v1":
        bad("不认识的决定版本")
    for name in ("gateId", "kind", "production", "locale"):
        if decision.get(name) != gate.get(name):
            bad(f"决定里的 {name} 与这个审核任务不符")
    if decision.get("verdict") not in VERDICTS:
        bad("结论只能是批准或要求修改")
    checks = decision.get("checks")
    if not isinstance(checks, dict) or any(not isinstance(value, bool) for value in checks.values()):
        bad("确认项必须是布尔值")
    if decision["verdict"] == "approved" and not all(checks.values()):
        bad("还有确认项没有勾，不能批准")
    if not isinstance(decision.get("payload"), dict):
        bad("决定缺少内容")
    note = decision.get("note")
    if not isinstance(note, str) or len(note) > MAX_NOTE:
        bad("备注太长或格式不对")
    key = decision.get("idempotencyKey")
    if not isinstance(key, str) or not 16 <= len(key) <= 64:
        bad("缺少幂等键")
    client = decision.get("client")
    if not isinstance(client, dict) or not isinstance(client.get("submittedAt"), str) or not isinstance(client.get("userAgent"), str):
        bad("缺少提交设备信息")
    if gate.get("state") != "open":
        bad("这个审核任务现在不能提交", 409, "not_open")
    if decision.get("revision") != gate.get("revision") or decision.get("bindings") != gate.get("bindings"):
        bad("页面展示的版本已经过期，请刷新后重新审", 409, "stale")


class Store:
    def __init__(self, work_root: Path):
        self.work_root = Path(work_root).resolve()
        self.root = self.work_root / ROOT_NAME

    # ---- productions
    def production_dir(self, production: str) -> Path:
        if not isinstance(production, str) or not PRODUCTION.fullmatch(production):
            raise GateError(404, "unknown_production", "没有这个生产")
        return self.root / production

    def productions(self) -> list[str]:
        if not self.root.is_dir():
            return []
        names = [path.name for path in self.root.iterdir()
                 if PRODUCTION.fullmatch(path.name) and (path / "production.json").is_file()]
        return sorted(names, key=lambda name: (self.root / name / "production.json").stat().st_mtime, reverse=True)

    def production(self, production: str) -> dict:
        path = self.production_dir(production) / "production.json"
        if not path.is_file():
            raise GateError(404, "unknown_production", "没有这个生产")
        return read_json(path)

    def write_production(self, record: dict) -> None:
        write_json(self.production_dir(record["production"]) / "production.json", record)

    # ---- gates
    def gate_dir(self, production: str, gate_id: str) -> Path:
        if not isinstance(gate_id, str) or not GATE_ID.fullmatch(gate_id):
            raise GateError(404, "unknown_gate", "没有这个审核任务")
        return self.production_dir(production) / "gates" / gate_id

    def gate(self, production: str, gate_id: str) -> dict:
        path = self.gate_dir(production, gate_id) / "gate.json"
        if not path.is_file():
            raise GateError(404, "unknown_gate", "没有这个审核任务")
        return read_json(path)

    def gates(self, production: str) -> list[dict]:
        folder = self.production_dir(production) / "gates"
        found = [read_json(path / "gate.json") for path in (folder.iterdir() if folder.is_dir() else [])
                 if (path / "gate.json").is_file()]
        return sorted(found, key=lambda gate: _order(gate["gateId"]))

    def open_gate(self, production: str, *, gate_id: str, kind: str, title: str, bindings: dict, data: dict,
                  assets_root: Path | None = None, locale: str | None = None, summary: str | None = None,
                  state: str = "open") -> dict:
        """Open a step for review. Different bindings make a new revision; the same ones change nothing."""
        if kind not in KINDS:
            raise ValueError(f"unknown gate kind {kind}")
        if not bindings or any(not isinstance(value, str) or not value for value in bindings.values()):
            raise ValueError("a gate needs the hashes its decision binds to")
        folder = self.gate_dir(production, gate_id)
        path = folder / "gate.json"
        previous = read_json(path) if path.is_file() else None
        if previous and previous["bindings"] == bindings and previous["state"] not in ("stale", "changes_requested"):
            return previous
        record = self.production(production)
        gate = {"schemaVersion": "sermon-review-gate-record-v1", "gateId": gate_id, "kind": kind, "production": production,
                "locale": locale, "title": title, "state": state, "revision": (previous["revision"] + 1) if previous else 1,
                "openedAt": now_iso() if state == "open" else None, "bindings": bindings, "summary": summary,
                "episode": record.get("episode") or {},
                "assetsRoot": str(Path(assets_root).resolve()) if assets_root else None}
        write_json(folder / "data.json", data)
        write_json(path, gate)
        return gate

    def set_state(self, production: str, gate_id: str, state: str, **fields) -> dict:
        gate = self.gate(production, gate_id)
        gate.update(state=state, **fields)
        write_json(self.gate_dir(production, gate_id) / "gate.json", gate)
        return gate

    # ---- decisions
    def _decisions(self, production: str, gate_id: str) -> list[dict]:
        folder = self.gate_dir(production, gate_id) / "decisions"
        return [read_json(path) for path in sorted(folder.glob("*.json"))] if folder.is_dir() else []

    def outcome(self, production: str, gate_id: str, decision_id: str) -> dict | None:
        path = self.gate_dir(production, gate_id) / "outcomes" / f"{decision_id}.json"
        return read_json(path) if path.is_file() else None

    def record_decision(self, decision: dict, reviewer: dict) -> dict:
        """Accept one decision for the open revision. The same idempotency key returns the first record."""
        production, gate_id = decision.get("production"), decision.get("gateId")
        gate = self.gate(production, gate_id)
        for earlier in self._decisions(production, gate_id):
            if earlier["decision"].get("idempotencyKey") == decision.get("idempotencyKey"):
                return earlier
        validate_decision(gate, decision)
        received = now_iso()
        digest = hashlib.sha256(decision["idempotencyKey"].encode()).hexdigest()[:8]
        decision_id = f"d-{received[:19].replace('-', '').replace(':', '')}-{digest}"
        record = {"schemaVersion": "sermon-review-decision-record-v1", "decisionId": decision_id, "receivedAt": received,
                  "reviewer": reviewer, "decision": decision}
        path = self.gate_dir(production, gate_id) / "decisions" / f"{decision_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "x", encoding="utf-8") as handle:      # never overwrite an accepted decision
            handle.write(json.dumps(record, ensure_ascii=False, indent=1) + "\n")
        self.set_state(production, gate_id, "submitted")
        return record

    def pending(self, production: str) -> list[dict]:
        """Accepted decisions the driver has not dealt with yet, oldest first."""
        waiting = []
        for gate in self.gates(production):
            for record in self._decisions(production, gate["gateId"]):
                if self.outcome(production, gate["gateId"], record["decisionId"]) is None:
                    waiting.append(record)
        return sorted(waiting, key=lambda record: record["receivedAt"])

    def record_outcome(self, production: str, gate_id: str, decision_id: str, outcome: str, *, message: str | None = None,
                       receipt_sha256: str | None = None, next_stage: str | None = None) -> dict:
        if outcome not in ("applied", "rejected_stale", "failed"):
            raise ValueError(outcome)
        record = next(r for r in self._decisions(production, gate_id) if r["decisionId"] == decision_id)
        result = {"decisionId": decision_id, "outcome": outcome, "at": now_iso(), "message": message,
                  "receiptSha256": receipt_sha256, "nextStage": next_stage}
        write_json(self.gate_dir(production, gate_id) / "outcomes" / f"{decision_id}.json", result)
        verdict = record["decision"]["verdict"]
        if record["decision"]["revision"] != self.gate(production, gate_id)["revision"]:
            return result                                      # about an earlier revision: the current one is untouched
        if outcome == "applied":
            self.set_state(production, gate_id, "applied" if verdict == "approved" else "changes_requested", decidedAt=result["at"])
        elif outcome == "rejected_stale":
            self.set_state(production, gate_id, "stale")
        return result

    def last_decision(self, production: str, gate_id: str) -> dict | None:
        revision = self.gate(production, gate_id)["revision"]
        records = [r for r in self._decisions(production, gate_id) if r["decision"]["revision"] == revision]
        if not records:
            return None
        record = records[-1]
        outcome = self.outcome(production, gate_id, record["decisionId"]) or {}
        return {"decisionId": record["decisionId"], "verdict": record["decision"]["verdict"], "submittedAt": record["receivedAt"],
                "reviewer": record["reviewer"].get("name") or record["reviewer"].get("login"),
                "outcome": outcome.get("outcome", "queued"), "message": outcome.get("message"),
                "receiptSha256": outcome.get("receiptSha256"), "nextStage": outcome.get("nextStage")}

    # ---- what the pages load
    def descriptor(self, production: str, gate_id: str, viewer: dict) -> dict:
        gate = self.gate(production, gate_id)
        return {"schemaVersion": "sermon-review-gate-v1", "gateId": gate["gateId"], "kind": gate["kind"],
                "production": production, "locale": gate["locale"], "title": gate["title"], "state": gate["state"],
                "revision": gate["revision"], "openedAt": gate.get("openedAt"), "bindings": gate["bindings"],
                "labels": {"machineGenerated": True, "humanApproval": False,
                           "rehearsal": bool(self.production(production).get("rehearsal"))},
                "episode": gate.get("episode") or {},
                "viewer": viewer, "assetsBase": f"files/{production}/{gate_id}/",
                "data": read_json(self.gate_dir(production, gate_id) / "data.json"),
                "lastDecision": self.last_decision(production, gate_id)}

    def index(self, production: str) -> dict:
        record = self.production(production)
        gates = []
        for gate in self.gates(production):
            gates.append({"gateId": gate["gateId"], "kind": gate["kind"], "locale": gate["locale"], "title": gate["title"],
                          "state": gate["state"], "summary": gate.get("summary"), "openedAt": gate.get("openedAt"),
                          "decidedAt": gate.get("decidedAt")})
        return {"schemaVersion": "sermon-review-index-v1", "production": production, "rehearsal": bool(record.get("rehearsal")),
                "episode": record.get("episode") or {},
                "worker": record.get("worker") or {}, "gates": gates}

    def asset(self, production: str, gate_id: str, relative: str) -> Path:
        """A media file under the gate's declared directory, and nothing outside it."""
        root = self.gate(production, gate_id).get("assetsRoot")
        if not root:
            raise GateError(404, "no_assets", "这个任务没有媒体文件")
        base = Path(root).resolve()
        path = (base / relative).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise GateError(404, "unknown_asset", "没有这个文件")
        return path
