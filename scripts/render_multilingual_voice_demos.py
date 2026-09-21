#!/usr/bin/env python3
"""Render one immutable multilingual voice demo per registered speaker and locale.

The checkpoint map is deployment-local and must stay outside Git.  The registry
contains only stable checkpoint refs and hashes; generated audio remains under
the ignored artifacts tree.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import time
from typing import Any


REGISTRY_SCHEMA_VERSION = "sermon-speaker-voice-registry-v1"
SCRIPT_SCHEMA_VERSION = "sermon-multilingual-voice-demo-script-v1"
MANIFEST_SCHEMA_VERSION = "sermon-multilingual-voice-demo-manifest-v1"


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


def _index(items: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    values = [item.get(key) for item in items]
    if any(not isinstance(value, str) or not value for value in values) or len(values) != len(set(values)):
        raise ValueError(f"{label} {key} values must be non-empty and unique")
    return dict(zip(values, items))


def prepare_tasks(
    registry: dict[str, Any],
    script: dict[str, Any],
    checkpoint_map: dict[str, Any],
    *,
    selected_speakers: list[str] | None = None,
    selected_locales: list[str] | None = None,
) -> list[dict[str, Any]]:
    if registry.get("schemaVersion") != REGISTRY_SCHEMA_VERSION:
        raise ValueError("Unsupported Speaker Voice Registry schema")
    if script.get("schemaVersion") != SCRIPT_SCHEMA_VERSION:
        raise ValueError("Unsupported multilingual demo script schema")
    if checkpoint_map.get("schemaVersion") != "sermon-speaker-checkpoint-map-v1":
        raise ValueError("Unsupported checkpoint map schema")
    speakers = _index(registry.get("speakers", []), "speakerId", "Speaker")
    scripts = _index(script.get("locales", []), "targetLocale", "Demo script")
    checkpoints = _index(checkpoint_map.get("checkpoints", []), "speakerId", "Checkpoint")
    speaker_ids = selected_speakers or list(speakers)
    locales = selected_locales or list(registry.get("supportedTargetLocales", []))
    if len(speaker_ids) != len(set(speaker_ids)) or len(locales) != len(set(locales)):
        raise ValueError("Selected speakers and locales must be unique")
    tasks = []
    for speaker_id in speaker_ids:
        if speaker_id not in speakers or speaker_id not in checkpoints:
            raise ValueError(f"Missing speaker or checkpoint mapping: {speaker_id}")
        speaker = speakers[speaker_id]
        authorization = speaker.get("authorization", {})
        if authorization.get("status") != "authorized" or "multilingual_voice_demo" not in authorization.get("purposes", []):
            raise ValueError(f"Speaker is not authorized for multilingual demos: {speaker_id}")
        checkpoint = speaker["checkpoint"]
        mapping = checkpoints[speaker_id]
        if mapping.get("checkpointRef") != checkpoint["checkpointRef"]:
            raise ValueError(f"Checkpoint mapping ref differs from registry: {speaker_id}")
        capabilities = _index(speaker.get("localeCapabilities", []), "targetLocale", "Locale capability")
        for locale in locales:
            if locale not in scripts or locale not in capabilities:
                raise ValueError(f"Missing demo script or voice capability for {speaker_id}/{locale}")
            capability = capabilities[locale]
            if capability.get("status") == "unsupported":
                raise ValueError(f"Unsupported demo locale for {speaker_id}: {locale}")
            if capability.get("adapterOverride"):
                if selected_locales is not None:
                    raise ValueError(f"Locale {locale} requires its registered adapter override")
                continue
            if scripts[locale].get("modelLanguage") != capability.get("modelLanguage"):
                raise ValueError(f"Model language mismatch for {speaker_id}/{locale}")
            tasks.append({
                "speakerId": speaker_id,
                "displayName": speaker["displayName"],
                "speakerKey": speaker["speakerKey"],
                "checkpointRef": checkpoint["checkpointRef"],
                "checkpointSha256": checkpoint["checkpointSha256"],
                "checkpointPath": mapping.get("path"),
                "targetLocale": locale,
                "modelLanguage": capability["modelLanguage"],
                "capabilityStatus": capability["status"],
                "text": scripts[locale]["text"],
            })
    return tasks


def validate_checkpoint(task: dict[str, Any]) -> Path:
    path = Path(str(task.get("checkpointPath", ""))).expanduser().resolve()
    weights = path / "model.safetensors"
    config_path = path / "config.json"
    if not weights.is_file() or not config_path.is_file():
        raise ValueError(f"Checkpoint is incomplete: {path}")
    if file_sha256(weights) != task["checkpointSha256"]:
        raise ValueError(f"Checkpoint hash differs from registry: {task['speakerId']}")
    config = read_object(config_path, "checkpoint config")
    speaker_ids = config.get("talker_config", {}).get("spk_id", {})
    if task["speakerKey"] not in speaker_ids:
        raise ValueError(f"Checkpoint does not contain speaker slot {task['speakerKey']}")
    return path


def _expected_receipt(task: dict[str, Any], script_hash: str, renderer_hash: str, seed: int) -> dict[str, Any]:
    return {
        "speakerId": task["speakerId"],
        "speakerKey": task["speakerKey"],
        "checkpointRef": task["checkpointRef"],
        "checkpointSha256": task["checkpointSha256"],
        "targetLocale": task["targetLocale"],
        "modelLanguage": task["modelLanguage"],
        "textSha256": hashlib.sha256(task["text"].encode()).hexdigest(),
        "scriptJsonSha256": script_hash,
        "rendererSha256": renderer_hash,
        "seed": seed,
        "temperature": 0.7,
        "repetitionPenalty": 1.05,
        "maxNewTokens": 768,
        "ratePolicy": "natural_no_time_stretch",
    }


def render(args: argparse.Namespace) -> dict[str, Any]:
    registry = read_object(args.registry, "Speaker Voice Registry")
    script = read_object(args.script, "multilingual voice demo script")
    checkpoint_map = read_object(args.checkpoint_map, "speaker checkpoint map")
    tasks = prepare_tasks(
        registry,
        script,
        checkpoint_map,
        selected_speakers=args.speakers,
        selected_locales=args.locales,
    )
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        raise ValueError("Completed demo manifest already exists; use a new output directory")

    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    script_hash = json_sha256(script)
    renderer_hash = file_sha256(Path(__file__).resolve())
    tracks = []
    for speaker_id in dict.fromkeys(task["speakerId"] for task in tasks):
        speaker_tasks = [task for task in tasks if task["speakerId"] == speaker_id]
        checkpoint = validate_checkpoint(speaker_tasks[0])
        dtype = torch.bfloat16 if args.dtype == "bfloat16" else torch.float32
        model_kwargs = {"device_map": args.device, "dtype": dtype}
        if args.attention:
            model_kwargs["attn_implementation"] = args.attention
        model = Qwen3TTSModel.from_pretrained(str(checkpoint), **model_kwargs)
        try:
            for task in speaker_tasks:
                destination = out / speaker_id / f"{task['targetLocale']}.wav"
                receipt_path = destination.with_suffix(".json")
                expected = _expected_receipt(task, script_hash, renderer_hash, args.seed)
                if destination.exists() or receipt_path.exists():
                    if not destination.is_file() or not receipt_path.is_file():
                        raise ValueError(f"Partial cached demo exists: {destination}")
                    receipt = read_object(receipt_path, "demo receipt")
                    if any(receipt.get(key) != value for key, value in expected.items()):
                        raise ValueError(f"Cached demo identity changed: {destination}")
                    if receipt.get("audioSha256") != file_sha256(destination):
                        raise ValueError(f"Cached demo hash changed: {destination}")
                    tracks.append(receipt)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                torch.manual_seed(args.seed)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed_all(args.seed)
                started = time.monotonic()
                wavs, sample_rate = model.generate_custom_voice(
                    text=task["text"],
                    language=task["modelLanguage"],
                    speaker=task["speakerKey"],
                    temperature=0.7,
                    repetition_penalty=1.05,
                    max_new_tokens=768,
                )
                wave = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
                duration = len(wave) / sample_rate
                if not np.isfinite(wave).all() or not 0.3 < duration < 90:
                    raise ValueError(f"Suspicious audio for {speaker_id}/{task['targetLocale']}: {duration:.2f}s")
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
                    "fullDecode": "pass",
                    "machineScreening": "not_run",
                    "humanListeningStatus": "pending",
                }
                receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                tracks.append(receipt)
                print(json.dumps({"speakerId": speaker_id, "targetLocale": task["targetLocale"], "durationSeconds": duration}), flush=True)
        finally:
            del model
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    manifest = {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "status": "generated_waveforms",
        "scope": script["scope"],
        "registryJsonSha256": json_sha256(registry),
        "scriptJsonSha256": script_hash,
        "rendererSha256": renderer_hash,
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
    parser.add_argument("--checkpoint-map", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--speaker", action="append", dest="speakers")
    parser.add_argument("--locale", action="append", dest="locales")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", choices=("bfloat16", "float32"), default="bfloat16")
    parser.add_argument("--attention", default="sdpa")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    manifest = render(args)
    print(json.dumps({"manifest": str(args.out / "manifest.json"), "trackCount": manifest["trackCount"]}))


if __name__ == "__main__":
    main()
