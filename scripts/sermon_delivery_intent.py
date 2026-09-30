#!/usr/bin/env python3
"""Private DEV-WEEK-001 intent and OFFLINE duration preflight (never a release gate).

API: freeze_intent(request, weekly_plan=None), validate_intent(manifest), and
preflight(manifest, measurements=None, weekly_plan=None). All accept JSON objects;
only the CLI reads explicitly supplied local files and writes a new private file.
The optional weekly_plan is existing prepare_multilingual_weekly_plan output. We
bind its canonical JSON hash, source and locales without dispatching/replanning.

v1 hashes use UTF-8 JSON, sorted object keys, compact separators, no NaN/Infinity,
and unescaped Unicode. Locale arrays are sorted when freezing. Number spelling
(1 versus 1.0) is significant. No timestamps or local paths enter identities.
Schema/semantics changes require a new version; v1 and legacy planners stay intact.

Approval references and decoded-audio measurements are supplied claims, not
approvals granted or independently verified here. Receipt adapters, complete
decode, local alignment, producer admission, release integration, HTTP, devices
and venue acceptance remain the responsibility of their existing owners.

Integration contract:
* The bundled schema's $defs/request and $defs/measurements validate inputs.
  python scripts/sermon_delivery_intent.py freeze --request request.json
      --weekly-plan existing-plan.json --out new-private-intent.json
  python scripts/sermon_delivery_intent.py preflight --intent intent.json
      --measurements measurements.json --weekly-plan existing-plan.json
      --out new-private-report.json
* A measurement binds intentSha256 plus canonical_hash(request['source']), locale,
  candidate/review identities, decoded-audio hash, measurement receipt and natural
  rate policy. A full-text overrun requires a separately approved AND measured
  short script. Null identities and absent measurements remain unknown. This is
  an aggregate duration comparison, not a local timing/synchronization proof.
* Exit codes: 0 frozen/offline pass, 1 malformed input or output conflict,
  2 unknown, 3 duration overrun. Unknown/fail still write the private report.
* Dependencies: Python 3.10+, jsonschema (already used by existing producers),
  bundled private schema and optional existing weekly-plan schema. No model,
  media, network, controller, ledger, job or release integration is invoked.
* Existing release-plan integration must consume the frozen hash, revalidate
  actual referenced receipts/packages with the existing gates, and collect every
  required acceptance row separately. An offline pass never authorizes release.
"""
from __future__ import annotations

import argparse
import copy
from decimal import Decimal, localcontext
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator


SCHEMA_VERSION = "private-sermon-delivery-intent-v1"
REQUEST_VERSION = "private-sermon-delivery-intent-request-v1"
MEASUREMENTS_VERSION = "private-sermon-delivery-measurements-v1"
REPORT_VERSION = "private-sermon-delivery-preflight-v1"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / (SCHEMA_VERSION + ".schema.json")


