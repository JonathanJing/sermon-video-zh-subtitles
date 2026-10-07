#!/usr/bin/env python3
"""Isolated read-only paired Decisions experiment; never a production producer.

Private artifacts hold evidence and raw outputs. Public summaries contain only
IDs, hashes, labels, timings and fixed errors. A reservation precedes every
single network dispatch; unknown outcomes cannot be retried on resume.
"""
from __future__ import annotations
import argparse
import copy
from contextlib import contextmanager
from decimal import Decimal, ROUND_CEILING
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VERSION = "decision-weekly-ab-runner-v2"
ENDPOINTS = {"chat": "https://api.openai.com/v1/chat/completions",
             "decisions": "https://api.openai.com/v1/decisions"}
MAX_CHAT_INPUT_BOUND = 16384
MAX_INPUT_BOUND = 32768
MAX_COMPLETION = 8192
MAX_RESPONSE_BYTES = 262144
MAX_QUESTIONS = 64
# Frozen short-context default-tier planning rates, including 10% regional
# cushion. These are reservations/list-price estimates, never invoices.
PRICE_VERSION = "20261006-short-context-default-fast-regional-cushion-v2"
RATES = {"gpt-6.1-sol": (Decimal("2.75"), Decimal("11")),
         "gpt-6.1-sol:fast": (Decimal("5.5"), Decimal("22")),
         "decisions:gpt-6-luna": (Decimal("0.11"), Decimal("0"))}
SAFE_ID = re.compile(r"[A-Za-z0-9_.-]{1,160}")

def require(ok, code):
    if not ok:
        raise ValueError(code)

def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")

def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".pending")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)

