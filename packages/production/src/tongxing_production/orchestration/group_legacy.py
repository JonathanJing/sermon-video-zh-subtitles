"""Derive per-group stage records from an existing whole-sermon run (DEV-GRP-001).

Before the per-group pipeline writes its own records, ``plan`` needs to know what
each group already has. This module reads the products a whole-sermon run left
behind and expresses them as ``sermon-group-stage-record-v1`` records in memory:

* T and R from the Layer 2 round caches (``group-NNNN-astra``/``-sol`` with their
  policy previews; the runner identity from the payload-cache success receipt or the
  round's ``runner-identity.json``);
* P from the language plugin receipt;
* Q from the machine text QC receipt;
* S from the formal renderer's unit intents and unit receipts;
* A from the formal back-ASR unit cache and the screening receipt;
* U from the machine audio QC receipt.

It reads only; it writes nothing, calls nothing, and never upgrades a missing
observation into a pass. Where a product does not record an input (for example a
revision round without a success receipt records no runner identity), the record
says so in ``provenance.notRecorded`` instead of borrowing a current value.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from . import group_records as records

MAX_PRODUCT_BYTES = 64 * 1024 * 1024
# Prompt fields every Layer 2 group payload carries; anything else is a revision,
# repair or operator instruction and goes into revisionSha256.
BASE_PROMPT_FIELDS = {"translationGroupId", "sourceUnitIds", "englishUnits", "context", "targetLocale",
                      "terminology", "scripture", "formatting", "modelRules", "astraDraft"}
# Renderer intent fields that are assembly or batch information, not sound identity
# (design section 3; batch membership is open decision 1 and stays out of the key).
INTENT_ASSEMBLY_FIELDS = {"unitIndex", "jobJsonSha256", "jobFileSha256", "sourceJsonSha256",
                          "anchorJsonSha256", "translationPolicySha256", "candidateJsonSha256",
                          "checkpointMapFileSha256", "groupId", "sourceUnitIds", "textSha256",
                          "rendererSha256", "batchSize", "batchSeedPolicy", "batchExecutionDevice",
                          "batchImplementationSha256", "batchWindowInputsSha256", "batchWindowStart",
                          "batchWindowUnitIndices", "batchCachedUnitPolicy", "replicaCount",
                          "replicaPolicy", "replicaImplementationSha256"}
NOT_RECORDED_SHA256 = records.json_sha256({"notRecorded": "stage-implementation"})


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_json(path: Path) -> Any:
    path = Path(path)
    _require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_PRODUCT_BYTES,
             f"product_unreadable:{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# --- Inputs that both the recorded side and the current side compute the same way ---

def english_rows(anchor: dict, unit_ids: Iterable[str]) -> list[dict]:
    units = {unit["sourceUnitId"]: unit["english"] for unit in anchor["sourceUnits"]}
    return [{"sourceUnitId": unit_id, "english": units[unit_id]} for unit_id in unit_ids]


def english_units_sha256(rows: list[dict]) -> str:
    return records.json_sha256(rows)


def qc_english_sha256(rows: list[dict]) -> str:
    """The text QC's English for a group: unit English joined by single spaces."""
    return records.text_sha256(" ".join(row["english"] for row in rows))


def group_contexts(anchor: dict, plan: list[dict]) -> dict[str, dict]:
    """The Layer 2 prompt context per group: three English units before, two after."""
    rows = [{"sourceUnitId": unit["sourceUnitId"], "english": unit["english"]} for unit in anchor["sourceUnits"]]
    contexts, start = {}, 0
    for group in plan:
        end = start + len(group["sourceUnitIds"])
        contexts[group["translationGroupId"]] = {"before": copy.deepcopy(rows[max(0, start - 3):start]),
                                                 "after": copy.deepcopy(rows[end:end + 2])}
        start = end
    return contexts


ROLES = ("translator", "reviewer")


