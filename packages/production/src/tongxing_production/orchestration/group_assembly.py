"""Assemble a Layer 2 candidate from per-group records (DEV-GRP-002, merge steps 1 and 2).

docs/design/per-group-independent-pipeline.zh.md section 5: the merge checks that every
group has a current terminal record for T, R and P, rebuilds the evidence the whole-sermon
path would hand to ``admit_evidence`` from those records, and calls that function
unchanged. Admission (coverage and order, distinct request IDs, schema, the fresh plugin
run) stays in ``text.candidate``; nothing here re-implements it.

A record names its bytes by hash; the bytes live in a ``PayloadStore`` beside the
records. An R record that passes names its reviewed evidence row (``evidenceRowSha256``);
a P record names its plugin group review (``groupReviewSha256``). Payloads are hashed
over their order-preserving compact JSON, because the candidate keeps each row's key
order: the assembled candidate must equal the whole-sermon one byte for byte.

Records read from a whole-sermon run's products (``provenance.derivation`` starting
``legacy_``) are planning estimates only and are refused here; so are records whose
verdict is not a pass, and stages with no record or more than one passing record.
The assembler makes no model call and writes nothing but what its caller saves.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from . import group_records as records


ASSEMBLY_SCHEMA = "sermon-group-candidate-assembly-v1"
PAYLOAD_DIRECTORY = "_payloads"
# The evidence row the runner writes per group, in its key order.
EVIDENCE_ROW_KEYS = ("translationGroupId", "sourceUnitIds", "targetUtterances", "coverage",
                     "semanticReview", "translatorRequestId", "reviewerRequestId")
ASSEMBLED_STAGES = ("T", "R", "P")
# Records written for the whole-path equivalence check (``equivalence_records``) are
# accepted only when the caller asks for that check; they never feed a production merge.
EQUIVALENCE_DERIVATION = "whole_path_equivalence_check"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


class AssemblyRefused(ValueError):
    """Groups that are not ready, by reason; no candidate is produced."""

    def __init__(self, reasons: dict[str, list[str]]):
        self.reasons = {reason: sorted(groups) for reason, groups in sorted(reasons.items()) if groups}
        super().__init__("group_assembly_refused:" + ";".join(
            f"{reason}={len(groups)}" for reason, groups in self.reasons.items()))


def payload_bytes(value: Any) -> bytes:
    """Compact JSON that keeps key order, so a rebuilt row has the original's bytes."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def payload_sha256(value: Any) -> str:
    return hashlib.sha256(payload_bytes(value)).hexdigest()


class PayloadStore:
    """Append-only, content-addressed payloads next to a ``RecordStore``."""

    def __init__(self, root: Path):
        self.root = Path(root) / PAYLOAD_DIRECTORY

    def path(self, sha256: str) -> Path:
        _require(records._is_sha(sha256), "invalid_payload_sha256")
        return self.root / sha256[:2] / f"{sha256}.json"

    def put(self, value: Any) -> str:
        data = payload_bytes(value)
        _require(len(data) <= records.MAX_RECORD_BYTES, "payload_too_large")
        sha = hashlib.sha256(data).hexdigest()
        path = self.path(sha)
        if path.exists():
            _require(path.read_bytes() == data, "payload_bytes_differ_from_their_hash")
            return sha
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{os.urandom(4).hex()}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                _require(path.read_bytes() == data, "payload_bytes_differ_from_their_hash")
        finally:
            temporary.unlink(missing_ok=True)
        return sha

    def get(self, sha256: str) -> Any:
        path = self.path(sha256)
        _require(path.is_file() and not path.is_symlink(), f"payload_missing:{sha256}")
        data = path.read_bytes()
        _require(hashlib.sha256(data).hexdigest() == sha256, f"payload_changed:{sha256}")
        return json.loads(data.decode("utf-8"))


def evidence_row(row: dict) -> dict:
    """The row exactly as the runner writes it; any other shape is refused."""
    _require(isinstance(row, dict) and tuple(row) == EVIDENCE_ROW_KEYS, "evidence_row_shape")
    return row


def reviewed_outputs(row: dict, payloads: PayloadStore) -> dict:
    """R outputs for a reviewed row: the joined target text and the stored row."""
    evidence_row(row)
    return {"targetTextSha256": records.text_sha256("".join(row["targetUtterances"])),
            "evidenceRowSha256": payloads.put(row)}


def plugin_outputs(group_review: dict, payloads: PayloadStore) -> dict:
    """P outputs for one group's plugin review."""
    _require(isinstance(group_review, dict), "invalid_group_review")
    return {"groupReviewSha256": payloads.put(group_review)}


