#!/usr/bin/env python3
"""Write the machine-checked full-video text content (content v3) for one locale.

Reading cues use source-video time from the frozen anchor (clip-relative); the
bound dub's measured duration is recorded separately for playback. Display
fields come from the metadata proposal the operator approves; the disclosure is
the waiver policy's text for the locale. Nothing here is a review.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts import build_full_video_app_release as release  # noqa: E402
from scripts import machine_quality_release_basis as basis  # noqa: E402
from scripts.delivery_contract import sha  # noqa: E402

WL = ROOT / "artifacts/weekend-live"
PAGE_ID = "resi-20261011-54475d42"
SOURCE = WL / "layer1-54475d42/formal/english-source-package.json"
ANCHOR = WL / "layer1-54475d42/output4-rebuild4/anchor-manifest.json"
CANDIDATES = {"zh-Hans": WL / "layer2-54475d42/text-r12/zh-Hans/candidate.json",
              "ko": WL / "layer2-54475d42/recovered/ko/candidate.json",
              "es": WL / "layer2-54475d42/recovered/es/candidate.json"}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--locale", required=True, choices=list(CANDIDATES))
    ap.add_argument("--audio-package", required=True, type=Path)
    ap.add_argument("--metadata-proposal", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    source = json.loads(SOURCE.read_text())
    anchor = json.loads(ANCHOR.read_text())
    candidate = json.loads(CANDIDATES[args.locale].read_text())
    package = json.loads(args.audio_package.read_text())
    display = json.loads(args.metadata_proposal.read_text())["locales"][args.locale]
    assert package["targetLanguageCandidateJsonSha256"] == sha(candidate) and package["englishSourcePackageJsonSha256"] == sha(source)
    units = {u["sourceUnitId"]: u for u in anchor["sourceUnits"]}
    window = source["source"]["approvedWindow"]
    duration = window["endSeconds"] - window["startSeconds"]
    cues = []
    for group in candidate["groups"]:
        spans = [units[i] for i in group["sourceUnitIds"]]
        cues.append({"textGroupId": group["translationGroupId"], "sourceUnitIds": group["sourceUnitIds"],
                     "start": round(min(float(s["start"]) for s in spans), 3), "end": round(max(float(s["end"]) for s in spans), 3),
                     "text": group["targetText"]})
    track = Path(package["track"]["path"])
    content = dict(display, schemaVersion="sermon-full-video-text-content-v3", pageId=PAGE_ID, targetLocale=args.locale,
                   sourceLocale="en", status="machine_checked", englishSourcePackageJsonSha256=sha(source),
                   targetLanguageCandidateJsonSha256=sha(candidate), sourceMediaSha256=source["source"]["media"]["sha256"],
                   durationSeconds=duration, audioDurationSeconds=release.stage.decode_audio(track, args.locale + " measured audio clock"),
                   reviewMode="formal", cues=cues, disclosure=basis.disclosure(args.locale),
                   sourceWindow={"schemaVersion": "sermon-original-recording-window-v1", "mediaSha256": source["source"]["media"]["sha256"],
                                 "startSeconds": window["startSeconds"], "endSeconds": window["endSeconds"]})
    release.validate(content, "sermon-full-video-text-content-v3.schema.json")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(content, ensure_ascii=False, indent=1))
    print(json.dumps({"out": str(args.out), "cues": len(cues), "durationSeconds": duration,
                      "audioDurationSeconds": content["audioDurationSeconds"], "contentSha256": sha(content)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