def model_facing_policy_sha256(policy: dict, role: str) -> str:
    """The frozen policy without the fields no model reads.

    Uses the same field lists as ``policy_preview.classify_policy_change``: plugin and
    term-approval fields and ``componentSha256`` change no translator or reviewer
    instruction; every other field (terminology, scripture, formatting, register
    rules, prompt versions, model settings) does. Only ``role``'s own block counts: a
    reviewer-only edit leaves translator requests unchanged (``compare_previews``).
    """
    _require(role in ROLES, f"unknown_layer2_role:{role}")
    from ..text import policy_preview
    projection = copy.deepcopy(policy)
    projection.pop("componentSha256", None)
    projection.pop(next(other for other in ROLES if other != role), None)
    for pointer in policy_preview.PLUGIN_POLICY_FIELDS | policy_preview.APPROVAL_POLICY_FIELDS:
        *parents, leaf = pointer.strip("/").split("/")
        node = projection
        for key in parents:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, dict):
            node.pop(leaf, None)
    return records.json_sha256(projection)


def model_settings_sha256(model: str, effort: str | None) -> str:
    return records.json_sha256({"model": model, "reasoningEffort": effort})


def joined_text(utterances: list[str]) -> str:
    return "".join(utterances)


def result_utterances(result: dict) -> list[str] | None:
    """A cached model result's utterances as the runner read them, or None if unusable.

    Some replies wrap each utterance with its unit ID; the runner's own reader
    unwraps those, so the same reader decides here.
    """
    from ..text import models  # the Layer 2 runner's reply reader
    try:
        return models._utterances(result.get("targetUtterances"), result.get("sourceUnitIds"))
    except (ValueError, TypeError):
        return None


def repair_position_sha256(prior_failed: dict, unit_ids: list[str]) -> str:
    return records.json_sha256({unit: int(prior_failed.get(unit, 0)) for unit in unit_ids})


def synthesis_identity_sha256(intent: dict) -> str:
    return records.json_sha256({key: value for key, value in intent.items() if key not in INTENT_ASSEMBLY_FIELDS})


# --- Layer 2: T and R from round caches ---

def _prompt(preview: dict) -> dict:
    payload = preview["payload"]
    user = [message for message in payload["messages"] if message.get("role") == "user"]
    _require(len(user) == 1, "layer2_preview_without_one_user_message")
    return json.loads(user[0]["content"])


def _role_inputs(preview: dict, cache: dict, draft_text_sha256: str | None) -> dict:
    prompt = _prompt(preview)
    payload = preview["payload"]
    extra = {key: value for key, value in prompt.items() if key not in BASE_PROMPT_FIELDS}
    inputs = {
        "boundedPayloadSha256": preview["payloadSha256"],
        "requestFingerprintSha256": cache["payloadSha256"],
        "englishUnitsSha256": english_units_sha256(prompt["englishUnits"]),
        "englishContextSha256": records.json_sha256(prompt["context"]),
        "modelFacingPolicySha256": (model_facing_policy_sha256(preview["policy"], preview.get("role"))
                                    if isinstance(preview.get("policy"), dict) and preview.get("role") in ROLES
                                    else None),
        "modelRulesSha256": records.json_sha256(prompt["modelRules"]) if "modelRules" in prompt else None,
        "revisionSha256": records.json_sha256(extra) if extra else None,
        "modelSettingsSha256": model_settings_sha256(payload["model"], payload.get("reasoning_effort")),
    }
    if draft_text_sha256 is not None:
        inputs["draftTextSha256"] = draft_text_sha256
    return inputs


def _round_group_files(root: Path) -> dict[str, dict]:
    """Group stems in one round directory with complete T and R cache evidence."""
    found = {}
    for path in sorted(Path(root).glob("group-[0-9][0-9][0-9][0-9]-sol.json")):
        stem = path.name.removesuffix("-sol.json")
        files = {"astra": root / f"{stem}-astra.json", "astraPreview": root / f"{stem}-astra.policy-preview.json",
                 "sol": path, "solPreview": root / f"{stem}-sol.policy-preview.json",
                 "success": root / f"{stem}-payload-cache-success.json"}
        if all(files[name].is_file() for name in ("astra", "astraPreview", "sol", "solPreview")):
            found[stem] = files
    return found


