#!/usr/bin/env python3
"""Durable repair ledger for the machine QC repair cap (two, then two).

The cap counts failed attempts per frozen English source unit across every QC
rerun of one locale, separately for text and audio. A QC run reads the ledger
head (:func:`position`), records that position in its receipt, and is then
appended as an immutable entry (:func:`append`). Entries are created
exclusively and chained by hash, so two runs cannot claim the same position and
a run cannot start over from zero without deleting durable state. A waiver
accepts only the QC receipt at the head of a consistent chain
(:func:`head_problems`), so its ``failedAttempts`` follow from every earlier
run instead of a caller-supplied count.

The ledger is keyed by locale, English source package and anchor, not by
candidate or group id: a new revision, regrouping or renamed group keeps the
count of the English units it covers.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

SCHEMA = "sermon-machine-repair-ledger-entry-v1"
KINDS = ("text", "audio")


def json_sha256(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def lineage(kind: str, locale: str, source_sha: str, anchor_sha: str) -> dict:
    """What one ledger counts: one kind of QC for one locale of one frozen English source."""
    _require(kind in KINDS, f"Unknown repair ledger kind: {kind}")
    _require(all(isinstance(value, str) and len(value) == 64 for value in (source_sha, anchor_sha)),
             "Repair ledger lineage needs the English source and anchor hashes")
    return {"kind": kind, "targetLocale": locale, "englishSourcePackageJsonSha256": source_sha,
            "anchorManifestJsonSha256": anchor_sha}


def directory(root: Path, value: dict) -> Path:
    return Path(root) / value["kind"] / value["targetLocale"] / json_sha256(value)


def _counts(entries: list[dict]) -> dict[str, int]:
    return dict(entries[-1]["failedAttempts"]) if entries else {}


def position(value: dict, entries: list[dict]) -> dict:
    """The position the next QC run must record as its ``repairLedger``."""
    return {"lineageSha256": json_sha256(value), "sequence": len(entries) + 1,
            "previousEntryJsonSha256": json_sha256(entries[-1]) if entries else None,
            "priorFailedAttempts": _counts(entries)}


def prior(repair_position: dict | None, unit_ids) -> int:
    """Failed attempts so far for a row covering ``unit_ids``: the most of any of its units."""
    if repair_position is None:
        return 0
    _require(isinstance(unit_ids, list) and bool(unit_ids),
             "A ledger-bound QC row needs the frozen source unit ids it covers")
    return max(int(repair_position["priorFailedAttempts"].get(unit_id, 0)) for unit_id in unit_ids)


def chain_problems(value: dict, entries: list[dict]) -> list[str]:
    """Every entry must belong to ``value`` and follow from the one before it."""
    problems, counts, previous = [], {}, None
    for sequence, entry in enumerate(entries, 1):
        failed = entry.get("failedSourceUnitIds")
        expected = dict(counts)
        for unit_id in failed if isinstance(failed, list) else []:
            expected[unit_id] = expected.get(unit_id, 0) + 1
        if (entry.get("schemaVersion") != SCHEMA or entry.get("lineage") != value
                or entry.get("lineageSha256") != json_sha256(value) or entry.get("sequence") != sequence
                or entry.get("previousEntryJsonSha256") != previous
                or not isinstance(failed, list) or failed != sorted(set(failed))
                or not isinstance(entry.get("qcJsonSha256"), str)
                or entry.get("failedAttempts") != expected):
            problems.append(f"repair ledger entry {sequence} does not follow the chain")
            break
        counts, previous = expected, json_sha256(entry)
    return problems


def next_entry(value: dict, entries: list[dict], qc: dict) -> dict:
    """The entry recording ``qc`` at the ledger head; ``qc`` must have screened from that head."""
    chain = chain_problems(value, entries)
    _require(not chain, "; ".join(chain))
    here = position(value, entries)
    _require(qc.get("repairLedger") == here, "QC did not screen from the current repair ledger head")
    failed = set()
    for row in qc.get("results") or []:
        unit_ids = row.get("sourceUnitIds")
        attempts = prior(here, unit_ids) + (row.get("status") == "fail")
        _require(row.get("failedAttempts") == attempts,
                 f"QC failed-attempt count does not follow the repair ledger: {row.get('groupId')}")
        if row.get("status") == "fail":
            failed.update(unit_ids)
    counts = _counts(entries)
    for unit_id in failed:
        counts[unit_id] = counts.get(unit_id, 0) + 1
    return {"schemaVersion": SCHEMA, "lineage": value, "lineageSha256": here["lineageSha256"],
            "sequence": here["sequence"], "previousEntryJsonSha256": here["previousEntryJsonSha256"],
            "qcJsonSha256": json_sha256(qc), "failedSourceUnitIds": sorted(failed),
            "failedAttempts": dict(sorted(counts.items()))}


def load(root: Path, value: dict) -> list[dict]:
    """All entries of one ledger, checked as one unbroken chain."""
    folder = directory(root, value)
    names = sorted(path.name for path in folder.glob("*")) if folder.exists() else []
    _require(names == [f"entry-{index:06d}.json" for index in range(1, len(names) + 1)],
             "Repair ledger has a gap or a foreign file")
    entries = [json.loads((folder / name).read_text(encoding="utf-8")) for name in names]
    chain = chain_problems(value, entries)
    _require(not chain, "; ".join(chain))
    return entries


def append(root: Path, value: dict, qc: dict) -> dict:
    """Record ``qc`` as the next immutable entry; a concurrent run at the same position fails."""
    entry = next_entry(value, load(root, value), qc)
    folder = directory(root, value)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"entry-{entry['sequence']:06d}.json"
    # The complete entry is linked into place, so an interrupted append leaves no partial
    # entry; the temporary file sits beside the folder, which holds only entries.
    temporary = folder.parent / f".{folder.name}.{name}.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.link(temporary, folder / name)
    finally:
        temporary.unlink()
    return entry


def head_problems(value: dict, entries: list[dict], qc: dict) -> list[str]:
    """``qc`` must be the last entry of a consistent ledger for ``value``."""
    problems = chain_problems(value, entries)
    if problems:
        return problems
    if not entries or entries[-1]["qcJsonSha256"] != json_sha256(qc):
        return ["QC is not the head of its repair ledger"]
    if qc.get("repairLedger") != position(value, entries[:-1]):
        return ["QC did not screen from the repair ledger position before it"]
    return []
