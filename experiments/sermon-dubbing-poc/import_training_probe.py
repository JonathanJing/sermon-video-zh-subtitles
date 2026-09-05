#!/usr/bin/env python3
"""Normalize the expanded-training WAV into a hash-bound Chinese MP3 pack."""
import argparse
import json
from pathlib import Path
import subprocess

from poc import ROOT, probe, sha256, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    work = args.work.resolve()
    report = json.loads((work / "chinese-probe-v2/report.json").read_text())
    training = json.loads((work / "training-report.json").read_text())
    if report["checkpointSha256"] != training["checkpointSha256"]:
        raise ValueError("Wrong training checkpoint")
    prompt = work / "chinese-probe-input.json"
    if sha256(prompt) != report["inputSha256"]:
        raise ValueError("Chinese input changed")
    track = report["tracks"][0]
    raw = work / "chinese-probe-v2" / track["file"]
    if sha256(raw) != track["sha256"]:
        raise ValueError("Raw audio changed")
    out = work / "chinese-audio"
    out.mkdir(exist_ok=True)
    if (out / "library.json").exists():
        raise ValueError("Preserve the completed import")
    analysis = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(raw), "-af", "loudnorm=I=-18:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True, check=True)
    loudness, _ = json.JSONDecoder().raw_decode(analysis.stderr[analysis.stderr.rfind("{"):])
    filt = "loudnorm=I=-18:TP=-1.5:LRA=11:linear=true:" + ":".join(f"{a}={loudness[b]}" for a, b in [("measured_I", "input_i"), ("measured_TP", "input_tp"), ("measured_LRA", "input_lra"), ("measured_thresh", "input_thresh"), ("offset", "target_offset")])
    mp3 = out / "sft_expanded.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-n", "-i", str(raw), "-af", filt, "-ar", "48000", "-c:a", "libmp3lame", "-b:a", "192k", str(mp3)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-f", "null", "-"], check=True)
    original = ROOT / "artifacts/sermon-dubbing/2026-09-05-authorized-voice-poc/experiment.json"
    plan = json.loads(original.read_text())
    units = json.loads(prompt.read_text())["units"]
    if "".join(plan["paragraphs"]) != "".join(units) or "".join(c["text"] for c in track["cues"]) != "".join(units):
        raise ValueError("Expansion text must match the first voice pilot")
    write_json(out / "experiment.json", {k: plan[k] for k in ["sourceId", "sourceAudioSha256", "readingSha256", "paragraphs"]} | {"checkpointSha256": training["checkpointSha256"]})
    exported = {**track, "id": "sft_expanded", "file": mp3.name, "audioUrl": f"/media/{mp3.name}", "sha256": sha256(mp3),
        "label": "扩充训练", "voiceLabel": "Eric · 三篇证道训练音色（待试听）", "trainedCheckpointSha256": training["checkpointSha256"], "probe": probe(mp3)}
    write_json(out / "library.json", {"schemaVersion": "sermon-audio-library-v1", "date": "2026-08-23", "tracks": [exported]})
    write_json(out / "import-report.json", {"rawSha256": sha256(raw), "mp3Sha256": sha256(mp3), "fullDecode": "pass", "checkpointSha256": training["checkpointSha256"],
        "durationSeconds": track["durationSeconds"], "comparisonScope": "New trained checkpoint only; original trained Chinese probe is the retained listening control", "humanListeningStatus": "pending"})
    print(json.dumps({"file": str(mp3), "seconds": track["durationSeconds"], "sha256": sha256(mp3)}), flush=True)


if __name__ == "__main__":
    main()