def _round_layer1(root: Path, locale: str) -> dict | None:
    """The source a round translated, from the request the runner froze in it."""
    request_path = Path(root) / "request.json"
    if not request_path.is_file():
        return None
    request = load_json(request_path)
    if request.get("targetLocale") != locale:
        return None
    return records.layer1_identity(request["englishSourcePackageJsonSha256"], request["anchorManifestSha256"])


def _success_binds(success: dict | None, group: dict, files: dict) -> bool:
    """Whether a payload-cache success receipt describes exactly these cache and preview files."""
    if not isinstance(success, dict):
        return False
    roles = success.get("roles") or {}
    return (success.get("translationGroupId") == group["translationGroupId"]
            and success.get("sourceUnitIds") == group["sourceUnitIds"]
            and all(isinstance(roles.get(role), dict)
                    and roles[role].get("cacheSha256") == file_sha256(files[cache])
                    and roles[role].get("previewSha256") == file_sha256(files[preview])
                    for role, cache, preview in (("translator", "astra", "astraPreview"),
                                                 ("reviewer", "sol", "solPreview"))))


def _carried_from(files: dict, source_root: Path) -> bool:
    """Whether this group's T and R caches are byte copies of the same stem in ``source_root``."""
    if not source_root.is_dir():
        return False
    for name in ("astra", "sol"):
        source = source_root / files[name].name
        if not source.is_file() or file_sha256(source) != file_sha256(files[name]):
            return False
    return True


def layer2_records(locale: str, groups: list[dict], rounds: list[Path]) -> dict[str, dict]:
    """T and R per group from the round caches, ``rounds`` ordered oldest first.

    The latest round whose reviewed text equals the candidate's text decides. When no
    round produced that text (an operator ruling or manual edit), the group's latest
    round still gives T and R, and the R output then differs from the candidate, which
    ``plan`` reports. Groups no round touched get no record.
    """
    by_group = {group["translationGroupId"]: group for group in groups}
    chosen: dict[str, tuple[Path, dict]] = {}
    latest: dict[str, tuple[Path, dict]] = {}
    for root in rounds:
        if _round_layer1(Path(root), locale) is None:
            continue  # a round without its frozen request cannot say which source it translated
        for stem, files in _round_group_files(Path(root)).items():
            sol = load_json(files["sol"])
            result = sol.get("result") or {}
            group = by_group.get(result.get("translationGroupId"))
            utterances = result_utterances(result) if group is not None else None
            # A round whose translator cache cannot be read gives this group no T or R.
            if utterances is None or result_utterances(load_json(files["astra"]).get("result") or {}) is None:
                continue
            latest[group["translationGroupId"]] = (Path(root), files)
            if joined_text(utterances) == joined_text(group["targetUtterances"]):
                chosen[group["translationGroupId"]] = (Path(root), files)
    chosen = {**latest, **chosen}
    out = {}
    for group_id, (root, files) in chosen.items():
        group = by_group[group_id]
        layer1 = _round_layer1(root, locale)
        astra, astra_preview = load_json(files["astra"]), load_json(files["astraPreview"])
        sol, sol_preview = load_json(files["sol"]), load_json(files["solPreview"])
        success = load_json(files["success"]) if files["success"].is_file() else None
        runner = success.get("runnerImplementationSha256") if _success_binds(success, group, files) else None
        round_runner = Path(root) / "runner-identity.json"
        if runner is None and round_runner.is_file():
            # Rounds record their runner since sermon-layer2-round-runner-identity-v1. A group
            # carried byte for byte from the round's reuse source keeps that source's runner,
            # which may be unrecorded (None).
            recorded = load_json(round_runner)
            if recorded.get("schemaVersion") == "sermon-layer2-round-runner-identity-v1":
                runner = recorded.get("runnerImplementationSha256")
                carry = recorded.get("carrySource")
                if isinstance(carry, dict) and _carried_from(files, Path(carry.get("root", ""))):
                    runner = carry.get("runnerImplementationSha256")
        provenance = {"derivation": "legacy_round_cache", "round": str(root), "stem": files["sol"].name[:10],
                      "notRecorded": [] if runner else ["stageImplementation"]}
        implementation = runner or NOT_RECORDED_SHA256
        draft_sha = records.text_sha256(joined_text(result_utterances(astra["result"])))
        prompt_draft = _prompt(sol_preview).get("astraDraft")
        draft_utterances = result_utterances(prompt_draft) if isinstance(prompt_draft, dict) else None
        reviewed_draft = records.text_sha256(joined_text(draft_utterances)) if draft_utterances else None
        translator = records.make_record(
            "T", layer1, locale, group_id, group["sourceUnitIds"],
            _role_inputs(astra_preview, astra, None), implementation,
            {"draftTextSha256": draft_sha, "cacheSha256": file_sha256(files["astra"])}, "pass",
            spend={"kind": "paid_model_call", "model": astra.get("model"), "requestId": astra.get("requestId")},
            provenance=provenance)
        semantic = (sol.get("result") or {}).get("semanticReview") or {}
        # The runner's own acceptance: a pass status, every check passing, no uncertainty or issue.
        status = ("pass" if semantic.get("status") == "pass" and not semantic.get("uncertainty")
                  and not semantic.get("issues") and isinstance(semantic.get("checks"), dict)
                  and semantic["checks"] and all(value == "pass" for value in semantic["checks"].values())
                  else "fail")
        codes = [] if status == "pass" else [f"semantic_{semantic.get('status')}"]
        reviewer = records.make_record(
            "R", layer1, locale, group_id, group["sourceUnitIds"],
            _role_inputs(sol_preview, sol, reviewed_draft), implementation,
            {"targetTextSha256": records.text_sha256(joined_text(result_utterances(sol["result"]) or [])),
             "cacheSha256": file_sha256(files["sol"])}, status, codes=codes,
            spend={"kind": "paid_model_call", "model": sol.get("model"), "requestId": sol.get("requestId")},
            provenance=provenance)
        out[group_id] = {"T": translator, "R": reviewer}
    return out


