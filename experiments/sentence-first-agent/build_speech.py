#!/usr/bin/env python3
"""Apply the agent's review to translations.jsonl and write speech.jsonl (experiment only).

The agent writes ``translations.jsonl`` itself (step 5) and a small review file:

  {
    "locale": "ko",
    "speaker": "steve_bang_lee",
    "language": "Korean",                       optional; defaults from locale
    "revisions": {"s0036": {"target": "...", "note": "revised: ..."}},
    "notes": {"s0084": "note: ..."},            recorded as "pass; note: ..."
    "spokenForms": {"19쪽": "십구 쪽"},          subtitle form -> TTS reading
    "charsPerSecond": 6.0,                      optional; defaults from locale
    "speakers": {"steve_bang_lee": "steve_bang_lee", "john_thomas": "john_thomas"}
                                                optional, two-speaker runs: sentence speakerId
                                                (from assign_speakers.py) -> TTS speaker key
  }

With "speakers", every sentence must carry a speakerId listed there, and "speaker" is not
needed; each speech row then also records speakerId so the TTS can run one checkpoint at a time.

Every sentence without a revision or note gets reviewNote "pass". Each
spokenForms key must occur in at least one sentence, so a typo fails loudly.
``speech.jsonl`` keeps the subtitle text out of the TTS: only spokenText is read
aloud. budgetSeconds comes from slices/slices.json; estimatedSeconds is a rough
characters-per-second guess used only to flag sentences for attention.

For a second locale on the same clip, ``--share-from <first run>`` copies
sentences.jsonl and slices/slices.json from that run.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil

DEFAULTS = {  # locale -> (Qwen3-TTS language, counted characters, characters per second)
    "zh-Hans": ("Chinese", r"[一-鿿]", 4.3),
    "ko": ("Korean", r"[가-힣]", 6.0),
    "es": ("Spanish", r"[a-záéíóúñü]", 13.0),
}


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def share(source: Path, run: Path) -> None:
    for name in ("sentences.jsonl", "slices/slices.json"):
        src, dst = source / name, run / name
        if not src.exists():
            raise SystemExit(f"--share-from: missing {src}")
        if dst.exists():
            if dst.read_bytes() != src.read_bytes():
                raise SystemExit(f"{dst} exists and differs from {src}; refusing to overwrite")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--share-from", type=Path, help="run directory whose sentences and slice table to reuse")
    parser.add_argument("--over-budget-margin", type=float, default=1.0,
                        help="flag a sentence when estimatedSeconds > budgetSeconds + this")
    args = parser.parse_args()

    review = json.loads(args.review.read_text(encoding="utf-8"))
    locale = review["locale"]
    if locale not in DEFAULTS and not ("language" in review and "charsPerSecond" in review and "countPattern" in review):
        raise SystemExit(f"locale {locale!r}: give language, countPattern and charsPerSecond in the review file")
    language, pattern, per_second = DEFAULTS.get(locale, (None, None, None))
    language = review.get("language", language)
    pattern = review.get("countPattern", pattern)
    per_second = review.get("charsPerSecond", per_second)
    speaker_map = review.get("speakers")
    default_speaker = review.get("speaker")
    if not speaker_map and not default_speaker:
        raise SystemExit("review needs 'speaker' (one voice) or 'speakers' (speakerId -> speaker key)")
    revisions, notes, spoken_forms = review.get("revisions", {}), review.get("notes", {}), review.get("spokenForms", {})

    run = args.run
    if args.share_from:
        share(args.share_from, run)
    sentences = rows(run / "sentences.jsonl")
    translations = rows(run / "translations.jsonl")
    if [t["id"] for t in translations] != [s["id"] for s in sentences]:
        raise SystemExit("translations.jsonl ids must match sentences.jsonl ids, in order")
    unknown = (set(revisions) | set(notes)) - {t["id"] for t in translations}
    if unknown:
        raise SystemExit(f"review names unknown sentence ids: {sorted(unknown)}")
    for t in translations:
        if t.get("locale") != locale:
            raise SystemExit(f"{t['id']}: locale {t.get('locale')!r} differs from review locale {locale!r}")
        if t["id"] in revisions:
            t["target"], t["reviewNote"] = revisions[t["id"]]["target"], revisions[t["id"]]["note"]
        elif t["id"] in notes:
            t["reviewNote"] = "pass; " + notes[t["id"]]
        elif not t.get("reviewNote"):
            t["reviewNote"] = "pass"
    with (run / "translations.jsonl").open("w", encoding="utf-8") as out:
        for t in translations:
            out.write(json.dumps(t, ensure_ascii=False) + "\n")

    slices = {s["id"]: s for s in json.loads((run / "slices/slices.json").read_text(encoding="utf-8"))}
    by_id = {s["id"]: s for s in sentences}
    unused, flagged, digits = set(spoken_forms), [], []
    with (run / "speech.jsonl").open("w", encoding="utf-8") as out:
        for t in translations:
            speaker_id = by_id[t["id"]].get("speakerId")
            if speaker_map:
                if speaker_id not in speaker_map:
                    raise SystemExit(f"{t['id']}: speakerId {speaker_id!r} is not in review 'speakers'")
                speaker = speaker_map[speaker_id]
            else:
                speaker = default_speaker
            spoken = t["target"]
            for k, v in spoken_forms.items():
                if k in spoken:
                    spoken = spoken.replace(k, v)
                    unused.discard(k)
            budget = slices[t["id"]]["budgetSeconds"]
            est = round(len(re.findall(pattern, spoken.lower())) / per_second, 2)
            if est > budget + args.over_budget_margin:
                flagged.append(t["id"])
            if re.search(r"\d", spoken):
                digits.append(t["id"])
            row = {"id": t["id"], "spokenText": spoken, "language": language, "speaker": speaker,
                   "hint": "", "budgetSeconds": budget, "estimatedSeconds": est}
            if speaker_map:
                row["speakerId"] = speaker_id
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    if unused:
        raise SystemExit(f"spokenForms keys not found in any sentence: {sorted(unused)}")
    print(json.dumps({"locale": locale, "sentences": len(translations), "revised": sorted(revisions),
                      "noted": sorted(notes), "spokenFormsApplied": sorted(spoken_forms),
                      "flaggedOverBudget": flagged, "spokenTextWithDigits": digits}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
