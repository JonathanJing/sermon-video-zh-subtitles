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


def _write_once(path: Path, data: bytes, mismatch: str) -> None:
    """Install ``data`` at ``path`` once; a second write must carry the same bytes.

    The file and its directory entry are synced, so a crash cannot leave a durable
    record that names a payload or resolution which was never made durable.
    """
    if path.exists():
        _require(path.read_bytes() == data, mismatch)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{os.urandom(4).hex()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)  # never replaces an existing entry
        except FileExistsError:
            _require(path.read_bytes() == data, mismatch)
            return
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


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
        _write_once(self.path(sha), data, "payload_bytes_differ_from_their_hash")
        return sha

    def get(self, sha256: str) -> Any:
        path = self.path(sha256)
        _require(path.is_file() and not path.is_symlink(), f"payload_missing:{sha256}")
        data = path.read_bytes()
        _require(hashlib.sha256(data).hexdigest() == sha256, f"payload_changed:{sha256}")
        return json.loads(data.decode("utf-8"))


RESOLUTION_SCHEMA = "sermon-group-record-resolution-v1"
RESOLUTION_DIRECTORY = "_resolutions"


class ResolutionStore:
    """Reconciled outcomes of ``unknown`` records, append-only next to the records.

    The record store keeps one record per input key, so a reconciled attempt cannot be
    written over its ``unknown`` record. Its resolution is stored here instead: the full
    reconciled record (same stage, group, inputs, implementation and key) bound to the
    hash of the ``unknown`` record it settles. ``select`` reads it in that record's place.
    """

    def __init__(self, root: Path):
        self.root = Path(root) / RESOLUTION_DIRECTORY

    def path(self, record: dict) -> Path:
        return (self.root / record["targetLocale"] / record["translationGroupId"] / record["stage"]
                / f"{record['inputKey']}.json")

    def put(self, unknown: dict, resolved: dict) -> Path:
        records.validate_record(unknown)
        records.validate_record(resolved)
        same = ("stage", "layer1", "targetLocale", "translationGroupId", "sourceUnitIds", "inputs",
                "stageImplementationSha256", "inputKey")
        _require(unknown["verdict"]["status"] == "unknown" and resolved["verdict"]["status"] != "unknown"
                 and all(unknown[key] == resolved[key] for key in same), "resolution_must_settle_the_same_attempt")
        document = {"schemaVersion": RESOLUTION_SCHEMA, "unknownRecordSha256": records.json_sha256(unknown),
                    "resolved": resolved}
        path = self.path(unknown)
        _write_once(path, records.canonical_bytes(document) + b"\n", "resolution_already_written_with_other_bytes")
        return path

    def resolved(self, unknown: dict) -> dict | None:
        path = self.path(unknown)
        if not path.is_file():
            return None
        _require(not path.is_symlink(), "invalid_resolution_file")
        document = json.loads(path.read_text(encoding="utf-8"))
        _require(isinstance(document, dict) and document.get("schemaVersion") == RESOLUTION_SCHEMA
                 and document.get("unknownRecordSha256") == records.json_sha256(unknown),
                 f"resolution_belongs_to_another_record:{unknown['inputKey']}")
        resolved = records.validate_record(document["resolved"])
        _require(resolved["inputKey"] == unknown["inputKey"] and resolved["verdict"]["status"] != "unknown",
                 "invalid_resolution")
        return resolved


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
    # An input the record did not record cannot be compared, so it cannot prove a production merge current.
    if record["provenance"].get("notRecorded") and not equivalence_check:
        return "inputs_not_recorded"
    if record["layer1"] != layer1 or record["targetLocale"] != locale or record["sourceUnitIds"] != unit_ids:
        return "other_identity"
    return None


