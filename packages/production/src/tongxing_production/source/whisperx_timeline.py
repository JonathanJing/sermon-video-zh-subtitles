#!/usr/bin/env python3
"""Production timeline revision: WhisperX forced alignment of an approved English source.

The parent English Source Package already binds the human-approved text, source
media and window. This producer changes **only the word/unit timing**: it aligns
the parent unit text with WhisperX wav2vec2, validates the token sequence and
timeline, and writes a new candidate anchor manifest + English Source Package.
The text and unit IDs are never rewritten; a changed Layer 1 identity invalidates
downstream locales, so a new run is required.

Approval is a separate operator action. A candidate package is always
``translationEligible=false`` and ``review.humanApproval=false``. After the
operator listens to the review page, ``--approve`` writes an approved package
next to the candidate without overwriting it.

Run through the package CLI::

    .venv/bin/python tools/ops/run.py source.whisperx_timeline \
      --english-source <layer1>/english-source.json \
      --out <layer1>/whisperx-timeline \
      --runtime-python artifacts/whisperx-timeline-ab/runtime/bin/python
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any

SCHEMA = "sermon-whisperx-timeline-receipt-v1"
PACKAGE_SCHEMA = "sermon-english-source-package-v1"
ANCHOR_SCHEMA = "sermon-sentence-anchor-manifest-v2"
REQUEST_SCHEMA = "sermon-whisperx-alignment-request-v1"
RESULT_SCHEMA = "sermon-whisperx-alignment-result-v1"
TOKEN_RE = re.compile(r"[a-z0-9]+(?:['’][a-z0-9]+)?", re.I)
RELATIVE_REPO = Path(__file__).resolve().parents[5]


class TimelineError(ValueError):
    """A fail-closed producer error with a stable machine code."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TimelineError("json_unreadable", f"{label}: {path}: {exc}") from exc


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def normalized_tokens(text: str) -> list[str]:
    return [token.lower().replace("’", "'") for token in TOKEN_RE.findall(text or "")]


def _finite(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise TimelineError(code, detail)


def resolve_path(value: str | Path, root: Path = RELATIVE_REPO) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _evidence(path: Path, value: Any | None = None) -> dict:
    path = path.resolve()
    _require(path.is_file(), "artifact_missing", str(path))
    item = {"path": str(path.relative_to(RELATIVE_REPO)) if str(path).startswith(str(RELATIVE_REPO)) else str(path),
            "sha256": sha256_file(path)}
    if value is not None:
        item["jsonSha256"] = sha256_json(value)
    return item


def _package_ref(path: Path, value: dict) -> dict:
    ref = _evidence(path, value)
    return ref


def _manifest_ref(path: Path, value: dict) -> dict:
    return _evidence(path, value)


def _unit_tokens(unit: dict) -> list[str]:
    text = " ".join(str(unit.get("english", "")).split())
    tokens = text.split()
    _require(bool(tokens), "unit_text_empty", str(unit.get("sourceUnitId")))
    return tokens


def _unit_word_tokens(unit: dict) -> list[str]:
    words = unit.get("words")
    _require(isinstance(words, list) and bool(words), "unit_words_missing", str(unit.get("sourceUnitId")))
    return [str(word.get("text", "")) for word in words]


def _normalized_sequence(tokens: list[str]) -> list[str]:
    result = []
    for token in tokens:
        parts = normalized_tokens(token)
        _require(len(parts) == 1, "word_not_single_token", token)
        result.append(parts[0])
    return result


def build_chunks(units: list[dict], *, target_seconds: float = 18.0,
                 max_seconds: float = 24.0, gap_seconds: float = 1.0) -> list[dict]:
    _require(units, "parent_has_no_units")
    chunks: list[dict] = []
    current: list[int] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        first, last = current[0], current[-1]
        text = " ".join(" ".join(str(units[index]["english"]).split()) for index in current)
        token_count = sum(len(_unit_tokens(units[index])) for index in current)
        chunks.append({
            "id": f"c{len(chunks):04d}",
            "start": round(float(units[first]["start"]), 6),
            "end": round(float(units[last]["end"]), 6),
            "text": text,
            "tokenCount": token_count,
            "units": [{"unitIndex": index, "sourceUnitId": units[index]["sourceUnitId"],
                       "tokenStart": sum(len(_unit_tokens(units[j])) for j in current[:position]),
                       "tokenCount": len(_unit_tokens(units[index]))}
                      for position, index in enumerate(current)],
        })
        current = []

    for index, unit in enumerate(units):
        if current:
            gap = float(unit["start"]) - float(units[current[-1]]["end"])
            if gap >= gap_seconds:
                flush()
        current.append(index)
        span = float(units[current[-1]]["end"]) - float(units[current[0]]["start"])
        if span >= target_seconds or len(current) >= 8 or span >= max_seconds:
            flush()
    flush()
    for chunk in chunks:
        _require(float(chunk["end"]) > float(chunk["start"]), "chunk_empty", chunk["id"])
    return chunks


def _clip_audio(media: Path, out: Path, start: float, duration: float) -> None:
    _require(duration > 0, "window_empty")
    if out.exists():
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{start:.6f}", "-t", f"{duration:.6f}",
        "-i", str(media), "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out),
    ], check=True)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
        check=True, capture_output=True, text=True).stdout.strip()
    actual = float(probe)
    _require(abs(actual - duration) <= 0.08, "clip_duration_mismatch",
             f"{actual:.3f}s for {duration:.3f}s")


