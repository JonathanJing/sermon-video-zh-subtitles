#!/usr/bin/env python3
"""Build a static review pack from a sentence-first run directory.

    python3 tools/ops/review_pack.py build \
        --run artifacts/sentence-first-agent/20261108-jesus-is-just-zh \
        --locale zh-Hans --checkpoint audio --out artifacts/review-pack/20261108-zh

The pack is a plain directory that any static host can serve (an Aliyun OSS
Hong Kong bucket, a plain `python3 -m http.server`, or Firebase Hosting):

    index.html app.js styles.css   copied from apps/review-web/
    pack.json                     sentence-first-review-pack-v1
    audio/review.mp3              the reviewer's mixed track (audio checkpoint only)
    audio/clip-<id>.mp3           only the flagged sentences, cut from tts/<id>.wav

Why a static pack: the reviewer sits behind a network where the production
machine cannot be reached. A pack can be opened without an API, without a
session, and without the run directory ever leaving the producer.

Nothing here writes into the run directory, and nothing leaves the machine
until someone uploads the directory. `--checkpoint text` omits every audio
file so a text review survives an unusable network.

The page reports the verdict as one short command line to paste back into the
review channel (see docs/design/unattended-cross-pacific-production.zh.md
§6.5). It never posts anything by itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

SCHEMA = "sentence-first-review-pack-v1"
APP_DIR = Path(__file__).resolve().parents[2] / "apps" / "review-web"
REPO_ROOT = Path(__file__).resolve().parents[2]
LAG_FLAG_SECONDS = 0.8
MAX_CLIPS_DEFAULT = 120
CLIP_BITRATE = "48k"
CLIP_SAMPLE_RATE = "24000"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def short_code(seed: str) -> str:
    """Four unambiguous characters; the reviewer types this in the chat."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    value = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12], 16)
    return "".join(alphabet[value >> (5 * i) & 0x1F] for i in range(4))


def quiet_note(note: str) -> bool:
    return note == "pass" or str(note or "").startswith("reused")


def flags_for(sentence: dict, translated: dict, spoken: dict, scheduled: dict,
              notes: dict, doubt: dict) -> list[str]:
    flags = []
    note = str(translated.get("reviewNote") or "pass")
    if not quiet_note(note):
        flags.append("revised")
    if notes.get(sentence["id"]):
        flags.append("note")
    if sentence.get("speakerReview") == "check":
        flags.append("speaker")
    spoken_text = str(spoken.get("spokenText") or "")
    target = str(translated.get("target") or "")
    if spoken_text and target and spoken_text.strip() != target.strip():
        flags.append("spoken")
    if re.search(r"\d", spoken_text):
        flags.append("digits")
    lag = float(scheduled.get("lagSeconds") or 0.0)
    if lag > LAG_FLAG_SECONDS:
        flags.append("lag")
    if doubt.get(sentence["id"]):
        flags.append("doubt")
    return flags


def make_clip(source: Path, target: Path) -> bool:
    """Transcode one sentence to a small mp3; returns False when it cannot be read."""
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-v", "error", "-y", "-i", str(source), "-ac", "1",
               "-ar", CLIP_SAMPLE_RATE, "-b:a", CLIP_BITRATE, str(target)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False
    if result.returncode != 0:
        target.unlink(missing_ok=True)
        return False
    return True


