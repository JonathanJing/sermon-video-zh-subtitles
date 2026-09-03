from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
INJECTABLE_STATUSES = {"approved", "corrected", "reviewed"}
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "has", "he", "in", "is", "it", "of", "on", "or", "our", "that", "the",
    "their", "this", "to", "was", "we", "were", "will", "with", "you",
}


class PackValidationError(ValueError):
    pass


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise PackValidationError(f"invalid JSON on line {line_number}: {error}") from error
        if not isinstance(record, dict):
            raise PackValidationError(f"line {line_number} must contain a JSON object")
        records.append(record)
    if not records:
        raise PackValidationError("segments JSONL is empty")
    return records


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _clean_scripture_refs(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PackValidationError("scriptureRefs must be an array")
    references: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, str):
            reference = _clean_text(item)
            if reference:
                references.append({"reference": reference, "status": "candidate"})
            continue
        if not isinstance(item, dict):
            raise PackValidationError("each scripture reference must be a string or object")
        reference = _clean_text(item.get("reference"))
        if reference:
            references.append({
                "reference": reference,
                "status": _clean_text(item.get("status") or "candidate").lower(),
            })
    return references


def _clean_terms(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PackValidationError("terms must be an array")
    terms: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, str):
            source = _clean_text(item)
            if source:
                terms.append({"source": source, "preferredZh": "", "status": "candidate"})
            continue
        if not isinstance(item, dict):
            raise PackValidationError("each term must be a string or object")
        source = _clean_text(item.get("source"))
        if not source:
            continue
        terms.append({
            "source": source,
            "preferredZh": _clean_text(item.get("preferredZh")),
            "status": _clean_text(item.get("status") or "candidate").lower(),
        })
    return terms