def _run_adapter(runtime_python: str, adapter: Path, request: Path, result: Path,
                 *, device: str, language: str) -> dict:
    _require(Path(runtime_python).is_file(), "runtime_python_missing", runtime_python)
    _require(adapter.is_file(), "runtime_adapter_missing", str(adapter))
    command = [runtime_python, str(adapter), "--request", str(request), "--out", str(result),
               "--device", device, "--language", language]
    started = time.monotonic()
    proc = subprocess.run(command, capture_output=True, text=True)
    elapsed = round(time.monotonic() - started, 3)
    if proc.returncode != 0:
        tail = " | ".join((proc.stderr or proc.stdout).strip().splitlines()[-8:])
        raise TimelineError("alignment_runtime_failed", f"exit {proc.returncode}: {tail}")
    payload = read_json(result, "alignment result")
    _require(payload.get("schemaVersion") == RESULT_SCHEMA, "alignment_result_schema")
    payload["producerElapsedSeconds"] = elapsed
    return payload


def _validate_alignment(units: list[dict], chunks: list[dict], result: dict,
                        duration: float, *, max_word_seconds: float,
                        flag_word_seconds: float) -> tuple[list[dict], list[dict]]:
    by_chunk = {str(chunk.get("id")): chunk for chunk in result.get("chunks", [])
                if isinstance(chunk, dict)}
    _require(set(by_chunk) == {chunk["id"] for chunk in chunks}, "alignment_chunk_coverage")
    aligned_units: list[dict] = []
    issues: list[dict] = []
    previous_end = 0.0
    for chunk in chunks:
        payload = by_chunk[chunk["id"]]
        words = payload.get("words")
        _require(isinstance(words, list) and words, "alignment_chunk_empty", chunk["id"])
        _require(len(words) == chunk["tokenCount"], "alignment_token_count_mismatch",
                 f"{chunk['id']}: {len(words)} != {chunk['tokenCount']}")
        expected = normalized_tokens(chunk["text"])
        got = [token for word in words for token in normalized_tokens(str(word.get("text", "")))]
        _require(got == expected, "alignment_token_sequence_mismatch", chunk["id"])
        for word in words:
            text = str(word.get("text", "")).strip()
            _require(bool(text), "alignment_word_empty", chunk["id"])
            start, end = word.get("start"), word.get("end")
            _require(_finite(start) and _finite(end), "alignment_time_nonfinite", text)
            start, end = float(start), float(end)
            _require(0 <= start < end <= duration + 0.05, "alignment_time_out_of_bounds", text)
            _require(start >= previous_end - 0.001, "alignment_non_monotonic", text)
            previous_end = end
            if end - start > max_word_seconds:
                raise TimelineError("alignment_word_too_long", f"{text}: {end - start:.3f}s")
            if end - start > flag_word_seconds:
                issues.append({"type": "word_duration_outlier", "text": text,
                               "start": round(start, 4), "end": round(end, 4),
                               "durationSeconds": round(end - start, 4)})
        cursor = 0
        for unit_index in chunk["units"]:
            unit = units[unit_index["unitIndex"]]
            unit_words = words[cursor:cursor + unit_index["tokenCount"]]
            cursor += unit_index["tokenCount"]
            _require(bool(unit_words), "alignment_unit_empty", unit["sourceUnitId"])
            aligned_units.append({
                "unitIndex": unit_index["unitIndex"],
                "sourceUnitId": unit["sourceUnitId"],
                "english": " ".join(str(unit["english"]).split()),
                "words": [{"text": str(word["text"]).strip(),
                           "start": round(float(word["start"]), 6),
                           "end": round(float(word["end"]), 6)} for word in unit_words],
                "chunkId": chunk["id"],
            })
    _require(len(aligned_units) == len(units), "alignment_unit_coverage")
    for aligned in aligned_units:
        previous = aligned_units[aligned["unitIndex"] - 1] if aligned["unitIndex"] else None
        if previous and aligned["words"][0]["start"] < previous["words"][-1]["end"] - 0.001:
            raise TimelineError("alignment_unit_overlap", aligned["sourceUnitId"])
    return aligned_units, issues


