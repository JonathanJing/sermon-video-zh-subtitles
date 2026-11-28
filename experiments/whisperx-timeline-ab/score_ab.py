#!/usr/bin/env python3
"""Score the WhisperX versus OpenAI Layer 1 timeline A/B test.

Arm A is the historical production timeline: OpenAI ``whisper-1`` word times
mapped onto the human-approved corrected text by the anchor builder.
Arm B is WhisperX forced alignment of that same approved text.
MFA is a third forced-alignment estimate used only as a model reference.

No arm is human word-level Gold. The report keeps that limitation explicit and
emits a listening queue instead of upgrading model agreement into accuracy.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import re
import statistics
import sys

TOKEN_RE = re.compile(r"[a-z0-9]+(?:['’][a-z0-9]+)?", re.I)
EDGE_GUARD_SECONDS = 0.75


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def normalize_tokens(text: str) -> list[str]:
    return [token.lower().replace("’", "'") for token in TOKEN_RE.findall(text or "")]


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summary(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(values),
        "mean": round(statistics.fmean(values), 6),
        "p50": round(percentile(values, 0.50), 6),
        "p90": round(percentile(values, 0.90), 6),
        "p95": round(percentile(values, 0.95), 6),
        "p99": round(percentile(values, 0.99), 6),
        "max": round(max(values), 6),
    }


def thresholds(values: list[float], cuts=(0.05, 0.1, 0.2, 0.25, 0.5, 1.0)) -> dict:
    return {str(cut): round(sum(value <= cut for value in values) / len(values), 4)
            for cut in cuts} if values else {}


def structure(times: dict[int, dict], duration: float, expected: int) -> dict:
    entries = [times[index] for index in sorted(times)]
    zero = [word for word in entries if word["end"] <= word["start"]]
    overlaps, nonmonotonic, outside = [], 0, []
    previous = None
    for index in sorted(times):
        word = times[index]
        if previous is not None:
            if word["start"] < previous["end"] - 1e-6:
                overlaps.append({
                    "tokenIndex": index,
                    "overlapSeconds": round(previous["end"] - word["start"], 6),
                })
            if word["start"] < previous["start"] - 1e-6:
                nonmonotonic += 1
        if not (math.isfinite(word["start"]) and math.isfinite(word["end"])
                and 0 <= word["start"] <= duration + 0.05
                and 0 <= word["end"] <= duration + 0.05):
            outside.append({"tokenIndex": index, "start": word["start"], "end": word["end"]})
        previous = word
    durations = [word["end"] - word["start"] for word in entries]
    return {
        "expectedWords": expected,
        "presentWords": len(entries),
        "missingWords": expected - len(entries),
        "zeroOrNegativeDuration": len(zero),
        "zeroDurationExamples": zero[:8],
        "overlappingAdjacentPairs": len(overlaps),
        "overlapSeconds": summary([item["overlapSeconds"] for item in overlaps]),
        "nonMonotonicStarts": nonmonotonic,
        "outsideAudio": len(outside),
        "durationSeconds": summary(durations),
    }


def pairwise(a: dict[int, dict], b: dict[int, dict], metrics=("start", "end", "mid", "duration")) -> dict:
    common = sorted(set(a) & set(b))
    result = {"commonWords": len(common)}
    for metric in metrics:
        values, signed = [], []
        for index in common:
            left = a[index]["start"] if metric == "start" else (
                a[index]["end"] if metric == "end" else (
                    (a[index]["start"] + a[index]["end"]) / 2 if metric == "mid"
                    else a[index]["end"] - a[index]["start"]))
            right = b[index]["start"] if metric == "start" else (
                b[index]["end"] if metric == "end" else (
                    (b[index]["start"] + b[index]["end"]) / 2 if metric == "mid"
                    else b[index]["end"] - b[index]["start"]))
            values.append(abs(left - right))
            signed.append(right - left)
        result[metric] = {
            **summary(values),
            "thresholds": thresholds(values),
            "medianSignedBMinusASeconds": round(statistics.median(signed), 6) if signed else None,
            "p95SignedBMinusASeconds": round(percentile(signed, 0.95), 6) if signed else None,
        }
    return result


def compare_by_group(a: dict[int, dict], b: dict[int, dict], groups: dict[str, list[int]],
                     metric: str = "mid") -> dict:
    def value(times: dict, index: int) -> float:
        word = times[index]
        return ((word["start"] + word["end"]) / 2 if metric == "mid"
                else word["start"] if metric == "start" else word["end"])

    result = {}
    for name, indexes in groups.items():
        values = [abs(value(a, index) - value(b, index)) for index in indexes
                  if index in a and index in b]
        if values:
            result[name] = summary(values)
    return result


def levenshtein_counts(reference: list[str], hypothesis: list[str]) -> dict:
    rows, columns = len(reference), len(hypothesis)
    if rows == 0:
        return {"substitutions": 0, "deletions": 0, "insertions": columns,
                "distance": columns, "wer": 1.0 if columns else 0.0}
    directions = bytearray((rows + 1) * (columns + 1))
    previous = list(range(columns + 1))
    stride = columns + 1
    for i in range(1, rows + 1):
        current = [0] * (columns + 1)
        current[0] = i
        directions[i * stride] = 1  # deletion
        ref_token = reference[i - 1]
        for j in range(1, columns + 1):
            cost = 0 if ref_token == hypothesis[j - 1] else 1
            diagonal = previous[j - 1] + cost
            up = previous[j] + 1
            left = current[j - 1] + 1
            best = diagonal
            direction = 0
            if up < best:
                best, direction = up, 1
            if left < best:
                best, direction = left, 2
            current[j] = best
            directions[i * stride + j] = direction
        previous = current
    substitutions = deletions = insertions = 0
    i, j = rows, columns
    while i > 0 or j > 0:
        direction = directions[i * stride + j]
        if i > 0 and j > 0 and direction == 0:
            if reference[i - 1] != hypothesis[j - 1]:
                substitutions += 1
            i -= 1
            j -= 1
        elif i > 0 and (j == 0 or direction == 1):
            deletions += 1
            i -= 1
        else:
            insertions += 1
            j -= 1
    distance = previous[columns]
    return {
        "substitutions": substitutions,
        "deletions": deletions,
        "insertions": insertions,
        "distance": distance,
        "wer": round(distance / rows, 6) if rows else 0.0,
    }


def wer_block(reference: str, hypothesis: str) -> dict:
    ref_tokens, hyp_tokens = normalize_tokens(reference), normalize_tokens(hypothesis)
    counts = levenshtein_counts(ref_tokens, hyp_tokens)
    return {
        "referenceWords": len(ref_tokens),
        "hypothesisWords": len(hyp_tokens),
        "wordCountRatio": round(len(hyp_tokens) / len(ref_tokens), 6) if ref_tokens else None,
        **counts,
    }


def text_accuracy(case: dict, transcript: dict | None, raw_whisper: dict,
                  raw_gpt4o: str) -> dict:
    approved = " ".join(unit["text"] for unit in case["units"])
    rows = {
        "openai_whisper_1_raw": wer_block(approved, str(raw_whisper.get("text", ""))),
        "openai_gpt_4o_transcribe_raw": wer_block(approved, raw_gpt4o),
    }
    if transcript:
        text = " ".join(str(segment.get("text", "")) for segment in transcript.get("segments", []))
        rows["whisperx_large_v3"] = wer_block(approved, text)
    return {
        "reference": "human-approved English unit table (text only; times inherited from whisper-1)",
        "referenceWords": len(normalize_tokens(approved)),
        "arms": rows,
    }


def mfa_reference(case: dict, a: dict[int, dict], b: dict[int, dict], mfa_payload: dict) -> dict:
    chunk_bounds = {chunk["chunkId"]: (float(chunk["start"]), float(chunk["end"]))
                    for chunk in mfa_payload.get("chunks", [])}
    reference = {}
    edge_dropped = 0
    for word in mfa_payload.get("words", []):
        bound = chunk_bounds.get(word.get("chunkId"))
        if bound is None:
            continue
        start, end = float(word["start"]), float(word["end"])
        if end <= start:
            continue
        if start - bound[0] < EDGE_GUARD_SECONDS or bound[1] - end < EDGE_GUARD_SECONDS:
            edge_dropped += 1
            continue
        reference[int(word["tokenIndex"])] = {**word, "start": start, "end": end}
    common = sorted(set(reference) & set(a) & set(b))

    def errors(arm: dict[int, dict], metric: str) -> list[float]:
        values = []
        for index in common:
            left = arm[index]
            right = reference[index]
            if metric == "start":
                values.append(abs(left["start"] - right["start"]))
            elif metric == "end":
                values.append(abs(left["end"] - right["end"]))
            elif metric == "mid":
                values.append(abs((left["start"] + left["end"]) / 2
                                  - (right["start"] + right["end"]) / 2))
            else:
                values.append(abs((left["end"] - left["start"])
                                  - (right["end"] - right["start"])))
        return values

    result = {
        "status": "model_reference_not_human_gold",
        "referenceWordsAvailable": len(reference),
        "edgeWordsDropped": edge_dropped,
        "comparedWords": len(common),
        "chunks": len(mfa_payload.get("chunks", [])),
        "metrics": {},
        "byTimingSource": {},
    }
    for metric in ("start", "end", "mid", "duration"):
        a_values = errors(a, metric)
        b_values = errors(b, metric)
        closer = {"armA": 0, "armB": 0, "tie": 0}
        for left, right in zip(a_values, b_values):
            if right < left - 0.01:
                closer["armB"] += 1
            elif left < right - 0.01:
                closer["armA"] += 1
            else:
                closer["tie"] += 1
        result["metrics"][metric] = {
            "armA": {**summary(a_values), "thresholds": thresholds(a_values),
                     "grossOver0_5s": sum(value > 0.5 for value in a_values)},
            "armB": {**summary(b_values), "thresholds": thresholds(b_values),
                     "grossOver0_5s": sum(value > 0.5 for value in b_values)},
            "closer": closer,
        }
    # Report the two timing populations separately: A had a real whisper time for
    # matched words and a synthesized span for corrected words.
    for source in ("whisper_match", "synthetic_span"):
        selected = [index for index in common if case["tokens"][index].get("timingSource") == source]
        if not selected:
            continue
        group = {}
        for label, arm in (("armA", a), ("armB", b)):
            values = [abs((arm[index]["start"] + arm[index]["end"]) / 2
                          - (reference[index]["start"] + reference[index]["end"]) / 2)
                      for index in selected]
            group[label] = summary(values)
        group["words"] = len(selected)
        result["byTimingSource"][source] = group
    unit_rows = []
    for unit in case["units"]:
        first, last = unit["firstWordIndex"], unit["lastWordIndex"]
        if first not in reference or last not in reference:
            continue
        if first not in a or first not in b or last not in a or last not in b:
            continue
        unit_rows.append({
            "unitId": unit["unitId"],
            "text": unit["text"],
            "armAStartError": round(abs(unit["start"] - reference[first]["start"]), 6),
            "armBStartError": round(abs(b[first]["start"] - reference[first]["start"]), 6),
            "armAEndError": round(abs(unit["end"] - reference[last]["end"]), 6),
            "armBEndError": round(abs(b[last]["end"] - reference[last]["end"]), 6),
        })
    if unit_rows:
        unit_result = {
            "comparedUnits": len(unit_rows),
            "start": {
                "armA": summary([row["armAStartError"] for row in unit_rows]),
                "armB": summary([row["armBStartError"] for row in unit_rows]),
                "closer": {
                    "armA": sum(row["armAStartError"] < row["armBStartError"] - 0.01
                                for row in unit_rows),
                    "armB": sum(row["armBStartError"] < row["armAStartError"] - 0.01
                                for row in unit_rows),
                    "tie": sum(abs(row["armAStartError"] - row["armBStartError"]) <= 0.01
                               for row in unit_rows),
                },
            },
            "end": {
                "armA": summary([row["armAEndError"] for row in unit_rows]),
                "armB": summary([row["armBEndError"] for row in unit_rows]),
                "closer": {
                    "armA": sum(row["armAEndError"] < row["armBEndError"] - 0.01
                                for row in unit_rows),
                    "armB": sum(row["armBEndError"] < row["armAEndError"] - 0.01
                                for row in unit_rows),
                    "tie": sum(abs(row["armAEndError"] - row["armBEndError"]) <= 0.01
                               for row in unit_rows),
                },
            },
            "largestErrors": sorted(
                unit_rows,
                key=lambda row: max(row["armAStartError"], row["armBStartError"],
                                    row["armAEndError"], row["armBEndError"]),
                reverse=True)[:10],
        }
    else:
        unit_result = {"comparedUnits": 0}
    result["units"] = unit_result
    result["examples"] = [
        {
            "tokenIndex": index,
            "text": case["tokens"][index]["text"],
            "timingSource": case["tokens"][index].get("timingSource"),
            "armA": {"start": round(a[index]["start"], 4), "end": round(a[index]["end"], 4)},
            "armB": {"start": round(b[index]["start"], 4), "end": round(b[index]["end"], 4)},
            "mfa": {"start": round(reference[index]["start"], 4),
                    "end": round(reference[index]["end"], 4)},
            "armAErrorSeconds": round(abs((a[index]["start"] + a[index]["end"]) / 2
                                          - (reference[index]["start"] + reference[index]["end"]) / 2), 4),
            "armBErrorSeconds": round(abs((b[index]["start"] + b[index]["end"]) / 2
                                          - (reference[index]["start"] + reference[index]["end"]) / 2), 4),
        }
        for index in sorted(common, key=lambda item: max(
            abs((a[item]["start"] + a[item]["end"]) / 2
                - (reference[item]["start"] + reference[item]["end"]) / 2),
            abs((b[item]["start"] + b[item]["end"]) / 2
                - (reference[item]["start"] + reference[item]["end"]) / 2)), reverse=True)[:25]
    ]
    return result


def unit_metrics(case: dict, a: dict[int, dict], b: dict[int, dict]) -> dict:
    rows, dropped = [], 0
    for unit in case["units"]:
        first, last = unit["firstWordIndex"], unit["lastWordIndex"]
        if first not in a or first not in b or last not in a or last not in b:
            dropped += 1
            continue
        b_start, b_end = b[first]["start"], b[last]["end"]
        rows.append({
            "unitId": unit["unitId"],
            "text": unit["text"],
            "armA": {"start": unit["start"], "end": unit["end"]},
            "armB": {"start": round(b_start, 6), "end": round(b_end, 6)},
            "startDelta": round(abs(unit["start"] - b_start), 6),
            "endDelta": round(abs(unit["end"] - b_end), 6),
        })
    starts = [row["startDelta"] for row in rows]
    ends = [row["endDelta"] for row in rows]
    return {
        "units": len(rows),
        "droppedUnits": dropped,
        "startDelta": {**summary(starts), "thresholds": thresholds(starts)},
        "endDelta": {**summary(ends), "thresholds": thresholds(ends)},
        "unitsWithStartShiftOver250ms": sum(value > 0.25 for value in starts),
        "unitsWithStartShiftOver500ms": sum(value > 0.5 for value in starts),
        "largestShifts": sorted(rows, key=lambda row: max(row["startDelta"], row["endDelta"]),
                                reverse=True)[:15],
        "all": rows,
    }


def bucket_groups(tokens: dict[int, dict]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = {}
    for index, token in tokens.items():
        bucket = int(token["start"] // 300) * 5
        groups.setdefault(f"{bucket:02d}-{bucket + 5:02d}min", []).append(index)
    return groups


def review_queue(case: dict, a: dict[int, dict], b: dict[int, dict], mfa: dict | None,
                 units: dict) -> dict:
    candidates = []
    if mfa:
        chunk_bounds = {chunk["chunkId"]: (float(chunk["start"]), float(chunk["end"]))
                        for chunk in mfa.get("chunks", [])}
        reference = {}
        for word in mfa.get("words", []):
            bound = chunk_bounds.get(word.get("chunkId"))
            if bound is None or word["end"] <= word["start"]:
                continue
            if (word["start"] - bound[0] < EDGE_GUARD_SECONDS
                    or bound[1] - word["end"] < EDGE_GUARD_SECONDS):
                continue
            reference[int(word["tokenIndex"])] = word
        for index in sorted(set(reference) & set(a) & set(b)):
            a_mid = (a[index]["start"] + a[index]["end"]) / 2
            b_mid = (b[index]["start"] + b[index]["end"]) / 2
            r_mid = (reference[index]["start"] + reference[index]["end"]) / 2
            candidates.append({
                "kind": "word",
                "tokenIndex": index,
                "text": case["tokens"][index]["text"],
                "timingSource": case["tokens"][index].get("timingSource"),
                "armA": {"start": round(a[index]["start"], 4), "end": round(a[index]["end"], 4)},
                "armB": {"start": round(b[index]["start"], 4), "end": round(b[index]["end"], 4)},
                "mfa": {"start": round(reference[index]["start"], 4),
                        "end": round(reference[index]["end"], 4)},
                "maxReferenceErrorSeconds": round(max(abs(a_mid - r_mid), abs(b_mid - r_mid)), 4),
                "snippet": {
                    "start": round(max(0.0, min(a[index]["start"], b[index]["start"],
                                                reference[index]["start"]) - 0.8), 4),
                    "end": round(max(a[index]["end"], b[index]["end"],
                                     reference[index]["end"]) + 1.0, 4),
                },
            })
        candidates.sort(key=lambda item: item["maxReferenceErrorSeconds"], reverse=True)
    unit_candidates = [{
        "kind": "unit",
        "unitId": row["unitId"],
        "text": row["text"],
        "armA": row["armA"],
        "armB": row["armB"],
        "startDeltaSeconds": row["startDelta"],
        "endDeltaSeconds": row["endDelta"],
        "snippet": {
            "start": round(max(0.0, min(row["armA"]["start"], row["armB"]["start"]) - 0.5), 4),
            "end": round(max(row["armA"]["end"], row["armB"]["end"]) + 0.7, 4),
        },
    } for row in units["largestShifts"][:10]]
    return {
        "status": "human_listening_pending",
        "instructions": "Listen to the snippet twice with arm labels hidden; decide which boundary "
                        "matches the audible word onset/release. Do not infer a winner from this queue.",
        "wordCandidates": candidates[:20],
        "unitCandidates": unit_candidates,
    }


def markdown(report: dict) -> str:
    lines = [
        "# WhisperX vs OpenAI Layer 1 timeline A/B",
        "",
        f"- Status: `{report['status']}`",
        f"- Date: {report['source']['date']}",
        f"- Episode: {report['source']['episode'] or '2026-11-08 sermon'}",
        f"- Audio: {report['source']['durationSeconds']:.3f} s, SHA-256 `{report['source']['audioSha256'][:16]}`",
        f"- Human-approved source words: {report['case']['words']}",
        f"- Arms: A = OpenAI `whisper-1` word times (current Layer 1); "
        f"B = WhisperX wav2vec2 forced alignment of the same approved text",
        "",
        "## Headline",
        "",
        "| Check | Arm A | Arm B |",
        "|---|---:|---:|",
        f"| Words produced | {report['structure']['armA']['presentWords']} | "
        f"{report['structure']['armB']['presentWords']} |",
        f"| Zero/negative durations | {report['structure']['armA']['zeroOrNegativeDuration']} | "
        f"{report['structure']['armB']['zeroOrNegativeDuration']} |",
        f"| Overlapping adjacent pairs | {report['structure']['armA']['overlappingAdjacentPairs']} | "
        f"{report['structure']['armB']['overlappingAdjacentPairs']} |",
        f"| Non-monotonic starts | {report['structure']['armA']['nonMonotonicStarts']} | "
        f"{report['structure']['armB']['nonMonotonicStarts']} |",
        "",
        "### Agreement between A and B (same 6,136 words)",
        "",
        "| Boundary | p50 | p90 | p95 | max |",
        "|---|---:|---:|---:|---:|",
    ]
    for metric in ("start", "end", "mid", "duration"):
        block = report["agreement"]["ab"][metric]
        lines.append(f"| {metric} | {block['p50']:.3f} | {block['p90']:.3f} | "
                     f"{block['p95']:.3f} | {block['max']:.3f} |")
    reference = report.get("mfaReference")
    if reference:
        lines += [
            "",
            "### MFA model reference (not human Gold)",
            "",
            f"Compared words: **{reference['comparedWords']}** "
            f"(edge guard {EDGE_GUARD_SECONDS:.2f} s; {reference['edgeWordsDropped']} edge words dropped).",
            "",
            "| Metric | A p50 | A p95 | B p50 | B p95 | B closer | A closer | tie |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for metric in ("start", "end", "mid", "duration"):
            block = reference["metrics"][metric]
            lines.append(
                f"| {metric} | {block['armA']['p50']:.3f} | {block['armA']['p95']:.3f} | "
                f"{block['armB']['p50']:.3f} | {block['armB']['p95']:.3f} | "
                f"{block['closer']['armB']} | {block['closer']['armA']} | {block['closer']['tie']} |")
        lines += [
            "",
            "| A timing source | Words | A p50 | A p95 | B p50 | B p95 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for source, group in reference["byTimingSource"].items():
            lines.append(
                f"| {source} | {group['words']} | {group['armA']['p50']:.3f} | "
                f"{group['armA']['p95']:.3f} | {group['armB']['p50']:.3f} | "
                f"{group['armB']['p95']:.3f} |")
        unit_reference = reference.get("units") or {}
        if unit_reference.get("comparedUnits"):
            lines += [
                "",
                "#### Sentence/unit anchors against MFA",
                "",
                f"Compared units: **{unit_reference['comparedUnits']}** "
                f"(both first and last word outside the edge guard).",
                "",
                "| Anchor | A p50 | A p95 | B p50 | B p95 | B closer | A closer | tie |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
            for name in ("start", "end"):
                block = unit_reference[name]
                lines.append(
                    f"| {name} | {block['armA']['p50']:.3f} | {block['armA']['p95']:.3f} | "
                    f"{block['armB']['p50']:.3f} | {block['armB']['p95']:.3f} | "
                    f"{block['closer']['armB']} | {block['closer']['armA']} | "
                    f"{block['closer']['tie']} |")
    lines += [
        "",
        "### Text accuracy against the approved English table",
        "",
        "| Arm | WER | Sub | Del | Ins | Ref words | Hyp words |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm, block in report["text"]["arms"].items():
        lines.append(f"| {arm} | {block['wer']:.4%} | {block['substitutions']} | "
                     f"{block['deletions']} | {block['insertions']} | {block['referenceWords']} | "
                     f"{block['hypothesisWords']} |")
    lines += [
        "",
        "### Sentence/unit anchors",
        "",
        "| Delta | p50 | p90 | p95 | max | >250 ms | >500 ms |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, block in (("start", report["units"]["startDelta"]),
                        ("end", report["units"]["endDelta"])):
        lines.append(f"| {name} | {block['p50']:.3f} | {block['p90']:.3f} | "
                     f"{block['p95']:.3f} | {block['max']:.3f} | "
                     f"{report['units']['unitsWithStartShiftOver250ms'] if name == 'start' else ''} | "
                     f"{report['units']['unitsWithStartShiftOver500ms'] if name == 'start' else ''} |")
    lines += [
        "",
        "## Findings",
        "",
        *[f"- {item}" for item in report["findings"]],
        "",
        "## Limits",
        "",
        *[f"- {item}" for item in report["limitations"]],
        "",
        "## Reproduction",
        "",
        "```bash",
        *report["commands"],
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--whisperx", type=Path, required=True)
    parser.add_argument("--mfa", type=Path)
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--raw-whisper", type=Path, required=True)
    parser.add_argument("--raw-gpt4o", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    case = json.loads(args.case.read_text(encoding="utf-8"))
    whisperx_payload = json.loads(args.whisperx.read_text(encoding="utf-8"))
    raw_whisper = json.loads(args.raw_whisper.read_text(encoding="utf-8"))
    raw_gpt4o = args.raw_gpt4o.read_text(encoding="utf-8")
    transcript = json.loads(args.transcript.read_text(encoding="utf-8")) if args.transcript else None
    mfa_payload = json.loads(args.mfa.read_text(encoding="utf-8")) if args.mfa else None

    a = {int(token["index"]): token for token in case["tokens"]}
    b = {int(word["tokenIndex"]): word for word in whisperx_payload["words"]}
    duration = float(case["source"]["mediaDurationSeconds"])

    structure_a = structure(a, duration, len(case["tokens"]))
    structure_b = structure(b, duration, len(case["tokens"]))
    agreement_ab = pairwise(a, b)
    groups = bucket_groups(a)
    by_bucket = compare_by_group(a, b, groups)
    units = unit_metrics(case, a, b)
    text = text_accuracy(case, transcript, raw_whisper, raw_gpt4o)
    reference = mfa_reference(case, a, b, mfa_payload) if mfa_payload else None
    review = review_queue(case, a, b, mfa_payload, units)

    findings = []
    if structure_a["zeroOrNegativeDuration"] or structure_a["overlappingAdjacentPairs"]:
        findings.append(
            f"Arm A contains {structure_a['zeroOrNegativeDuration']} zero/negative-duration words and "
            f"{structure_a['overlappingAdjacentPairs']} overlapping adjacent pairs; arm B contains "
            f"{structure_b['zeroOrNegativeDuration']} and {structure_b['overlappingAdjacentPairs']}.")
    if reference:
        mid = reference["metrics"]["mid"]
        findings.append(
            f"Against MFA, B is closer on {mid['closer']['armB']} words and A on "
            f"{mid['closer']['armA']} (tie {mid['closer']['tie']}); median mid error "
            f"{mid['armA']['p50']:.3f} s for A versus {mid['armB']['p50']:.3f} s for B.")
        unit_reference = reference.get("units") or {}
        if unit_reference.get("comparedUnits"):
            start = unit_reference["start"]
            end = unit_reference["end"]
            findings.append(
                f"On {unit_reference['comparedUnits']} units covered at both edges by MFA, B is "
                f"closer on start for {start['closer']['armB']} units versus "
                f"{start['closer']['armA']} for A, and on end for {end['closer']['armB']} versus "
                f"{end['closer']['armA']}.")
    synthetic = reference["byTimingSource"].get("synthetic_span") if reference else None
    if synthetic:
        findings.append(
            f"On the {synthetic['words']} words whose A time was synthesized by the historical anchor "
            f"builder, A-MFA p95 is {synthetic['armA']['p95']:.3f} s and B-MFA p95 is "
            f"{synthetic['armB']['p95']:.3f} s.")
    findings.append(
        f"Unit start shifts: p50 {units['startDelta']['p50']:.3f} s, p95 "
        f"{units['startDelta']['p95']:.3f} s; {units['unitsWithStartShiftOver250ms']} of "
        f"{units['units']} units move more than 0.25 s, so the timeline cannot be swapped without "
        f"re-checking subtitle cue boundaries.")
    text_arm = text["arms"].get("whisperx_large_v3")
    if text_arm:
        findings.append(
            f"WhisperX large-v3 WER on its own transcript is {text_arm['wer']:.4%} versus the approved "
            f"table; this is a text check, not a timing check.")
    findings.append(
        f"No human word-level Gold exists for this episode. The MFA comparison and the listening "
        f"queue are machine evidence only; status remains `{review['status']}`.")

    limitations = [
        "Arm A word times came from OpenAI whisper-1 native timestamps; the approved text replaced "
        "some whisper tokens, and those replacement spans were synthesized by the historical builder.",
        "Arm B aligns the approved text with WhisperX wav2vec2; it cannot prove that the approved "
        "text is complete or that a forced boundary matches human perception.",
        "MFA is a third forced-alignment estimate with its own model errors; agreement with it is "
        "consistency, not absolute accuracy.",
        "Approved English text and window were human-approved in the source run; their timing was "
        "not independently reviewed.",
    ]

    commands = [
        "python3 experiments/whisperx-timeline-ab/prepare_case.py \\",
        "  --anchor-manifest <layer1>/anchor-manifest.json --raw-whisper <layer1>/raw-whisper.json \\",
        "  --audio <source>/media/sermon-16k.wav --out artifacts/whisperx-timeline-ab/case-20261108",
        "artifacts/whisperx-timeline-ab/runtime/bin/python experiments/whisperx-timeline-ab/run_whisperx_align.py \\",
        "  --case artifacts/whisperx-timeline-ab/case-20261108/case.json \\",
        "  --audio <source>/media/sermon-16k.wav --out artifacts/whisperx-timeline-ab/align-full-v2",
        "PYTHONPATH=packages/production/src python3 experiments/whisperx-timeline-ab/run_mfa.py \\",
        "  --case artifacts/whisperx-timeline-ab/case-20261108/case.json \\",
        "  --audio <source>/media/sermon-16k.wav --out artifacts/whisperx-timeline-ab/mfa-all-v3 \\",
        "  --all-safe --skip-chunk c0049",
        "python3 experiments/whisperx-timeline-ab/score_ab.py \\",
        "  --case artifacts/whisperx-timeline-ab/case-20261108/case.json \\",
        "  --whisperx artifacts/whisperx-timeline-ab/align-full-v2/whisperx-aligned.json \\",
        "  --mfa artifacts/whisperx-timeline-ab/mfa-all-v3/mfa-aligned.json \\",
        "  --transcript artifacts/whisperx-timeline-ab/full-run/sermon-16k.json \\",
        "  --raw-whisper <layer1>/raw-whisper.json --raw-gpt4o <layer1>/raw-gpt4o-transcribe.txt \\",
        "  --out artifacts/whisperx-timeline-ab/report-final",
        "python3 experiments/whisperx-timeline-ab/build_review.py \\",
        "  --report artifacts/whisperx-timeline-ab/report-final \\",
        "  --audio <source>/media/sermon-16k.wav --out artifacts/whisperx-timeline-ab/report-final/review",
    ]

    report = {
        "status": "machine_ab_requires_human_timing_gold",
        "schemaVersion": "sermon-whisperx-timeline-ab-report-v1",
        "source": {
            "date": case["source"]["date"],
            "episode": "2026-11-08 Sunday sermon source (jesus-is-just run)",
            "durationSeconds": duration,
            "audioSha256": case["source"]["audioSha256"],
            "anchorManifestSha256": case["source"]["anchorManifestSha256"],
            "caseSha256": __import__("hashlib").sha256(args.case.read_bytes()).hexdigest(),
        },
        "case": case["counts"],
        "arms": {
            "A": "OpenAI whisper-1 verbose_json word timestamps, mapped onto the approved text",
            "B": "WhisperX wav2vec2 forced alignment of the approved text",
            "reference": "MFA english_mfa forced alignment of the same text (model estimate)",
        },
        "structure": {"armA": structure_a, "armB": structure_b},
        "agreement": {"ab": agreement_ab, "byFiveMinuteBucket": by_bucket},
        "units": units,
        "text": text,
        "mfaReference": reference,
        "review": review,
        "findings": findings,
        "limitations": limitations,
        "commands": commands,
    }
    write_json(args.out / "report.json", report)
    (args.out / "summary.md").write_text(markdown(report), encoding="utf-8")
    write_json(args.out / "review-queue.json", review)

    with (args.out / "word-comparison.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["tokenIndex", "text", "timingSource", "aStart", "aEnd", "bStart", "bEnd",
                         "bMinusAStart", "bMinusAEnd"])
        for index in sorted(set(a) & set(b)):
            writer.writerow([index, a[index]["text"], a[index].get("timingSource", ""),
                             f"{a[index]['start']:.4f}", f"{a[index]['end']:.4f}",
                             f"{b[index]['start']:.4f}", f"{b[index]['end']:.4f}",
                             f"{b[index]['start'] - a[index]['start']:.4f}",
                             f"{b[index]['end'] - a[index]['end']:.4f}"])
    with (args.out / "unit-comparison.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["unitId", "text", "aStart", "aEnd", "bStart", "bEnd",
                         "startDelta", "endDelta"])
        for row in units["all"]:
            writer.writerow([row["unitId"], row["text"], f"{row['armA']['start']:.4f}",
                             f"{row['armA']['end']:.4f}", f"{row['armB']['start']:.4f}",
                             f"{row['armB']['end']:.4f}", f"{row['startDelta']:.4f}",
                             f"{row['endDelta']:.4f}"])
    print(json.dumps({"out": str(args.out), "status": report["status"],
                      "mfaComparedWords": reference["comparedWords"] if reference else 0,
                      "reviewWords": len(review["wordCandidates"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