# --- P from the plugin receipt ---

def plugin_records(layer1: dict, locale: str, anchor: dict, receipt: dict) -> dict[str, dict]:
    _require(receipt.get("schemaVersion") == "sermon-target-language-plugin-receipt-v1"
             and receipt.get("targetLocale") == locale, "invalid_plugin_receipt")
    receipt_layer1 = records.layer1_identity(receipt["englishSourcePackageJsonSha256"], receipt["anchorManifestSha256"])
    english_known = receipt_layer1 == layer1
    out = {}
    for row in receipt["groupReviews"]:
        failed = [check["checkId"] for check in row["checks"] if check["status"] != "pass"]
        inputs = {"languageReviewPolicySha256": receipt["languageReviewPolicySha256"],
                  # The English the plugin read is fixed by the receipt's Layer 1 identity;
                  # it is computed here only when that identity is the one supplied.
                  "englishUnitsSha256": (english_units_sha256(english_rows(anchor, row["sourceUnitIds"]))
                                         if english_known else None),
                  "targetTextSha256": row["targetTextSha256"]}
        out[row["translationGroupId"]] = records.make_record(
            "P", receipt_layer1, locale, row["translationGroupId"], row["sourceUnitIds"], inputs,
            receipt["pluginImplementationSha256"], {}, "pass" if row["status"] == "pass" else "fail",
            codes=failed, provenance={"derivation": "legacy_plugin_receipt", "pluginId": receipt.get("pluginId"),
                                      "notRecorded": [] if english_known else ["englishUnitsSha256"]})
    return out


# --- Q from the text QC receipt ---

