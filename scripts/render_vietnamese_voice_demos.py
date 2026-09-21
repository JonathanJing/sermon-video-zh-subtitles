#!/usr/bin/env python3
"""Render Vietnamese zero-shot clone demos through the registered Gwen adapter."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import time
from typing import Any


REGISTRY_SCHEMA_VERSION = "sermon-speaker-voice-registry-v1"
SCRIPT_SCHEMA_VERSION = "sermon-multilingual-voice-demo-script-v1"
REFERENCES_SCHEMA_VERSION = "sermon-multilingual-voice-demo-references-v1"
ADAPTER = "gwen_tts_zero_shot_reference"


def read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def split_sentences(value: str) -> list[str]:
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", value.strip()) if item.strip()]
    if not sentences:
        raise ValueError("Vietnamese demo text has no complete sentence")
    return sentences


def _index(items: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    values = [item.get(key) for item in items]
    if any(not isinstance(value, str) or not value for value in values) or len(values) != len(set(values)):
        raise ValueError(f"{label} {key} values must be non-empty and unique")
    return dict(zip(values, items))


def prepare_tasks(
    registry: dict[str, Any],
    script: dict[str, Any],
    references: dict[str, Any],
    *,
    selected_speakers: list[str] | None = None,
) -> list[dict[str, Any]]:
    if registry.get("schemaVersion") != REGISTRY_SCHEMA_VERSION:
        raise ValueError("Unsupported Speaker Voice Registry schema")
    if script.get("schemaVersion") != SCRIPT_SCHEMA_VERSION:
        raise ValueError("Unsupported multilingual demo script schema")
    if references.get("schemaVersion") != REFERENCES_SCHEMA_VERSION:
        raise ValueError("Unsupported voice reference schema")
    speakers = _index(registry.get("speakers", []), "speakerId", "Speaker")
    refs = _index(references.get("references", []), "speakerId", "Reference")
    scripts = _index(script.get("locales", []), "targetLocale", "Demo script")
    if "vi" not in scripts or scripts["vi"].get("modelLanguage") != "Vietnamese":
        raise ValueError("Vietnamese demo script is missing or misconfigured")
    speaker_ids = selected_speakers or list(speakers)
    if len(speaker_ids) != len(set(speaker_ids)):
        raise ValueError("Selected speaker IDs must be unique")
    tasks = []
    for speaker_id in speaker_ids:
        if speaker_id not in speakers or speaker_id not in refs:
            raise ValueError(f"Missing speaker or reference: {speaker_id}")
        speaker = speakers[speaker_id]
        authorization = speaker.get("authorization", {})
        if authorization.get("status") != "authorized" or "multilingual_voice_demo" not in authorization.get("purposes", []):
            raise ValueError(f"Speaker is not authorized for multilingual demos: {speaker_id}")
        capabilities = _index(speaker.get("localeCapabilities", []), "targetLocale", "Locale capability")
        capability = capabilities.get("vi", {})
        override = capability.get("adapterOverride", {})
        reference = refs[speaker_id]
        expected_ref = f"speaker-reference://{speaker_id}/{reference['sha256']}"
        if override.get("adapter") != ADAPTER or override.get("conditioningRef") != expected_ref:
            raise ValueError(f"Vietnamese adapter or conditioning ref mismatch: {speaker_id}")
        tasks.append({
            "speakerId": speaker_id,
            "displayName": speaker["displayName"],
            "capabilityStatus": capability["status"],
            "adapter": ADAPTER,
            "model": override["model"],
            "revision": override["revision"],
            "conditioningRef": expected_ref,
            "referenceFile": reference["file"],
            "referenceSha256": reference["sha256"],
            "referenceText": reference["text"],
            "text": scripts["vi"]["text"],
        })
    models = {(task["model"], task["revision"]) for task in tasks}
    if len(models) != 1:
        raise ValueError("One Vietnamese demo run must use one pinned model revision")
    return tasks


def render(args: argparse.Namespace) -> dict[str, Any]:
    registry = read_object(args.registry, "Speaker Voice Registry")
    script = read_object(args.script, "multilingual voice demo script")
    references = read_object(args.references, "voice references")
    tasks = prepare_tasks(registry, script, references, selected_speakers=args.speakers)
    reference_root = args.reference_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "vietnamese-manifest.json"
    if manifest_path.exists():
        raise ValueError("Completed Vietnamese manifest already exists; use a new output directory")

    import numpy as np
    import soundfile as sf
    import torch
    from huggingface_hub import snapshot_download
    from qwen_tts import Qwen3TTSModel

    repo_id, revision = tasks[0]["model"], tasks[0]["revision"]
    if args.model_path:
        model_path = args.model_path.resolve()
    else:
        model_path = Path(snapshot_download(repo_id=repo_id, revision=revision, cache_dir=args.cache_dir))
    model_weights = model_path / "model.safetensors"
    if not model_weights.is_file():
        raise ValueError(f"Vietnamese model weights are missing: {model_path}")
    model = Qwen3TTSModel.from_pretrained(
        str(model_path),
        device_map=args.device,
        dtype=torch.bfloat16 if args.dtype == "bfloat16" else torch.float32,
        attn_implementation=args.attention,
    )
    renderer_hash = file_sha256(Path(__file__).resolve())
    script_hash = json_sha256(script)
    tracks = []
    for task in tasks:
        reference_path = reference_root / task["referenceFile"]
        if not reference_path.is_file() or file_sha256(reference_path) != task["referenceSha256"]:
            raise ValueError(f"Reference audio is missing or changed: {task['speakerId']}")
        destination = out / task["speakerId"] / "vi.wav"
        receipt_path = destination.with_suffix(".json")
        expected = {
            "speakerId": task["speakerId"],
            "targetLocale": "vi",
            "adapter": ADAPTER,
            "model": repo_id,
            "modelRevision": revision,
            "modelWeightsSha256": file_sha256(model_weights),
            "conditioningRef": task["conditioningRef"],
            "referenceAudioSha256": task["referenceSha256"],
            "referenceTextSha256": hashlib.sha256(task["referenceText"].encode()).hexdigest(),
            "textSha256": hashlib.sha256(task["text"].encode()).hexdigest(),
            "scriptJsonSha256": script_hash,
            "rendererSha256": renderer_hash,
            "seed": args.seed,
            "temperature": 0.3,
            "topK": 20,
            "topP": 0.9,
            "maxNewTokens": 4096,
            "repetitionPenalty": 2.0,
            "chunkPolicy": "complete_sentences_v1",
            "gapSeconds": 0.18,
            "ratePolicy": "natural_no_time_stretch",
        }
        if destination.exists() or receipt_path.exists():
            if not destination.is_file() or not receipt_path.is_file():
                raise ValueError(f"Partial cached Vietnamese demo exists: {destination}")
            receipt = read_object(receipt_path, "Vietnamese demo receipt")
            if any(receipt.get(key) != value for key, value in expected.items()):
                raise ValueError(f"Cached Vietnamese demo identity changed: {destination}")
            if receipt.get("audioSha256") != file_sha256(destination):
                raise ValueError(f"Cached Vietnamese demo hash changed: {destination}")
            tracks.append(receipt)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        chunks = []
        chunk_durations = []
        sample_rate = None
        sentences = split_sentences(task["text"])
        for index, sentence in enumerate(sentences):
            torch.manual_seed(args.seed + index)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(args.seed + index)
            wavs, chunk_rate = model.generate_voice_clone(
                text=sentence,
                language="Vietnamese",
                ref_audio=str(reference_path),
                ref_text=task["referenceText"],
                temperature=0.3,
                top_k=20,
                top_p=0.9,
                max_new_tokens=4096,
                repetition_penalty=2.0,
                subtalker_do_sample=True,
                subtalker_temperature=0.1,
                subtalker_top_k=20,
                subtalker_top_p=1.0,
            )
            chunk = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
            if sample_rate is None:
                sample_rate = chunk_rate
            if sample_rate != chunk_rate:
                raise ValueError("Vietnamese chunks returned inconsistent sample rates")
            chunks.append(chunk)
            chunk_durations.append(round(len(chunk) / chunk_rate, 6))
            if index + 1 < len(sentences):
                chunks.append(np.zeros(round(0.18 * chunk_rate), dtype=np.float32))
        wave = np.concatenate(chunks)
        assert sample_rate is not None
        duration = len(wave) / sample_rate
        if not np.isfinite(wave).all() or not 0.3 < duration < 90:
            raise ValueError(f"Suspicious Vietnamese audio for {task['speakerId']}: {duration:.2f}s")
        sf.write(destination, wave, sample_rate, subtype="PCM_24")
        decoded, decoded_rate = sf.read(destination, always_2d=False)
        if decoded_rate != sample_rate or len(decoded) != len(wave):
            raise ValueError(f"Full decode differs from generated audio: {destination}")
        receipt = {
            "schemaVersion": "sermon-multilingual-voice-demo-track-v1",
            **expected,
            "displayName": task["displayName"],
            "capabilityStatus": task["capabilityStatus"],
            "file": str(destination.relative_to(out)),
            "audioSha256": file_sha256(destination),
            "sampleRate": sample_rate,
            "durationSeconds": round(duration, 6),
            "generationSeconds": round(time.monotonic() - started, 6),
            "chunkCount": len(sentences),
            "chunkDurations": chunk_durations,
            "fullDecode": "pass",
            "machineScreening": "not_run",
            "humanListeningStatus": "pending",
        }
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tracks.append(receipt)
        print(json.dumps({"speakerId": task["speakerId"], "targetLocale": "vi", "durationSeconds": duration}), flush=True)
    manifest = {
        "schemaVersion": "sermon-multilingual-voice-demo-manifest-v1",
        "status": "generated_waveforms",
        "scope": script["scope"],
        "adapter": ADAPTER,
        "model": repo_id,
        "modelRevision": revision,
        "registryJsonSha256": json_sha256(registry),
        "scriptJsonSha256": script_hash,
        "referencesJsonSha256": json_sha256(references),
        "trackCount": len(tracks),
        "fullDecodeCoverage": 1,
        "machineScreening": "not_run",
        "humanListeningStatus": "pending",
        "tracks": tracks,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--speaker", action="append", dest="speakers")
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", choices=("bfloat16", "float32"), default="bfloat16")
    parser.add_argument("--attention", default="flash_attention_2")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    manifest = render(args)
    print(json.dumps({"manifest": str(args.out / "vietnamese-manifest.json"), "trackCount": manifest["trackCount"]}))


if __name__ == "__main__":
    main()
