#!/usr/bin/env python3
"""Single-speaker Qwen3-TTS SFT for John Thomas from one podcast episode (engineering smoke).

Same recipe as experiments/sermon-dubbing-poc/run_qwen_training_smoke.py (2026-09-05):
official prepare_data.py + Tokenizer-12Hz on CUDA, sft_12hz.py from the original Base,
batch 1 / grad-accum 4 / lr 2e-6 / 1 epoch / bf16 / SDPA / seed 42. Differences: the
upstream files come from the hash-verified vendored copy (no network), the manifest is a
single-episode schema with a time-held-out validation split, and the weight check covers
several attention projections. Run in an isolated container with the 2026-09-05 venv
mounted read-only at /work/venv and its model cache at HF_HOME.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time

UPSTREAM = "022e286b98fbec7e1e916cb940cdf532cd9f488e"
UPSTREAM_HASHES = {
    "sft_12hz.py": "74d4359bff1ac5eddaca99f0cb5a8b76a55ffbd94af0ab50bffd49aee0e5c473",
    "prepare_data.py": "d5ed3611e85aadae0ade2b2ab4fa921bb0fdcd8dad8f62c518b75497fcb02b9c",
    "dataset.py": "fd15ee9e71822d9fc1cdf8eb6d6f042836d186e95de5920087d80828cf98a1cb",
}
BASE = ("Qwen/Qwen3-TTS-12Hz-1.7B-Base", "fd4b254389122332181a7c3db7f27e918eec64e3")
TOKENIZER = ("Qwen/Qwen3-TTS-Tokenizer-12Hz", "7dd38ad4e9bad454aae9cd937d0cd577604fe229")
SPEAKER, SPEAKER_KEY = "John Thomas", "john_thomas"
WEIGHT_KEYS = [f"talker.model.layers.{i}.self_attn.{p}_proj.weight" for i in (0, 13, 27) for p in ("q", "k", "v", "o")]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_inputs(work):
    manifest = json.loads((work / "research-inputs.json").read_text())
    permission = json.loads((work / "authorization.json").read_text())
    if manifest.get("schemaVersion") != "sermon-voice-single-episode-training-v1" or manifest.get("speaker") != SPEAKER or manifest.get("speakerKey") != SPEAKER_KEY:
        raise ValueError("Wrong manifest schema or speaker identity")
    if manifest.get("purpose") != "engineering_training_smoke" or manifest.get("productionTrainingAdmission") is not False:
        raise ValueError("Explicit non-production research purpose required")
    if permission.get("status") != "confirmed_by_user" or "voice_training" not in permission.get("purposes", []) or permission.get("speakerKey") != SPEAKER_KEY:
        raise ValueError("Voice training has not been authorized for this speaker")
    if not any(s.get("audio24kSha256") == manifest["sourceAudioSha256"] for s in permission.get("sources", [])):
        raise ValueError("Authorization is for a different source")
    if sha256(work / "source/audio_24k_mono.wav") != manifest["sourceAudioSha256"]:
        raise ValueError("Source audio changed")
    split = manifest["validationSplitStartSeconds"]
    held = {json.loads(line)["sha256"] for line in (work / "prep/validation.jsonl").read_text().splitlines() if line.strip()}
    if sha256(work / "prep/validation.jsonl") != manifest["validationManifestSha256"]:
        raise ValueError("Validation split changed")
    if not 1 <= len(manifest["samples"]) <= 96:
        raise ValueError("Pilot limit is 96 clips")
    for sample in manifest["samples"]:
        path = (work / sample["file"]).resolve()
        if not path.is_relative_to(work.resolve()) or sha256(path) != sample["sha256"] or sample.get("language") != "English":
            raise ValueError("Invalid candidate audio/language/hash")
        if not sample.get("text", "").strip() or sample.get("split") != "train" or sample.get("speaker") != SPEAKER:
            raise ValueError("Sample does not match the frozen speaker/split/label contract")
        if sample["sourceEndSeconds"] > split or sample["sha256"] in held:
            raise ValueError("Held-out validation audio leaked into training")
        if not 0 < sample["durationSeconds"] <= 16:
            raise ValueError("Invalid clip duration")
    if abs(sum(s["durationSeconds"] for s in manifest["samples"]) - manifest["sampleSeconds"]) > .01 or manifest["sampleSeconds"] > 900:
        raise ValueError("Sample duration totals differ or exceed 15 minutes")
    reference = (work / manifest["reference"]["file"]).resolve()
    if not reference.is_relative_to(work.resolve()) or sha256(reference) != manifest["reference"]["sha256"]:
        raise ValueError("Reference changed")
    if not any(s["sha256"] == manifest["reference"]["sha256"] for s in manifest["samples"]):
        raise ValueError("Reference must come from the training split")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    work = args.work.resolve()
    manifest = validate_inputs(work)
    report_path = work / "training-report.json"
    if report_path.exists() or (work / "checkpoints").exists():
        raise ValueError("Use a new work directory; preserve the previous run")
    vendor = work / "upstream"
    for name, digest in UPSTREAM_HASHES.items():
        if sha256(vendor / name) != digest:
            raise ValueError(f"Vendored upstream {name} differs from commit {UPSTREAM}")
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
    base_path = snapshot_download(repo_id=BASE[0], revision=BASE[1], local_files_only=True)
    tokenizer_path = snapshot_download(repo_id=TOKENIZER[0], revision=TOKENIZER[1], local_files_only=True)
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
    command = [sys.executable, str(modified), "--init_model_path", base_path, "--output_model_path", str(work / "checkpoints"), "--train_jsonl", str(coded),
               "--batch_size", "1", "--lr", "2e-6", "--num_epochs", "1", "--speaker_name", SPEAKER_KEY]
    with (work / "training.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    training_seconds = time.monotonic() - started
    checkpoint = work / "checkpoints/checkpoint-epoch-0"
    config = json.loads((checkpoint / "config.json").read_text())
    if config["tts_model_type"] != "custom_voice" or SPEAKER_KEY not in config["talker_config"]["spk_id"]:
        raise ValueError("Checkpoint missing learned speaker configuration")
    from safetensors import safe_open
    import torch
    checks = []
    with safe_open(str(Path(base_path) / "model.safetensors"), framework="pt", device="cpu") as original, safe_open(str(checkpoint / "model.safetensors"), framework="pt", device="cpu") as trained:
        # Attention projections only; the speaker slot written by the upstream export is excluded.
        for key in WEIGHT_KEYS:
            delta = (trained.get_tensor(key).float() - original.get_tensor(key).float()).abs()
            checks.append({"key": key, "elements": int(delta.numel()), "changedElements": int(torch.count_nonzero(delta)), "maxAbsDelta": float(delta.max()), "meanAbsDelta": float(delta.mean())})
    if not all(c["changedElements"] > 0 for c in checks):
        raise ValueError("An attention projection did not change")
    losses = [float(line.rsplit(":", 1)[1]) for line in (work / "training.log").read_text().splitlines() if line.startswith("Epoch 0 | Step")]
    report = {"status": "training_smoke_completed", "speaker": SPEAKER, "speakerKey": SPEAKER_KEY, "productionReady": False, "humanReviewStatus": "pending",
        "independentValidation": "time_held_out_same_episode_only", "sourceCount": 1, "sourceKind": "single_podcast_episode_two_speakers",
        "inputManifestSha256": sha256(work / "research-inputs.json"), "sampleCount": len(rows), "sampleSeconds": manifest["sampleSeconds"],
        "validationCount": manifest["validationCount"], "validationSeconds": manifest["validationSeconds"], "validationUsedInTraining": False,
        "epochs": 1, "batchSize": 1, "gradientAccumulation": 4, "learningRate": 2e-6, "seed": 42, "dtype": "bf16", "attention": "sdpa",
        "baseModel": BASE[0], "baseRevision": BASE[1], "tokenizer": TOKENIZER[0], "tokenizerRevision": TOKENIZER[1], "initializedFrom": "original_base",
        "upstreamCommit": UPSTREAM, "upstreamHashes": UPSTREAM_HASHES, "modifiedScriptSha256": sha256(modified),
        "changesFromUpstream": ["SDPA attention", "stdout logs instead of unconfigured TensorBoard", "log every batch", "seed 42", "reject nonfinite loss"],
        "preprocessSeconds": preprocess_seconds, "trainingSeconds": training_seconds, "steps": len(losses), "firstLoss": losses[0] if losses else None,
        "lastLoss": losses[-1] if losses else None, "allLossesFinite": bool(losses) and all(l == l and abs(l) != float("inf") for l in losses),
        "checkpoint": str(checkpoint), "checkpointSha256": sha256(checkpoint / "model.safetensors"), "learnedWeightCheck": checks,
        "packages": {name: importlib.metadata.version(name) for name in ["torch", "transformers", "accelerate", "qwen-tts"]}}
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
