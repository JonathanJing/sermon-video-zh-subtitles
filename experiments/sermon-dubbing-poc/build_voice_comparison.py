#!/usr/bin/env python3
"""Assemble an explicit cloned/preset listening library without exposing references."""
import argparse
import copy
import json
from pathlib import Path
import shutil

from poc import ROOT, sha256, write_json
from voice_source import verify_reference


def build(clone_pack: Path, preset_pack: Path, out: Path, training_pack: Path | None = None):
    clone_plan = json.loads((clone_pack / "experiment.json").read_text())
    preset_plan = json.loads((preset_pack / "experiment.json").read_text())
    verify_reference(clone_plan)
    for field in ["sourceId", "sourceAudioSha256", "readingSha256", "paragraphs"]:
        if clone_plan[field] != preset_plan[field]:
            raise ValueError("Comparison requires identical source and Chinese text")
    clone_library = json.loads((clone_pack / "library.json").read_text())
    preset_library = json.loads((preset_pack / "library.json").read_text())
    out.mkdir(parents=True, exist_ok=True)
    selected = [(clone_pack, clone_library["tracks"][0], "原声参考", "Eric 原声参考 · AI 中文音色克隆"),
                (preset_pack, next(t for t in preset_library["tracks"] if t["id"] == "flow"), "预设音色", "Uncle_Fu 中文预设音色 · 非讲员克隆")]
    source_packs = [clone_pack, preset_pack]
    if training_pack:
        training_plan = json.loads((training_pack / "experiment.json").read_text())
        for field in ["sourceId", "sourceAudioSha256", "readingSha256", "paragraphs"]:
            if clone_plan[field] != training_plan[field]:
                raise ValueError("Training probe must use the same source and Chinese")
        training_library = json.loads((training_pack / "library.json").read_text())
        trained = next(t for t in training_library["tracks"] if t["id"] == "sft_pilot")
        if trained["trainedCheckpointSha256"] != training_plan["checkpointSha256"]:
            raise ValueError("Training checkpoint identity differs")
        selected.insert(0, (training_pack, trained, "训练试跑", "Eric · 小样本训练中文配音"))
        source_packs.append(training_pack)
    tracks = []
    for pack, source_track, label, voice_label in selected:
        track = copy.deepcopy(source_track)
        path = pack / track["file"]
        if sha256(path) != track["sha256"]:
            raise ValueError("Compared audio changed")
        destination = out / track["file"]
        if destination.exists() and sha256(destination) != track["sha256"]:
            raise ValueError("Use a new comparison directory for changed media")
        shutil.copyfile(path, destination)
        track.update({"label": label, "voiceLabel": voice_label})
        tracks.append(track)
    library = {**clone_library, "voiceLabel": "中文音色对照", "tracks": tracks}
    write_json(out / "library.json", library)
    write_json(out / "comparison-receipt.json", {"sourceId": clone_plan["sourceId"], "identicalChinese": True, "sourcePlans": {str(pack / "experiment.json"): sha256(pack / "experiment.json") for pack in source_packs}, "trainingComparison": False, "includesTrainingProbe": bool(training_pack), "note": "The listening library mixes runtimes; use the separate matched-Torch experiment for training diagnostics.", "humanListeningStatus": "pending", "tracks": [{"id": t["id"], "sha256": t["sha256"]} for t in tracks]})
    return library


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--clone-pack", type=Path, default=ROOT / "artifacts/sermon-dubbing/2026-09-05-authorized-voice-poc")
    parser.add_argument("--preset-pack", type=Path, default=ROOT / "artifacts/sermon-dubbing/2026-09-05-fluency-poc-v2")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/sermon-dubbing/2026-09-05-authorized-voice-poc/listening-comparison")
    parser.add_argument("--training-pack", type=Path)
    args = parser.parse_args()
    result = build(args.clone_pack, args.preset_pack, args.out, args.training_pack)
    print(json.dumps({"tracks": len(result["tracks"]), "out": str(args.out)}))