def _usable(record: dict, layer1: dict, locale: str, unit_ids: list[str], equivalence_check: bool) -> str | None:
    derivation = str(record["provenance"].get("derivation", ""))
    if derivation.startswith("legacy_"):
        return "legacy_planning_only"
    if derivation == EQUIVALENCE_DERIVATION and not equivalence_check:
        return "equivalence_record_outside_check"
    if record["layer1"] != layer1 or record["targetLocale"] != locale or record["sourceUnitIds"] != unit_ids:
        return "other_identity"
    return None


def select(store: records.RecordStore, layer1: dict, locale: str, plan: list[dict], *,
           plugin_implementation_sha256: str, language_review_policy_sha256: str,
           equivalence_check: bool = False) -> dict[str, dict[str, dict]]:
    """One passing T, R and P record per group, chained R to T and P to R.

    Raises ``AssemblyRefused`` naming every group that has no usable record, only a
    failed, stopped or unknown one, or more than one candidate for a stage.
    """
    reasons: dict[str, list[str]] = {}
    chosen: dict[str, dict[str, dict]] = {}

    def refuse(reason: str, group_id: str) -> None:
        reasons.setdefault(reason, []).append(group_id)

    for group in plan:
        group_id, unit_ids = group["translationGroupId"], group["sourceUnitIds"]
        found = {stage: store.records(locale, group_id, stage) for stage in ASSEMBLED_STAGES}
        usable = {}
        for stage, rows in found.items():
            kept = []
            for record in rows:
                problem = _usable(record, layer1, locale, unit_ids, equivalence_check)
                if problem is None:
                    kept.append(record)
                elif problem != "other_identity":
                    refuse(f"{stage}:{problem}", group_id)
            usable[stage] = kept
        if any(record["verdict"]["status"] == "unknown" for rows in usable.values() for record in rows):
            refuse("unknown_outcome_needs_reconciliation", group_id)
            continue
        reviewed = [record for record in usable["R"] if record["verdict"]["status"] == "pass"
                    and records._is_sha(record["outputs"].get("evidenceRowSha256"))]
        if len(reviewed) != 1:
            refuse("R:" + ("missing_or_not_passed" if not reviewed else "conflict"), group_id)
            continue
        review = reviewed[0]
        draft = review["inputs"].get("draftTextSha256")
        drafts = [record for record in usable["T"] if record["verdict"]["status"] == "pass"
                  and (draft is None or record["outputs"].get("draftTextSha256") == draft)]
        if len(drafts) != 1:
            refuse("T:" + ("missing_or_not_passed" if not drafts else "conflict"), group_id)
            continue
        target = review["outputs"]["targetTextSha256"]
        plugins = [record for record in usable["P"]
                   if record["stageImplementationSha256"] == plugin_implementation_sha256
                   and record["inputs"].get("languageReviewPolicySha256") == language_review_policy_sha256
                   and record["inputs"].get("targetTextSha256") == target]
        passed = [record for record in plugins if record["verdict"]["status"] == "pass"
                  and records._is_sha(record["outputs"].get("groupReviewSha256"))]
        if len(passed) != 1:
            refuse("P:" + ("conflict" if len(passed) > 1 else
                           "failed" if plugins else "missing_for_current_plugin_and_text"), group_id)
            continue
        chosen[group_id] = {"T": drafts[0], "R": review, "P": passed[0]}
    if reasons:
        raise AssemblyRefused(reasons)
    return chosen