def select(store: records.RecordStore, anchor: dict, policy: dict, layer1: dict, locale: str, plan: list[dict],
           identities: dict, *, resolutions: ResolutionStore | None = None,
           equivalence_check: bool = False, notes: dict | None = None) -> dict[str, dict[str, dict]]:
    """One current, passing T, R and P record per group.

    A record counts only when its inputs and implementation match the current ones as
    ``group_plan.evaluate`` compares them (English, English context, model-facing policy,
    model settings, runner; for P the plugin, language-review policy, English and the
    reviewed text), R names the draft of the chosen T, and P reviewed R's text. An
    ``unknown`` record blocks its group until a resolution settles it. ``identities``
    gives ``runnerImplementationSha256``, ``pluginImplementationSha256`` and
    ``languageReviewPolicySha256``; the runner may be ``None`` only in the equivalence
    check, which then does not compare it.

    Raises ``AssemblyRefused`` naming every group without exactly one such chain.
    """
    from . import group_plan
    runner = identities.get("runnerImplementationSha256")
    _require(runner is not None or equivalence_check, "runner_identity_required")
    locale_identity = {"pluginImplementationSha256": identities["pluginImplementationSha256"],
                       "languageReviewPolicySha256": identities["languageReviewPolicySha256"]}
    contexts = legacy_contexts(anchor, plan)
    reasons: dict[str, list[str]] = {}
    chosen: dict[str, dict[str, dict]] = {}

    def refuse(reason: str, group_id: str) -> None:
        reasons.setdefault(reason, []).append(group_id)

    def current(stage: str, group: dict, record: dict, upstream: dict, implementation: str | None) -> bool:
        values = group_plan.current_inputs(stage, group, contexts[group["translationGroupId"]], anchor, policy,
                                           locale_identity, upstream, notes)
        return not group_plan.evaluate(record, layer1, values, implementation)["reasons"]

    def attempt_is_current(stage: str, group: dict, record: dict) -> bool:
        """Whether an attempt ran under the current inputs, upstream bytes aside."""
        if stage in {"T", "R"}:
            return current(stage, group, record, {}, runner)
        english = group_plan.current_inputs("T", group, contexts[group["translationGroupId"]], anchor, policy,
                                            locale_identity, {}, notes)["englishUnitsSha256"]
        expected = {"languageReviewPolicySha256": identities["languageReviewPolicySha256"],
                    "englishUnitsSha256": english}
        return not group_plan.evaluate(record, layer1, expected, identities["pluginImplementationSha256"])["reasons"]

    for group in plan:
        group_id, unit_ids = group["translationGroupId"], group["sourceUnitIds"]
        usable: dict[str, list[dict]] = {}
        blocked = False
        for stage in ASSEMBLED_STAGES:
            kept = []
            for record in store.records(locale, group_id, stage):
                problem = _usable(record, layer1, locale, unit_ids, equivalence_check)
                if problem is not None:
                    if problem != "other_identity":
                        refuse(f"{stage}:{problem}", group_id)
                    continue
                if record["verdict"]["status"] == "unknown":
                    settled = resolutions.resolved(record) if resolutions is not None else None
                    if settled is not None:
                        record = dict(settled, _resolvesUnknownSha256=records.json_sha256(record))
                    else:
                        # An unsettled attempt under the current inputs blocks; one under old
                        # inputs is stale and cannot be chosen anyway.
                        if attempt_is_current(stage, group, record):
                            refuse("unknown_outcome_needs_reconciliation", group_id)
                            blocked = True
                        continue
                kept.append(record)
            usable[stage] = kept
        if blocked:
            continue
        drafts = [record for record in usable["T"] if record["verdict"]["status"] == "pass"
                  and current("T", group, record, {}, runner)]
        pairs = [(draft, review) for draft in drafts for review in usable["R"]
                 if review["verdict"]["status"] == "pass"
                 and records._is_sha(review["outputs"].get("evidenceRowSha256"))
                 and current("R", group, review, {"T": draft}, runner)]
        if len(pairs) != 1:
            refuse(("T" if not drafts else "R") + ":" + ("conflict" if len(pairs) > 1 else "missing_or_not_current"),
                   group_id)
            continue
        draft, review = pairs[0]
        target = review["outputs"]["targetTextSha256"]
        english = group_plan.current_inputs("T", group, contexts[group_id], anchor, policy, locale_identity,
                                            {}, notes)["englishUnitsSha256"]
        expected = {"languageReviewPolicySha256": identities["languageReviewPolicySha256"],
                    "englishUnitsSha256": english, "targetTextSha256": target}
        plugins = [record for record in usable["P"] if not group_plan.evaluate(
            record, layer1, expected, identities["pluginImplementationSha256"])["reasons"]]
        passed = [record for record in plugins if record["verdict"]["status"] == "pass"
                  and records._is_sha(record["outputs"].get("groupReviewSha256"))]
        if len(passed) != 1:
            refuse("P:" + ("conflict" if len(passed) > 1 else
                           "failed" if plugins else "missing_for_current_plugin_and_text"), group_id)
            continue
        chosen[group_id] = {"T": draft, "R": review, "P": passed[0]}
    if reasons:
        raise AssemblyRefused(reasons)
    return chosen


def legacy_contexts(anchor: dict, plan: list[dict]) -> dict[str, dict]:
    """The English context each group's request carries (the plan computes it the same way)."""
    from . import group_legacy
    return group_legacy.group_contexts(anchor, plan)


