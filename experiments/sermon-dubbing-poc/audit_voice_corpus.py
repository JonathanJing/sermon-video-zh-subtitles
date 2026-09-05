#!/usr/bin/env python3
"""Read the existing translation corpus; export a separate voice-candidate index."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from poc import ROOT, sha256, write_json


def audit(corpus: Path, out: Path):
    split_path = corpus / "data/reports/sermon-parallel-corpus-splits-v1/split-manifest.json"
    audio_path = corpus / "data/reports/mariners-sermon-training-audio-v1/manifest.jsonl"
    final_path = corpus / "data/benchmarks/milmmt-sermon-v4/corpus-split.json"
    split = json.loads(split_path.read_text())["assignments"]
    assignments = {s["videoId"]: s for s in split}
    final = json.loads(final_path.read_text())["sermons"]
    protected = {s["videoId"] for s in split if s["split"] != "train"}
    protected.update(s["videoId"] for s in final if s["split"] == "untouched_final_v4")
    protected_dates = {s["uploadDate"] for s in split if s["videoId"] in protected}
    records = []
    for line in audio_path.read_text().splitlines():
        item = json.loads(line)
        sid = item["videoId"]
        assignment = assignments[sid]
        audio = corpus / item["outputPath"]
        reasons = []
        if sid in protected or assignment["uploadDate"] in protected_dates:
            reasons.append("reserved_sermon_or_same_date")
        if item["split"] != "train" or assignment["split"] != "train":
            reasons.append("not_training_split")
        exists = audio.is_file()
        matches = exists and sha256(audio) == item["outputSha256"]
        if not matches:
            reasons.append("missing_or_changed_audio")
        english = next((p for p in [
            corpus / f"data/derived/sermon-caption-source-reconciled-v1/{sid}/segments.en.jsonl",
            corpus / f"data/derived/sermon-caption-source-v1/{sid}/segments.en.jsonl",
        ] if p.is_file() and p.stat().st_size), None)
        if english is None:
            reasons.append("missing_english")
        records.append({"sourceId": sid, "speaker": assignment["speaker"], "speakerEvidence": assignment["speakerProvenance"],
            "date": assignment["uploadDate"], "title": assignment["title"], "split": assignment["split"],
            "audio": str(audio), "sha256": item["outputSha256"], "audioHashVerified": matches,
            "durationSeconds": item["output"]["durationSeconds"], "english": str(english) if english else None,
            "englishSha256": sha256(english) if english else None,
            "eligibleForVoicePreparation": not reasons, "exclusions": reasons,
            "speakerTurnsVerified": False, "voiceTrainingAdmission": "pending_audio_text_and_speaker_review",
            "legacyTranslationEligibility": item.get("trainingEligibility")})
    eligible = [r for r in records if r["eligibleForVoicePreparation"]]
    report = {"schemaVersion": "sermon-voice-corpus-audit-v1", "corpusRoot": str(corpus),
        "sourceManifestHashes": {str(p.relative_to(corpus)): sha256(p) for p in [split_path, audio_path, final_path]},
        "frozenSplitCounts": dict(Counter(s["split"] for s in split)), "audioRecordCount": len(records),
        "verifiedAudioCount": sum(r["audioHashVerified"] for r in records),
        "preparationCandidateCount": len(eligible), "preparationCandidateHours": round(sum(r["durationSeconds"] for r in eligible) / 3600, 3),
        "candidateCountsBySpeaker": dict(Counter(r["speaker"] for r in eligible)),
        "protectedIds": sorted(protected), "protectedDates": sorted(protected_dates),
        "trainingAdmittedCount": 0, "sourceRecordsModified": False,
        "authorization": "User confirmed voice training and dubbing in this conversation; legacy translation rights fields are retained, not rewritten.",
        "records": records}
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "audit.json", report)
    eric = sorted((r for r in eligible if r["speaker"] == "Eric Geiger"), key=lambda r: r["date"], reverse=True)
    # The Aug 23 archive is already used in the first pilot; do not count its VOD as another sermon.
    selected = [r for r in eric if r["date"] != "20260823"][:3]
    write_json(out / "expansion-plan.json", {"schemaVersion": "sermon-voice-expansion-plan-v1", "auditSha256": sha256(out / "audit.json"),
        "speaker": "Eric Geiger", "sources": selected, "windowOffsetsSeconds": [300, 360, 420, 480, 540],
        "sourceMinutes": len(selected) * 5, "purpose": "engineering_multisermon_training", "productionTrainingAdmission": False})
    print(json.dumps({k: report[k] for k in ["audioRecordCount", "verifiedAudioCount", "preparationCandidateCount", "preparationCandidateHours", "candidateCountsBySpeaker"]}, ensure_ascii=False), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/sermon-dubbing/2026-09-05-corpus-expansion")
    args = parser.parse_args()
    audit(args.corpus.resolve(), args.out.resolve())