def _build_manifest(parent: dict, aligned_units: list[dict], *, parent_anchor: Path,
                    parent_anchor_sha: str, words_sha: str, text_sha: str,
                    source: dict, runtime: dict, window: dict) -> dict:
    manifest = copy.deepcopy(parent)
    units = manifest.get("sourceUnits")
    _require(isinstance(units, list) and len(units) == len(aligned_units), "parent_unit_count_changed")
    updated = []
    for unit, aligned in zip(units, aligned_units):
        _require(unit.get("sourceUnitId") == aligned["sourceUnitId"], "unit_identity_reordered")
        new = copy.deepcopy(unit)
        words = aligned["words"]
        new["start"] = round(words[0]["start"], 6)
        new["end"] = round(words[-1]["end"], 6)
        new["words"] = words
        boundary = copy.deepcopy(new.get("boundary") or {})
        boundary["pauseAfterSeconds"] = 0.0
        new["boundary"] = boundary
        updated.append(new)
    for index, unit in enumerate(updated):
        next_start = updated[index + 1]["start"] if index + 1 < len(updated) else unit["end"]
        unit["boundary"]["pauseAfterSeconds"] = round(max(0.0, next_start - unit["end"]), 6)
    manifest["sourceUnits"] = updated
    manifest["status"] = "machine_anchor_candidate_requires_review"
    manifest["releaseEligible"] = False
    policy = copy.deepcopy(manifest.get("policy") or {})
    policy["timingBasis"] = "whisperx_wav2vec2_forced_alignment"
    policy["timelineProducer"] = "whisperx-timeline-v1"
    manifest["policy"] = policy
    input_value = copy.deepcopy(manifest.get("input") or {})
    input_value.update({
        "mfaSegmentsSha256": words_sha,
        "alignmentNote": "WhisperX wav2vec2 forced alignment of the frozen approved text; "
                         "text and unit IDs unchanged.",
        "parentAnchor": str(parent_anchor),
        "parentAnchorSha256": parent_anchor_sha,
        "mediaSha256": source["mediaSha256"],
        "mediaDurationSeconds": source["mediaDurationSeconds"],
        "windowStartSeconds": window["start"],
        "windowEndSeconds": window["end"],
        "textSha256": text_sha,
        "timingKind": "whisperx_forced_alignment_estimate",
        "whisperx": runtime,
    })
    manifest["input"] = input_value
    human = copy.deepcopy(manifest.get("humanReview") or {})
    human["wordAlignment"] = "pending"
    manifest["humanReview"] = human
    manifest["counts"] = {
        **(manifest.get("counts") or {}),
        "sourceUnits": len(updated),
        "sourceWords": sum(len(unit["words"]) for unit in updated),
    }
    manifest["issues"] = []
    return manifest


def _build_flat_words(aligned_units: list[dict]) -> list[dict]:
    return [{"text": word["text"], "start": word["start"], "end": word["end"]}
            for unit in aligned_units for word in unit["words"]]


def _build_segments(aligned_units: list[dict], units: list[dict]) -> list[dict]:
    segments = []
    for aligned, unit in zip(aligned_units, units):
        segments.append({
            "id": aligned["unitIndex"],
            "referenceChunkId": unit["sourceUnitId"],
            "start": aligned["words"][0]["start"],
            "end": aligned["words"][-1]["end"],
            "text": " ".join(str(unit["english"]).split()),
            "source": "whisperx",
            "timingQuality": "whisperx_forced_alignment_estimate",
            "requires_operator_review": True,
            "wordTimes": aligned["words"],
        })
    return segments


def _shift_summary(units: list[dict], aligned_units: list[dict]) -> dict:
    starts, ends = [], []
    for unit, aligned in zip(units, aligned_units):
        starts.append(abs(float(unit["start"]) - aligned["words"][0]["start"]))
        ends.append(abs(float(unit["end"]) - aligned["words"][-1]["end"]))
    def block(values: list[float]) -> dict:
        ordered = sorted(values)
        def pct(fraction: float) -> float:
            position = (len(ordered) - 1) * fraction
            lower = int(position)
            upper = min(lower + 1, len(ordered) - 1)
            return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 6)
        return {
            "count": len(values),
            "p50": pct(0.50), "p90": pct(0.90), "p95": pct(0.95), "max": round(max(values), 6),
            "over100ms": sum(value > 0.1 for value in values),
            "over250ms": sum(value > 0.25 for value in values),
            "over500ms": sum(value > 0.5 for value in values),
            "over1000ms": sum(value > 1.0 for value in values),
        }
    return {"start": block(starts), "end": block(ends)}


def _review_rows(units: list[dict], aligned_units: list[dict], *, flag_word_seconds: float) -> list[dict]:
    rows = []
    for unit, aligned in zip(units, aligned_units):
        start, end = aligned["words"][0]["start"], aligned["words"][-1]["end"]
        start_shift = abs(float(unit["start"]) - start)
        end_shift = abs(float(unit["end"]) - end)
        flags = []
        if start_shift > 0.25:
            flags.append("start_shift_over_250ms")
        if end_shift > 0.25:
            flags.append("end_shift_over_250ms")
        if end - start > 30:
            flags.append("unit_over_30s")
        long_words = [word for word in aligned["words"] if word["end"] - word["start"] > flag_word_seconds]
        if long_words:
            flags.append("word_duration_outlier")
        rows.append({
            "unitId": unit["sourceUnitId"],
            "english": " ".join(str(unit["english"]).split()),
            "parentStart": round(float(unit["start"]), 4),
            "parentEnd": round(float(unit["end"]), 4),
            "whisperxStart": round(start, 4),
            "whisperxEnd": round(end, 4),
            "startShiftSeconds": round(start_shift, 4),
            "endShiftSeconds": round(end_shift, 4),
            "flags": ";".join(flags),
        })
    return rows


