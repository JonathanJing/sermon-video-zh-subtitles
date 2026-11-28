#!/usr/bin/env python3
"""Layer 1 sentence table for a single-speaker sermon, from the two OpenAI passes.

  build    raw-whisper.json (+ optional machine fixes) -> anchor-manifest.json,
           english-review.csv, layer1-summary.json, english-crosscheck.json
  revise   a candidate manifest + the reviewer's edits -> the final manifest and csv

Timing and per-word text come from the timing pass: segment text is assigned word by word
inside its own segment, so a dropped filler cannot drift across a pause. Sentence units close
on . ? ! and split again at the largest pause when longer than --max-seconds. The text pass is
never spliced into the word stream; `build` aligns it per unit and records where the two passes
disagree, so the reviewer sees both readings.

`revise` works on the candidate the reviewer saw, with that candidate's unit ids: replace a
unit's English, merge a unit into the previous one, or drop a unit. Units are renumbered after
it, so the receipt must bind the revised manifest, not the candidate.

This is the 2026-11-21 week-11 script with the episode-specific values turned into arguments.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path

NORMAL = re.compile(r"[^0-9a-z']")
CLOSERS = "\"'”’)]}"
END = (".", "?", "!")
TEXT_SOURCE = ("whisper-1 verbose_json segment text, assigned per word inside its own pause segment; "
               "gpt-4o-transcribe is the independent text cross-check and only feeds correction rules")


def norm(text: str) -> str:
    return NORMAL.sub("", text.lower().replace("’", "'"))


def json_sha(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def media_sha(path: Path) -> tuple[str, float]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    duration = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                               "-of", "csv=p=0", str(path)], check=True, capture_output=True,
                              text=True).stdout.strip()
    return digest.hexdigest(), float(duration)


def word_texts(words: list[dict], segments: list[dict]) -> list[str]:
    texts: list[str | None] = [None] * len(words)
    mid = [(w["start"] + w["end"]) / 2 for w in words]
    for seg in segments:
        lo, hi = float(seg["start"]), float(seg["end"])
        idx = [i for i, t in enumerate(mid) if lo - 0.05 <= t <= hi + 0.05]
        if not idx:
            continue
        tokens = str(seg.get("text", "")).split()
        if not tokens:
            continue
        if len(tokens) == len(idx):
            for k, i in enumerate(idx):
                texts[i] = tokens[k]
            continue
        a = [norm(words[i]["text"]) or "_" for i in idx]
        b = [norm(t) or "_" for t in tokens]
        matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
        blocks = [(m.a, m.b, m.size) for m in matcher.get_matching_blocks() if m.size]
        previous_end = 0
        for i1, j1, n in blocks:
            if i1 > 0:
                anchor = idx[i1 - 1]
                for t in range(previous_end, j1):
                    texts[anchor] = ((texts[anchor] or words[anchor]["text"]) + " " + tokens[t]).strip()
            for k in range(n):
                texts[idx[i1 + k]] = tokens[j1 + k]
            previous_end = j1 + n
    return [t if t else w["text"] for t, w in zip(texts, words)]


def closes(text: str) -> bool:
    return text.rstrip(CLOSERS).endswith(END)


def biggest_pause(words: list[dict]) -> int | None:
    best, gap = None, 0.0
    for i in range(1, len(words)):
        g = words[i]["start"] - words[i - 1]["end"]
        if g > gap:
            best, gap = i, g
    return best if gap >= 0.25 else None


def chunk(words: list[dict], max_seconds: float) -> list[list[dict]]:
    if not words:
        return []
    if words[-1]["end"] - words[0]["start"] <= max_seconds or len(words) < 2:
        return [words]
    cut = biggest_pause(words)
    if cut is None:
        mids = [i for i in range(1, len(words))
                if words[i - 1]["text"].rstrip(CLOSERS).endswith(",")]
        cut = min(mids, key=lambda i: abs(i - len(words) // 2)) if mids else len(words) // 2
    return chunk(words[:cut], max_seconds) + chunk(words[cut:], max_seconds)


def sentences(words: list[dict], max_seconds: float) -> list[list[dict]]:
    groups, current = [], []
    for word in words:
        current.append(word)
        if closes(word["text"]):
            groups.extend(chunk(current, max_seconds))
            current = []
    if current:
        groups.extend(chunk(current, max_seconds))
    return groups


def tidy(text: str) -> str:
    return re.sub(r"\s+([,.;:!?])", r"\1", text).strip()


def renumber(units: list[dict]) -> None:
    for i, unit in enumerate(units):
        unit["sourceUnitId"] = f"u{i + 1:04d}"
    for i, unit in enumerate(units):
        nxt = units[i + 1]["start"] if i + 1 < len(units) else unit["end"]
        unit["boundary"]["pauseAfterSeconds"] = round(max(0.0, nxt - unit["end"]), 3)


def merge_groups(units: list[dict], merges: list[list[str]], dropped: set[str]) -> tuple[list[dict], list[dict]]:
    """Fold each group into its first unit, drop the listed units, renumber."""
    index = {unit["sourceUnitId"]: unit for unit in units}
    merged_from, absorbed = [], set()
    for group in merges:
        head = index.get(group[0])
        if head is None or any(uid in absorbed for uid in group):
            raise SystemExit(f"fixes: bad merge {group}")
        text, merged_words = head["english"], list(head["words"])
        for uid in group[1:]:
            tail = index.get(uid)
            if tail is None:
                raise SystemExit(f"fixes: bad merge tail {uid}")
            text = text.rstrip() + " " + tail["english"].strip()
            merged_words.extend(tail["words"])
            absorbed.add(uid)
        head.update({"english": text, "words": merged_words, "end": index[group[-1]]["end"],
                     "boundary": {"pauseAfterSeconds": 0.0,
                                  "clauseComplete": text.rstrip(CLOSERS).endswith(END)}})
        merged_from.append({"kept": head["sourceUnitId"], "absorbed": group[1:],
                            "seconds": round(head["end"] - head["start"], 2)})
    unknown = sorted(dropped - set(index))
    if unknown:
        raise SystemExit(f"fixes: unknown unit to drop {unknown}")
    units = [u for u in units if u["sourceUnitId"] not in absorbed and u["sourceUnitId"] not in dropped]
    for unit in units:
        unit["english"] = tidy(unit["english"])
    renumber(units)
    return units, merged_from


def apply_fixes(units: list[dict], fixes: dict) -> tuple[list[dict], dict]:
    """Machine fixes: regex rules everywhere or per unit, then merges and drops."""
    index = {unit["sourceUnitId"]: unit for unit in units}
    fixed = []
    for rule in fixes.get("global", []):
        for unit in units:
            before = unit["english"]
            unit["english"] = re.sub(rule["pattern"], rule["replacement"], unit["english"])
            if unit["english"] != before:
                fixed.append({"sourceUnitId": unit["sourceUnitId"], "kind": "global",
                              "pattern": rule["pattern"], "before": before, "after": unit["english"]})
    for unit_id, rules_for_unit in fixes.get("text", {}).items():
        unit = index.get(unit_id)
        if unit is None:
            raise SystemExit(f"fixes: unknown unit {unit_id}")
        for rule in rules_for_unit:
            before = unit["english"]
            unit["english"] = re.sub(rule["pattern"], rule["replacement"], unit["english"])
            if unit["english"] != before:
                fixed.append({"sourceUnitId": unit_id, "kind": "text", "pattern": rule["pattern"],
                              "before": before, "after": unit["english"]})
    dropped = set(fixes.get("drop", []))
    units, merged_from = merge_groups(units, fixes.get("merge", []), dropped)
    return units, {"fixes": fixed, "merges": merged_from, "dropped": sorted(dropped)}


def second_pass(units: list[dict], chunks: list[dict]) -> dict[str, dict]:
    """Per unit, the text-pass words aligned to the unit's own words, and whether the passes agree."""
    flat = [(ui, word) for ui, unit in enumerate(units) for word in unit["words"]]
    assigned: list[list[str]] = [[] for _ in units]
    covered = [False] * len(units)
    for part in chunks:
        lo, hi = float(part["start"]), float(part["end"])
        idx = [i for i, (_, w) in enumerate(flat) if lo <= (w["start"] + w["end"]) / 2 < hi]
        tokens = str(part.get("text", "")).split()
        if not idx or not tokens:
            continue
        a = [norm(flat[i][1]["text"]) or "_" for i in idx]
        b = [norm(t) or "_" for t in tokens]
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag == "delete":
                continue
            if tag == "equal":
                for k in range(i2 - i1):
                    assigned[flat[idx[i1 + k]][0]].append(tokens[j1 + k])
            elif i1 == i2:  # insert: belongs to the word before it
                assigned[flat[idx[max(i1 - 1, 0)]][0]].extend(tokens[j1:j2])
            else:  # replace: spread over the replaced words in order
                span, count = i2 - i1, j2 - j1
                for t in range(count):
                    assigned[flat[idx[i1 + (t * span) // count]][0]].append(tokens[j1 + t])
        for i in idx:
            covered[flat[i][0]] = True
    out = {}
    for ui, unit in enumerate(units):
        if not covered[ui]:
            continue
        text = " ".join(assigned[ui])
        mine = [n for n in (norm(t) for t in unit["english"].split()) if n]
        other = [n for n in (norm(t) for t in assigned[ui]) if n]
        out[unit["sourceUnitId"]] = {"secondPass": text, "agrees": mine == other}
    return out


def write_outputs(out: Path, manifest: dict) -> dict:
    units = manifest["sourceUnits"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "anchor-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    with (out / "english-review.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "sourceUnitId", "start", "end", "english"])
        writer.writeheader()
        for i, unit in enumerate(units):
            writer.writerow({"id": f"s{i + 1:04d}", "sourceUnitId": unit["sourceUnitId"],
                             "start": f"{unit['start']:.2f}", "end": f"{unit['end']:.2f}",
                             "english": unit["english"]})
    summary = {"units": len(units), "words": manifest["counts"]["sourceWords"],
               "duration": manifest["input"]["mediaDurationSeconds"],
               "mediaSha256": manifest["input"]["mediaSha256"],
               "maxUnitSeconds": max(u["end"] - u["start"] for u in units),
               "over12s": sum(1 for u in units if u["end"] - u["start"] > 12.01),
               "anchorManifestJsonSha256": json_sha(manifest), "out": str(out)}
    (out / "layer1-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n")
    return summary


def build(args) -> dict:
    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    whisper_words = [{"text": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"])}
                     for w in raw["words"] if str(w.get("word", "")).strip()]
    per_word = word_texts(whisper_words, raw["segments"])
    words = [{"text": text, "start": w["start"], "end": w["end"]} for text, w in zip(per_word, whisper_words)]

    units = []
    for i, group in enumerate(sentences(words, args.max_seconds)):
        english = tidy(" ".join(w["text"] for w in group))
        if english:
            english = english[0].upper() + english[1:]
        units.append({
            "sourceUnitId": f"u{i + 1:04d}", "english": english,
            "start": round(group[0]["start"], 3), "end": round(group[-1]["end"], 3),
            "boundary": {"pauseAfterSeconds": 0.0, "clauseComplete": english.rstrip(CLOSERS).endswith(END)},
            "words": [{"text": w["text"], "start": round(w["start"], 3), "end": round(w["end"], 3)}
                      for w in group],
        })
    renumber(units)

    applied = None
    if args.fixes and args.fixes.exists():
        units, applied = apply_fixes(units, json.loads(args.fixes.read_text(encoding="utf-8")))
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "english-fixes-applied.json").write_text(
            json.dumps(applied, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    sha, duration = (args.media_sha256, args.media_duration) if args.media_sha256 else media_sha(args.media)
    manifest = {
        "schemaVersion": "sermon-sentence-anchor-manifest-v2",
        "status": "machine_anchor_candidate_requires_review",
        "releaseEligible": False,
        "humanReview": {"englishTranscriptCompleteness": "pending",
                        "sentenceAndPauseBoundaries": "pending",
                        "speakerAttribution": "pending"},
        "policy": {
            "unitPolicy": "sermon_single_speaker_clause_v1",
            "timingBasis": args.timing_basis,
            "textSource": TEXT_SOURCE,
            "speakerSource": args.speaker_source,
            "splitRule": f"sentence close on .?! then max {args.max_seconds:g} s at the largest pause (>=0.25 s)",
        },
        "input": {"source": args.timing_source, "sourceUrl": args.source_url, "date": args.date,
                  "mediaSha256": sha, "mediaDurationSeconds": duration,
                  "whisperSegments": len(raw.get("segments", [])), "words": len(words)},
        "counts": {"sourceUnits": len(units), "sourceWords": len(words)},
        "sourceUnits": units,
    }
    summary = write_outputs(args.out, manifest)
    summary["machineFixes"] = len(applied["fixes"]) if applied else 0
    if args.text_chunks and args.text_chunks.exists():
        check = second_pass(units, json.loads(args.text_chunks.read_text(encoding="utf-8")))
        (args.out / "english-crosscheck.json").write_text(json.dumps(
            {"anchorManifestJsonSha256": summary["anchorManifestJsonSha256"], "units": check},
            ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        summary["secondPassDisagreements"] = sum(1 for row in check.values() if not row["agrees"])
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def revise_manifest(manifest: dict, edits: dict) -> tuple[dict, dict]:
    """Apply the reviewer's edits to the candidate they reviewed. Returns (revised manifest, record)."""
    units = json.loads(json.dumps(manifest["sourceUnits"]))
    index = {unit["sourceUnitId"]: unit for unit in units}
    order = [unit["sourceUnitId"] for unit in units]
    replaced = []
    for unit_id, text in (edits.get("replace") or {}).items():
        unit = index.get(unit_id)
        text = tidy(str(text))
        if unit is None or not text:
            raise SystemExit(f"edits: bad replacement for {unit_id}")
        if text != unit["english"]:
            replaced.append({"sourceUnitId": unit_id, "before": unit["english"], "after": text})
            unit["english"] = text
            unit["boundary"]["clauseComplete"] = text.rstrip(CLOSERS).endswith(END)
    dropped = set(edits.get("drop") or [])
    groups: list[list[str]] = []
    for unit_id in sorted(set(edits.get("mergeWithPrevious") or []), key=order.index if order else None):
        if unit_id not in index or order.index(unit_id) == 0:
            raise SystemExit(f"edits: cannot merge {unit_id} into a previous unit")
        previous = order[order.index(unit_id) - 1]
        if unit_id in dropped or previous in dropped:
            raise SystemExit(f"edits: {unit_id} is both merged and dropped")
        if groups and groups[-1][-1] == previous:
            groups[-1].append(unit_id)
        else:
            groups.append([previous, unit_id])
    units, merged = merge_groups(units, groups, dropped)
    revised = {**manifest, "counts": {**manifest["counts"], "sourceUnits": len(units)}, "sourceUnits": units}
    record = {"candidateAnchorManifestJsonSha256": json_sha(manifest),
              "revisedAnchorManifestJsonSha256": json_sha(revised),
              "replaced": replaced, "merges": merged, "dropped": sorted(dropped)}
    return revised, record


def revise(args) -> dict:
    manifest = json.loads(args.candidate.read_text(encoding="utf-8"))
    edits = json.loads(args.edits.read_text(encoding="utf-8"))
    revised, record = revise_manifest(manifest, edits)
    summary = write_outputs(args.out, revised)
    (args.out / "english-edits-applied.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    summary.update(replaced=len(record["replaced"]), merges=len(record["merges"]), dropped=len(record["dropped"]))
    if args.text_chunks and args.text_chunks.exists():
        check = second_pass(revised["sourceUnits"], json.loads(args.text_chunks.read_text(encoding="utf-8")))
        (args.out / "english-crosscheck.json").write_text(json.dumps(
            {"anchorManifestJsonSha256": summary["anchorManifestJsonSha256"], "units": check}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    b = commands.add_parser("build", help="sentence table from the timing pass")
    b.add_argument("--raw", type=Path, required=True, help="raw-whisper.json")
    b.add_argument("--media", type=Path, help="source media, hashed unless --media-sha256 is given")
    b.add_argument("--media-sha256")
    b.add_argument("--media-duration", type=float)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--source-url", required=True)
    b.add_argument("--date", required=True, help="the Sunday this message belongs to, YYYY-MM-DD")
    b.add_argument("--speaker-source", required=True, help="how the speaker was determined (manifest policy text)")
    b.add_argument("--max-seconds", type=float, default=12.0)
    b.add_argument("--fixes", type=Path, help="machine fixes: global / text / merge / drop")
    b.add_argument("--text-chunks", type=Path, help="gpt-4o-chunks.json for the per-unit cross-check")
    b.add_argument("--timing-basis", default="OpenAI whisper-1 verbose_json word timestamps",
                   help="policy text for the word-timing source")
    b.add_argument("--timing-source", default="raw-whisper.json",
                   help="manifest input.source; use raw-whisperx.json for WhisperX timing")
    r = commands.add_parser("revise", help="apply the reviewer's edits to a candidate manifest")
    r.add_argument("--candidate", type=Path, required=True)
    r.add_argument("--edits", type=Path, required=True, help="JSON: replace / mergeWithPrevious / drop")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--text-chunks", type=Path, help="gpt-4o-chunks.json: rewrite the per-unit cross-check for the revised units")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        if not args.media_sha256 and not args.media:
            raise SystemExit("build needs --media or --media-sha256 with --media-duration")
        if args.media_sha256 and args.media_duration is None:
            raise SystemExit("--media-sha256 needs --media-duration")
        build(args)
    else:
        revise(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
