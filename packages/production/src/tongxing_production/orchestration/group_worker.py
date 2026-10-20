"""Execute one Layer 1 group's Layer 2 stages and write its records (DEV-GRP-002 worker).

docs/design/per-group-independent-pipeline.zh.md section 2: a group's translation (T),
independent review (R) and language plugin (P) are one independent task. This module
runs exactly those three stages for one group through the existing runner
(``text.models.run_accounted``) with a one-group plan, then writes the immutable
``sermon-group-stage-record-v1`` records and payloads the merge reads. It adds no
model prompt, admission rule or approval.

The worker never invents reuse authority: a record is written only from the round
this worker just produced, its inputs are read back from that round's own payload
previews and caches, and its provenance says ``per_group_pipeline``. A round that
made no paid call writes no record. A paid outcome that is unknown writes no record
and raises ``unknown`` so the caller stops new paid dispatch. A content failure still
writes the terminal records the round can name, so the group shows failed, not missing.

One worker per ``(locale, group)``: the lock is exclusive and non-blocking, and a
second worker refuses before any call. These records and preview audio are
intermediate evidence, never release material.
"""
from __future__ import annotations

import fcntl
import json
from pathlib import Path
from typing import Any

from . import group_assembly
from . import group_legacy as legacy
from . import group_records as records

CONFIG_SCHEMA = "sermon-group-run-config-v1"
DERIVATION = "per_group_pipeline"
PAID_STAGES = ("T", "R", "P")
REQUIRED_FIELDS = {"schemaVersion", "source", "anchor", "locale", "policy", "plugin", "records", "work"}


class GroupWorkerError(RuntimeError):
    """A group cannot produce a terminal chain; ``kind`` says what happened."""

    def __init__(self, kind: str, group_id: str, detail: str, *, dispatched: bool):
        self.kind, self.group_id, self.detail, self.dispatched = kind, group_id, detail, dispatched
        super().__init__(f"{kind}:{group_id}:{detail}")


class GroupBusy(GroupWorkerError):
    def __init__(self, group_id: str):
        super().__init__("group_busy", group_id, "another worker holds this group's lock", dispatched=False)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _path(value: Any, base: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def load_configuration(path: Path) -> dict:
    """Read a ``sermon-group-run-config-v1`` and resolve its paths against the file."""
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(config, dict) and config.get("schemaVersion") == CONFIG_SCHEMA, "invalid_group_run_config")
    _require(REQUIRED_FIELDS <= set(config) <= REQUIRED_FIELDS | {"merge"}, "unknown_group_run_config_field")
    return {
        "path": path,
        "source": _path(config["source"], path.parent),
        "anchor": _path(config["anchor"], path.parent),
        "locale": config["locale"],
        "policy": _path(config["policy"], path.parent),
        "plugin": _path(config["plugin"], path.parent),
        "records": _path(config["records"], path.parent),
        "work": _path(config["work"], path.parent),
        "merge": _path(config.get("merge", "merge"), path.parent),
    }


class _CountingCaller:
    """Delegate to the real transport and count what happened, for unknown handling."""

    def __init__(self, caller):
        self.caller = caller
        self.calls = 0
        self.transport_errors = 0

    def __getattr__(self, name):
        return getattr(self.caller, name)

    def verify_execution(self, api_key):
        verifier = getattr(self.caller, "verify_execution", None)
        if verifier is not None:
            return verifier(api_key)
        return None

    def __call__(self, api_key, payload):
        self.calls += 1
        try:
            return self.caller(api_key, payload)
        except Exception:
            self.transport_errors += 1
            raise


class _GroupLock:
    """Exclusive, non-blocking lock per ``(locale, group)``."""

    def __init__(self, root: Path, locale: str, group_id: str):
        _require(records.LOCALE.fullmatch(locale) is not None
                 and records.GROUP_ID.fullmatch(group_id) is not None, "invalid_lock_identity")
        directory = Path(root) / "_locks" / locale
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{group_id}.lock"
        self.handle = None

    def __enter__(self):
        self.handle = open(self.path, "a+")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.handle.close()
            raise
        return self

    def __exit__(self, *_):
        fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()
        return False


def _rebuilt(record: dict, *, provenance: dict, outputs: dict | None = None) -> dict:
    """The same record under this worker's provenance; the input key is unchanged."""
    return records.make_record(
        record["stage"], record["layer1"], record["targetLocale"], record["translationGroupId"],
        record["sourceUnitIds"], record["inputs"], record["stageImplementationSha256"],
        outputs if outputs is not None else record["outputs"], record["verdict"]["status"],
        codes=record["verdict"]["codes"], spend=record["spend"], provenance=provenance)


def _provenance(round_dir: Path, record: dict) -> dict:
    return {"derivation": DERIVATION, "round": str(round_dir), "worker": "group_worker",
            "notRecorded": list(record["provenance"].get("notRecorded") or [])}