def text_qc_records(locale: str, receipt: dict) -> dict[str, dict]:
    _require(receipt.get("schemaVersion") == "sermon-target-text-auto-qc-v1" and receipt.get("locale") == locale,
             "invalid_text_qc_receipt")
    context = receipt["semanticIdentity"]["settings"]["qcContext"]
    layer1 = records.layer1_identity(context["englishSourcePackageJsonSha256"], context["anchorManifestJsonSha256"])
    prior = (receipt.get("repairLedger") or {}).get("priorFailedAttempts") or {}
    out = {}
    for row in receipt["results"]:
        status = "pass" if row["status"] == "pass" else "fail"
        problems = [problem if isinstance(problem, str) else json.dumps(problem, sort_keys=True)
                    for problem in row.get("problems") or []]
        out[row["groupId"]] = records.make_record(
            "Q", layer1, locale, row["groupId"], row["sourceUnitIds"],
            {"englishSha256": row["englishSha256"], "targetTextSha256": row["targetTextSha256"],
             "semanticIdentitySha256": receipt["semanticIdentitySha256"],
             "repairPositionSha256": repair_position_sha256(prior, row["sourceUnitIds"])},
            receipt["implementationSha256"],
            {"backTranslationRequestsSha256": records.json_sha256(
                (row.get("backTranslation") or {}).get("requestSha256s") or [])},
            status, codes=(problems or [row.get("nextAction", "fail")]) if status == "fail" else (),
            provenance={"derivation": "legacy_text_qc_receipt", "mode": row.get("mode"),
                        "nextAction": row.get("nextAction"), "failedAttempts": row.get("failedAttempts"),
                        "model": receipt["semanticIdentity"].get("model")})
    return out


# --- S and A from the formal speech job directory ---

def speech_records(locale: str, speech_job: Path, screening: dict | None) -> dict[str, dict]:
    receipts = Path(speech_job) / "receipts"
    screened = {}
    if screening is not None:
        _require(screening.get("schemaVersion") == "sermon-target-language-audio-screening-v2"
                 and screening.get("targetLocale") == locale, "invalid_audio_screening_receipt")
        screened = {row["textGroupId"]: row for row in screening["results"]}
    asr_dirs = sorted(Path(speech_job).glob("asr-unit-cache-*"))
    out = {}
    for intent_path in sorted(receipts.glob("unit-[0-9][0-9][0-9][0-9].intent.json")):
        stem = intent_path.name.removesuffix(".intent.json")
        unit_path = receipts / f"{stem}.json"
        if not unit_path.is_file():
            continue  # an intent without a completed unit receipt is not a result
        intent, unit = load_json(intent_path), load_json(unit_path)
        _require(intent.get("targetLocale") == locale, f"speech_intent_locale_mismatch:{stem}")
        # The unit receipt must be the result of this very intent, and its bytes must still be there.
        audio_path = Path(speech_job) / str(unit.get("audioRelativePath", ""))
        if (unit.get("translationGroupId") != intent.get("groupId")
                or unit.get("targetTextSha256") != intent.get("textSha256")
                or unit.get("targetLocale") != locale or unit.get("unitIndex") != intent.get("unitIndex")
                or unit.get("jobJsonSha256") != intent.get("jobJsonSha256")
                or unit.get("sourceUnitIds") != intent.get("sourceUnitIds")
                or not audio_path.resolve().is_relative_to(Path(speech_job).resolve())
                or not audio_path.is_file() or file_sha256(audio_path) != unit.get("audioSha256")):
            continue
        layer1 = records.layer1_identity(intent["sourceJsonSha256"], intent["anchorJsonSha256"])
        group_id = intent["groupId"]
        audio = unit["audioSha256"]
        batch = {key: intent.get(key) for key in ("batchWindowStart", "batchWindowUnitIndices",
                                                  "batchWindowInputsSha256", "batchSeedPolicy")}
        stages = {"S": records.make_record(
            "S", layer1, locale, group_id, intent["sourceUnitIds"],
            {"textSha256": intent["textSha256"], "synthesisIdentitySha256": synthesis_identity_sha256(intent)},
            intent["rendererSha256"], {"audioSha256": audio},
            "pass" if unit.get("fullDecode") == "pass" else "fail",
            codes=() if unit.get("fullDecode") == "pass" else ["full_decode_failed"],
            spend={"kind": "local_tts"},
            provenance={"derivation": "legacy_formal_render", "unitIndex": intent.get("unitIndex"),
                        "jobJsonSha256": intent.get("jobJsonSha256"), "batch": batch,
                        "speechJob": str(speech_job)})}
        cached = next((load_json(directory / f"{stem}.json") for directory in reversed(asr_dirs)
                       if (directory / f"{stem}.json").is_file()), None)
        row = screened.get(group_id)
        # A verdict counts only when the screening receipt measured this job's audio and text.
        bound = (screening is not None and row is not None
                 and screening.get("targetLanguageSpeechJobJsonSha256") == intent.get("jobJsonSha256")
                 and row.get("audioSha256") == audio and row.get("targetTextSha256") == intent["textSha256"])
        if (cached is not None and cached["identity"].get("audioSha256") == audio and bound
                and records._is_sha(cached.get("recognizedSha256"))):
            identity = cached["identity"]
            verdict = "pass" if row.get("status") == "pass" else "fail"
            stages["A"] = records.make_record(
                "A", layer1, locale, group_id, intent["sourceUnitIds"],
                {"audioSha256": audio, "targetTextSha256": identity["targetTextSha256"],
                 "asrSettingsSha256": screening["asrSettingsSha256"]},
                identity["implementationSha256"], {"recognizedSha256": cached.get("recognizedSha256")}, verdict,
                codes=[f"asr_{row.get('status')}"] if verdict == "fail" else (), spend={"kind": "local_asr"},
                provenance={"derivation": "legacy_formal_back_asr", "similarity": row.get("similarity")})
        out[group_id] = stages
    return out