def _write_review_csv(path: Path, rows: list[dict]) -> None:
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["unitId", "english", "parentStart", "parentEnd",
                                                    "whisperxStart", "whisperxEnd",
                                                    "startShiftSeconds", "endShiftSeconds", "flags"])
        writer.writeheader()
        writer.writerows(rows)


def _write_review_html(path: Path, rows: list[dict], clip: Path, snippets: Path,
                       *, top_units: int) -> None:
    import html as _html
    import csv
    snippets.mkdir(parents=True, exist_ok=True)
    selected = sorted(rows, key=lambda row: max(row["startShiftSeconds"], row["endShiftSeconds"]),
                      reverse=True)[:top_units]
    blocks = []
    for index, row in enumerate(selected, start=1):
        start = max(0.0, min(row["parentStart"], row["whisperxStart"]) - 0.4)
        end = max(row["parentEnd"], row["whisperxEnd"]) + 0.8
        name = f"unit-{index:02d}.wav"
        target = snippets / name
        if not target.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.4f}",
                            "-t", f"{max(end - start, 0.3):.4f}", "-i", str(clip),
                            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target)], check=True)
        blocks.append(f"""
        <article>
          <h3>{index}. {_html.escape(row['unitId'])}</h3>
          <p>{_html.escape(row['english'])}</p>
          <audio controls preload="none" src="{_html.escape(str(target.relative_to(path.parent)))}"></audio>
          <pre>parent   {row['parentStart']:.3f} – {row['parentEnd']:.3f}
whisperx {row['whisperxStart']:.3f} – {row['whisperxEnd']:.3f}
shift    start {row['startShiftSeconds']:.3f}s / end {row['endShiftSeconds']:.3f}s
flags    {_html.escape(row['flags']) or '—'}</pre>
        </article>""")
    page = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>WhisperX timeline review</title>