def _as_nonnegative_int(value: Any, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise PackValidationError(f"{field} must be an integer") from error
    if number < 0:
        raise PackValidationError(f"{field} must not be negative")
    return number


def _iso_end_of_day(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise PackValidationError("validUntil must be YYYY-MM-DD") from error
    return datetime.combine(parsed, time(23, 59, 59), timezone.utc).isoformat().replace("+00:00", "Z")


def build_weekly_pack(
    segments: Iterable[dict[str, Any]],
    *,
    service_date: str,
    source_id: str,
    audio_sha256: str,
    valid_until: str,
) -> dict[str, Any]:
    try:
        date.fromisoformat(service_date)
    except ValueError as error:
        raise PackValidationError("serviceDate must be YYYY-MM-DD") from error
    source_id = _clean_text(source_id)
    if not source_id:
        raise PackValidationError("sourceId is required")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", audio_sha256):
        raise PackValidationError("audioSha256 must be a 64-character SHA-256 hex digest")

    entries: list[dict[str, Any]] = []
    for index, segment in enumerate(segments, 1):
        segment_id = _clean_text(segment.get("segmentId") or f"seg_{index:06d}")
        source_en = _clean_text(segment.get("sourceTextEn"))
        if not source_en:
            raise PackValidationError(f"segment {segment_id} is missing sourceTextEn")
        start_ms = _as_nonnegative_int(segment.get("startMs", 0), "startMs")
        end_ms = _as_nonnegative_int(segment.get("endMs", start_ms), "endMs")
        if end_ms < start_ms:
            raise PackValidationError(f"segment {segment_id} ends before it starts")
        target_zh = _clean_text(segment.get("targetTextZh"))
        translation_status = _clean_text(
            segment.get("translationStatus") or segment.get("reviewStatus") or "machine_generated"
        ).lower()
        transcript_status = _clean_text(segment.get("transcriptStatus") or "machine_generated").lower()
        terms = _clean_terms(segment.get("terms"))
        scripture_refs = _clean_scripture_refs(segment.get("scriptureRefs"))
        injectable_scripture_refs = [
            reference["reference"] for reference in scripture_refs
            if reference["status"] in INJECTABLE_STATUSES
        ]
        can_inject_translation = bool(target_zh and translation_status in INJECTABLE_STATUSES)
        injectable_terms = [
            term for term in terms
            if term["preferredZh"] and term["status"] in INJECTABLE_STATUSES
        ]
        entry_seed = f"{source_id}\n{segment_id}\n{source_en}\n{target_zh}".encode("utf-8")
        entries.append({
            "entryId": hashlib.sha256(entry_seed).hexdigest()[:20],
            "segmentId": segment_id,
            "audioStartMs": start_ms,
            "audioEndMs": end_ms,
            "sourceTextEn": source_en,
            "candidateTargetTextZh": target_zh,
            "translationStatus": translation_status,
            "transcriptStatus": transcript_status,
            "canInjectTranslation": can_inject_translation,
            "scriptureRefs": scripture_refs,
            "injectableScriptureRefs": injectable_scripture_refs,
            "terms": terms,
            "injectableTerms": injectable_terms,
        })

    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    pack_version = f"weekly-{service_date}-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:12]}"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "packType": "weekly",
        "packVersion": pack_version,
        "status": "active",
        "sourceType": "saturday_livestream",
        "serviceDate": service_date,
        "validUntil": _iso_end_of_day(valid_until),
        "provenance": {
            "sourceId": source_id,
            "audioSha256": audio_sha256.lower(),
            "segmentCount": len(entries),
        },
        "policy": {
            "machineTranslationInjectable": False,
            "currentLiveEnglishIsSourceOfTruth": True,
            "maxRuntimeHits": 8,
        },
        "entries": entries,
    }


def write_pack(pack: dict[str, Any], path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)


def load_pack(path: str | Path) -> dict[str, Any]:
    try:
        pack = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PackValidationError(f"unable to load context pack: {error}") from error
    if pack.get("schemaVersion") != SCHEMA_VERSION:
        raise PackValidationError("unsupported context pack schemaVersion")
    if pack.get("packType") != "weekly" or not isinstance(pack.get("entries"), list):
        raise PackValidationError("invalid weekly context pack")
    return pack


def _tokens(text: str) -> set[str]:
    values = re.findall(r"[a-z0-9']+", text.lower())
    return {value for value in values if len(value) > 1 and value not in STOPWORDS}


def _normal(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", text.lower()))


def _pack_is_active(pack: dict[str, Any], now: datetime) -> bool:
    if pack.get("status") != "active":
        return False
    try:
        valid_until = datetime.fromisoformat(str(pack["validUntil"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return False
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now <= valid_until


def retrieve(
    pack: dict[str, Any],
    source_text_en: str,
    *,
    limit: int = 5,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    source_text_en = _clean_text(source_text_en)
    if not source_text_en or not 1 <= limit <= 8:
        return []
    current_time = now or datetime.now(timezone.utc)
    if not _pack_is_active(pack, current_time):
        return []

    query_tokens = _tokens(source_text_en)
    query_normal = _normal(source_text_en)
    ranked: list[tuple[float, dict[str, Any]]] = []
    for entry in pack["entries"]:
        entry_source = _clean_text(entry.get("sourceTextEn"))
        entry_normal = _normal(entry_source)
        entry_tokens = _tokens(entry_source)
        exact_match = bool(query_normal and entry_normal and query_normal == entry_normal)
        phrase_match = bool(
            query_normal and entry_normal and not exact_match
            and (query_normal in entry_normal or entry_normal in query_normal)
        )
        overlap = len(query_tokens & entry_tokens) / max(1, len(query_tokens))
        term_matches = [
            term for term in entry.get("terms", [])
            if _normal(term.get("source", "")) in query_normal
        ]
        scripture_matches = [
            reference for reference in entry.get("scriptureRefs", [])
            if _normal(reference.get("reference", ""))
            and _normal(reference.get("reference", "")) in query_normal
        ]
        score = (
            (4.0 if exact_match else 0.0)
            + (1.5 if phrase_match else 0.0)
            + overlap * 3.0
            + len(term_matches) * 1.5
            + len(scripture_matches) * 2.0
        )
        if score < 0.55:
            continue
        translation_reviewed = bool(entry.get("canInjectTranslation"))
        can_inject_this_hit = bool(translation_reviewed and exact_match)
        ranked.append((score, {
            "entryId": entry["entryId"],
            "segmentId": entry["segmentId"],
            "score": round(score, 4),
            "exactMatch": exact_match,
            "phraseMatch": phrase_match,
            "sourceTextEn": entry_source,
            "targetTextZh": entry.get("candidateTargetTextZh") if can_inject_this_hit else None,
            "hasCandidateMachineTranslation": bool(entry.get("candidateTargetTextZh") and not translation_reviewed),
            "hasReviewedTranslation": bool(entry.get("candidateTargetTextZh") and translation_reviewed),
            "translationStatus": entry.get("translationStatus"),
            "canInjectTranslation": can_inject_this_hit,
            "scriptureRefs": [reference["reference"] for reference in entry.get("scriptureRefs", [])],
            "injectableScriptureRefs": entry.get("injectableScriptureRefs", []),
            "injectableTerms": entry.get("injectableTerms", []),
            "audioStartMs": entry.get("audioStartMs"),
            "audioEndMs": entry.get("audioEndMs"),
            "provenance": {
                "packVersion": pack["packVersion"],
                "sourceId": pack["provenance"]["sourceId"],
                "audioSha256": pack["provenance"]["audioSha256"],
                "serviceDate": pack["serviceDate"],
            },
        }))
    ranked.sort(key=lambda item: (-item[0], item[1]["audioStartMs"], item[1]["entryId"]))
    return [hit for _, hit in ranked[:limit]]


def prompt_context(hits: Iterable[dict[str, Any]]) -> dict[str, Any]:
    terms: dict[str, str] = {}
    exact_examples: list[dict[str, str]] = []
    scripture_refs: set[str] = set()
    for hit in hits:
        for term in hit.get("injectableTerms", []):
            terms[term["source"]] = term["preferredZh"]
        scripture_refs.update(hit.get("injectableScriptureRefs", []))
        if hit.get("canInjectTranslation") and hit.get("targetTextZh"):
            exact_examples.append({
                "sourceTextEn": hit["sourceTextEn"],
                "targetTextZh": hit["targetTextZh"],
            })
    return {
        "approvedTerms": [{"source": source, "preferredZh": target} for source, target in sorted(terms.items())],
        "verifiedScriptureRefs": sorted(scripture_refs),
        "reviewedExactExamples": exact_examples[:2],
    }
