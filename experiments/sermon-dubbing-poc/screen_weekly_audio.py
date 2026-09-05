#!/usr/bin/env python3
"""Screen every rendered unit, avoiding long-audio transcription truncation."""
import argparse
import difflib
from pathlib import Path
import subprocess
import json

from poc import sha256, write_json
from prepare_voice_candidates import ASR
from screen_audio import normalize
from weekly_dubbing import read, validate_frozen


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--work", type=Path, required=True)
    args = p.parse_args()
    work = args.work.resolve()
    job, render = read(work / "job.json"), read(work / "render/report.json")
    validate_frozen(job)
    if render["jobSha256"] != sha256(work / "job.json"):
        raise ValueError("Audio belongs to another weekly job")
    mp3 = work / "audio/zh-natural.mp3"
    track = read(work / "audio/library.json")["tracks"][0]
    if sha256(mp3) != track["sha256"]:
        raise ValueError("MP3 changed")
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-f", "null", "-"], check=True)
    from huggingface_hub import snapshot_download
    from mlx_audio.stt.utils import load_model
    import mlx.core as mx
    model = load_model(snapshot_download(repo_id=ASR[0], revision=ASR[1], local_files_only=True))
    checks, issues = [], []
    out = work / "audio/unit-screening"
    out.mkdir(exist_ok=True)
    for i, unit in enumerate(job["units"]):
        raw = work / f"render/unit-{i:04d}.wav"
        saved = read(raw.with_suffix(".json"))
        if saved["unit"] != unit or saved["sha256"] != sha256(raw) or saved["identity"]["jobSha256"] != sha256(work / "job.json"):
            raise ValueError("Changed or unbound audio unit")
        receipt = out / f"unit-{i:04d}.json"
        expected_text = unit.get("spokenText", unit["text"])
        identity = {"audioSha256": sha256(raw), "expected": expected_text, "model": ASR[0], "revision": ASR[1]}
        if receipt.exists():
            check = read(receipt)
            if check["identity"] != identity:
                raise ValueError("Stale ASR screening")
        else:
            text = model.generate(str(raw), language="Chinese", max_tokens=1024).text
            expected, actual = normalize(expected_text), normalize(text)
            matcher = difflib.SequenceMatcher(None, expected, actual, autojunk=False)
            differences = [{"kind": op, "expected": expected[a:b], "recognized": actual[c:d]} for op, a, b, c, d in matcher.get_opcodes() if op != "equal"]
            check = {"unitId": i, "blockId": unit["blockId"], "identity": identity, "recognized": text, "similarity": matcher.ratio(), "differences": differences}
            write_json(receipt, check)
        checks.append(check)
        issues.extend({"unitId": i, "blockId": unit["blockId"], "audioStart": render["cues"][i]["start"], **d} for d in check["differences"])
        mx.clear_cache()
        print(f"Screened {i + 1}/{len(job['units'])}; differences {len(check['differences'])}", flush=True)
    measure = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(mp3), "-af", "loudnorm=I=-18:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True, check=True)
    loud, _ = json.JSONDecoder().raw_decode(measure.stderr[measure.stderr.rfind("{"):])
    write_json(work / "audio/asr-screening.json", {"status": "machine_screening_only", "model": ASR[0], "revision": ASR[1], "jobSha256": sha256(work / "job.json"), "humanListeningStatus": "pending",
        "warning": "ASR differences can be homophones or recognition errors; matching text is not listening acceptance.",
        "results": [{"id": track["id"], "sha256": sha256(mp3), "fullDecode": "pass", "durationSeconds": render["durationSeconds"], "screenedUnits": len(checks), "expectedUnits": len(job["units"]),
            "reviewCandidates": issues, "integratedLufs": float(loud["input_i"]), "truePeakDbtp": float(loud["input_tp"])}]})
    print(json.dumps({"screenedUnits": len(checks), "differences": len(issues)}), flush=True)


if __name__ == "__main__":
    main()
