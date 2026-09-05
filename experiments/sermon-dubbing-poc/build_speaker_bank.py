#!/usr/bin/env python3
"""Import five trained voice auditions with short, authorized source references."""
import argparse
from pathlib import Path

from poc import sha256, write_json
from prepare_voice_bank import SPEAKERS, PROBE
from run_qwen_training_smoke import validate_inputs
from weekly_dubbing import read, normalize_mp3


def validate_speaker_identity(manifest, training, key, name):
    if any(record.get("speaker") != name or record.get("speakerKey") != key for record in [manifest, training]):
        raise ValueError("Voice-bank directory and training speaker identity differ")
    if training.get("status") != "training_smoke_completed":
        raise ValueError("Voice-bank training is incomplete")


def build(root):
    speakers = []
    for key, name in SPEAKERS.items():
        work = root / key
        manifest = validate_inputs(work)
        training = read(work / "training-report.json")
        validate_speaker_identity(manifest, training, key, name)
        report = read(work / "chinese-probe-v2/report.json")
        prompt = read(work / "chinese-probe-input.json")
        if training["inputManifestSha256"] != sha256(work / "research-inputs.json") or report["checkpointSha256"] != training["checkpointSha256"] or report["inputSha256"] != sha256(work / "chinese-probe-input.json") or prompt["units"] != PROBE:
            raise ValueError("Speaker training or probe provenance changed")
        out = work / "audition"
        out.mkdir(exist_ok=True)
        track = report["tracks"][0]
        raw = work / "chinese-probe-v2" / track["file"]
        if sha256(raw) != track["sha256"]:
            raise ValueError("Speaker audio changed")
        mp3 = out / f"{key}-zh.mp3"
        info = normalize_mp3(raw, mp3)
        chinese = {**track, "id": key + "_zh", "file": mp3.name, "audioUrl": "/media/" + mp3.name, "sha256": info["sha256"], "label": "中文训练音色", "voiceLabel": name, "scope": "voice_audition"}
        reference = manifest["reference"]
        original = work / reference["file"]
        refmp3 = out / f"{key}-reference.mp3"
        refinfo = normalize_mp3(original, refmp3)
        sample = next(s for s in manifest["samples"] if s["sha256"] == reference["sha256"])
        ref = {"id": key + "_reference", "file": refmp3.name, "audioUrl": "/media/" + refmp3.name, "sha256": refinfo["sha256"], "label": "英文原声对照", "voiceLabel": name,
            "durationSeconds": sample["durationSeconds"], "scope": "authorized_source_reference", "cues": [{"start": 0, "end": sample["durationSeconds"], "text": reference["text"]}]}
        write_json(out / "library.json", {"schemaVersion": "sermon-audio-library-v1", "date": "2026-09-05", "tracks": [chinese]})
        write_json(out / "experiment.json", {"paragraphs": PROBE, "speaker": name, "scope": "neutral_voice_audition_not_sermon_translation"})
        write_json(out / "reference.json", ref)
        speakers.append({"id": key, "name": name, "sourceCount": training["sourceCount"], "clipCount": training["sampleCount"], "trainingSeconds": training["sampleSeconds"],
            "checkpointSha256": training["checkpointSha256"], "humanListeningStatus": "pending", "referenceSourceUrl": f'https://www.youtube.com/watch?v={sample["sourceId"]}&t={int(sample["sourceStartSeconds"])}',
            "referenceSourceSha256": sample["sourceSha256"], "pack": str(out), "reference": ref, "chinese": chinese})
    write_json(root / "speaker-bank.json", {"schemaVersion": "sermon-speaker-auditions-v1", "probeText": PROBE, "speakers": speakers,
        "notice": "以下中文为统一的音色试听文稿，并非讲员原话或某周证道译文。原声对照来自已授权证道片段。"})
    print(f"Imported {len(speakers)} distinct trained speaker auditions")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    build(p.parse_args().root.resolve())