def assemble(source: dict, anchor: dict, policy: dict, request: dict, rule_receipt: dict | None,
             plugin_path: Path, store: records.RecordStore, payloads: PayloadStore, *,
             resolutions: ResolutionStore | None = None, runner_implementation_sha256: str | None = None,
             equivalence_check: bool = False, notes: dict | None = None) -> dict[str, Any]:
    """Evidence, plugin receipt and candidate from the records, plus a manifest of what was used.

    The runner identity defaults to this checkout's ``RUNNER_PRODUCTION_IDENTITY_SHA256``;
    only the equivalence check may leave it uncompared (``runner_implementation_sha256=None``
    with ``equivalence_check=True``), because historical rounds ran under older runners.
    """
    from ..text import candidate as producer
    from ..text import models
    from ..text import policy as policy_tools
    layer1 = records.layer1_identity(request["englishSourcePackageJsonSha256"], request["anchorManifestSha256"])
    locale = request["targetLocale"]
    plan = models.group_plan(request, anchor)
    plugin_sha = policy["languageReview"]["pluginImplementationSha256"]
    # The identity the plugin receipt itself carries for this policy.
    review_policy_sha = policy_tools.validate_policy(policy)["languageReviewPolicySha256"]
    runner = (runner_implementation_sha256 if runner_implementation_sha256 is not None or equivalence_check
              else models.RUNNER_PRODUCTION_IDENTITY_SHA256)
    identities = {"runnerImplementationSha256": runner, "pluginImplementationSha256": plugin_sha,
                  "languageReviewPolicySha256": review_policy_sha}
    chosen = select(store, anchor, policy, layer1, locale, plan, identities, resolutions=resolutions,
                    equivalence_check=equivalence_check, notes=notes)
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
        # The full selected record by hash: two stores may hold different bytes under one key.
        "groups": [{"translationGroupId": group["translationGroupId"],
                    "records": {stage: _manifest_entry(chosen[group["translationGroupId"]][stage])
                                for stage in ASSEMBLED_STAGES}} for group in plan],
        "runnerImplementationSha256": runner,
        "evidenceSha256": records.json_sha256(evidence),
        "languageReviewSha256": records.json_sha256(receipt),
        "candidateSha256": records.json_sha256(candidate),
        "equivalenceCheck": equivalence_check,
        "releaseEligible": False, "humanApproval": False,
    }
    return {"evidence": evidence, "languageReview": receipt, "candidate": candidate, "manifest": manifest}


def _manifest_entry(record: dict) -> dict:
    settles = record.get("_resolvesUnknownSha256")
    plain = {key: value for key, value in record.items() if key != "_resolvesUnknownSha256"}
    entry = {"inputKey": plain["inputKey"], "recordSha256": records.json_sha256(plain)}
    if settles is not None:
        entry["resolvesUnknownRecordSha256"] = settles
    return entry


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
    invented: a group whose round cache has no passing T and R, or whose cached review
    produced other text (an operator ruling or manual edit), gets no records, and its ID
    is returned.
    """
    layer1 = records.layer1_identity(evidence["englishSourcePackageJsonSha256"], evidence["anchorManifestSha256"])
    locale = evidence["targetLocale"]
    skipped = []
    for row, review in zip(evidence["groups"], receipt["groupReviews"]):
        _require(review["translationGroupId"] == row["translationGroupId"], "receipt_order_differs_from_evidence")
        group_id, units = row["translationGroupId"], row["sourceUnitIds"]
        prior = legacy.get(group_id) or {}
        target_sha = records.text_sha256("".join(row["targetUtterances"]))
        # Only a round-cache review that passed and produced this very text reconstructs it.
        if ("T" not in prior or "R" not in prior or prior["T"]["verdict"]["status"] != "pass"
                or prior["R"]["verdict"]["status"] != "pass"
                or prior["R"]["outputs"].get("targetTextSha256") != target_sha):
            skipped.append(group_id)
            continue

        def carried(record: dict) -> dict:
            return {"derivation": EQUIVALENCE_DERIVATION, "from": record["provenance"].get("derivation"),
                    "notRecorded": list(record["provenance"].get("notRecorded", []))}

        translator, reviewer = prior["T"], prior["R"]
        store.put(records.make_record("T", layer1, locale, group_id, units, translator["inputs"],
                                      translator["stageImplementationSha256"], translator["outputs"], "pass",
                                      spend=translator["spend"], provenance=carried(translator)))
        store.put(records.make_record("R", layer1, locale, group_id, units, reviewer["inputs"],
                                      reviewer["stageImplementationSha256"], reviewed_outputs(row, payloads), "pass",
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
