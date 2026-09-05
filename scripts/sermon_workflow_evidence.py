"""Bounded, read-only snapshots of known sermon workflow receipts.

File presence proves neither a current execution nor publication. This module
never follows artifact paths stored inside receipts or inspects arbitrary JSON.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

MAX_JSON_BYTES = 1_048_576
MAX_WEEK_ENTRIES = 128
SCHEMA = "sermon-workflow-evidence-v1"
# Exact relative paths, including layouts accepted by standalone tools.
PATHS = {
    "same_video_source": ("same-video-source.json",),
    "same_video_archive": ("same-video-archive.json",),
    "same_video_handoff": ("same-video-reviewed-handoff.json",),
    "same_video_pdf_render": ("same-video-pdfs/render-receipt.json",),
    "source": ("source.json", "source-receipt.json", "download/local-download-manifest.json", "download/source-metadata.json", "source_clip.m4a.cache.json", "pipeline/source_clip.m4a.cache.json"),
    "summary": ("summary.json", "pipeline/summary.json"),
    "reading": ("reading_quality_report.json", "reading-edition-v2/reading_quality_report.json", "pipeline/reading-edition-v2/reading_quality_report.json"),
    "reading_pdf_qa": ("sermon_zh_en_reading.qa.json", "pipeline/sermon_zh_en_reading.qa.json", "same-video-pdfs/sermon_zh_en_reading.qa.json"),
    "companion_pdf_qa": ("sermon_interpretation_zh.qa.json", "pipeline/sermon_interpretation_zh.qa.json", "same-video-pdfs/sermon_interpretation_zh.qa.json"),
    "notes": ("openai-notes.json", "insights/openai-notes.json", "sermon-interpretation/insights/openai-notes.json", "pipeline/sermon-interpretation/insights/openai-notes.json"),
    "context_pack": ("weekly-pack.json", "sunday-context/weekly-pack.json", "sunday-context/manifest.json", "sunday-context/pack-readiness.json", "pipeline/sunday-context/weekly-pack.json", "pipeline/sunday-context/manifest.json", "pipeline/sunday-context/pack-readiness.json", "manifest.json", "pack-readiness.json", "context-pack/manifest.json", "context-pack/pack-readiness.json", "saturday-context-pack/manifest.json", "saturday-context-pack/pack-readiness.json"),
    "window_approval": ("sunday-context/message-identity-approval.json", "pipeline/sunday-context/message-identity-approval.json", "operator-window-approval.json", "message-identity-approval.json", "context-pack/message-identity-approval.json"),
    "timeline": ("timeline/report.json",),
    "generation": ("agent-generation-report.json", "run-status.json"),
    "job": ("job.json",),
    "render": ("render/report.json", "assembly-report.json"),
    "audio_qa": ("audio/asr-screening.json", "audio-review.json", "audio-review-synced.json"),
    "synchronization": ("synchronization/report.json", "synchronization/assembly.json"),
    "anchor_approval": ("source-alignment/anchor-model-review.json", "source-alignment/anchor-review.json"),
    "alignment": ("source-alignment/report.json",),
    "workflow_receipt": ("workflow-receipt.json", "workflow-report.json", "saturday-completion.json", "bridge-latest.json"),
}
HASH_FIELDS = {"sha256", "sourceAudioSha256", "sourceSha256", "sourceHash", "mediaSha256", "sermonClipSha256", "sourceUrlHash", "jobSha256", "alignmentSha256", "anchorReviewSha256", "mp3Sha256", "checkpointSha256", "readingInputFingerprint", "pipelineInputFingerprint", "inputFingerprint", "outputSha256", "timingReportSha256", "segmentSourceSha256", "englishBlocksSha256", "wordsSha256", "sourceNaturalMp3Sha256", "sourceNaturalWavSha256", "authorizationSha256"}
IDENTITY_FIELDS = {"packType", "sourceType", "contextPolicy", "runtimeMode", "sourceId", "videoId", "runId", "packId", "packVersion", "speakerKey", "schemaVersion", "status", "stage", "reviewType", "model", "translationModel", "transcriptionModel", "classifierModel", "readingEditModel", "reasoningEffort", "translationEffort", "provider", "revision", "promptVersion", "qaPromptVersion", "qualityRuleVersion", "timeOrigin", "outputMode", "timingPrecision", "fullDecode", "humanReview", "humanAudioReview", "humanListeningStatus", "matchStatus", "publicationRecheck", "sameVideoSynchronization"}
DATE_FIELDS = {"evaluatedAt", "week", "sunday", "date", "serviceDate", "sourceServiceDate", "targetSunday", "createdAt", "completedAt", "approvedAt", "reviewedAt", "recordedAt", "notBefore", "validUntil"}
BOOL_FIELDS = {"alignmentEnabled", "approvedTermsReady", "asrPhraseCandidatesReady", "englishMapReady", "reviewedExamplesReady", "verifiedScriptureReady", "humanApproval", "generationComplete", "requiresOperatorReview", "machineChineseInjectable", "machineTranslationInjectable", "humanListeningPerformed", "currentLiveEnglishIsSourceOfTruth", "readingTextReplaced"}
NUMBER_FIELDS = {"asrPhraseCandidateCount", "machineTranslationViolationCount", "reviewedExampleCount", "reviewedTermCount", "verifiedScriptureCount", "blockCount", "segmentCount", "unitCount", "cueCount", "sliceCount", "pageCount", "screenedUnits", "expectedUnits", "durationSeconds", "sourceDurationSeconds", "sourceStartSeconds", "sourceEndSeconds", "startSeconds", "endSeconds", "start", "end", "fullVideoOffsetSeconds", "overflowSeconds", "availableSeconds", "naturalSeconds", "requiredSpeed", "passes", "englishCharacters", "chineseCharacters", "sourceSubtitleSegmentCount", "finalReadingBlockCount", "approvedBilingualCount", "phraseCount", "sourceSegmentCount", "reviewedSegmentCount", "rejectedCount", "approvedCount", "candidateCount"}
# Only these named containers may be traversed, and only to a bounded depth.
CONTAINERS = {"policy", "counts", "capabilities", "provenance", "voice", "review", "inheritedReview", "timing", "validity", "pipeline", "models", "metrics", "comparisonToSubtitleDraft", "analysis", "suggestedWindow", "messageIdentity", "approval", "inputs", "artifacts", "sourceAudio", "sermonClip", "reading", "readingQuality", "readingPdfQa", "companionPdfQa", "summary", "outline", "source", "audio", "video", "clipReceipt", "windowApproval", "timeline", "generationReport", "english", "chinese", "asr", "translation", "correction"}
COUNT_LISTS = {"entries", "blocks", "units", "segments", "cues", "results", "outline", "quotes", "slices", "reviewCandidates", "failures", "issues", "unresolved", "unresolvedBoundaryIssues", "blockers", "unexpectedEnglishTokens", "lengthRatioOutliers", "sourceTermCoverageErrors", "bilingualReferenceMismatches"}
BLOCKER_LISTS = {"failures", "issues", "unresolved", "unresolvedBoundaryIssues", "blockers"}
# Unknown prose/error strings are counted, never copied into accounting receipts.
BLOCKER_CODES = {"legacy_pack_expired", "message_match_not_confirmed:unknown", "pack_expired", "unexpected_english_tokens", "missing_required_english_tokens",
    "weak_boundary_anchor", "natural_chinese_exceeds_video_slot", "missing_anchor",
    "missing_audio", "source_hash_mismatch", "job_hash_mismatch", "needs_revision",
    "requires_operator_review", "human_review_pending", "bilingual_reference_mismatches",
    "source_term_coverage_errors", "length_ratio_outliers", "unbalanced_quotes",
    "missing_terminal_punctuation", "ellipsis", "oral_fillers", "dangling_fragments"}
SAFE_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}\Z")
HASH = re.compile(r"[0-9a-fA-F]{64}\Z")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:T[0-9:.+-]+Z?)?\Z")
SOURCE_FIELDS = {"sourceId", "videoId", "sourceAudioSha256", "sourceSha256", "mediaSha256", "sermonClipSha256", "serviceDate", "sourceServiceDate", "sourceStartSeconds", "sourceEndSeconds", "sourceDurationSeconds"}
HASH_FIELDS.update({"sourceVideoSha256", "sourceContractSha256", "sourceContractIdentitySha256"})
SOURCE_FIELDS.update({"sourceVideoSha256", "sourceContractSha256"})
IDENTITY_FIELDS.update({"sourceRoute", "boundaryBasis", "humanWindow"})
BOOL_FIELDS.update({"sameVersionConfirmed", "sermonOnly"})
CONTAINERS.update({"sourceContract", "sameVideoArchive", "sameVideoHandoff"})


def _code(value):
    return isinstance(value, str) and bool(SAFE_CODE.fullmatch(value)) and "://" not in value


def _summary(data, depth=0):
    if not isinstance(data, dict) or depth > 4:
        return {}
    result = {}
    for key, value in data.items():
        if key in HASH_FIELDS and isinstance(value, str) and HASH.fullmatch(value):
            result[key] = value.lower()
        elif key in {"sourceId", "videoId"} and isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
            result[key] = value
        elif key in IDENTITY_FIELDS and (_code(value) or key == "schemaVersion" and isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 1000):
            result[key] = value
        elif key in DATE_FIELDS and isinstance(value, str) and DATE.fullmatch(value):
            result[key] = value
        elif key in BOOL_FIELDS and isinstance(value, bool):
            result[key] = value
        elif key in NUMBER_FIELDS and isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1e15 and math.isfinite(value):
            result[key] = value
        elif key in COUNT_LISTS and isinstance(value, list):
            details = {"count": len(value)}
            if key in BLOCKER_LISTS:
                codes = sorted({item for item in value if isinstance(item, str) and item in BLOCKER_CODES})
                codes += sorted({item[k] for item in value if isinstance(item, dict) for k in ("code", "reason", "kind") if isinstance(item.get(k), str) and item[k] in BLOCKER_CODES})
                details["codes"] = sorted(set(codes))[:64]
                details["detailsOmitted"] = True
            if key == "results":
                details["items"] = [_summary(item, depth + 1) for item in value[:16] if isinstance(item, dict)]
            result[key] = details
        elif key in CONTAINERS and isinstance(value, dict):
            nested = _summary(value, depth + 1)
            if nested:
                result[key] = nested
    return result


def _safe_file(root, relative):
    """Reject symlinks at every path component, including links inside the root."""
    current = root
    for part in relative.parts:
        current = current / part
        mode = current.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError("symlink_rejected")
    if not stat.S_ISREG(mode):
        raise ValueError("not_regular_file")
    current.resolve().relative_to(root)
    with os.fdopen(os.open(current, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb") as stream:
        data = stream.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("oversized_json")
    return data


def _expected(workflow):
    value = workflow.lower()
    if value == "same_video_intake":
        return {"same_video_source", "same_video_archive"}
    if value == "same_video_handoff":
        return {"same_video_source", "same_video_archive", "same_video_handoff", "same_video_pdf_render", "reading_pdf_qa", "companion_pdf_qa"}
    if "dubb" in value:
        return {"job", "render", "audio_qa", "alignment", "anchor_approval", "synchronization", "workflow_receipt"}
    if "reading" in value:
        return {"reading"}
    if "notes" in value or "interpretation" in value:
        return {"notes", "companion_pdf_qa"}
    if "timeline" in value:
        return {"timeline", "window_approval"}
    return {"summary", "reading", "reading_pdf_qa", "companion_pdf_qa", "generation", "window_approval", "context_pack"}


def _source_identity(summary):
    found = {}
    def visit(node, prefix=""):
        for key, value in node.items():
            if isinstance(value, dict):
                visit(value, prefix + key + ".")
            elif key in SOURCE_FIELDS or key == "sha256" and prefix in {"inputs.sourceAudio.", "artifacts.sourceAudio.", "sourceAudio."}:
                found[prefix + key] = value
    visit(summary)
    return found


def collect_workflow_evidence(directory: Path, workflow: str) -> dict:
    """Return bounded existing-file evidence, never a current-run success claim."""
    workflow = workflow if _code(workflow) else "unspecified"
    result = {"schemaVersion": SCHEMA, "workflow": workflow,
              "observedAt": datetime.now(timezone.utc).isoformat(),
              "evidenceScope": "existing_files_snapshot", "currentRunExecutionProven": False,
              "artifacts": [], "errors": [], "missingCategories": [],
              "limits": {"maxJsonBytes": MAX_JSON_BYTES, "maxWeekEntries": MAX_WEEK_ENTRIES,
                         "lookup": "fixed_relative_paths_and_sermon_prefix_direct_children_only"}}
    try:
        root = Path(directory).resolve()
        available = root.is_dir()
    except (OSError, RuntimeError):
        available = False
    if not available:
        result["errors"].append({"path": ".", "code": "directory_missing"})
        result["missingCategories"] = sorted(_expected(workflow))
        result["status"] = "evidence_gaps"
        return result
    prefixes = [Path()]
    try:
        with os.scandir(root) as entries:
            children = list(itertools.islice(entries, MAX_WEEK_ENTRIES + 1))
        if len(children) > MAX_WEEK_ENTRIES:
            result["errors"].append({"path": ".", "code": "direct_child_inventory_truncated"})
        for entry in children[:MAX_WEEK_ENTRIES]:
            if re.fullmatch(r"sermon_[A-Za-z0-9_-]{1,128}", entry.name):
                if entry.is_symlink():
                    result["errors"].append({"path": entry.name, "code": "symlink_rejected"})
                elif entry.is_dir(follow_symlinks=False):
                    prefixes.append(Path(entry.name))
    except OSError:
        result["errors"].append({"path": ".", "code": "directory_unreadable"})
    categories = set()
    identities = []
    for prefix in prefixes:
        for category, paths in PATHS.items():
            for name in paths:
                relative = prefix / name
                try:
                    raw = _safe_file(root, relative)
                except FileNotFoundError:
                    continue
                except (OSError, ValueError) as exc:
                    code = str(exc) if isinstance(exc, ValueError) and str(exc) in {"symlink_rejected", "not_regular_file", "oversized_json"} else "file_unreadable"
                    result["errors"].append({"path": relative.as_posix(), "code": code})
                    continue
                digest = hashlib.sha256(raw).hexdigest()
                try:
                    data = json.loads(raw)
                    if not isinstance(data, dict):
                        raise ValueError("not_object")
                except (ValueError, UnicodeError, RecursionError):
                    result["errors"].append({"path": relative.as_posix(), "sha256": digest, "code": "invalid_json_object"})
                    continue
                # Avoid interpreting an unrelated generic manifest as a Context Pack.
                if category == "context_pack" and relative.name == "manifest.json" and not str(data.get("schemaVersion", "")).startswith("weekly-context-pack-"):
                    result["errors"].append({"path": relative.as_posix(), "sha256": digest, "code": "unrecognized_context_manifest_schema"})
                    continue
                if category == "context_pack" and relative.name == "weekly-pack.json" and not (data.get("packType") == "weekly" and data.get("schemaVersion") == 1):
                    result["errors"].append({"path": relative.as_posix(), "sha256": digest, "code": "unrecognized_weekly_pack_schema"})
                    continue
                summary = _summary(data)
                categories.add(category)
                identity = _source_identity(summary)
                if identity:
                    identities.append(identity)
                result["artifacts"].append({"path": relative.as_posix(), "sha256": digest,
                                            "bytes": len(raw), "category": category,
                                            "executionAssociation": "not_established",
                                            "summary": summary})
    result["artifacts"].sort(key=lambda item: item["path"])
    result["missingCategories"] = sorted(_expected(workflow) - categories)
    unique_identities = sorted({json.dumps(item, sort_keys=True, separators=(",", ":")) for item in identities})
    result["sourceIdentityClaims"] = [json.loads(item) for item in unique_identities]
    result["sourceFingerprint"] = hashlib.sha256(json.dumps(unique_identities).encode()).hexdigest() if unique_identities else None
    result["sourceFingerprintMeaning"] = "digest_of_reported_identity_claims_not_media_verification"
    snapshot = [{"path": item["path"], "sha256": item["sha256"]} for item in result["artifacts"]]
    result["evidenceFingerprint"] = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    result["reportedBlockers"] = []
    for item in result["artifacts"]:
        summary = item["summary"]
        counts = {key: summary[key]["count"] for key in BLOCKER_LISTS if key in summary and summary[key]["count"]}
        if counts or summary.get("status") in {"failed", "needs_revision", "requires_operator_review", "needs_timing_review", "anchor_review_required", "blocked", "invalid"}:
            result["reportedBlockers"].append({"path": item["path"], "status": summary.get("status"), "counts": counts})
    result["missingCategoryMeaning"] = "not_found_in_bounded_lookup_not_proof_of_failed_or_required_stage"
    result["status"] = "evidence_gaps" if result["errors"] or result["missingCategories"] else "snapshot_collected"
    return result
