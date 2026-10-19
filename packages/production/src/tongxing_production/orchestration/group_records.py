"""Per-group stage records and their input keys (DEV-GRP-001).

One immutable record per ``(Layer 1 identity, targetLocale, translationGroupId, stage)``
and input key. A stage's input key hashes exactly the inputs that decide its output,
plus the implementation identity of that stage, so a change reruns only the stages
that read it (docs/design/per-group-independent-pipeline.zh.md, sections 4 and 7).

This module is pure: it computes keys, builds and validates records, and reads or
writes them in a store directory. It never dispatches work, reads run products, or
imports a layer. Records are intermediate evidence, never release material.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

RECORD_SCHEMA = "sermon-group-stage-record-v1"
# stageImplementationSha256 per stage: T/R the Layer 2 runner production identity,
# P the plugin implementation, Q/C/U the machine-QC implementation closure, S the
# renderer sound identity, A the ASR screening implementation.
INPUT_KEY_SCHEMA = "sermon-group-stage-input-key-v1"

# Pipeline order. C (spoken condensation) applies only to groups the text QC sends to
# shortening; every other group goes from R straight to S.
STAGES = ("T", "R", "P", "Q", "C", "S", "A", "U")
STAGE_NAMES = {"T": "translation", "R": "independent_review", "P": "language_plugin",
               "Q": "text_qc", "C": "spoken_condensation", "S": "speech_synthesis",
               "A": "asr_back_check", "U": "unit_audio_qc"}
VERDICTS = ("pass", "fail", "stopped", "unknown")

# The named inputs each stage's key binds (section 4). A record must carry exactly
# these; a builder that omits one cannot mint a key that later looks complete.
STAGE_INPUTS = {
    # The bounded payload holds the group English, English context, the model-facing
    # policy, rules, revision brief and model settings; the fingerprint adds the route.
    "T": ("boundedPayloadSha256", "requestFingerprintSha256", "englishUnitsSha256",
          "englishContextSha256", "modelFacingPolicySha256", "modelRulesSha256", "revisionSha256",
          "modelSettingsSha256"),
    # The review payload also carries T's draft.
    "R": ("boundedPayloadSha256", "requestFingerprintSha256", "englishUnitsSha256",
          "englishContextSha256", "modelFacingPolicySha256", "modelRulesSha256", "revisionSha256",
          "modelSettingsSha256", "draftTextSha256"),
    # The plugin implementation is this stage's implementation identity.
    "P": ("languageReviewPolicySha256", "englishUnitsSha256", "targetTextSha256"),
    # Text QC also reads the policy (terminology and name checks), not its plugin or model-role fields.
    "Q": ("englishSha256", "targetTextSha256", "qcPolicySha256", "semanticIdentitySha256", "repairPositionSha256"),
    "C": ("condensationRequestSha256", "englishSha256", "targetTextSha256"),
    # Sound is decided by the spoken text and the synthesis identity alone; the job
    # and candidate hashes, unit index and batch window are assembly information.
    "S": ("textSha256", "synthesisIdentitySha256"),
    "A": ("audioSha256", "targetTextSha256", "asrSettingsSha256"),
    "U": ("audioSha256", "textSha256", "sourceSecondsSha256", "thresholdsSha256",
          "repairPositionSha256"),
}

# Which upstream output each stage reads. A stage whose upstream will produce new
# bytes is stale even when its own recorded inputs still match (section 7).
UPSTREAM = {"T": (), "R": ("T",), "P": ("R",), "Q": ("R",), "C": ("R",),
            "S": ("R", "C"), "A": ("S",), "U": ("S", "A")}
# Stages that produce bytes a downstream stage consumes. P and Q are verdicts: a
# change to the plugin or the text QC reruns only that step (section 7).
PRODUCES = {"T", "R", "C", "S", "A"}
# The output each byte-producing stage must name when it passes; consumers compare it.
REQUIRED_OUTPUTS = {"T": ("draftTextSha256",), "R": ("targetTextSha256",), "C": ("spokenTextSha256",),
                    "S": ("audioSha256",), "A": ("recognizedSha256",)}

SHA256 = re.compile(r"[0-9a-f]{64}")
GROUP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}")
LOCALE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*")
MAX_RECORD_BYTES = 256 * 1024


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def layer1_identity(english_source_package_json_sha256: str, anchor_manifest_sha256: str) -> dict:
    """The global part of every key: a changed source package or anchor invalidates all."""
    identity = {"englishSourcePackageJsonSha256": english_source_package_json_sha256,
                "anchorManifestSha256": anchor_manifest_sha256}
    _require(all(_is_sha(value) for value in identity.values()), "invalid_layer1_identity")
    return identity


def _require_inputs(stage: str, inputs: dict) -> None:
    _require(stage in STAGE_INPUTS, f"unknown_stage:{stage}")
    _require(isinstance(inputs, dict) and set(inputs) == set(STAGE_INPUTS[stage]),
             f"stage_inputs_mismatch:{stage}")
    # None marks an input this stage did not have (no revision brief, no rule receipt).
    _require(all(value is None or _is_sha(value) for value in inputs.values()),
             f"stage_input_not_sha256:{stage}")


def input_key(stage: str, layer1: dict, target_locale: str, translation_group_id: str,
              inputs: dict, stage_implementation_sha256: str) -> str:
    """Hash of everything that decides this stage's output for this group.

    No position: group IDs and their source units come from Layer 1, whose change
    already invalidates every key through ``layer1``.
    """
    _require_inputs(stage, inputs)
    _require(isinstance(target_locale, str) and LOCALE.fullmatch(target_locale) is not None,
             "invalid_target_locale")
    _require(isinstance(translation_group_id, str) and GROUP_ID.fullmatch(translation_group_id) is not None,
             "invalid_translation_group_id")
    _require(_is_sha(stage_implementation_sha256), "invalid_stage_implementation_sha256")
    return json_sha256({"schemaVersion": INPUT_KEY_SCHEMA, "stage": stage,
                        "layer1": layer1_identity(layer1["englishSourcePackageJsonSha256"],
                                                  layer1["anchorManifestSha256"]),
                        "targetLocale": target_locale, "translationGroupId": translation_group_id,
                        "inputs": dict(sorted(inputs.items())),
                        "stageImplementationSha256": stage_implementation_sha256})


def make_record(stage: str, layer1: dict, target_locale: str, translation_group_id: str,
                source_unit_ids: list[str], inputs: dict, stage_implementation_sha256: str,
                outputs: dict, verdict: str, *, codes=(), spend=None, provenance=None) -> dict:
    """Build one record. ``outputs`` maps names to SHA-256 values of produced bytes."""
    _require(verdict in VERDICTS, "invalid_verdict")
    _require(isinstance(source_unit_ids, list) and source_unit_ids
             and all(isinstance(unit, str) and unit for unit in source_unit_ids), "invalid_source_unit_ids")
    _require(isinstance(outputs, dict) and all(isinstance(name, str) and (value is None or _is_sha(value))
                                               for name, value in outputs.items()), "invalid_outputs")
    codes = sorted({str(code) for code in codes})
    _require(verdict in {"fail", "stopped"} or not codes, "codes_only_on_fail_or_stop")
    record = {
        "schemaVersion": RECORD_SCHEMA,
        "stage": stage, "stageName": STAGE_NAMES.get(stage),
        "layer1": layer1_identity(layer1["englishSourcePackageJsonSha256"], layer1["anchorManifestSha256"]),
        "targetLocale": target_locale, "translationGroupId": translation_group_id,
        "sourceUnitIds": list(source_unit_ids),
        "inputs": dict(sorted(inputs.items())),
        "stageImplementationSha256": stage_implementation_sha256,
        "inputKey": input_key(stage, layer1, target_locale, translation_group_id, inputs,
                              stage_implementation_sha256),
        "outputs": dict(sorted(outputs.items())),
        "verdict": {"status": verdict, "codes": codes},
        # A paid stage settles through the budget ledger; this is only its reference.
        "spend": spend if spend is not None else {"kind": "none"},
        "provenance": provenance if provenance is not None else {},
        "releaseEligible": False,
        "humanApproval": False,
    }
    validate_record(record)
    return record


def validate_record(record: dict) -> dict:
    _require(isinstance(record, dict) and record.get("schemaVersion") == RECORD_SCHEMA, "invalid_record_schema")
    expected = {"schemaVersion", "stage", "stageName", "layer1", "targetLocale", "translationGroupId",
                "sourceUnitIds", "inputs", "stageImplementationSha256", "inputKey", "outputs", "verdict",
                "spend", "provenance", "releaseEligible", "humanApproval"}
    _require(set(record) == expected, "record_fields_mismatch")
    _require(record["releaseEligible"] is False and record["humanApproval"] is False,
             "group_record_is_never_release_or_human_approval")
    _require(record["stageName"] == STAGE_NAMES.get(record["stage"]), "record_stage_name_mismatch")
    _require(isinstance(record["sourceUnitIds"], list) and record["sourceUnitIds"]
             and all(isinstance(unit, str) and unit for unit in record["sourceUnitIds"]), "invalid_source_unit_ids")
    _require(isinstance(record["outputs"], dict)
             and all(isinstance(name, str) and (value is None or _is_sha(value))
                     for name, value in record["outputs"].items()), "invalid_record_outputs")
    if record["verdict"]["status"] == "pass":
        _require(all(_is_sha(record["outputs"].get(name)) for name in REQUIRED_OUTPUTS.get(record["stage"], ())),
                 "record_missing_required_output")
    _require(isinstance(record["verdict"], dict) and set(record["verdict"]) == {"status", "codes"}
             and record["verdict"]["status"] in VERDICTS and isinstance(record["verdict"]["codes"], list)
             and all(isinstance(code, str) and code for code in record["verdict"]["codes"])
             and (record["verdict"]["status"] in {"fail", "stopped"} or not record["verdict"]["codes"]),
             "invalid_record_verdict")
    _require(isinstance(record["spend"], dict) and isinstance(record["spend"].get("kind"), str),
             "invalid_record_spend")
    _require(isinstance(record["provenance"], dict), "invalid_record_provenance")
    _require(record["inputKey"] == input_key(record["stage"], record["layer1"], record["targetLocale"],
                                             record["translationGroupId"], record["inputs"],
                                             record["stageImplementationSha256"]),
             "record_input_key_mismatch")
    _require(len(canonical_bytes(record)) <= MAX_RECORD_BYTES, "record_too_large")
    return record


class RecordStore:
    """Append-only directory of records: ``<locale>/<group>/<stage>/<inputKey>.json``.

    A second write of the same key must carry identical bytes; it can never replace
    the first. The directory is run state (ignored, never in Git).
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, target_locale: str, translation_group_id: str, stage: str, key: str) -> Path:
        _require(LOCALE.fullmatch(target_locale) is not None and GROUP_ID.fullmatch(translation_group_id) is not None
                 and stage in STAGES and _is_sha(key), "invalid_record_path")
        return self.root / target_locale / translation_group_id / stage / f"{key}.json"

    def put(self, record: dict) -> Path:
        validate_record(record)
        path = self.path(record["targetLocale"], record["translationGroupId"], record["stage"],
                         record["inputKey"])
        data = canonical_bytes(record) + b"\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            _require(path.read_bytes() == data, "record_key_already_written_with_other_bytes")
            return path
        # Write and sync a private temporary file, then link it into place: a crash can
        # leave only the temporary file, never a truncated record under the key.
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{os.urandom(4).hex()}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)  # never replaces an existing key
            except FileExistsError:
                _require(path.read_bytes() == data, "record_key_already_written_with_other_bytes")
                return path
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def records(self, target_locale: str, translation_group_id: str, stage: str) -> list[dict]:
        directory = self.root / target_locale / translation_group_id / stage
        if not directory.is_dir():
            return []
        found = []
        for path in sorted(directory.glob("*.json")):
            _require(not path.is_symlink() and path.stat().st_size <= MAX_RECORD_BYTES, f"invalid_record_file:{path.name}")
            record = validate_record(json.loads(path.read_text(encoding="utf-8")))
            # A record filed under another locale, group, stage or key is never used here.
            _require(record["targetLocale"] == target_locale and record["translationGroupId"] == translation_group_id
                     and record["stage"] == stage and path.stem == record["inputKey"],
                     f"record_filed_under_other_identity:{path}")
            found.append(record)
        return found
