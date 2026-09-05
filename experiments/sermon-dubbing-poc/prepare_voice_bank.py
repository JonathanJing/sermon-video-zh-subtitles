#!/usr/bin/env python3
"""Prepare isolated speaker pilots from a frozen, train-only corpus audit.

Plan -> prepare_corpus_voice_candidates.py -> pack. No shared corpus is changed.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from poc import sha256, write_json
from run_qwen_training_smoke import validate_inputs

SPEAKERS = {"jared_kirkwood": "Jared Kirkwood", "christine_caine": "Christine Caine",
            "doug_fields": "Doug Fields", "kenton_beshore": "Kenton Beshore", "steve_bang_lee": "Steve Bang Lee"}
PROBE = [
    "每个人都会遇到难以理解的时刻。有些问题，我们暂时找不到答案，但我们仍然可以带着真实的感受来到神面前。",
    "祷告不需要华丽的语言。我们可以安静地停下来，把心里的忧虑告诉神，也学习认真倾听身边的人。",
    "今天，让我们迈出一个小小的步子：给需要帮助的人一些关怀，在平凡的生活中活出爱与盼望。",
]


def plan(audit_path, authorization_path, out):
    audit = json.loads(audit_path.read_text())
    authorization = json.loads(authorization_path.read_text())
    if authorization.get("status") != "confirmed_by_user" or not {"voice_training", "chinese_dubbing"} <= set(authorization.get("purposes", [])):
        raise ValueError("Existing authorization for training and dubbing is required")
    if out.exists():
        raise ValueError("Preserve previous voice-bank runs")
    for key, speaker in SPEAKERS.items():
        sources = sorted((s for s in audit["records"] if s["speaker"] == speaker and s["eligibleForVoicePreparation"]), key=lambda s: s["date"], reverse=True)[:3]
        if len(sources) != 3:
            raise ValueError(f"Three eligible sermons unavailable for {speaker}")
        work = out / key
        work.mkdir(parents=True)
        shutil.copyfile(audit_path, work / "audit.json")
        write_json(work / "expansion-plan.json", {"schemaVersion": "sermon-voice-expansion-plan-v1", "auditSha256": sha256(audit_path),
            "speaker": speaker, "speakerKey": key, "sources": sources, "windowOffsetsSeconds": [300, 360, 420, 480, 540],
            "purpose": "engineering_multisermon_training", "productionTrainingAdmission": False})
        write_json(work / "authorization.json", {**authorization, "authorizationId": f"user-confirmation-20260905-{key}",
            "recordedAt": datetime.now(timezone.utc).isoformat(), "scopeEvidence": "已获得授权，声音可以用于训练和配音。制作其他讲员的语音。",
            "sources": [{"sourceId": s["sourceId"], "sha256": s["sha256"]} for s in sources]})
        write_json(work / "protection.json", {"protectedIds": audit["protectedIds"], "protectedDates": audit["protectedDates"], "auditSha256": sha256(audit_path)})
    write_json(out / "plan.json", {"speakers": SPEAKERS, "sourceCount": 15, "probeText": PROBE,
        "probeAttribution": "New neutral listening text written for voice comparison; not a quote or translation of any speaker's sermon",
        "sourceAudioPublished": False, "humanSpeakerAndClipReview": "pending"})


def pack(work):
    plan = json.loads((work / "expansion-plan.json").read_text())
    all_samples = [json.loads(line) for line in (work / "candidates.jsonl").read_text().splitlines()]
    # Balance sermons; keep the same 15-minute / 96-clip bound as the Eric experiment.
    samples = []
    for source in plan["sources"]:
        candidates = [s for s in all_samples if s["sourceId"] == source["sourceId"]]
        if len(candidates) < 3:
            raise ValueError("Insufficient clean candidate sentences in a source")
        samples.extend(candidates[:30])
    if sum(s["durationSeconds"] for s in samples) > 900:
        raise ValueError("Pilot exceeds the 15-minute cap")
    reference = min((s for s in samples if 8 <= s["durationSeconds"] <= 15), key=lambda s: abs(s["durationSeconds"] - 12))
    manifest = {"schemaVersion": "sermon-voice-multisource-training-v2", "purpose": "engineering_multisermon_training",
        "speaker": plan["speaker"], "speakerKey": plan["speakerKey"], "sourceId": reference["sourceId"], "sourceSha256": reference["sourceSha256"],
        "sources": plan["sources"], "samples": samples, "sampleSeconds": sum(s["durationSeconds"] for s in samples),
        "reference": {"file": reference["file"], "sha256": reference["sha256"], "text": reference["text"]},
        "protectedEvaluationOverlap": False, "protectionSha256": sha256(work / "protection.json"), "productionTrainingAdmission": False}
    write_json(work / "research-inputs.json", manifest)
    validate_inputs(work)
    write_json(work / "chinese-probe-input.json", {"sourceId": reference["sourceId"], "sourceSha256": reference["sourceSha256"],
        "units": PROBE, "referenceText": reference["text"], "scope": "neutral_voice_audition_not_sermon_translation"})
    print(json.dumps({"speaker": plan["speaker"], "clips": len(samples), "seconds": manifest["sampleSeconds"], "bySource": Counter(s["sourceId"] for s in samples)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--audit", type=Path, required=True)
    p.add_argument("--authorization", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("pack")
    p.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        plan(args.audit.resolve(), args.authorization.resolve(), args.out.resolve())
    else:
        pack(args.work.resolve())
