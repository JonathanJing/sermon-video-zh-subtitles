#!/usr/bin/env python3
"""Build a blinded GPT-6 judge packet from a frozen Gemini sidecar."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from schema import sha256


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sidecar = json.loads(args.sidecar.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    silences = sidecar["evidence"]["acoustics"]["silenceIntervals"]
    windows: list[dict] = []
    for window in manifest["windows"]:
        start = float(window["relativeStartSeconds"])
        end = float(window["relativeEndSeconds"])
        proposals = []
        for sentence in sidecar["sentences"]:
            midpoint = (float(sentence["startSeconds"]) + float(sentence["endSeconds"])) / 2
            if sentence.get("geminiWindowId") != window["windowId"]:
                continue
            overlap_silences = [item["silenceId"] for item in silences
                                if item["endSeconds"] > sentence["startSeconds"]
                                and item["startSeconds"] < sentence["endSeconds"]]
            proposals.append({
                "sentenceId": sentence["sentenceId"], "blockId": sentence["blockId"],
                "text": sentence["text"], "startSeconds": sentence["startSeconds"],
                "endSeconds": sentence["endSeconds"], "firstWordId": sentence["firstWordId"],
                "lastWordId": sentence["lastWordId"], "wordTimingStatus": sentence["timingStatus"],
                "proposedType": sentence.get("geminiType"),
                "proposedScriptureRef": sentence.get("geminiScriptureRef"),
                "proposedOnScreenText": sentence.get("geminiOnScreenText"),
                "acousticSilenceIds": overlap_silences,
            })
        windows.append({
            "windowId": window["windowId"], "startSeconds": start, "endSeconds": end,
            "transcriptKind": "reading_candidate_mapped_to_candidate_word_timing",
            "contactSheet": {
                "evidenceId": f'{window["windowId"]}-contact-sheet',
                "path": str((args.manifest.resolve().parent / window["paths"]["contactSheet"]).resolve()),
                "sha256": window["hashes"]["contactSheet"], "imageAttached": True,
            },
            "sentenceProposals": proposals,
        })
    packet = {
        "schemaVersion": "sermon-sidecar-judge-input-v1",
        "reviewState": "frozen_blinded_machine_evidence",
        "source": sidecar["source"],
        "candidate": {"path": str(args.sidecar.resolve()), "sha256": sha256(args.sidecar),
                      "modelIdentityWithheld": True, "confidenceWithheld": True,
                      "candidateNotesWithheld": True},
        "wordTiming": sidecar["evidence"]["wordTiming"],
        "acoustics": sidecar["evidence"]["acoustics"],
        "windows": windows,
        "judgeRequirements": {
            "reviewState": "machine_judge_candidate", "humanGold": False,
            "releaseEligible": False,
            "verdicts": ["supported", "unsupported", "uncertain"],
            "oneJudgmentPerSentence": True,
            "mustNotClaimDirectAudioInspection": True,
        },
    }
    write_json(args.out, packet)
    print(json.dumps({"out": str(args.out), "windows": len(windows),
                      "sentences": sum(len(item["sentenceProposals"]) for item in windows)}))


if __name__ == "__main__":
    main()
