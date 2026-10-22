#!/usr/bin/env python3
"""Give every sentence a speaker from a diarization result (experiment only, two-speaker podcasts).

Inputs: a run prepared by prepare_clip.py (its clip.json gives the media start), diarization
segments ``[{"start_time", "end_time", "speaker_id"}]`` in media seconds, and a label mapping
``{"mapping": {"0": {"speakerId": "steve_bang_lee", "displayName": ...}, ...}}``. A label whose
speakerId is null keeps its displayName as a slug (``john_thomas``) so the sentence still has an
owner; whether that speaker has a voice is decided later in build_speech.py.

By default each sentence gets the label with the most overlap with its own time span. Diarization
boundaries are only accurate to about half a second, so a short line ("What up, Steve?") can sit
inside the other speaker's segment. With --use-text the sentence words are aligned to the
diarization transcript (difflib over normalized tokens, in order) and each matched word votes with
its segment's label; time overlap decides only for sentences with no matched words. Either way:
  speakerId        the mapped speaker
  speakerShare     that label's share of the sentence's diarized speech (0-1)
  speakerReview    "check" when the share is below --min-share or the sentence has no diarized speech
Rewrites sentences.jsonl in place (other fields unchanged) and writes speakers.json with counts and
the sentences to check. Sentences are not split at speaker changes here; a sentence marked "check"
may contain both speakers and should be split by hand if it matters.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import re


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower().replace("’", "'"))


def text_votes(rows: list[dict], segments: list[dict]) -> list[collections.Counter]:
    """Per sentence, count diarization labels of the transcript words its own words align to."""
    import difflib
    diar = [(tok, str(s["speaker_id"])) for s in segments for tok in tokens(s.get("text", ""))]
    mine = [(tok, i) for i, row in enumerate(rows) for tok in tokens(row["english"])]
    matcher = difflib.SequenceMatcher(None, [t for t, _ in mine], [t for t, _ in diar], autojunk=False)
    votes = [collections.Counter() for _ in rows]
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            votes[mine[block.a + k][1]][diar[block.b + k][1]] += 1
    return votes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--segments", type=Path, required=True, help="diarization segments.json (media seconds)")
    parser.add_argument("--mapping", type=Path, required=True, help="speaker label mapping json")
    parser.add_argument("--min-share", type=float, default=0.8)
    parser.add_argument("--use-text", action="store_true", help="vote by aligned transcript words, time overlap as fallback")
    parser.add_argument("--offset", type=float, help="media seconds of clip time 0 (default: clip.json mediaStart)")
    args = parser.parse_args()

    clip = json.loads((args.run / "clip.json").read_text(encoding="utf-8"))
    media_start = clip["mediaStart"] if args.offset is None else args.offset
    raw = json.loads(args.segments.read_text(encoding="utf-8"))
    segments = [s for s in (raw if isinstance(raw, list) else raw["segments"]) if s.get("speaker_id") is not None]
    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))["mapping"]
    owners = {str(label): (m.get("speakerId") or slug(m["displayName"])) for label, m in mapping.items()}

    path = args.run / "sentences.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    counts, review = collections.Counter(), []
    votes = text_votes(rows, segments) if args.use_text else [collections.Counter() for _ in rows]
    for row, vote in zip(rows, votes):
        a, b = media_start + row["start"], media_start + row["end"]
        overlap = collections.Counter()
        for s in segments:
            o = min(b, s["end_time"]) - max(a, s["start_time"])
            if o > 0:
                overlap[str(s["speaker_id"])] += o
        total = sum(overlap.values())
        row.pop("speakerBasis", None)
        if sum(vote.values()) > 0:
            label, top = vote.most_common(1)[0]
            share = top / sum(vote.values())
            row["speakerBasis"] = "text"
        elif total <= 0:
            # No diarized speech inside the sentence: take the nearest segment's label.
            nearest = min(segments, key=lambda s: min(abs(s["start_time"] - b), abs(s["end_time"] - a)))
            label, share = str(nearest["speaker_id"]), 0.0
        else:
            label, top = overlap.most_common(1)[0]
            share = top / total
        if label not in owners:
            raise SystemExit(f"diarization label {label!r} has no entry in the mapping")
        row["speakerId"] = owners[label]
        row["speakerShare"] = round(share, 3)
        if share < args.min_share:
            row["speakerReview"] = "check"
            review.append({"id": row["id"], "speakerId": row["speakerId"], "share": round(share, 3), "english": row["english"]})
        else:
            row.pop("speakerReview", None)
        counts[row["speakerId"]] += 1
    with path.open("w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    seconds = collections.Counter()
    for row in rows:
        seconds[row["speakerId"]] += row["end"] - row["start"]
    summary = {"sentences": len(rows), "bySpeaker": dict(counts), "secondsBySpeaker": {k: round(v, 1) for k, v in seconds.items()},
               "minShare": args.min_share, "toCheck": review, "segments": str(args.segments), "mapping": str(args.mapping)}
    (args.run / "speakers.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("sentences", "bySpeaker", "secondsBySpeaker")} | {"toCheck": len(review)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
