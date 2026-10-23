#!/usr/bin/env python3
"""Normalize a rolling YouTube-style SRT into sentence units and validate timing.

The input is the common "rolling captions" SRT: consecutive cues overlap in time and
repeat the tail of the previous cue at their head. The normalizer de-duplicates the token
stream, interpolates each token inside its cue, splits at sentence punctuation/pauses,
cleans verified names, and enforces a monotonic, non-overlapping, minimum-duration
timeline. It writes an anchor manifest, an English-review CSV and a validation report.

This is a timing approximation, not MFA word alignment; the manifest says so. It is the
P0 preflight for the SRT-derived Layer 1 path: run it before slicing so a zero-duration
or overlapping unit cannot reach ``prepare_clip``.

Usage:
  srt_normalize.py --srt episode.srt --out layer1-srt --media episode.mkv \
      --source-url 'https://www.youtube.com/watch?v=...' --date 2026-09-19
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

ABBREV = {"mr.", "mrs.", "ms.", "dr.", "vs.", "e.g.", "i.e.", "a.d.", "b.c.", "st.", "jr.", "sr.", "no.", "fig.", "rev."}
# Verified name/term fixes from the 2026-10-23 episode; a new episode passes --replacements.
DEFAULT_REPLACEMENTS = {
    r"\bEric Guyer\b": "Eric Geiger",
    r"\bTom Delange\b": "Tom DeLonge",
    r"\bBlink ?182\b": "Blink-182",
    r"\bWhen the Man Comes Around\b": "The Man Comes Around",
    r"\bIranius\b": "Irenaeus",
    r"\bsecondguessing\b": "second-guessing",
}
STUTTER = {"i", "it's", "and", "the", "we", "you", "he", "she", "they", "a", "to", "of", "in", "for", "but",
           "or", "if", "as", "at", "on", "with", "from", "by", "my", "your", "his", "her", "its", "our",
           "their", "me", "him", "us", "them", "this", "that", "these", "those", "was", "were", "is", "are",
           "am", "do", "does", "did", "have", "has", "had", "will", "would", "can", "could", "should",
           "last", "through", "some", "just", "like"}


def parse_srt(text: str) -> list[tuple[float, float, str]]:
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)\s+-->\s+(\d+):(\d+):(\d+)[,.](\d+)", lines[1])
        if not m:
            continue
        g = list(map(int, m.groups()))
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        body = re.sub(r"<[^>]+>", " ", " ".join(lines[2:]))
        body = body.replace(">>", " ").replace("♪", " ")
        body = re.sub(r"\s+", " ", body).strip()
        if body and re.search(r"[A-Za-z0-9]", body):
            cues.append((start, end, body))
    return cues


def clean(text: str, replacements: dict[str, str]) -> str:
    for pattern, repl in replacements.items():
        text = re.sub(pattern, repl, text, flags=re.I)
    text = re.sub(r"\[[^\]]*\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def dedupe_tokens(cues: list[tuple[float, float, str]]) -> list[tuple[str, str, float, float]]:
    acc: list[tuple[str, str, float, float]] = []
    for start, end, body in cues:
        toks = [t for t in body.split() if re.search(r"[A-Za-z0-9]", t)]
        if not toks:
            continue
        norm = [re.sub(r"[^a-z0-9']", "", t.lower()) for t in toks]
        acc_norm = [a[1] for a in acc]
        k = 0
        for m in range(1, min(len(acc_norm), len(norm), 40) + 1):
            if acc_norm[-m:] == norm[:m]:
                k = m
        for i in range(k, len(toks)):
            t0 = start + i * (end - start) / len(toks)
            t1 = start + (i + 1) * (end - start) / len(toks)
            if acc:
                t0 = max(t0, acc[-1][3] - 0.05)
                t1 = max(t1, t0 + 0.08)
            acc.append((toks[i], norm[i], max(0.0, t0), t1))
    deduped = []
    for tok in acc:
        if deduped and tok[1] in STUTTER and tok[1] == deduped[-1][1]:
            deduped[-1] = (deduped[-1][0], deduped[-1][1], deduped[-1][2], tok[3])
            continue
        deduped.append(tok)
    # Rolling cues can overlap backwards; force one monotonic token timeline.
    for i in range(1, len(deduped)):
        t0 = max(deduped[i][2], deduped[i - 1][3])
        t1 = max(deduped[i][3], t0 + 0.08)
        deduped[i] = (deduped[i][0], deduped[i][1], t0, t1)
    return deduped


def build_units(acc, replacements, *, pause=0.8, max_unit_seconds=28.0, max_words=70):
    units, cur = [], []
    for i, tok in enumerate(acc):
        cur.append(tok)
        nxt = acc[i + 1][2] if i + 1 < len(acc) else tok[3]
        gap = nxt - tok[3]
        terminal = bool(re.search(r"[.?!][\"')\]]?$", tok[0]))
        abbreviation = tok[0].lower().rstrip("\"'") in ABBREV
        too_long = (tok[3] - cur[0][2]) > max_unit_seconds or len(cur) > max_words
        if (terminal and not abbreviation) or gap > pause or too_long:
            units.append(cur)
            cur = []
    if cur:
        units.append(cur)
    kept, dropped = [], 0
    for cur in units:
        text = clean(" ".join(t[0] for t in cur), replacements)
        if len(cur) == 1 and not re.search(r"[.?!]", text) and len(text) < 8:
            dropped += 1
            continue
        kept.append((cur, text))
    return kept, dropped


def normalize(cues, *, replacements, media_duration, window_start=None, window_end=None,
              min_duration=0.2, pause=0.8, max_unit_seconds=28.0):
    acc = dedupe_tokens(cues)
    kept, dropped = build_units(acc, replacements, pause=pause, max_unit_seconds=max_unit_seconds)
    source_units, rows = [], []
    prev_end = 0.0
    for i, (cur, text) in enumerate(kept, start=1):
        start = round(max(0.0, cur[0][2], prev_end), 3)
        end = round(max(cur[-1][3], start + 0.2), 3)
        if media_duration:
            end = min(end, round(float(media_duration), 3))
        if window_end is not None and start >= window_end:
            continue
        if window_start is not None and end <= window_start:
            continue
        prev_end = end
        words = [{"text": t[0], "start": round(t[2], 3), "end": round(t[3], 3)} for t in cur]
        uid = f"srt-u{i:04d}"
        unit = {"sourceUnitId": uid, "start": start, "end": end,
                "durationSeconds": round(end - start, 3), "english": text,
                "words": words, "partIndex": 1}
        source_units.append(unit)
        flags = []
        if re.search(r"\b(Eric|Geiger|Guyer|Steve|JT|Revelation|Mariners)\b", text, re.I):
            flags.append("name/term")
        if end - start > 20:
            flags.append("long")
        if len(cur) < 4:
            flags.append("short")
        rows.append({"id": f"s{i:04d}", "sourceUnitId": uid, "start": start, "end": end,
                     "english": text, "flags": ";".join(flags)})
    # Validation: the normalized timeline must be monotonic and non-overlapping.
    issues = []
    for i, u in enumerate(source_units):
        if u["end"] - u["start"] < min_duration - 1e-6:
            issues.append(f"{u['sourceUnitId']}: duration {u['durationSeconds']} < {min_duration}")
        if i and u["start"] < source_units[i - 1]["end"] - 1e-6:
            issues.append(f"{u['sourceUnitId']}: starts before previous end")
        if any(w["end"] < w["start"] for w in u["words"]):
            issues.append(f"{u['sourceUnitId']}: word end before start")
    return source_units, rows, acc, dropped, issues


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--srt", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--media", type=Path, help="optional media file for sha256 and duration")
    p.add_argument("--media-duration", type=float)
    p.add_argument("--source-url")
    p.add_argument("--date")
    p.add_argument("--window-start", type=float)
    p.add_argument("--window-end", type=float)
    p.add_argument("--min-duration", type=float, default=0.2)
    p.add_argument("--pause", type=float, default=0.8)
    p.add_argument("--replacements", type=Path, help="JSON object of regex -> replacement (merged over defaults)")
    p.add_argument("--validate-only", action="store_true", help="report raw cue and normalized issues without writing units")
    p.add_argument("--allow-issues", action="store_true", help="exit 0 even if normalized issues remain")
    a = p.parse_args(argv)

    text = a.srt.read_text(encoding="utf-8-sig")
    cues = parse_srt(text)
    raw_zero = sum(1 for s, e, _ in cues if e <= s)
    raw_overlap = sum(1 for i in range(1, len(cues)) if cues[i][0] < cues[i - 1][1] - 1e-6)
    replacements = dict(DEFAULT_REPLACEMENTS)
    if a.replacements:
        replacements.update(json.loads(a.replacements.read_text(encoding="utf-8")))
    media_sha = hashlib.sha256(a.media.read_bytes()).hexdigest() if a.media and a.media.exists() else None
    media_duration = a.media_duration
    if media_duration is None and a.media and a.media.exists():
        media_duration = None  # not probed here; pass --media-duration or let clamp use the last cue
    units, rows, acc, dropped, issues = normalize(
        cues, replacements=replacements, media_duration=media_duration,
        window_start=a.window_start, window_end=a.window_end,
        min_duration=a.min_duration, pause=a.pause)
    report = {
        "schemaVersion": "sermon-srt-normalization-v1",
        "srt": str(a.srt), "cues": len(cues),
        "rawIssues": {"zeroOrNegativeDuration": raw_zero, "overlappingCues": raw_overlap},
        "tokensRaw": len(acc), "tokensDeduped": sum(len(u["words"]) for u in units),
        "units": len(units), "droppedShortFragments": dropped,
        "minDurationSeconds": a.min_duration,
        "first": rows[0] if rows else None, "last": rows[-1] if rows else None,
        "flagged": sum(1 for r in rows if r["flags"]),
        "issues": issues, "status": "pass" if not issues else "fail",
        "timingBasis": "rolling SRT cue token interpolation (not MFA)",
    }
    print(json.dumps({k: v for k, v in report.items() if k not in ("first", "last")}, ensure_ascii=False, indent=1))
    if a.validate_only:
        return 0 if (not issues or a.allow_issues) else 1
    if issues and not a.allow_issues:
        print("refusing to write units with validation issues", file=sys.stderr)
        return 1
    a.out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schemaVersion": "sermon-sentence-anchor-manifest-v2",
        "status": "machine_anchor_candidate_requires_review", "releaseEligible": False,
        "humanReview": {"englishTranscriptCompleteness": "pending", "sentenceAndPauseBoundaries": "pending",
                        "speakerAttribution": "pending"},
        "policy": {"unitPolicy": "srt_rolling_token_v1",
                   "timingBasis": "rolling SRT cue token interpolation"},
        "input": {"source": a.srt.name, "sourceUrl": a.source_url, "date": a.date,
                  "mediaSha256": media_sha, "mediaDurationSeconds": media_duration,
                  "srtCues": len(cues)},
        "counts": {"sourceUnits": len(units), "sourceWords": sum(len(u["words"]) for u in units)},
        "sourceUnits": units,
    }
    (a.out / "anchor-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (a.out / "srt-normalization-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    with (a.out / "english-review.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "sourceUnitId", "start", "end", "english", "flags"])
        w.writeheader()
        w.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