def build(args: argparse.Namespace) -> dict:
    run = Path(args.run).resolve()
    if not (run / "sentences.jsonl").exists():
        raise SystemExit(f"{run}: sentences.jsonl not found; not a sentence-first run directory")

    sentences = read_jsonl(run / "sentences.jsonl")
    translations = {row["id"]: row for row in read_jsonl(run / "translations.jsonl")}
    speech = {row["id"]: row for row in read_jsonl(run / "speech.jsonl")}
    schedule_rows = (json.loads((run / "schedule.json").read_text(encoding="utf-8"))["sentences"]
                     if (run / "schedule.json").exists() else [])
    scheduled = {row["id"]: row for row in schedule_rows}
    review = (json.loads((run / "review.json").read_text(encoding="utf-8"))
              if (run / "review.json").exists() else {})
    notes = review.get("notes") or {}
    doubt = {}
    decisions = (json.loads((run / "decisions.json").read_text(encoding="utf-8"))
                 if (run / "decisions.json").exists() else {})
    clip = (json.loads((run / "clip.json").read_text(encoding="utf-8"))
            if (run / "clip.json").exists() else {})

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "audio").mkdir(exist_ok=True)

    rows = []
    for index, sentence in enumerate(sentences, start=1):
        sid = sentence["id"]
        translated = translations.get(sid, {})
        spoken = speech.get(sid, {})
        sched = scheduled.get(sid, {})
        flags = flags_for(sentence, translated, spoken, sched, notes, doubt)
        rows.append({
            "id": sid,
            "index": index,
            "sourceUnitId": sentence.get("sourceUnitId"),
            "speaker": sentence.get("speakerId") or spoken.get("speaker"),
            "start": round(float(sentence.get("start") or 0.0), 3),
            "end": round(float(sentence.get("end") or 0.0), 3),
            "dubStart": round(float(sched.get("actualStart") or 0.0), 3),
            "dubSeconds": round(float(sched.get("dubSeconds") or 0.0), 3),
            "lag": round(float(sched.get("lagSeconds") or 0.0), 3),
            "english": sentence.get("english") or "",
            "target": translated.get("target") or "",
            "spoken": spoken.get("spokenText") or "",
            "note": translated.get("reviewNote") if not quiet_note(translated.get("reviewNote") or "") else "",
            "flags": flags,
            "clip": None,
        })

    flagged = [row for row in rows if row["flags"]]
    production_id = (args.production_id or decisions.get("productionId")
                     or f"{run.name}-{args.locale}")
    code = args.code or short_code(f"{production_id}|{args.locale}")

    track = None
    if args.checkpoint == "audio":
        source_mp3 = run / "review.mp3"
        if not source_mp3.exists():
            raise SystemExit(f"{source_mp3}: audio checkpoint needs review.mp3 (run finish_run.py first)")
        shutil.copyfile(source_mp3, out / "audio" / "review.mp3")
        track = {
            "url": "audio/review.mp3",
            "sha256": sha256_file(out / "audio" / "review.mp3"),
            "bytes": (out / "audio" / "review.mp3").stat().st_size,
            "seconds": round(float(schedule_rows[-1]["actualStart"]), 3) if schedule_rows else None,
        }

    clipped = 0
    if args.checkpoint == "audio" and args.clips:
        for row in flagged[: args.clips]:
            source = run / "tts" / f"{row['id']}.wav"
            if not source.exists():
                continue
            target = out / "audio" / f"clip-{row['id']}.mp3"
            if make_clip(source, target):
                row["clip"] = f"audio/{target.name}"
                clipped += 1

    pack = {
        "schemaVersion": SCHEMA,
        "productionId": production_id,
        "runId": run.name,
        "locale": args.locale,
        "checkpoint": args.checkpoint,
        "title": args.title or decisions.get("title") or run.name,
        "code": code,
        "builtAt": args.built_at,
        "source": {
            "media": Path(clip["media"]).name if clip.get("media") else None,
            "windowStart": clip.get("windowStart"),
            "clipSeconds": decisions.get("clipSeconds"),
            "sync": decisions.get("sync"),
        },
        "counts": {"sentences": len(rows), "flagged": len(flagged), "clips": clipped},
        "track": track,
        "sentences": rows,
    }

    for name in ("index.html", "app.js", "styles.css"):
        source = APP_DIR / name
        if not source.exists():
            raise SystemExit(f"{source}: review web app asset missing")
        shutil.copyfile(source, out / name)

    (out / "pack.json").write_text(
        json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8")
    return pack


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    build_parser = sub.add_parser("build", help="write a static review pack directory")
    build_parser.add_argument("--run", required=True, help="sentence-first run directory")
    build_parser.add_argument("--locale", required=True)
    build_parser.add_argument("--out", required=True, help="output directory (ignored path)")
    build_parser.add_argument("--checkpoint", choices=("text", "audio"), default="audio")
    build_parser.add_argument("--title")
    build_parser.add_argument("--production-id")
    build_parser.add_argument("--code", help="override the four-character review code")
    build_parser.add_argument("--clips", type=int, default=MAX_CLIPS_DEFAULT,
                              help=f"per-sentence clips for flagged rows (default {MAX_CLIPS_DEFAULT}, 0 disables)")
    build_parser.add_argument("--built-at", default=None, help="ISO timestamp; defaults to now")
    build_parser.set_defaults(func=build)

    args = parser.parse_args(argv)
    if getattr(args, "built_at", None) is None:
        import datetime as dt
        args.built_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    pack = args.func(args)
    print(json.dumps({
        "ok": True,
        "out": str(Path(args.out).resolve()),
        "productionId": pack["productionId"],
        "code": pack["code"],
        "checkpoint": pack["checkpoint"],
        "counts": pack["counts"],
        "trackBytes": pack["track"]["bytes"] if pack["track"] else 0,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