def run_group(config: dict, group: dict, *, source: dict, anchor: dict, policy: dict,
              request: dict, caller, api_key: str) -> dict:
    """Run T, R and P for one group and write its records.

    Returns ``{"group", "records", "dispatched", "round"}``. Raises ``GroupWorkerError``
    when the group cannot produce a terminal chain: ``unknown`` means a paid outcome
    is not settled (stop new paid dispatch on the run); ``failed`` means content or
    plugin failure (revise by group ID); ``not_dispatched`` means nothing was sent.
    """
    group_id = group["translationGroupId"]
    locale = config["locale"]
    store = records.RecordStore(config["records"])
    payloads = group_assembly.PayloadStore(config["records"])
    round_dir = Path(config["work"]) / locale / group_id
    round_dir.mkdir(parents=True, exist_ok=True)
    try:
        with _GroupLock(config["records"], locale, group_id):
            return _run_locked(store, payloads, round_dir, group, source, anchor, policy,
                               request, caller, api_key, config["plugin"])
    except BlockingIOError:
        raise GroupBusy(group_id)


def _run_locked(store, payloads, round_dir, group, source, anchor, policy, request,
                caller, api_key, plugin_path) -> dict:
    from ..text import candidate as producer
    from ..text import models
    from ..text import policy as policy_tools

    group_id, locale = group["translationGroupId"], policy["targetLocale"]
    layer1 = records.layer1_identity(request["englishSourcePackageJsonSha256"], request["anchorManifestSha256"])
    counting = _CountingCaller(caller)
    error = None
    evidence = None
    full_plan = models.group_plan(request, anchor)
    try:
        evidence = models.run_accounted(source, anchor, policy, round_dir, api_key, counting,
                                        [group], plugin_path, None, None,
                                        emit_payload_cache_success=True, allow_subset=True,
                                        context_plan=full_plan)
    except Exception as exc:  # noqa: BLE001 - classified below, never swallowed
        error = exc

    derived = legacy.layer2_records(locale, [group], [round_dir]).get(group_id, {})
    wrote = []
    if error is not None and counting.calls == 0:
        raise GroupWorkerError("not_dispatched", group_id, str(error), dispatched=False)
    if error is not None and counting.transport_errors:
        # A provider call's outcome is unknown: never mint a terminal record for it.
        raise GroupWorkerError("unknown", group_id, str(error), dispatched=True)
    if error is not None:
        # Content failure: the round returned, so write what it can name.
        for stage in ("T", "R"):
            if stage in derived:
                wrote.append(_write(store, _rebuilt(derived[stage], provenance=_provenance(round_dir, derived[stage]))))
        raise GroupWorkerError("failed", group_id, str(error), dispatched=counting.calls > 0)

    _require(evidence is not None and len(evidence.get("groups") or []) == 1,
             f"single_group_evidence_expected:{group_id}")
    row = evidence["groups"][0]
    _require("T" in derived and "R" in derived, f"round_without_translation_or_review_records:{group_id}")
    target = derived["R"]["outputs"].get("targetTextSha256")
    _require(target == records.text_sha256("".join(row["targetUtterances"])),
             f"reviewed_text_differs_from_evidence:{group_id}")
    reviewed = group_assembly.reviewed_outputs(row, payloads)
    _require(reviewed["targetTextSha256"] == target, f"evidence_row_and_record_differ:{group_id}")
    wrote.append(_write(store, _rebuilt(derived["T"], provenance=_provenance(round_dir, derived["T"]))))
    wrote.append(_write(store, _rebuilt(derived["R"], provenance=_provenance(round_dir, derived["R"]),
                                        outputs=reviewed)))
    plugin_sha = policy["languageReview"]["pluginImplementationSha256"]
    review = producer.evaluate_plugin_groups(policy, request, plugin_path, plugin_sha, [row])["groupReviews"][0]
    units = group["sourceUnitIds"]
    plugin_record = records.make_record(
        "P", layer1, locale, group_id, units,
        {"languageReviewPolicySha256": policy_tools.validate_policy(policy)["languageReviewPolicySha256"],
         "englishUnitsSha256": legacy.english_units_sha256(legacy.english_rows(anchor, units)),
         "targetTextSha256": target},
        plugin_sha, group_assembly.plugin_outputs(review, payloads),
        "pass" if review["status"] == "pass" else "fail",
        codes=[] if review["status"] == "pass" else ["plugin_group_failed"],
        provenance={"derivation": DERIVATION, "round": str(round_dir), "worker": "group_worker"})
    wrote.append(_write(store, plugin_record))
    if review["status"] != "pass":
        raise GroupWorkerError("failed", group_id, "language plugin rejected the reviewed group", dispatched=True)
    return {"group": group_id, "records": [record["stage"] for record in wrote],
            "dispatched": counting.calls > 0, "round": str(round_dir)}


def _write(store: records.RecordStore, record: dict) -> dict:
    store.put(record)
    return record
