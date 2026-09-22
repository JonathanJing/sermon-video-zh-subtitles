#!/usr/bin/env python3
"""Package generated fragment WAVs as honest Layer 3 POC artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


LOCALES = ("zh-Hans", "ko", "es", "vi")


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def duration(path: Path) -> float:
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], check=True, capture_output=True, text=True)
    return float(json.loads(proc.stdout)["format"]["duration"])


def timestamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer2", type=Path, required=True)
    parser.add_argument("--layer3", type=Path, required=True)
    parser.add_argument("--fragment-id", default="2026-09-20-lion-of-judah")
    parser.add_argument("--speaker-id", default="eric_geiger")
    parser.add_argument("--source-start", type=float, default=1858.4)
    parser.add_argument("--source-end", type=float, default=1899.280001)
    args = parser.parse_args()
    standard = json.loads((args.layer3 / "manifest.json").read_text())
    vietnamese = json.loads((args.layer3 / "vietnamese-manifest.json").read_text())
    tracks = {item["targetLocale"]: item for item in standard["tracks"] + vietnamese["tracks"]}
    if set(tracks) != set(LOCALES):
        raise SystemExit("Layer 3 renderer manifests do not cover the expected locales")

    summary = []
    for locale in LOCALES:
        candidate_path = args.layer2 / locale / "target-language-candidate.json"
        candidate = json.loads(candidate_path.read_text())
        candidate_sha = canonical_sha(candidate)
        group = candidate["groups"][0]
        track = tracks[locale]
        wav = args.layer3 / track["file"]
        if file_sha(wav) != track["audioSha256"] or track.get("fullDecode") != "pass":
            raise SystemExit(f"WAV verification failed for {locale}")
        locale_dir = args.layer3 / locale
        locale_dir.mkdir(exist_ok=False)
        mp3 = locale_dir / "audio.mp3"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-n", "-i", str(wav), "-map", "0:a:0", "-ac", "1", "-ar", "44100", "-b:a", "128k", str(mp3)], check=True)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(mp3), "-map", "0:a:0", "-f", "null", "-"], check=True)
        audio_duration = round(duration(mp3), 6)

        utterances = group["targetUtterances"]
        weights = [max(1, len(text.replace(" ", ""))) for text in utterances]
        total = sum(weights)
        cursor = 0.0
        cues = []
        for index, (coverage, text, weight) in enumerate(zip(group["coverage"], utterances, weights), 1):
            end = audio_duration if index == len(utterances) else round(cursor + audio_duration * weight / total, 3)
            cues.append({"cueId": f"{locale}-{index:02d}", "sourceUnitId": coverage["sourceUnitId"], "startSeconds": round(cursor, 3), "endSeconds": end, "text": text})
            cursor = end
        schedule = {
            "schemaVersion": "sermon-target-language-poc-schedule-v1",
            "targetLocale": locale,
            "timingKind": "estimated_proportional_to_target_text_poc",
            "sourceTimelineStartSeconds": args.source_start,
            "sourceTimelineEndSeconds": args.source_end,
            "trackDurationSeconds": audio_duration,
            "ratePolicy": "natural_no_time_stretch",
            "cues": cues,
        }
        schedule_path = locale_dir / "schedule.json"
        schedule_path.write_text(json.dumps(schedule, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        vtt_path = locale_dir / "captions.vtt"
        lines = ["WEBVTT", "", "NOTE Machine POC; timing is estimated and human review is pending.", ""]
        for cue in cues:
            lines.extend([cue["cueId"], f"{timestamp(cue['startSeconds'])} --> {timestamp(cue['endSeconds'])}", cue["text"], ""])
        vtt_path.write_text("\n".join(lines), encoding="utf-8")
        speech_job = {
            "schemaVersion": "sermon-target-language-poc-speech-job-v1",
            "scope": "voice_demo_only_not_production",
            "targetLocale": locale,
            "targetLanguageCandidateJsonSha256": candidate_sha,
            "translationStatus": candidate["status"],
            "humanTranslationApproval": False,
            "speakerId": args.speaker_id,
            "ratePolicy": "natural_no_time_stretch",
            "textGroupId": group["translationGroupId"],
            "targetTextSha256": hashlib.sha256(group["targetText"].encode()).hexdigest(),
        }
        speech_job_path = locale_dir / "poc-speech-job.json"
        speech_job_path.write_text(json.dumps(speech_job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        checkpoint_sha = track.get("checkpointSha256") or track.get("modelWeightsSha256")
        model = "Qwen/Qwen3-TTS-12Hz-1.7B-Base SFT" if locale != "vi" else track["model"]
        package = {
            "schemaVersion": "sermon-target-language-audio-package-v1",
            "packageId": f"{args.fragment_id}-{locale}-poc-v1",
            "englishSourcePackageJsonSha256": candidate["englishSourcePackageJsonSha256"],
            "targetLanguageCandidateJsonSha256": candidate_sha,
            "targetLanguageSpeechJobJsonSha256": canonical_sha(speech_job),
            "targetLocale": locale,
            "status": "candidate",
            "ratePolicy": "natural_no_time_stretch",
            "voice": {"provider": "Qwen" if locale != "vi" else "Gwen", "model": model, "checkpointSha256": checkpoint_sha, "targetLocaleCapability": "reviewed" if locale == "zh-Hans" else "candidate", "authorizationStatus": "authorized"},
            "units": [{"textGroupId": group["translationGroupId"], "targetTextSha256": hashlib.sha256(group["targetText"].encode()).hexdigest(), "audio": {"path": "audio.mp3", "sha256": file_sha(mp3)}, "durationSeconds": audio_duration}],
            "track": {"path": "audio.mp3", "sha256": file_sha(mp3)},
            "captions": {"path": "captions.vtt", "sha256": file_sha(vtt_path)},
            "schedule": {"path": "schedule.json", "sha256": file_sha(schedule_path), "jsonSha256": canonical_sha(schedule)},
            "machineScreening": {"status": "not_run", "model": None, "coverage": 0},
            "humanReview": {"status": "pending", "humanApproval": False, "reviewedBy": None, "reviewedAt": None, "fullPlayback": "pending"},
            "issues": ["machine_asr_screening_not_run", "human_listening_pending", "estimated_caption_timing_poc"],
            "downstreamInvalidationKey": hashlib.sha256((candidate_sha + file_sha(mp3) + canonical_sha(schedule)).encode()).hexdigest(),
        }
        package_path = locale_dir / "target-language-audio-package.json"
        package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary.append({"targetLocale": locale, "durationSeconds": audio_duration, "audioSha256": file_sha(mp3), "packageJsonSha256": canonical_sha(package), "humanListeningStatus": "pending"})
    receipt = {"schemaVersion": "sermon-multilingual-fragment-layer3-poc-v1", "scope": "layer_3_voice_demo_only_not_production", "status": "encoded_and_fully_decoded", "productionEligible": False, "humanApproval": False, "machineScreening": "not_run", "tracks": summary}
    (args.layer3 / "layer3-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"layer3": str(args.layer3), "tracks": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
