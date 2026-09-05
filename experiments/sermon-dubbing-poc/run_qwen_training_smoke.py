#!/usr/bin/env python3
"""One bounded, non-production English single-speaker SFT and Chinese probe.

Run in an isolated CUDA environment. Consumes an explicit research input manifest;
does not change candidate admission or human-review records.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import re
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

UPSTREAM = "022e286b98fbec7e1e916cb940cdf532cd9f488e"
BASE = ("Qwen/Qwen3-TTS-12Hz-1.7B-Base", "fd4b254389122332181a7c3db7f27e918eec64e3")
TOKENIZER = ("Qwen/Qwen3-TTS-Tokenizer-12Hz", "7dd38ad4e9bad454aae9cd937d0cd577604fe229")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_isolated_runtime(work):
    if importlib.util.find_spec("torchaudio") is not None:
        return
    distribution = importlib.metadata.distribution("qwen-tts")
    path = Path(distribution.locate_file("qwen_tts/core/tokenizer_25hz/vq/speech_vq.py")).resolve()
    if not path.is_relative_to((work / "venv").resolve()) or distribution.version != "0.1.1":
        raise ValueError("Optional-codec adaptation is limited to qwen-tts 0.1.1 in this run's venv")
    text = path.read_text()
    needle = "\nimport torchaudio.compliance.kaldi as kaldi\n"
    target = "    def extract_code(self, audio):\n"
    deferred = target + "        import torchaudio.compliance.kaldi as kaldi\n"
    if deferred in text and needle not in text:
        return
    if text.count(needle) != 1 or text.count(target) != 1:
        raise ValueError("Unexpected optional-codec source; inspect it")
    modified = text.replace(needle, "\n").replace(target, deferred)
    (work / "speech_vq.original.py").write_text(text)
    import difflib
    (work / "qwen-tts-optional-25hz.patch").write_text("".join(difflib.unified_diff(text.splitlines(keepends=True), modified.splitlines(keepends=True), fromfile="speech_vq.original.py", tofile="speech_vq.py")))
    path.write_text(modified)
    (work / "compatibility-receipt.json").write_text(json.dumps({"change": "defer unused 25Hz torchaudio import until extract_code; 12Hz logic unchanged", "path": str(path), "before": hashlib.sha256(text.encode()).hexdigest(), "after": sha256(path)}, indent=2) + "\n")


def validate_inputs(work):
    manifest = json.loads((work / "research-inputs.json").read_text())
    authorization = json.loads((work / "authorization.json").read_text())
    speaker_bank = manifest.get("schemaVersion") == "sermon-voice-multisource-training-v2"
    expanded = speaker_bank or manifest.get("schemaVersion") == "sermon-voice-multisource-training-v1"
    speaker = manifest.get("speaker") if speaker_bank else "Eric Geiger"
    if speaker_bank and (not speaker or not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", manifest.get("speakerKey", ""))):
        raise ValueError("A named speaker and safe, separate speaker key are required")
    purpose = "engineering_multisermon_training" if expanded else "engineering_training_smoke"
    if manifest.get("purpose") != purpose or manifest.get("productionTrainingAdmission") is not False:
        raise ValueError("Explicit non-production research purpose required")
    if (not speaker_bank and manifest.get("sourceId") != "ZDQwL3K-A44") or manifest.get("protectedEvaluationOverlap") is not False:
        raise ValueError("This pilot accepts only the selected non-benchmark sermon")
    if authorization.get("status") != "confirmed_by_user" or "voice_training" not in authorization.get("purposes", []):
        raise ValueError("Voice training has not been authorized")
    if not any(s.get("sourceId") == manifest["sourceId"] and s.get("sha256") == manifest["sourceSha256"] for s in authorization.get("sources", [])):
        raise ValueError("Authorization is for a different source")
    limit = 96 if expanded else 32
    if not 1 <= len(manifest["samples"]) <= limit:
        raise ValueError(f"Pilot limit is {limit} candidate clips")
    sources = {}
    if expanded:
        protection = work / "protection.json"
        if sha256(protection) != manifest["protectionSha256"]:
            raise ValueError("Frozen corpus protection changed")
        reserved = json.loads(protection.read_text())
        for source in manifest["sources"]:
            sid = source["sourceId"]
            if source["speaker"] != speaker or source["split"] != "train" or sid in reserved["protectedIds"] or source["date"] in reserved["protectedDates"]:
                raise ValueError("Wrong speaker or reserved whole-sermon source")
            if not any(s.get("sourceId") == sid and s.get("sha256") == source["sha256"] for s in authorization["sources"]):
                raise ValueError("Expansion source is not authorized")
            if sid in sources:
                raise ValueError("Duplicate source")
            sources[sid] = source
        if len(sources) != 3 or not 0 < manifest["sampleSeconds"] <= 900:
            raise ValueError("This expansion is limited to three sermons and 15 minutes of clips")
    for sample in manifest["samples"]:
        path = (work / sample["file"]).resolve()
        if not path.is_relative_to(work.resolve()) or sha256(path) != sample["sha256"] or sample.get("language") != "English":
            raise ValueError("Invalid candidate audio/language/hash")
        if not sample.get("text", "").strip():
            raise ValueError("Missing English label")
        if expanded:
            source = sources.get(sample.get("sourceId"))
            if not source or sample.get("sourceSha256") != source["sha256"] or sample.get("split") != "train" or sample.get("speaker") != speaker:
                raise ValueError("Sample does not match the frozen speaker/source/split")
            if not 0 < sample.get("durationSeconds", 0) <= 16:
                raise ValueError("Invalid clip duration")
    if expanded and abs(sum(s["durationSeconds"] for s in manifest["samples"]) - manifest["sampleSeconds"]) > .001:
        raise ValueError("Sample duration totals differ")
    reference = (work / manifest["reference"]["file"]).resolve()
    if not reference.is_relative_to(work.resolve()) or sha256(reference) != manifest["reference"]["sha256"]:
        raise ValueError("Reference changed")
    if speaker_bank:
        source = sources.get(manifest["sourceId"])
        if not source or source["sha256"] != manifest["sourceSha256"] or not any(s["sha256"] == manifest["reference"]["sha256"] and s["sourceId"] == manifest["sourceId"] for s in manifest["samples"]):
            raise ValueError("Reference must come from this speaker's eligible training clips")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    work = args.work.resolve()
    manifest = validate_inputs(work)
    speaker_key = manifest.get("speakerKey", "eric_pilot")
    report_path = work / "training-report.json"
    if report_path.exists() or (work / "checkpoints").exists():
        raise ValueError("Use a new work directory; preserve the previous run")
    prepare_isolated_runtime(work)
    vendor = work / "upstream"
    vendor.mkdir(exist_ok=True)
    originals = {}
    for name in ["sft_12hz.py", "prepare_data.py", "dataset.py"]:
        url = f"https://raw.githubusercontent.com/QwenLM/Qwen3-TTS/{UPSTREAM}/finetuning/{name}"
        with urllib.request.urlopen(url) as response:
            data = response.read()
        (vendor / name).write_bytes(data)
        originals[name] = hashlib.sha256(data).hexdigest()
    # GB10 pilot uses PyTorch SDPA; preserve upstream originals and patch receipts.
    script = (vendor / "sft_12hz.py").read_text()
    changes = [
        ('attn_implementation="flash_attention_2"', 'attn_implementation="sdpa"'),
        ('log_with="tensorboard"', 'log_with=None'),
        ('if step % 10 == 0:', 'if step % 1 == 0:'),
        ('    global target_speaker_embedding\n', '    global target_speaker_embedding\n    torch.manual_seed(42)\n'),
        ('                loss = outputs.loss + 0.3 * sub_talker_loss\n', '                loss = outputs.loss + 0.3 * sub_talker_loss\n                if not torch.isfinite(loss):\n                    raise RuntimeError("Nonfinite training loss")\n'),
    ]
    for old, new in changes:
        if script.count(old) != 1:
            raise ValueError("Upstream training script changed unexpectedly")
        script = script.replace(old, new)
    modified = vendor / "sft_pilot.py"
    modified.write_text(script)
    from huggingface_hub import snapshot_download
    base_path = snapshot_download(repo_id=BASE[0], revision=BASE[1])
    tokenizer_path = snapshot_download(repo_id=TOKENIZER[0], revision=TOKENIZER[1])
    rows = [{"audio": str(work / s["file"]), "text": s["text"], "ref_audio": str(work / manifest["reference"]["file"]), "language": "English"} for s in manifest["samples"]]
    raw = work / "research_train_raw.jsonl"
    raw.write_text("".join(json.dumps(row) + "\n" for row in rows))
    coded = work / "research_train_codes.jsonl"
    started = time.monotonic()
    subprocess.run([sys.executable, str(vendor / "prepare_data.py"), "--device", "cuda:0", "--tokenizer_model_path", tokenizer_path, "--input_jsonl", str(raw), "--output_jsonl", str(coded)], check=True)
    code_rows = [json.loads(line) for line in coded.read_text().splitlines()]
    if len(code_rows) != len(rows) or any(not row.get("audio_codes") for row in code_rows):
        raise ValueError("Incomplete tokenizer output")
    preprocess_seconds = time.monotonic() - started
    started = time.monotonic()
    command = [sys.executable, str(modified), "--init_model_path", base_path, "--output_model_path", str(work / "checkpoints"), "--train_jsonl", str(coded), "--batch_size", "1", "--lr", "2e-6", "--num_epochs", "1", "--speaker_name", speaker_key]
    with (work / "training.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    training_seconds = time.monotonic() - started
    checkpoint = work / "checkpoints/checkpoint-epoch-0"
    config = json.loads((checkpoint / "config.json").read_text())
    if config["tts_model_type"] != "custom_voice" or speaker_key not in config["talker_config"]["spk_id"]:
        raise ValueError("Checkpoint missing learned speaker configuration")
    from safetensors import safe_open
    import torch
    original_weight_file = Path(base_path) / "model.safetensors"
    with safe_open(str(original_weight_file), framework="pt", device="cpu") as original, safe_open(str(checkpoint / "model.safetensors"), framework="pt", device="cpu") as trained:
        # Exclude the speaker slot deliberately written by the upstream export.
        key = "talker.model.layers.0.self_attn.q_proj.weight"
        delta = (trained.get_tensor(key).float() - original.get_tensor(key).float()).abs()
        changed = int(torch.count_nonzero(delta))
        if changed == 0:
            raise ValueError("No learned weight change detected")
        weight_check = {"key": key, "changedElements": changed, "maxAbsDelta": float(delta.max())}
    report = {"status": "training_smoke_completed", "speaker": manifest.get("speaker", "Eric Geiger"), "speakerKey": speaker_key, "productionReady": False, "humanReviewStatus": "pending", "independentValidation": "not_performed" if manifest.get("sources") else "unavailable_single_sermon",
        "sourceCount": len(manifest.get("sources", [])) or 1,
        "inputManifestSha256": sha256(work / "research-inputs.json"), "sampleCount": len(rows), "sampleSeconds": manifest["sampleSeconds"], "epochs": 1, "batchSize": 1, "gradientAccumulation": 4, "learningRate": 2e-6,
        "baseModel": BASE[0], "baseRevision": BASE[1], "tokenizerRevision": TOKENIZER[1], "upstreamCommit": UPSTREAM, "upstreamHashes": originals, "modifiedScriptSha256": sha256(modified),
        "changesFromUpstream": ["SDPA attention", "stdout logs instead of unconfigured TensorBoard", "log every batch", "seed 42", "reject nonfinite loss"], "preprocessSeconds": preprocess_seconds, "trainingSeconds": training_seconds,
        "checkpoint": str(checkpoint), "checkpointSha256": sha256(checkpoint / "model.safetensors"), "learnedWeightCheck": weight_check,
        "packages": {name: importlib.metadata.version(name) for name in ["torch", "transformers", "accelerate", "qwen-tts"]}}
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
