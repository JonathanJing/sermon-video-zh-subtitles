#!/usr/bin/env python3
"""Machine screening of generated MP3; never grants human listening approval."""
import argparse
import difflib
import json
from pathlib import Path
import re
import subprocess

from poc import DEFAULT_OUT, probe, sha256, write_json


def normalize(text):
    numerals = {"15": "十五", "18": "十八", "30": "三十"}
    text = re.sub(r"\d+", lambda m: numerals.get(m.group(), m.group()), text)
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    from huggingface_hub import snapshot_download
    from mlx_audio.stt.utils import load_model
    import mlx.core as mx

    repo = "mlx-community/Qwen3-ASR-0.6B-8bit"
    revision = "89e96d92ba34aca20b3e29fb10cc284097d1219f"
    model = load_model(snapshot_download(repo_id=repo, revision=revision))
    experiment = json.loads((args.pack / "experiment.json").read_text())
    library = json.loads((args.pack / "library.json").read_text())
    expected = normalize("".join(experiment["paragraphs"]))
    checks = []
    for track in library["tracks"]:
        path = args.pack / track["file"]
        if sha256(path) != track["sha256"]:
            raise ValueError("Audio changed after library generation")
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], check=True)
        text = model.generate(str(path), language="Chinese", max_tokens=4096).text
        (args.pack / f"{track['id']}.asr.txt").write_text(text + "\n")
        actual = normalize(text)
        diff = difflib.SequenceMatcher(None, expected, actual, autojunk=False)
        review = [{"kind": op, "expected": expected[a:b], "recognized": actual[c:d], "context": expected[max(0, a - 8):min(len(expected), b + 8)]} for op, a, b, c, d in diff.get_opcodes() if op != "equal"]
        measure = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "loudnorm=I=-18:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True, check=True)
        loudness, _ = json.JSONDecoder().raw_decode(measure.stderr[measure.stderr.rfind("{"):])
        entry = {"id": track["id"], "sha256": track["sha256"], "fullDecode": "pass", **probe(path), "text": text, "reviewCandidates": review, "integratedLufs": float(loudness["input_i"]), "truePeakDbtp": float(loudness["input_tp"])}
        checks.append(entry)
        print(json.dumps({"id": entry["id"], "reviewCandidates": review, "lufs": entry["integratedLufs"], "truePeak": entry["truePeakDbtp"]}, ensure_ascii=False), flush=True)
        mx.clear_cache()
    write_json(args.pack / "asr-screening.json", {"status": "machine_screening_only", "model": repo, "revision": revision, "humanListeningStatus": "pending", "normalization": "punctuation/whitespace ignored; 15/18/30 expanded to Chinese; names unchanged", "warning": "Differences may be ASR errors, TTS errors, or homophones. Matching ASR text does not prove naturalness.", "results": checks})


if __name__ == "__main__":
    main()