<style>
:root {{ color-scheme: dark; --bg:#111318; --panel:#1b1f27; --text:#e7ecf3; --muted:#9aa7b8; --accent:#7cc4ff; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
main {{ max-width:900px; margin:0 auto; padding:32px 20px 80px; }}
h1 {{ font-size:25px; }} p {{ color:var(--muted); }}
article {{ background:var(--panel); border:1px solid #2b3240; border-radius:12px; padding:14px 16px; margin:14px 0; }}
article h3 {{ margin:0 0 6px; font-size:16px; }} audio {{ width:100%; margin:6px 0; }}
pre {{ background:#0d1015; padding:10px; border-radius:8px; color:#d6e2f0; overflow:auto; }}
</style><main>
<h1>WhisperX timeline review</h1>
<p>这是 Layer 1 时间轴候选的人工听审页。先听片段，再看时间；确认每个词/句边界后，
用 <code>--approve</code> 写批准包。机器审核不是人工批准。</p>
{''.join(blocks)}
</main></html>"""
    path.write_text(page, encoding="utf-8")


def _build_package(parent: dict, *, manifest_path: Path, manifest: dict,
                   words_path: Path, review_csv: Path,
                   parent_package_path: Path, parent_package: dict,
                   approved: bool, reviewer: str | None, reviewed_at: str | None,
                   note: str, approval_evidence: dict | None = None) -> dict:
    package = copy.deepcopy(parent)
    package["schemaVersion"] = PACKAGE_SCHEMA
    package["status"] = "ready_for_translation" if approved else "machine_candidate_requires_review"
    package["translationEligible"] = bool(approved)
    manifest_artifact = _manifest_ref(manifest_path, manifest)
    words_artifact = _evidence(words_path)
    package["source"] = copy.deepcopy(parent["source"])
    package["transcript"] = {
        **(copy.deepcopy(parent.get("transcript") or {})),
        "model": "whisperx",
        "textModel": (parent.get("transcript") or {}).get("textModel", "gpt-4o-transcribe"),
        "artifact": words_artifact,
        "note": "WhisperX wav2vec2 forced alignment of the frozen approved text; text unchanged.",
    }
    package["anchors"] = {
        **(copy.deepcopy(parent.get("anchors") or {})),
        "artifact": manifest_artifact,
        "sourceUnitCount": len(manifest["sourceUnits"]),
        "policy": copy.deepcopy(manifest.get("policy") or {}),
        "input": {
            "mfaSegmentsSha256": words_artifact["sha256"],
            "note": "Field name retained for the sentence-first schema; binds whisperx-words.json.",
        },
    }
    package["units"] = [{
        "sourceUnitId": unit["sourceUnitId"],
        "english": unit["english"],
        "start": unit["start"],
        "end": unit["end"],
        "pauseAfterSeconds": unit.get("boundary", {}).get("pauseAfterSeconds", 0.0),
    } for unit in manifest["sourceUnits"]]
    checks = ({key: "approved" for key in
               ("sourceIdentity", "transcriptCompleteness", "wordAlignment", "sentenceAndPauseBoundaries")}
              if approved else {key: "pending" for key in
                                ("sourceIdentity", "transcriptCompleteness", "wordAlignment",
                                 "sentenceAndPauseBoundaries")})
    review = {
        "schemaVersion": "sermon-english-source-review-v1",
        "humanApproval": bool(approved),
        "reviewer": reviewer if approved else None,
        "reviewedAt": reviewed_at if approved else None,
        "checks": checks,
        "reviewedSourceUnitIds": [unit["sourceUnitId"] for unit in manifest["sourceUnits"]] if approved else [],
        "anchorManifestJsonSha256": sha256_json(manifest),
        "alignedSegmentsSha256": words_artifact["sha256"],
        "reviewFile": str(review_csv.relative_to(RELATIVE_REPO)) if str(review_csv).startswith(str(RELATIVE_REPO)) else str(review_csv),
        "reviewFileSha256": sha256_file(review_csv),
        "note": note,
        "checksInheritedFromParent": (["sourceIdentity", "transcriptCompleteness",
                                      "sentenceAndPauseBoundaries"] if approved else []),
    }
    if approval_evidence is not None:
        review["evidence"] = approval_evidence
    package["review"] = review
    package["evidence"] = [
        _package_ref(parent_package_path, parent_package),
        manifest_artifact,
        words_artifact,
        _evidence(review_csv),
    ]
    window = parent.get("source", {}).get("approvedWindow")
    if isinstance(window, dict) and isinstance(window.get("evidence"), dict):
        package["evidence"].append(window["evidence"])
    return package


def _build_receipt(*, parent_package_path: Path, parent_package: dict,
                   parent_anchor_path: Path, parent_anchor: dict,
                   manifest_path: Path, manifest: dict,
                   package_path: Path, package: dict,
                   words_path: Path, segments_path: Path,
                   review_csv: Path, review_html: Path,
                   clip: Path, runtime: dict, result: dict,
                   units: list[dict], aligned_units: list[dict],
                   shifts: dict, issues: list[dict],
                   approved: bool, reviewer: str | None, reviewed_at: str | None) -> dict:
    return {
        "schemaVersion": SCHEMA,
        "status": "approved" if approved else "machine_candidate_requires_review",
        "limitations": [
            "WhisperX wav2vec2 times are forced-alignment estimates, not human word-level Gold.",
            "A machine review is never human approval.",
            "Changing the Layer 1 timeline invalidates every locale; rebuild downstream for a new run.",
        ],
        "parent": {
            "package": _package_ref(parent_package_path, parent_package),
            "anchor": _manifest_ref(parent_anchor_path, parent_anchor),
            "humanApproval": bool((parent_package.get("review") or {}).get("humanApproval")),
        },
        "source": {
            "media": str(copy.deepcopy(parent_package.get("source", {}).get("media", {}))),
            "window": copy.deepcopy(parent_package.get("source", {}).get("approvedWindow", {})),
            "clip": _evidence(clip),
        },
        "text": {
            "sha256": sha256_json([" ".join(str(unit["english"]).split()) for unit in units]),
            "sourceUnitsSha256": sha256_json([unit["sourceUnitId"] for unit in units]),
            "unitCount": len(units),
            "wordCount": sum(len(unit["words"]) for unit in units),
        },
        "runtime": runtime,
        "alignment": {
            "resultSha256": sha256_json(result),
            "chunkCount": len(result.get("chunks", [])),
            "wordCount": sum(len(unit["words"]) for unit in aligned_units),
            "resultElapsedSeconds": result.get("elapsedSeconds"),
            "producerElapsedSeconds": result.get("producerElapsedSeconds"),
            "attemptCounts": result.get("attemptCounts", {}),
        },
        "structure": {
            "zeroOrNegativeDuration": 0,
            "overlappingAdjacentPairs": 0,
            "nonMonotonicStarts": 0,
            "maxWordSeconds": round(max((word["end"] - word["start"] for unit in aligned_units
                                         for word in unit["words"]), default=0.0), 6),
        },
        "shifts": shifts,
        "issues": issues[:500],
        "issueCount": len(issues),
        "outputs": {
            "anchorManifest": _manifest_ref(manifest_path, manifest),
            "package": _package_ref(package_path, package),
            "words": _evidence(words_path),
            "segments": _evidence(segments_path),
            "reviewCsv": _evidence(review_csv),
            "reviewHtml": _evidence(review_html),
        },
        "approval": {
            "humanApproval": bool(approved),
            "reviewer": reviewer if approved else None,
            "reviewedAt": reviewed_at if approved else None,
            "reviewFileSha256": sha256_file(review_csv),
        },
    }


def _validate_parent(package_path: Path, package: dict, media_path: Path | None) -> tuple[dict, Path, Path, dict, float, float]:
    _require(package.get("schemaVersion") == PACKAGE_SCHEMA, "parent_package_schema")
    _require(package.get("translationEligible") is True, "parent_not_translation_eligible")
    review = package.get("review") or {}
    _require(review.get("humanApproval") is True, "parent_not_human_approved")
    anchors = package.get("anchors") or {}
    anchor_path = resolve_path((anchors.get("artifact") or {}).get("path", ""))
    _require(anchor_path.is_file(), "parent_anchor_missing", str(anchor_path))
    _require(sha256_file(anchor_path) == (anchors.get("artifact") or {}).get("sha256"), "parent_anchor_sha_changed")
    manifest = read_json(anchor_path, "parent anchor manifest")
    _require(manifest.get("schemaVersion") == ANCHOR_SCHEMA, "parent_anchor_schema")
    _require(isinstance(manifest.get("sourceUnits"), list) and manifest["sourceUnits"], "parent_units_missing")
    window = (package.get("source") or {}).get("approvedWindow") or {}
    _require(window.get("humanApproval") is True and window.get("status") == "approved", "window_not_approved")
    start, end = window.get("start"), window.get("end")
    _require(_finite(start) and _finite(end) and 0 <= start < end, "window_invalid")
    media = package.get("source", {}).get("media") or {}
    expected_media_sha = media.get("sha256")
    _require(isinstance(expected_media_sha, str), "parent_media_sha_missing")
    if media_path is None:
        media_path = resolve_path(media.get("file", ""))
    _require(media_path.is_file(), "media_missing", str(media_path))
    _require(sha256_file(media_path) == expected_media_sha, "media_sha_changed", str(media_path))
    duration = float(end) - float(start)
    _require(duration > 0, "window_empty")
    return manifest, anchor_path, media_path, package, float(start), duration


def run_candidate(args: argparse.Namespace) -> int:
    package_path = args.english_source.resolve()
    parent_package = read_json(package_path, "parent English Source Package")
    manifest, parent_anchor_path, media_path, _, window_start, duration = _validate_parent(
        package_path, parent_package, args.media.resolve() if args.media else None)
    if args.window_start is not None:
        _require(abs(args.window_start - window_start) <= 0.001, "window_start_override_mismatch")
    if args.window_end is not None:
        _require(abs(args.window_end - (window_start + duration)) <= 0.001, "window_end_override_mismatch")
    units = manifest["sourceUnits"]
    parent_anchor_sha = sha256_file(parent_anchor_path)
    chunks = build_chunks(units, target_seconds=args.chunk_target_seconds,
                          max_seconds=args.chunk_max_seconds, gap_seconds=args.chunk_gap_seconds)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    clip = out / "source-clip.wav"
    _clip_audio(media_path, clip, window_start, duration)
    request = {
        "schemaVersion": REQUEST_SCHEMA,
        "audio": str(clip),
        "language": args.language,
        "device": args.device,
        "chunks": [{"id": chunk["id"], "start": chunk["start"], "end": chunk["end"],
                    "text": chunk["text"], "tokenCount": chunk["tokenCount"]} for chunk in chunks],
    }
    request_path = out / "runtime-request.json"
    write_json(request_path, request)
    result_path = out / "runtime-result.json"
    result = _run_adapter(args.runtime_python, args.adapter.resolve(), request_path, result_path,
                          device=args.device, language=args.language)
    aligned_units, issues = _validate_alignment(units, chunks, result, duration,
                                                max_word_seconds=args.max_word_seconds,
                                                flag_word_seconds=args.flag_word_seconds)
    text_sha = sha256_json([" ".join(str(unit["english"]).split()) for unit in units])
    words = _build_flat_words(aligned_units)
    words_path = out / "whisperx-words.json"
    write_json(words_path, words)
    words_sha = sha256_file(words_path)
    runtime = {
        **(result.get("model") or {}),
        "runtimePython": args.runtime_python,
        "adapter": str(args.adapter.resolve()),
        "adapterSha256": sha256_file(args.adapter),
        "requestSha256": sha256_file(request_path),
        "resultSha256": sha256_file(result_path),
        "device": args.device,
        "language": args.language,
        "producerVersion": "whisperx-timeline-v1",
    }
    new_manifest = _build_manifest(
        manifest, aligned_units, parent_anchor=parent_anchor_path,
        parent_anchor_sha=parent_anchor_sha, words_sha=words_sha, text_sha=text_sha,
        source={"mediaSha256": (parent_package.get("source", {}).get("media") or {}).get("sha256"),
                "mediaDurationSeconds": (parent_package.get("source", {}).get("media") or {}).get("durationSeconds")},
        runtime=runtime,
        window={"start": window_start, "end": window_start + duration})
    manifest_path = out / "anchor-manifest.json"
    write_json(manifest_path, new_manifest)
    segments_path = out / "whisperx-aligned-segments.json"
    write_json(segments_path, _build_segments(aligned_units, units))
    shifts = _shift_summary(units, aligned_units)
    review_rows = _review_rows(units, aligned_units, flag_word_seconds=args.flag_word_seconds)
    review_csv = out / "timeline-review.csv"
    _write_review_csv(review_csv, review_rows)
    review_html = out / "timeline-review.html"
    if args.review_snippets:
        _write_review_html(review_html, review_rows, clip, out / "review-snippets",
                           top_units=args.review_top_units)
    else:
        review_html.write_text("<html><body><p>Review snippets disabled.</p></body></html>", encoding="utf-8")
    package = _build_package(
        parent_package, manifest_path=manifest_path, manifest=new_manifest,
        words_path=words_path, review_csv=review_csv,
        parent_package_path=package_path, parent_package=parent_package,
        approved=False, reviewer=None, reviewed_at=None,
        note="Timeline-only revision candidate: WhisperX forced alignment of the approved text; "
             "text/window inherited from the parent approval; word alignment requires operator review.")
    package_path_out = out / "english-source.json"
    write_json(package_path_out, package)
    receipt = _build_receipt(
        parent_package_path=package_path, parent_package=parent_package,
        parent_anchor_path=parent_anchor_path, parent_anchor=manifest,
        manifest_path=manifest_path, manifest=new_manifest,
        package_path=package_path_out, package=package,
        words_path=words_path, segments_path=segments_path,
        review_csv=review_csv, review_html=review_html, clip=clip,
        runtime=runtime, result=result, units=units, aligned_units=aligned_units,
        shifts=shifts, issues=issues, approved=False, reviewer=None, reviewed_at=None)
    write_json(out / "whisperx-timeline-receipt.json", receipt)
    print(json.dumps({
        "out": str(out), "status": receipt["status"], "units": len(units), "words": len(words),
        "startShiftP50Seconds": shifts["start"]["p50"], "startShiftP95Seconds": shifts["start"]["p95"],
        "unitsOver250ms": shifts["start"]["over250ms"], "issues": len(issues),
        "review": str(review_html),
    }, ensure_ascii=False))
    return 0


def _candidate_paths(out: Path) -> dict[str, Path]:
    return {
        "package": out / "english-source.json",
        "manifest": out / "anchor-manifest.json",
        "words": out / "whisperx-words.json",
        "receipt": out / "whisperx-timeline-receipt.json",
        "reviewCsv": out / "timeline-review.csv",
    }


def approve(args: argparse.Namespace) -> int:
    out = (args.from_dir or args.out).resolve()
    paths = _candidate_paths(out)
    receipt = read_json(paths["receipt"], "candidate receipt")
    _require(receipt.get("schemaVersion") == SCHEMA, "candidate_receipt_schema")
    _require(receipt.get("status") == "machine_candidate_requires_review", "candidate_not_pending")
    package = read_json(paths["package"], "candidate package")
    manifest = read_json(paths["manifest"], "candidate manifest")
    words = read_json(paths["words"], "candidate words")
    _require(receipt["outputs"]["package"]["sha256"] == sha256_file(paths["package"]), "candidate_package_changed")
    _require(receipt["outputs"]["anchorManifest"]["sha256"] == sha256_file(paths["manifest"]), "candidate_manifest_changed")
    _require(receipt["outputs"]["words"]["sha256"] == sha256_file(paths["words"]), "candidate_words_changed")
    review_csv = (args.review_file or paths["reviewCsv"]).resolve()
    _require(review_csv.is_file(), "review_file_missing", str(review_csv))
    parent_path = resolve_path(receipt["parent"]["package"]["path"])
    parent_package = read_json(parent_path, "parent package")
    _require(sha256_file(parent_path) == receipt["parent"]["package"]["sha256"], "parent_package_changed")
    _require(len(manifest["sourceUnits"]) == len(parent_package.get("units", [])), "unit_count_changed")
    approval_receipt = {
        "schemaVersion": "sermon-english-source-review-v1",
        "status": "approved",
        "humanApproval": True,
        "reviewer": args.approve,
        "reviewedAt": args.approved_at,
        "checks": {key: "approved" for key in
                   ("sourceIdentity", "transcriptCompleteness", "wordAlignment", "sentenceAndPauseBoundaries")},
        "reviewedSourceUnitIds": [unit["sourceUnitId"] for unit in manifest["sourceUnits"]],
        "anchorManifestJsonSha256": sha256_json(manifest),
        "alignedSegmentsSha256": sha256_file(paths["words"]),
        "reviewFile": str(review_csv),
        "reviewFileSha256": sha256_file(review_csv),
        "candidateReceipt": _evidence(paths["receipt"]),
        "note": "Operator approved the timing-only revision. Text and source window inherit the "
                "parent approval; WhisperX word alignment was reviewed from the signed CSV.",
    }
    approval_path = out / "timeline-approval-receipt.json"
    write_json(approval_path, approval_receipt)
    approved = _build_package(
        parent_package, manifest_path=paths["manifest"], manifest=manifest,
        words_path=paths["words"], review_csv=review_csv,
        parent_package_path=parent_path, parent_package=parent_package,
        approved=True, reviewer=args.approve, reviewed_at=args.approved_at,
        note="Timing-only revision approved by the operator; English text and source window "
             "inherit the parent approval. WhisperX word alignment reviewed from timeline-review.csv.",
        approval_evidence=_evidence(approval_path, approval_receipt))
    approved_path = out / "english-source.approved.json"
    write_json(approved_path, approved)
    print(json.dumps({"out": str(out), "status": approved["status"],
                      "package": str(approved_path), "units": len(approved["units"])}, ensure_ascii=False))
    return 0


def check(out: Path) -> int:
    out = out.resolve()
    paths = _candidate_paths(out)
    receipt = read_json(paths["receipt"], "receipt")
    errors = []
    def expect(condition: bool, code: str) -> None:
        if not condition:
            errors.append(code)
    expect(receipt.get("schemaVersion") == SCHEMA, "receipt_schema")
    for name, path in (("package", paths["package"]), ("anchorManifest", paths["manifest"]),
                       ("words", paths["words"]), ("reviewCsv", paths["reviewCsv"])):
        ref = (receipt.get("outputs") or {}).get(name) or {}
        expect(ref.get("sha256") == sha256_file(path), f"{name}_sha")
    package = read_json(paths["package"], "package")
    manifest = read_json(paths["manifest"], "manifest")
    expect((package.get("anchors") or {}).get("artifact", {}).get("sha256") == sha256_file(paths["manifest"]),
           "package_manifest_binding")
    expect((package.get("transcript") or {}).get("artifact", {}).get("sha256") == sha256_file(paths["words"]),
           "package_words_binding")
    units = manifest.get("sourceUnits") or []
    expect(bool(units), "manifest_units")
    previous = 0.0
    for unit in units:
        words = unit.get("words") or []
        if not words:
            errors.append("unit_words_empty")
            continue
        if unit.get("start") != words[0].get("start") or unit.get("end") != words[-1].get("end"):
            errors.append("unit_span_mismatch")
        for word in words:
            start, end = word.get("start"), word.get("end")
            if not (_finite(start) and _finite(end) and start >= previous - 0.001 and end > start):
                errors.append("word_timeline_invalid")
                break
            previous = end
    approved_path = out / "english-source.approved.json"
    if approved_path.exists():
        approved = read_json(approved_path, "approved package")
        expect(approved.get("translationEligible") is True, "approved_not_eligible")
        expect((approved.get("review") or {}).get("humanApproval") is True, "approved_not_human")
        expect((approved.get("anchors") or {}).get("artifact", {}).get("sha256") == sha256_file(paths["manifest"]),
               "approved_manifest_binding")
    print(json.dumps({"out": str(out), "status": "pass" if not errors else "fail",
                      "errors": sorted(set(errors))}, ensure_ascii=False))
    return 0 if not errors else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--english-source", type=Path, help="parent approved Layer 1 english-source.json")
    parser.add_argument("--out", type=Path, required=True, help="candidate output directory")
    parser.add_argument("--media", type=Path, help="override media path (must match the parent hash)")
    parser.add_argument("--window-start", type=float, help="must match the parent window")
    parser.add_argument("--window-end", type=float, help="must match the parent window")
    parser.add_argument("--runtime-python", default=os.environ.get("WHISPERX_PYTHON", ""),
                        help="isolated Python that has whisperx (or WHISPERX_PYTHON)")
    parser.add_argument("--adapter", type=Path,
                        default=RELATIVE_REPO / "tools" / "ops" / "whisperx_align_runtime.py")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--language", default="en")
    parser.add_argument("--chunk-target-seconds", type=float, default=18.0)
    parser.add_argument("--chunk-max-seconds", type=float, default=24.0)
    parser.add_argument("--chunk-gap-seconds", type=float, default=1.0)
    parser.add_argument("--max-word-seconds", type=float, default=5.0)
    parser.add_argument("--flag-word-seconds", type=float, default=2.5)
    parser.add_argument("--review-top-units", type=int, default=20)
    parser.add_argument("--review-snippets", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--approve", metavar="REVIEWER",
                        help="write the approved package from an existing candidate")
    parser.add_argument("--approved-at")
    parser.add_argument("--review-file", type=Path,
                        help="signed timeline review CSV (defaults to the candidate CSV)")
    parser.add_argument("--from", dest="from_dir", type=Path,
                        help="candidate directory for --approve")
    parser.add_argument("--check", action="store_true", help="validate an existing candidate")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.check:
        return check(args.out)
    if args.approve:
        _require(bool(args.approved_at), "approval_time_required")
        return approve(args)
    _require(bool(args.english_source), "parent_package_required")
    _require(bool(args.runtime_python), "runtime_python_required")
    return run_candidate(args)


if __name__ == "__main__":
    raise SystemExit(main())