# --- U from the audio QC receipt ---

def audio_qc_records(locale: str, receipt: dict, speech: dict[str, dict]) -> dict[str, dict]:
    """U per group, only where the receipt measured the speech job ``speech`` came from.

    The receipt binds the speech job, not the source package, so each record takes its
    Layer 1 identity and source units from that job's S record; rows for another job,
    other units or other audio get no record.
    """
    _require(receipt.get("schemaVersion") == "sermon-target-audio-auto-qc-v1" and receipt.get("locale") == locale,
             "invalid_audio_qc_receipt")
    prior = (receipt.get("repairLedger") or {}).get("priorFailedAttempts") or {}
    thresholds = records.json_sha256(receipt["thresholds"])
    job = (receipt.get("durationNormalization") or {}).get("speechJobJsonSha256")
    out = {}
    for row in receipt["results"]:
        synthesis = (speech.get(row["groupId"]) or {}).get("S")
        if (synthesis is None or job is None or job != synthesis["provenance"].get("jobJsonSha256")
                or row["sourceUnitIds"] != synthesis["sourceUnitIds"]
                or row["audioSha256"] != synthesis["outputs"]["audioSha256"]):
            continue
        status = row["status"]
        verdict = "pass" if status == "pass" else ("fail" if status == "fail" else "unknown")
        out[row["groupId"]] = records.make_record(
            "U", synthesis["layer1"], locale, row["groupId"], row["sourceUnitIds"],
            {"audioSha256": row["audioSha256"], "textSha256": row["textSha256"],
             "sourceSecondsSha256": records.json_sha256(float(row["sourceSeconds"])),
             "thresholdsSha256": thresholds,
             "repairPositionSha256": repair_position_sha256(prior, row["sourceUnitIds"])},
            receipt["implementationSha256"], {}, verdict,
            codes=list(row.get("issues") or []) if verdict == "fail" else (),
            provenance={"derivation": "legacy_audio_qc_receipt", "layer1": "from_speech_job",
                        "speechJobJsonSha256": job, "status": status})
    return out