class IntentError(ValueError):
    """Invalid private input; messages deliberately exclude paths/input values."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise IntentError(message)


def _json_value(value: Any) -> None:
    if value is None or type(value) in (str, bool, int):
        if type(value) is str:
            try:
                value.encode("utf-8")
            except UnicodeError as exc:
                raise IntentError("JSON contains invalid Unicode") from exc
        return
    if type(value) is float:
        require(math.isfinite(value), "JSON requires finite numbers")
        return
    if type(value) is list:
        for item in value:
            _json_value(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            require(type(key) is str, "JSON object keys must be strings")
            _json_value(key)
            _json_value(item)
        return
    raise IntentError("Expected JSON values only")


def canonical_hash(value: Any) -> str:
    """Canonical JSON SHA-256, distinct from SHA-256 of file bytes."""
    _json_value(value)
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, RecursionError) as exc:
        raise IntentError("Cannot canonicalize JSON") from exc
    return hashlib.sha256(raw).hexdigest()


def _pairs(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise IntentError("JSON requires finite numbers")


def read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_constant)
        _json_value(value)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise IntentError("Cannot read strict JSON object") from exc
    require(type(value) is dict, "Expected JSON object")
    return value


@lru_cache(maxsize=1)
def _schema() -> dict:
    return read_object(SCHEMA_PATH)


def _validate(value: Any, definition: str | None = None) -> None:
    _json_value(value)
    schema = _schema()
    if definition:
        schema = {"$ref": f"#/$defs/{definition}", "$defs": schema["$defs"]}
    # Bundled schema contains only local references; no network resolver is used.
    require(next(Draft202012Validator(schema).iter_errors(value), None) is None,
            "Input does not match private delivery schema")


def acceptance_matrix(request: dict) -> list[dict]:
    """Required evidence to collect later; no row is approved by this module."""
    rows = []

    def add(check: str, locale: str | None = None) -> None:
        rows.append({"checkId": f"{locale or 'shared'}:{check}",
                     "targetLocale": locale, "evidenceRequired": True})

    for check in ("source_window_approval", "full_video_asset", "http_assets_and_range",
                  "web_app_refresh_and_entry", "ios_installed_app_refresh_and_entry",
                  "final_qr_decode_and_target"):
        add(check)
    if request["venueAcceptanceRequired"]:
        add("venue_acceptance")
    for target in request["requestedLocales"]:
        locale = target["targetLocale"]
        for check in ("approved_full_text", "page_and_english_reference",
                      "web_content_and_locale", "ios_content_and_locale"):
            add(check, locale)
        if target["audioRequirement"] == "required":
            for check in ("approved_spoken_text", "same_locale_layer3_binding",
                          "complete_audio_decode_and_screening", "full_listening_review",
                          "one_x_video_synchronization", "web_audio_playback",
                          "ios_audio_playback"):
                add(check, locale)
        else:
            for check in ("same_locale_layer3_audio_unavailable",
                          "web_text_only_compatibility", "ios_text_only_compatibility"):
                add(check, locale)
    return rows


def _validate_request(request: dict) -> None:
    _validate(request, "request")
    source = request["source"]
    window = source["window"]
    require(window["endSeconds"] > window["startSeconds"], "Source window is empty or reversed")
    if source["mediaDurationSeconds"] is not None:
        require(window["endSeconds"] <= source["mediaDurationSeconds"],
                "Source window exceeds supplied media duration")
    locales = [target["targetLocale"] for target in request["requestedLocales"]]
    require(len(set(locales)) == len(locales), "Duplicate requested locale")
    delivery = request["delivery"]
    root = delivery["appRootUrl"]
    try:
        parsed = urlsplit(root)
        valid_root = (parsed.scheme == "https" and parsed.hostname
                      and parsed.username is None and parsed.password is None
                      and parsed.path == "/" and not parsed.query and not parsed.fragment
                      and parsed.port in (None, 443))
    except ValueError as exc:
        raise IntentError("Invalid App root URL") from exc
    require(bool(valid_root) and root.isascii()
            and all(ord(char) > 32 for char in root) and "\\" not in root
            and "%" not in root, "Expected an HTTPS App root URL")
    expected = f"{root}?week={request['pageId']}"
    require(delivery["webAppEntryUrl"] == expected and delivery["qrTargetUrl"] == expected,
            "App entry and QR target must identify the same week at the App root")
    require(delivery["iosPageId"] == request["pageId"], "iOS entry must identify the same page")
    for target in request["requestedLocales"]:
        full = target["approvedFullText"]
        spoken = target["approvedSpokenText"]
        unavailable = target["layer3AudioUnavailable"]
        if target["audioRequirement"] == "required":
            require(unavailable is None, "Required audio cannot be downgraded to text-only")
            if spoken is not None:
                require(full is not None, "Spoken text needs its full-text identity")
                if spoken["kind"] == "full_text":
                    require({key: spoken[key] for key in full} == full,
                            "Full spoken text must match the full-text approval identity")
                else:
                    require(spoken["candidateJsonSha256"] != full["candidateJsonSha256"]
                            and spoken["humanReviewReceiptJsonSha256"] != full["humanReviewReceiptJsonSha256"],
                            "Short script needs a separate candidate and review identity")
        else:
            require(spoken is None, "Text-only intent cannot advertise spoken text")
            if unavailable is not None:
                require(full is not None
                        and unavailable["targetLocale"] == target["targetLocale"]
                        and unavailable["englishSourcePackageJsonSha256"] == source["englishSourcePackageJsonSha256"]
                        and unavailable["targetLanguageCandidateJsonSha256"] == full["candidateJsonSha256"],
                        "Text-only Layer 3 identity differs from source, locale or full text")


def _plan_binding(plan: dict, request: dict) -> dict:
    _json_value(plan)
    # Validate the existing output contract without changing it or importing its producer.
    legacy_schema = read_object(SCHEMA_PATH.parent / "sermon-multilingual-weekly-plan-v1.schema.json")
    require(next(Draft202012Validator(legacy_schema).iter_errors(plan), None) is None,
            "Unsupported or invalid existing weekly plan")
    require(plan["englishSourcePackage"]["jsonSha256"] == request["source"]["englishSourcePackageJsonSha256"]
            and plan["englishSourcePackage"]["downstreamInvalidationKey"] == request["source"]["downstreamInvalidationKey"],
            "Existing weekly plan source identity differs")
    locales = [lane["targetLocale"] for lane in plan["lanes"]]
    require(len(locales) == len(set(locales))
            and set(locales) == {target["targetLocale"] for target in request["requestedLocales"]},
            "Existing weekly plan locales differ")
    return {"planId": plan["planId"], "jsonSha256": canonical_hash(plan)}


def freeze_intent(request: dict, weekly_plan: dict | None = None) -> dict:
    """Freeze a new identity without mutating inputs or granting any approval."""
    _validate_request(request)
    request = copy.deepcopy(request)
    request["requestedLocales"].sort(key=lambda item: item["targetLocale"])
    if weekly_plan is not None:
        binding = _plan_binding(weekly_plan, request)
        require(request["weeklyPlanBinding"] in (None, binding), "Existing weekly plan binding differs")
        request["weeklyPlanBinding"] = binding
    payload = {"schemaVersion": SCHEMA_VERSION, "visibility": "private",
               "request": request, "acceptanceMatrix": acceptance_matrix(request)}
    digest = canonical_hash(payload)
    manifest = {**payload, "intentId": f"delivery-intent-{digest}", "intentSha256": digest}
    _validate(manifest)
    return manifest


def validate_intent(manifest: dict) -> None:
    _validate(manifest)
    expected = freeze_intent(manifest["request"])
    require(manifest == expected, "Frozen intent hash, order or acceptance matrix differs")


def _measurement_map(bundle: dict | None, manifest: dict) -> dict:
    if bundle is None:
        return {}
    _validate(bundle, "measurements")
    require(bundle["intentSha256"] == manifest["intentSha256"], "Measurements belong to a different intent")
    result = {}
    request = manifest["request"]
    targets = {target["targetLocale"]: target for target in request["requestedLocales"]}
    for item in bundle["measurements"]:
        key = (item["targetLocale"], item["kind"])
        require(key not in result, "Duplicate duration measurement")
        require(key[0] in targets, "Measurement has an unrequested locale")
        target = targets[key[0]]
        require(target["audioRequirement"] == "required", "Text-only intent cannot consume audio measurements")
        identity = target["approvedFullText"] if key[1] == "full_text" else target["approvedSpokenText"]
        require(identity is not None and (key[1] == "full_text" or identity["kind"] == "short_script"),
                "Measurement has no matching supplied approved text identity")
        require(item["candidateJsonSha256"] == identity["candidateJsonSha256"]
                and item["humanReviewReceiptJsonSha256"] == identity["humanReviewReceiptJsonSha256"]
                and item["sourceBindingSha256"] == canonical_hash(request["source"]),
                "Duration measurement identity differs")
        result[key] = item
    return result


def preflight(manifest: dict, measurements: dict | None = None,
              weekly_plan: dict | None = None) -> dict:
    """Compare supplied measurements only; never infer duration from text or run TTS."""
    validate_intent(manifest)
    request = manifest["request"]
    supplied = _measurement_map(measurements, manifest)
    plan_status = "not_bound"
    if weekly_plan is not None:
        require(request["weeklyPlanBinding"] == _plan_binding(weekly_plan, request),
                "Supplied weekly plan is not the frozen binding")
        plan_status = "binding_matches"
    elif request["weeklyPlanBinding"] is not None:
        plan_status = "unknown"
    window = request["source"]["window"]
    # Use an explicit context so a caller's Decimal settings cannot alter the result.
    with localcontext() as context:
        context.prec = 400
        available = Decimal(str(window["endSeconds"])) - Decimal(str(window["startSeconds"]))
    rows = []

    def duration(locale: str, kind: str, identity: dict | None) -> dict:
        item = supplied.get((locale, kind))
        if identity is None or item is None:
            return {"status": "unknown", "reason": "missing_approved_identity_or_measurement",
                    "measuredDurationSeconds": None, "overrunSeconds": None}
        measured = Decimal(str(item["measuredDurationSeconds"]))
        with localcontext() as context:
            context.prec = 400
            overrun = float(max(Decimal(0), measured - available))
        return {"status": "fits" if measured <= available else "overrun",
                "reason": "supplied_decoded_audio_measurement",
                "measuredDurationSeconds": item["measuredDurationSeconds"],
                "overrunSeconds": overrun,
                "audioSha256": item["audioSha256"],
                "measurementReceiptJsonSha256": item["measurementReceiptJsonSha256"]}

    for target in request["requestedLocales"]:
        locale = target["targetLocale"]
        if target["audioRequirement"] == "text_only":
            status = "pass" if target["layer3AudioUnavailable"] is not None else "unknown"
            row = {"targetLocale": locale, "audioRequirement": "text_only", "status": status,
                   "duration": {"status": "not_applicable"},
                   "nextAction": "collect_text_only_client_evidence" if status == "pass" else "supply_same_locale_layer3_audio_unavailable"}
        else:
            full = duration(locale, "full_text", target["approvedFullText"])
            spoken_identity = target["approvedSpokenText"]
            spoken = (duration(locale, spoken_identity["kind"], spoken_identity)
                      if spoken_identity else duration(locale, "full_text", None))
            if spoken["status"] == "overrun":
                status, action = "fail", "prepare_separately_reviewed_short_script_or_revise_it"
            elif "unknown" in (full["status"], spoken["status"]):
                status, action = "unknown", "supply_approved_identities_and_decoded_audio_measurements"
            else:
                status, action = "pass", "continue_existing_layer3_gates"
            row = {"targetLocale": locale, "audioRequirement": "required", "status": status,
                   "fullTextDuration": full, "spokenDuration": spoken, "nextAction": action}
        rows.append(row)
    source_unknown = (window["approvalReceiptJsonSha256"] is None
                      or request["source"]["mediaDurationSeconds"] is None)
    statuses = {row["status"] for row in rows}
    offline_status = ("fail" if "fail" in statuses else "unknown"
                      if "unknown" in statuses or source_unknown or plan_status == "unknown" else "pass")
    return {"schemaVersion": REPORT_VERSION, "visibility": "private", "executionMode": "offline",
            "intentId": manifest["intentId"], "intentSha256": manifest["intentSha256"],
            "measurementsJsonSha256": canonical_hash(measurements) if measurements is not None else None,
            "evidenceAuthority": "supplied_identity_references_and_measurements_only",
            "offlineStatus": offline_status, "sourceStatus": "unknown" if source_unknown else "supplied_bindings_present",
            "weeklyPlanStatus": plan_status, "availableWindowSeconds": float(available),
            "locales": rows,
            "acceptanceMatrix": [{**row, "status": "not_run", "receiptJsonSha256": None}
                                 for row in manifest["acceptanceMatrix"]],
            "humanApproval": False, "productionEligible": False, "publicationAuthorized": False}


def write_new(path: Path, value: dict) -> None:
    raw = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(raw)
    except OSError as exc:
        raise IntentError("Cannot create new private output; existing files are never overwritten") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze", help="Freeze a private delivery request")
    freeze.add_argument("--request", type=Path, required=True)
    check = commands.add_parser("preflight", help="Report from supplied offline measurements only")
    check.add_argument("--intent", type=Path, required=True)
    check.add_argument("--measurements", type=Path)
    for command in (freeze, check):
        command.add_argument("--weekly-plan", type=Path)
        command.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan = read_object(args.weekly_plan) if args.weekly_plan else None
        if args.command == "freeze":
            output = freeze_intent(read_object(args.request), plan)
            code = 0
        else:
            output = preflight(read_object(args.intent),
                               read_object(args.measurements) if args.measurements else None, plan)
            code = {"pass": 0, "unknown": 2, "fail": 3}[output["offlineStatus"]]
        write_new(args.out, output)
        print(json.dumps({"intentId": output["intentId"], "result": output.get("offlineStatus", "frozen")}))
        return code
    except (IntentError, RecursionError) as exc:
        print(str(exc) if isinstance(exc, IntentError) else "JSON nesting is too deep", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