def assemble(source: dict, anchor: dict, policy: dict, request: dict, rule_receipt: dict | None,
             plugin_path: Path, store: records.RecordStore, payloads: PayloadStore, *,
             equivalence_check: bool = False) -> dict[str, Any]:
    """Evidence, plugin receipt and candidate from the records, plus a manifest of what was used."""
    from ..text import candidate as producer
    from ..text import models
    from ..text import policy as policy_tools
    layer1 = records.layer1_identity(request["englishSourcePackageJsonSha256"], request["anchorManifestSha256"])
    locale = request["targetLocale"]
    plan = models.group_plan(request, anchor)
    plugin_sha = policy["languageReview"]["pluginImplementationSha256"]
    # The identity the plugin receipt itself carries for this policy.
    review_policy_sha = policy_tools.validate_policy(policy)["languageReviewPolicySha256"]
    chosen = select(store, layer1, locale, plan, plugin_implementation_sha256=plugin_sha,
                    language_review_policy_sha256=review_policy_sha, equivalence_check=equivalence_check)
    rows = []
    for group in plan:
        review = chosen[group["translationGroupId"]]["R"]
        row = evidence_row(payloads.get(review["outputs"]["evidenceRowSha256"]))
        _require(row["translationGroupId"] == group["translationGroupId"]
                 and row["sourceUnitIds"] == group["sourceUnitIds"]
                 and records.text_sha256("".join(row["targetUtterances"])) == review["outputs"]["targetTextSha256"],
                 f"evidence_row_differs_from_record:{group['translationGroupId']}")
        rows.append(row)
    # The runner admits one translator and one reviewer request per group, in group order,
    # under the policy's model and prompt (text/group_revision.py checks the same).
    generation = {role: {"model": policy[role]["model"], "promptVersion": policy[role]["promptVersion"],
                         "requestIds": [row[role + "RequestId"] for row in rows]}
                  for role in ("translator", "reviewer")}
    _require(request.get("generation") is None and request.get("groups") is None, "request_already_filled")
    evidence = copy.deepcopy(request)
    evidence["generation"] = generation
    evidence["groups"] = rows
    receipt = producer.run_language_plugin(source, anchor, policy, request, evidence, plugin_path, plugin_sha,
                                           rule_preflight_receipt=rule_receipt)
    for group, review in zip(plan, receipt["groupReviews"]):
        _require(payload_sha256(review) == chosen[group["translationGroupId"]]["P"]["outputs"]["groupReviewSha256"],
                 f"plugin_record_differs_from_fresh_run:{group['translationGroupId']}")
    candidate = producer.admit_evidence(source, anchor, policy, request, evidence, receipt, plugin_path, plugin_sha,
                                        rule_preflight_receipt=rule_receipt)
    manifest = {
        "schemaVersion": ASSEMBLY_SCHEMA, "layer1": layer1, "targetLocale": locale,
        "translationPolicySha256": request["translationPolicySha256"],
        "groups": [{"translationGroupId": group["translationGroupId"],
                    "records": {stage: chosen[group["translationGroupId"]][stage]["inputKey"]
                                for stage in ASSEMBLED_STAGES}} for group in plan],
        "evidenceSha256": records.json_sha256(evidence),
        "languageReviewSha256": records.json_sha256(receipt),
        "candidateSha256": records.json_sha256(candidate),
        "equivalenceCheck": equivalence_check,
        "releaseEligible": False, "humanApproval": False,
    }
    return {"evidence": evidence, "languageReview": receipt, "candidate": candidate, "manifest": manifest}


def file_bytes(value: Any) -> bytes:
    """The bytes the Layer 2 runner saves (``text.models.save_new``)."""
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def equivalence_records(evidence: dict, receipt: dict, legacy: dict[str, dict],
                        store: records.RecordStore, payloads: PayloadStore) -> list[str]:
    """Split a whole-sermon evidence and plugin receipt into per-group T, R and P records.

    Only for the equivalence check: these records are marked so ``assemble`` accepts them
    only with ``equivalence_check=True``. ``legacy`` holds each group's T and R records read
    from the run's round caches (``group_legacy.layer2_records``); their inputs, draft and
    runner identity are carried over, the R output is the evidence row itself. Nothing is
    invented: a group without a round-cache T and R gets no records, and its ID is returned.
    """
    layer1 = records.layer1_identity(evidence["englishSourcePackageJsonSha256"], evidence["anchorManifestSha256"])
    locale = evidence["targetLocale"]
    skipped = []
    for row, review in zip(evidence["groups"], receipt["groupReviews"]):
        _require(review["translationGroupId"] == row["translationGroupId"], "receipt_order_differs_from_evidence")
        group_id, units = row["translationGroupId"], row["sourceUnitIds"]
        prior = legacy.get(group_id) or {}
        if "T" not in prior or "R" not in prior:
            skipped.append(group_id)
            continue
        target_sha = records.text_sha256("".join(row["targetUtterances"]))

        def carried(record: dict) -> dict:
            return {"derivation": EQUIVALENCE_DERIVATION, "from": record["provenance"].get("derivation"),
                    "notRecorded": list(record["provenance"].get("notRecorded", []))}

        translator, reviewer = prior["T"], prior["R"]
        store.put(records.make_record("T", layer1, locale, group_id, units, translator["inputs"],
                                      translator["stageImplementationSha256"], translator["outputs"], "pass",
                                      spend=translator["spend"], provenance=carried(translator)))
        passed = row["semanticReview"].get("status") == "pass"
        store.put(records.make_record("R", layer1, locale, group_id, units, reviewer["inputs"],
                                      reviewer["stageImplementationSha256"], reviewed_outputs(row, payloads),
                                      "pass" if passed else "fail",
                                      codes=() if passed else ["semantic_review_not_passed"],
                                      spend=reviewer["spend"], provenance=carried(reviewer)))
        store.put(records.make_record("P", layer1, locale, group_id, units,
                                      {"languageReviewPolicySha256": receipt["languageReviewPolicySha256"],
                                       "englishUnitsSha256": None, "targetTextSha256": target_sha},
                                      receipt["pluginImplementationSha256"], plugin_outputs(review, payloads),
                                      "pass" if review["status"] == "pass" else "fail",
                                      codes=() if review["status"] == "pass" else ["plugin_group_failed"],
                                      provenance={"derivation": EQUIVALENCE_DERIVATION,
                                                  "notRecorded": ["englishUnitsSha256"]}))
    return skipped