@contextmanager
def run_lock(directory):
    directory = Path(directory).resolve()
    require(directory.is_relative_to(ROOT / "artifacts"), "output_outside_experiment_artifacts")
    ignored = subprocess.run(["git", "check-ignore", "-q", str(directory)], cwd=ROOT,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    require(ignored.returncode == 0, "output_not_git_ignored")
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / "run.lock", os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("experiment_run_busy") from None
        yield


def safe_request_id(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value) else None

def valid_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0

def validate_cases(cases):
    require(isinstance(cases, list) and cases, "empty_case_set")
    ids = set()
    for case in cases:
        require(type(case) is dict and SAFE_ID.fullmatch(case.get("caseId", "")),
                "invalid_case_id")
        require(case["caseId"] not in ids and case["caseId"] not in {".", ".."}, "duplicate_or_unsafe_case_id")
        ids.add(case["caseId"])
        require(case.get("stageId") in {f"E{i:02d}" for i in range(1, 9)},
                "invalid_stage")
        require(type(case.get("sharedEvidence")) is dict and
                case["a"].get("kind") in {"program", "chat", "no_executable_baseline"},
                "invalid_case_evidence_or_arm")
        if case["a"]["kind"] != "no_executable_baseline":
            try:
                same = json.loads(case["b"]["input"]) == case["sharedEvidence"]
            except (ValueError, TypeError):
                same = False
            require(same, "decision_input_evidence_mismatch")
            validate_decisions_payload({"model": "gpt-6-luna", **case["b"]})
    return copy.deepcopy(cases)

def validate_decisions_payload(payload):
    require(set(payload) == {"model", "input", "questions"} and
            payload["model"] == "gpt-6-luna" and type(payload["input"]) is str,
            "unsupported_decisions_payload")
    questions = payload["questions"]
    require(type(questions) is list and 1 <= len(questions) <= MAX_QUESTIONS,
            "invalid_question_count")
    names = set()
    for question in questions:
        require(type(question) is dict and question.get("type") in {"predicate", "choice", "score"}
                and SAFE_ID.fullmatch(question.get("name", "")) and
                question["name"] not in names and type(question.get("instructions")) is str
                and bool(question["instructions"]), "invalid_decision_question")
        names.add(question["name"])
        required = {"name", "type", "instructions"}
        if question["type"] == "choice":
            required.add("choices")
            values = []
            require(type(question["choices"]) is list and len(question["choices"]) >= 2,
                    "invalid_decision_choices")
            for option in question["choices"]:
                require(type(option) is dict and set(option) <= {"value", "description"}
                        and "value" in option and type(option["value"]) in {str, bool},
                        "invalid_choice_option")
                values.append((type(option["value"]).__name__, option["value"]))
            require(len(values) == len(set(values)), "duplicate_choice_values")
        elif question["type"] == "score":
            required.add("levels")
            require(type(question["levels"]) is list and len(question["levels"]) >= 2 and
                    all(type(level) is dict and set(level) <= {"label", "description"}
                        and type(level.get("label")) is str for level in question["levels"]),
                    "invalid_score_levels")
        require(set(question) == required, "unexpected_question_fields")
    return copy.deepcopy(payload)

def payload_and_bounds(case, arm):
    if arm == "B":
        payload = validate_decisions_payload({"model": "gpt-6-luna", **case["b"]})
        input_bound = len(encoded(payload)) + 256 + 32 * len(payload["questions"])
        key, output_bound, kind = "decisions:gpt-6-luna", 0, "decisions"
    else:
        payload = copy.deepcopy(case["a"]["payload"])
        require({"model", "reasoning_effort", "messages", "response_format"} <= set(payload),
                "missing_chat_baseline_fields")
        require(type(payload["messages"]) is list and 1 <= len(payload["messages"]) <= 16 and
                all(type(m) is dict and set(m) == {"role", "content"} and
                    m["role"] in {"system", "developer", "user", "assistant"} and
                    type(m["content"]) is str and bool(m["content"]) for m in payload["messages"]),
                "invalid_chat_baseline_messages")
        require(payload.get("model") == "gpt-6.1-sol" and
                payload.get("reasoning_effort") in {"high", "medium"},
                "unexpected_chat_baseline_model")
        require(payload.get("response_format", {}).get("type") in {"json_schema", "json_object"}
                and isinstance(payload.get("messages"), list), "invalid_chat_baseline_payload")
        require(set(payload) <= {"model", "reasoning_effort", "messages", "response_format",
                                "max_completion_tokens", "service_tier"},
                "unsupported_chat_baseline_parameter")
        existing_cap = payload.get("max_completion_tokens")
        require(existing_cap is None or type(existing_cap) is int and 1 <= existing_cap <= MAX_COMPLETION,
                "baseline_completion_cap_too_large")
        tier = payload.get("service_tier", "default")
        require(tier in {"default", "fast"}, "unsupported_baseline_tier")
        payload["max_completion_tokens"] = existing_cap or MAX_COMPLETION
        payload["service_tier"] = tier
        # Count the actual schema, not an artificial json_object substitute.
        from scripts import sermon_provider_limits as limits
        input_bound = limits._input_upper_bound(payload)
        key = payload["model"] + (":fast" if tier == "fast" else "")
        output_bound, kind = payload["max_completion_tokens"], "chat"
    require(input_bound <= (MAX_INPUT_BOUND if arm == "B" else MAX_CHAT_INPUT_BOUND), "experiment_input_bound_exceeded")
    in_rate, out_rate = RATES[key]
    cost = int((in_rate * input_bound + out_rate * output_bound).to_integral_value(rounding=ROUND_CEILING))
    return payload, {"requests": 1, "inputTokens": input_bound,
                     "outputTokens": output_bound, "costMicrousd": cost}, kind

def normalize_b(case, response):
    require(type(response) is dict and response.get("model") == "gpt-6-luna" and type(response.get("answers")) is list,
            "invalid_decision_response")
    questions = {q["name"]: q for q in case["b"]["questions"]}
    require(len(response["answers"]) == len(questions) and
            all(type(a) is dict and a.get("name") in questions for a in response["answers"]) and
            {a["name"] for a in response["answers"]} == set(questions), "decision_answer_count_mismatch")
    labels, probabilities, names = {}, {}, set()
    for answer in response["answers"]:
        require(type(answer) is dict and answer.get("name") in questions and
                answer["name"] not in names, "decision_answer_identity_mismatch")
        name = answer["name"]
        names.add(name)
        question = questions[name]
        if answer.get("type") == "refusal":
            return {"status": "refusal", "labels": {}, "refusedQuestion": name}
        require(answer.get("type") == question["type"], "decision_answer_type_mismatch")
        if answer["type"] == "choice":
            value = answer.get("choice")
            require(any(type(value) is type(option["value"]) and value == option["value"]
                        for option in question["choices"]), "decision_choice_not_allowed")
            confidence = answer.get("confidence")
            require(valid_number(confidence) and confidence <= 1, "invalid_decision_confidence")
            distribution = answer.get("probabilities")
            allowed = {(type(o["value"]).__name__, o["value"]) for o in question["choices"]}
            require(type(distribution) is list and len(distribution) == len(allowed) and
                    all(type(o) is dict and (type(o.get("value")).__name__, o.get("value")) in allowed
                        and valid_number(o.get("probability")) and o["probability"] <= 1 for o in distribution)
                    and {(type(o["value"]).__name__, o["value"]) for o in distribution} == allowed
                    and abs(sum(o["probability"] for o in distribution) - 1) <= 1e-5,
                    "invalid_choice_probability_distribution")
            labels[name] = value
            probabilities[name] = {"confidence": confidence, "probabilities": distribution}
        elif answer["type"] == "predicate":
            probability = answer.get("probability")
            require(valid_number(probability) and probability <= 1, "invalid_decision_probability")
            # Protocol smoke threshold only; not calibrated production admission.
            labels[name] = probability >= .5
            probabilities[name] = {"probability": probability, "smokeThreshold": .5}
        else:
            score = answer.get("score")
            require(valid_number(score) and score <= len(question["levels"]) - 1,
                    "invalid_decision_score")
            distribution, confidence = answer.get("probabilities"), answer.get("confidence")
            require(valid_number(confidence) and confidence <= 1 and type(distribution) is list
                    and len(distribution) == len(question["levels"]) and
                    all(type(o) is dict and type(o.get("value")) is int and o["value"] == index
                        and o.get("label") == question["levels"][index]["label"]
                        and valid_number(o.get("probability")) and o["probability"] <= 1
                        for index, o in enumerate(distribution))
                    and abs(sum(o["probability"] for o in distribution) - 1) <= 1e-5
                    and abs(sum(o["value"] * o["probability"] for o in distribution) - score) <= 1e-5,
                    "invalid_score_probability_distribution")
            labels[name] = score
            probabilities[name] = {"probabilities": distribution, "confidence": confidence}
    return {"labels": labels, "probabilities": probabilities}

def normalize_a(case, response):
    from scripts.experiments.decision_api_cases_content import normalize_content_a
    return normalize_content_a(case, response)

def measured_usage(response, kind):
    usage = response.get("usage")
    if type(usage) is not dict:
        return None, None
    inputs = usage.get("input_tokens") if kind == "decisions" else usage.get("prompt_tokens")
    outputs = usage.get("output_tokens") if kind == "decisions" else usage.get("completion_tokens")
    if type(inputs) is not int or inputs < 0 or type(outputs) is not int or outputs < 0:
        return copy.deepcopy(usage), None
    if kind == "decisions":
        if response.get("model") != "gpt-6-luna":
            return copy.deepcopy(usage), None
        # Official guide says input-only billing; optional compute_units is
        # preserved telemetry, not invented separate billed dollars.
        in_rate, out_rate = RATES["decisions:gpt-6-luna"]
    elif response.get("model") == "gpt-6.1-sol" and response.get("service_tier") in {"default", "fast"}:
        in_rate, out_rate = RATES["gpt-6.1-sol" + (":fast" if response["service_tier"] == "fast" else "")]
    else:
        return copy.deepcopy(usage), None
    cost = int((in_rate * inputs + out_rate * outputs).to_integral_value(rounding=ROUND_CEILING))
    return copy.deepcopy(usage), cost

class Ledger:
    def __init__(self, directory, authority):
        self.directory = Path(directory).resolve()
        self.authority = copy.deepcopy(authority)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        require(authority.get("root") == str(self.directory) and
                authority.get("schemaVersion") == "decision-ab-budget-authority-v1" and
                type(authority.get("maxCostMicrousd")) is int and authority["maxCostMicrousd"] > 0
                and type(authority.get("maxRequests")) is int and 0 < authority["maxRequests"] <= 2000,
                "invalid_experiment_authority")
    @contextmanager
    def locked(self):
        fd = os.open(self.directory / "ledger.lock", os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, "r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.directory / "ledger.json"
            data = read(path) if path.exists() else {
                "schemaVersion": "decision-ab-ledger-v1", "authoritySha256": digest(self.authority),
                "operations": {}}
            require(data.get("authoritySha256") == digest(self.authority) and
                    data.get("schemaVersion") == "decision-ab-ledger-v1" and
                    type(data.get("operations")) is dict, "experiment_authority_changed")
            yield data, path
    def reserve(self, operation, identity, bounds):
        with self.locked() as (data, path):
            require(not data.get("sealedForSuccessor"), "previous_ledger_sealed")
            if operation in data["operations"]:
                record = data["operations"][operation]
                require(record["identity"] == identity and record["bounds"] == bounds,
                        "experiment_operation_identity_changed")
                return False, record
            require(not any(r.get("status") == "budget_bound_exceeded" for r in data["operations"].values()),
                    "experiment_observed_bound_exceeded")
            costs = sum(record.get("settledCostMicrousd")
                        if record.get("settledCostMicrousd") is not None
                        else record["bounds"]["costMicrousd"] for record in data["operations"].values())
            carry = self.authority.get("previousBudget", {}).get("estimatedOrReservedMicrousd", 0)
            require(len(data["operations"]) < self.authority["maxRequests"] and
                    carry + costs + bounds["costMicrousd"] <= self.authority["maxCostMicrousd"],
                    "experiment_budget_unavailable")
            record = {"identity": identity, "bounds": bounds, "status": "reserved_outcome_unknown",
                      "settledCostMicrousd": None}
            data["operations"][operation] = record
            atomic(path, data)
            return True, copy.deepcopy(record)
    def finish(self, operation, receipt, cost):
        with self.locked() as (data, path):
            require(not data.get("sealedForSuccessor"), "previous_ledger_sealed")
            record = data["operations"][operation]
            record.update(status=receipt["status"], receiptSha256=digest(receipt))
            if cost is not None:
                record["settledCostMicrousd"] = cost
                if cost > record["bounds"]["costMicrousd"]:
                    record["status"] = "budget_bound_exceeded"
            atomic(path, data)
    def summary(self):
        with self.locked() as (data, _):
            records = list(data["operations"].values())
            return {"networkAttempts": len(records),
                    "carriedPreviousMicrousd": self.authority.get("previousBudget", {}).get("estimatedOrReservedMicrousd", 0),
                    "estimatedOrReservedMicrousd": sum(r["settledCostMicrousd"]
                        if r["settledCostMicrousd"] is not None else r["bounds"]["costMicrousd"] for r in records)
                        + self.authority.get("previousBudget", {}).get("estimatedOrReservedMicrousd", 0),
                    "unsettledAttempts": sum(r["settledCostMicrousd"] is None for r in records),
                    "maxCostMicrousd": self.authority["maxCostMicrousd"],
                    "invoiceVerified": False, "hardProviderFinancialCapVerified": False}

def seal_previous_run(directory, successor):
    root = Path(directory).resolve()
    require(root != Path(successor).resolve(), "previous_run_is_current")
    with run_lock(root):
        ledger = Ledger(root, read(root/"authority.json"))
        with ledger.locked() as (data, path):
            target = str(Path(successor).resolve())
            require(data.get("sealedForSuccessor", target) == target,
                    "previous_ledger_already_has_successor")
            # A new code/case identity cannot authorize redispatching an
            # original uncertain attempt. Resolve it before any successor.
            require(not any(row["status"] in {"reserved_outcome_unknown", "outcome_unknown",
                                             "blocked_prior_operation", "budget_bound_exceeded"}
                            for row in data["operations"].values()), "previous_attempt_requires_reconciliation")
            data["sealedForSuccessor"] = target
            atomic(path, data)

def previous_budget(directory, successor):
    root = Path(directory).resolve()
    require(root.is_relative_to(ROOT / "artifacts"), "previous_run_outside_artifacts")
    with run_lock(root):
        bound, data = read(root/"authority.json"), read(root/"ledger.json")
        require(data["authoritySha256"] == digest(bound), "previous_ledger_identity_changed")
        require(data.get("sealedForSuccessor") == str(Path(successor).resolve()),
                "previous_run_not_sealed_for_current")
        ledger = Ledger(root, bound)
        consumed = ledger.summary()["estimatedOrReservedMicrousd"]
        return {"root": str(root), "ledgerSha256": digest(data),
                "authoritySha256": digest(bound), "estimatedOrReservedMicrousd": consumed}

def authority(directory, cases, max_usd, max_requests, authorization_note, previous_run=None):
    deps = ["scripts/experiments/decision_api_weekly_ab.py",
            "scripts/experiments/decision_api_cases_content.py",
            "scripts/experiments/decision_api_cases_rules.py",
            "scripts/judge_english_source_for_translation.py",
            "scripts/sermon_repair_planning.py",
            "scripts/sermon_provider_error.py",
            "scripts/screen_target_language_audio_units.py",
            "scripts/target_audio_timing_plan.py",
            "scripts/render_formal_target_language_speech.py",
            "scripts/sermon_production_supervisor.py"]
    deps = sorted(set(deps) | {
        str(path.relative_to(ROOT)) for folder in ("scripts", "schemas", "config")
        for path in (ROOT / folder).rglob("*")
        if path.is_file() and path.suffix in {".py", ".json", ".md"}
    })
    code = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in deps}
    result = {"schemaVersion": "decision-ab-budget-authority-v1",
            "root": str(Path(directory).resolve()), "caseSetSha256": digest(cases),
            "codeDependencySha256": digest(code), "codeDependencies": code,
            "planSha256": hashlib.sha256((ROOT / "config/decision-api-weekly-ab-plan-v1.json").read_bytes()).hexdigest(),
            "maxCostMicrousd": int(Decimal(str(max_usd)) * 1000000),
            "maxRequests": max_requests, "maxInputTokensPerCall": MAX_INPUT_BOUND,
            "maxChatInputTokensPerCall": MAX_CHAT_INPUT_BOUND,
            "maxCompletionTokensPerChat": MAX_COMPLETION, "priceAssumptionVersion": PRICE_VERSION,
            "priceSource": "https://developers.openai.com/api/docs/pricing",
            "decisionPriceSource": "https://developers.openai.com/api/docs/guides/decisions",
            "authorizationSha256": digest({"source": "user_message", "authorizationNote": authorization_note}),
            "credentialAlias": "tongxing-dev-runtime", "environment": "dev",
            "productionMutationAllowed": False, "thresholdStatus": "protocol_smoke_only"}
    if previous_run:
        require(Path(previous_run).resolve() != Path(directory).resolve(), "previous_run_is_current")
        result["previousBudget"] = previous_budget(previous_run, directory)
        require(result["previousBudget"]["estimatedOrReservedMicrousd"] < result["maxCostMicrousd"],
                "previous_run_exhausted_budget")
    return result

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _worker():
    try:
        raw = sys.stdin.buffer.read(262145)
        require(len(raw) <= 262144, "request_too_large")
        packet = json.loads(raw)
        require(packet["url"] in ENDPOINTS.values(), "endpoint_not_allowed")
        headers = {"Authorization": "Bearer " + packet["key"],
                   "Content-Type": "application/json", "OpenAI-Project": packet["project"]}
        require(re.fullmatch(r"proj_[A-Za-z0-9_-]+", packet["project"]) and
                re.fullmatch(r"[A-Za-z0-9._~-]+", packet["key"]), "invalid_route")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                     urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        request = urllib.request.Request(packet["url"], encoded(packet["payload"]),
                                         headers=headers, method="POST")
        try:
            with opener.open(request, timeout=packet["timeout"]) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                require(len(body) <= MAX_RESPONSE_BYTES, "response_too_large")
                result = {"status": "returned", "response": json.loads(body),
                          "requestId": safe_request_id(response.headers.get("x-request-id"))}
        except urllib.error.HTTPError as error:
            result = {"status": "http_error", "httpStatus": error.code,
                      "requestId": safe_request_id(error.headers.get("x-request-id"))}
    except BaseException:
        result = {"status": "outcome_unknown", "reasonCode": "provider_worker_failed"}
    sys.stdout.buffer.write(encoded(result))
    sys.stdout.buffer.flush()

def dispatch(kind, payload, timeout_seconds):
    require(os.environ.get("SERMON_OPENAI_ENVIRONMENT") == "dev" and
            os.environ.get("SERMON_OPENAI_CREDENTIAL_ALIAS") == "tongxing-dev-runtime",
            "explicit_dev_launcher_required")
    key, project = os.environ.get("OPENAI_API_KEY"), os.environ.get("OPENAI_PROJECT_ID")
    require(bool(key) and bool(project), "dev_credentials_missing")
    packet = {"url": ENDPOINTS[kind], "payload": payload, "key": key,
              "project": project, "timeout": timeout_seconds}
    child = subprocess.Popen([sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--worker"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, env={})
    try:
        output, _ = child.communicate(encoded(packet), timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()
        return {"status": "outcome_unknown", "reasonCode": "wall_timeout"}
    except BaseException:
        child.kill()
        child.communicate()
        raise
    if child.returncode or len(output) > MAX_RESPONSE_BYTES + 4096:
        return {"status": "outcome_unknown", "reasonCode": "worker_result_invalid"}
    try:
        result = json.loads(output)
        require(result.get("status") in {"returned", "http_error", "outcome_unknown"},
                "invalid_worker_envelope")
        return result
    except (ValueError, TypeError):
        return {"status": "outcome_unknown", "reasonCode": "worker_result_invalid"}

def measured_attempt(case, arm, *, mode, directory, ledger=None, dispatcher=dispatch,
                     timeout_seconds=120, order_position=None):
    case_hash = digest(case)
    path = Path(directory) / case["stageId"] / case["caseId"] / arm / "receipt.json"
    if path.exists():
        previous = read(path)
        require(previous["caseSha256"] == case_hash and previous["mode"] == mode,
                "cached_receipt_identity_changed")
        return {**previous, "restored": True}
    started = time.monotonic()
    row = {"schemaVersion": VERSION, "caseId": case["caseId"], "stageId": case["stageId"],
           "startedUtc": datetime.now(timezone.utc).isoformat(), "orderPosition": order_position,
           "attemptId": digest({"directory": str(Path(directory).resolve()), "case": case_hash, "arm": arm}),
           "subtaskId": case["subtaskId"], "clusterId": case["clusterId"],
           "sourceKind": case["sourceKind"], "oracleKind": case["oracleKind"],
           "caseSha256": case_hash, "evidenceSha256": digest(case["sharedEvidence"]),
           "arm": arm, "mode": mode, "status": "not_run", "labels": None,
           "usage": None, "requestId": None, "actualModel": None, "actualTier": None,
           "estimatedCostMicrousd": None, "restored": False,
           "timings": {"evidencePreparationMs": None, "queueWaitMs": 0,
                       "decisionCallMs": None, "postprocessValidationMs": None,
                       "effectiveDecisionMs": None}}
    def finish():
        row["timings"]["effectiveDecisionMs"] = (time.monotonic() - started) * 1000
        row["finishedUtc"] = datetime.now(timezone.utc).isoformat()
        atomic(path, row)
        return row
    if case["a"]["kind"] == "no_executable_baseline":
        row["status"] = "no_executable_baseline"
        return finish()
    if arm == "A" and case["a"]["kind"] == "program":
        from scripts.experiments.decision_api_cases_rules import run_rule_a
        before = time.monotonic()
        result = run_rule_a(case)
        row["timings"].update(evidencePreparationMs=0,
                             decisionCallMs=(time.monotonic()-before)*1000,
                             postprocessValidationMs=0)
        row.update(status="validated", labels=result["labels"], requestedModel=None,
                   backend="deterministic_program")
        return finish()
    if mode == "offline":
        row["status"] = "network_not_run"
        return finish()
    require(ledger is not None, "live_requires_bound_ledger")
    before = time.monotonic()
    try:
        payload, bounds, kind = payload_and_bounds(case, arm)
    except ValueError:
        row.update(status="preflight_blocked", reasonCode="request_limits_or_payload")
        return finish()
    row["timings"]["evidencePreparationMs"] = (time.monotonic() - before)*1000
    row.update(payloadSha256=digest(payload), requestedModel=payload["model"],
               codeDependencySha256=ledger.authority["codeDependencySha256"],
               requestedEffort=payload.get("reasoning_effort"), requestedTier=payload.get("service_tier"),
               backend=kind, inputTokenUpperBound=bounds["inputTokens"],
               completionTokenCap=bounds["outputTokens"])
    if arm == "A":
        row["baselineTransportOverrides"] = {
            name: {"original": case["a"]["payload"].get(name), "experiment": payload.get(name)}
            for name in ("max_completion_tokens", "service_tier")
            if case["a"]["payload"].get(name) != payload.get(name)}
    operation = case["caseId"] + "." + arm
    identity = {"caseSha256": case_hash, "payloadSha256": digest(payload), "arm": arm,
                "evidenceSha256": row["evidenceSha256"], "codeDependencySha256": ledger.authority["codeDependencySha256"]}
    try:
        reserved, prior = ledger.reserve(operation, identity, bounds)
    except ValueError as error:
        row.update(status="preflight_blocked", reasonCode="budget_unavailable_or_identity_changed")
        return finish()
    if not reserved:
        # Missing durable receipt cannot turn an old reservation into another request.
        row.update(status="blocked_prior_operation", reasonCode="reconcile_original_attempt")
        return finish()
    before = time.monotonic()
    try:
        envelope = dispatcher(kind, payload, timeout_seconds)
    except Exception:
        envelope = {"status": "outcome_unknown", "reasonCode": "dispatch_failed"}
    row["timings"]["decisionCallMs"] = (time.monotonic() - before)*1000
    row["requestId"] = safe_request_id(envelope.get("requestId"))
    before = time.monotonic()
    cost = None
    if envelope.get("status") == "returned":
        response = envelope.get("response")
        atomic(path.with_name("raw-response.json"), response)
        if isinstance(response, dict):
            row["actualModel"] = response.get("model") if isinstance(response.get("model"), str) else None
            row["actualTier"] = response.get("service_tier")
            row["usage"], cost = measured_usage(response, kind)
            row["estimatedCostMicrousd"] = cost
        try:
            result = normalize_b(case, response) if arm == "B" else normalize_a(case, response)
            row.update(status="refusal" if result.get("status") == "refusal" else "validated",
                       labels=result.get("labels"), normalized=result)
        except Exception:
            row.update(status="invalid_response", reasonCode="response_validation_failed")
    elif envelope.get("status") == "http_error":
        row.update(status="http_error", httpStatus=envelope.get("httpStatus"),
                   reasonCode="provider_http_error")
    else:
        row.update(status="outcome_unknown", reasonCode="provider_outcome_unknown")
    row["timings"]["postprocessValidationMs"] = (time.monotonic()-before)*1000
    if cost is not None and cost > bounds["costMicrousd"]:
        row.update(status="budget_bound_exceeded", reasonCode="observed_cost_exceeds_reserved_bound")
    result = finish()
    ledger.finish(operation, result, cost)
    return result

def quantile(values, probability):
    values = sorted(values)
    if not values:
        return None
    index = (len(values)-1)*probability
    lower = math.floor(index); upper = math.ceil(index)
    return values[lower] + (values[upper]-values[lower])*(index-lower)

def summarize(cases, rows):
    stages = {}
    for stage in {case["stageId"] for case in cases}:
        selected = [row for row in rows if row["stageId"] == stage]
        pairs = []
        for case in [case for case in cases if case["stageId"] == stage]:
            by_arm = {r["arm"]: r for r in selected if r["caseId"] == case["caseId"]}
            if set(by_arm) != {"A","B"} or any(r["status"] != "validated" for r in by_arm.values()):
                continue
            pairs.append({"caseId":case["caseId"],"labelsAgree":by_arm["A"]["labels"]==by_arm["B"]["labels"],
                          "aEffectiveMs":by_arm["A"]["timings"]["effectiveDecisionMs"],
                          "bEffectiveMs":by_arm["B"]["timings"]["effectiveDecisionMs"]})
        arms = {}
        for arm in ("A","B"):
            arm_rows=[r for r in selected if r["arm"]==arm]
            times=[r["timings"]["effectiveDecisionMs"] for r in arm_rows if r["status"]=="validated"]
            oracle_rows=[r for r in arm_rows if r["status"]=="validated"
                         and next(c for c in cases if c["caseId"]==r["caseId"]).get("expected") is not None]
            conform=sum(r["labels"]==next(c for c in cases if c["caseId"]==r["caseId"])["expected"]["labels"]
                        for r in oracle_rows)
            arms[arm]={"attemptRecords":len(arm_rows),
                       "statuses":{status:sum(r["status"]==status for r in arm_rows) for status in sorted({r["status"] for r in arm_rows})},
                       "successfulEffectiveMsP50":quantile(times,.5),"successfulEffectiveMsP95":quantile(times,.95),
                       "programOracleFixtureConformance":{"matches":conform,"denominator":len(oracle_rows)},
                       "estimatedCostMicrousdKnown":sum(r["estimatedCostMicrousd"] or 0 for r in arm_rows)}
        stages[stage]={"arms":arms,"validPairs":len(pairs),
                       "pairLabelAgreement":sum(p["labelsAgree"] for p in pairs),
                       "pairs":pairs,"qualityConclusion":"inconclusive_protocol_or_unlabelled",
                       "productionReplacementEligible":False}
    return {"schemaVersion":"decision-ab-summary-v1","stages":stages,
            "liveResultIsProductionEvidence":False,"humanGoldCompleted":False}

def prepare(args):
    from scripts.experiments.decision_api_cases_rules import build_rule_cases
    from scripts.experiments.decision_api_cases_content import build_content_cases, get_content_case_report
    cases = build_content_cases(Path(args.source_root), max_cases=args.max_content_cases)
    if args.real_rule_cases:
        from scripts.experiments.decision_api_cases_rules import build_real_rule_cases
        cases += build_real_rule_cases(Path(args.source_root), max_cases=args.real_rule_cases)
    if not args.content_only:
        cases += build_rule_cases()
    if args.previous_run and args.exclude_completed:
        previous_cases = read(Path(args.previous_run)/"cases.json")
        completed = set()
        for previous in previous_cases:
            paths = [Path(args.previous_run)/"live"/previous["stageId"]/previous["caseId"]/arm/"receipt.json"
                     for arm in ("A", "B")]
            same = True
            for arm, path in zip(("A", "B"), paths):
                if not path.exists():
                    same = False
                    break
                row = read(path)
                if row.get("status") != "validated" or row.get("caseSha256") != digest(previous):
                    same = False
                    break
                if previous["a"]["kind"] != "program" or arm == "B":
                    payload, _, _ = payload_and_bounds(previous, arm)
                    if row.get("payloadSha256") != digest(payload):
                        same = False
                        break
            if same:
                completed.add(digest(previous))
        cases = [case for case in cases if digest(case) not in completed]
    cases = validate_cases(cases)
    root = Path(args.out).resolve()
    require("artifacts" in root.parts, "output_must_be_ignored_artifacts")
    require(not (root/"cases.json").exists() or read(root/"cases.json") == cases,
            "existing_case_set_changed")
    bound = None
    if args.max_usd is not None:
        require(bool(args.authorization_note), "authorization_note_required")
        require(args.max_usd > 0 and 0 < args.max_requests <= 2000, "invalid_budget_limits")
        if args.previous_run:
            seal_previous_run(args.previous_run, root)
        bound=authority(root, cases, args.max_usd, args.max_requests, args.authorization_note, args.previous_run)
        require(not (root/"authority.json").exists() or read(root/"authority.json")==bound,
                "existing_authority_changed")
    # Complete every identity check before writing any existing artifact.
    atomic(root/"cases.json", cases)
    atomic(root/"case-readiness.json", get_content_case_report())
    if bound is not None:
        atomic(root/"authority.json",bound)
    print(json.dumps({"caseCount":len(cases),"stages":sorted({c["stageId"] for c in cases}),
                      "out":str(root),"requestsSent":0}))

def run(args):
    root = Path(args.out).resolve()
    cases=validate_cases(read(root/"cases.json"))
    ledger=None
    if args.mode=="live":
        bound=read(root/"authority.json")
        require(digest(cases)==bound["caseSetSha256"],"case_set_changed")
        current=authority(root,cases,Decimal(bound["maxCostMicrousd"])/1000000,
                          bound["maxRequests"],args.authorization_note,
                          bound.get("previousBudget", {}).get("root"))
        require(current==bound,"authority_or_code_changed")
        ledger=Ledger(root,bound)
    rows=[]; stopped=False
    stage_cases = [c for c in cases if c["stageId"] == args.stage]
    random.Random(20261006).shuffle(stage_cases)
    for index, case in enumerate(stage_cases):
        order = ["A", "B"] if index % 2 == 0 else ["B", "A"]
        for position, arm in enumerate(order, 1):
            row=measured_attempt(case,arm,mode=args.mode,directory=root/args.mode,
                                 ledger=ledger,timeout_seconds=args.timeout,order_position=position)
            rows.append(row)
            atomic(root/args.mode/(args.stage+"-summary.json"), summarize(cases,rows))
            print(json.dumps({"stage":args.stage,"caseId":case["caseId"],"arm":arm,
                              "status":row["status"],"effectiveDecisionMs":row["timings"]["effectiveDecisionMs"],
                              "restored":row["restored"]}),flush=True)
            if row["status"] in {"outcome_unknown", "budget_bound_exceeded", "blocked_prior_operation"} or row["status"]=="http_error" and row.get("httpStatus") in {400,401,403,404,429}:
                stopped=True
                break
        if stopped:
            break
    summary=summarize([c for c in cases if c["stageId"]==args.stage],rows)
    summary.update(stage=args.stage,stoppedOnProviderOrUnknown=stopped,
                   budget=ledger.summary() if ledger else None)
    atomic(root/args.mode/(args.stage+"-summary.json"),summary)
    return 2 if stopped else 0

def main():
    if sys.argv[1:]==["--worker"]:
        _worker();return 0
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest="command",required=True)
    p=commands.add_parser("prepare")
    p.add_argument("--source-root",required=True)
    p.add_argument("--out",required=True)
    p.add_argument("--max-content-cases",type=int,default=12)
    p.add_argument("--max-usd",type=Decimal)
    p.add_argument("--max-requests",type=int,default=200)
    p.add_argument("--authorization-note",default="")
    p.add_argument("--previous-run", help="Bind frozen prior ledger and carry its consumed/reserved cost")
    p.add_argument("--exclude-completed",action="store_true")
    p.add_argument("--content-only",action="store_true")
    p.add_argument("--real-rule-cases",type=int,default=0)
    r=commands.add_parser("run")
    r.add_argument("--out",required=True)
    r.add_argument("--stage",choices=[f"E{i:02d}" for i in range(1,9)],required=True)
    r.add_argument("--mode",choices=["offline","live"],default="offline")
    r.add_argument("--timeout",type=float,default=120)
    r.add_argument("--authorization-note",default="")
    args=parser.parse_args()
    try:
        require(args.command=="prepare" or 0<args.timeout<=120,"invalid_timeout")
        with run_lock(args.out):
            return (prepare(args) or 0) if args.command == "prepare" else run(args)
    except Exception:
        print(json.dumps({"status":"blocked","reasonCode":"experiment_preflight_or_integrity_failure"}))
        return 2

if __name__=="__main__":
    raise SystemExit(main())
