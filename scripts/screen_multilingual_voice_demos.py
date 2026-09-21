#!/usr/bin/env python3
"""Back-transcribe every multilingual voice demo as a machine-only screen."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any


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


def normalize(value: str, locale: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", value).casefold()
    if locale == "zh-Hans":
        return [character for character in folded if character.isalnum()]
    return [token for token in re.findall(r"[^\W_]+", folded, flags=re.UNICODE) if token]


def collect_generation_tracks(root: Path) -> list[dict[str, Any]]:
    tracks = []
    for name in ("manifest.json", "vietnamese-manifest.json"):
        manifest = read_object(root / name, "voice demo manifest")
        if manifest.get("schemaVersion") != "sermon-multilingual-voice-demo-manifest-v1":
            raise ValueError(f"Unsupported voice demo manifest: {name}")
        tracks.extend(manifest.get("tracks", []))
    identities = [(track.get("speakerId"), track.get("targetLocale")) for track in tracks]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate speaker/locale generation tracks")
    return tracks


def screen(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    script = read_object(args.script, "multilingual demo script")
    scripts = {item["targetLocale"]: item for item in script["locales"]}
    tracks = collect_generation_tracks(root)
    receipt_path = root / "asr-screening.json"
    if receipt_path.exists():
        raise ValueError("ASR screening receipt already exists; preserve completed evidence")

    import soundfile as sf
    import torch
    from qwen_asr import Qwen3ASRModel

    model_path = args.model_path.resolve()
    model = Qwen3ASRModel.from_pretrained(
        str(model_path),
        dtype=torch.bfloat16,
        device_map=args.device,
        max_inference_batch_size=1,
        max_new_tokens=2048,
    )
    results = []
    for track in sorted(tracks, key=lambda item: (item["speakerId"], item["targetLocale"])):
        locale = track["targetLocale"]
        if locale not in scripts:
            raise ValueError(f"Missing expected script for locale {locale}")
        audio_path = root / track["file"]
        if not audio_path.is_file() or file_sha256(audio_path) != track["audioSha256"]:
            raise ValueError(f"Generated audio is missing or changed: {track['speakerId']}/{locale}")
        audio, sample_rate = sf.read(audio_path, dtype="float32")
        transcription = model.transcribe(audio=(audio, sample_rate), language=scripts[locale]["modelLanguage"])[0].text.strip()
        expected_tokens = normalize(scripts[locale]["text"], locale)
        actual_tokens = normalize(transcription, locale)
        matcher = difflib.SequenceMatcher(None, expected_tokens, actual_tokens, autojunk=False)
        differences = [
            {
                "kind": operation,
                "expected": expected_tokens[left_start:left_end],
                "recognized": actual_tokens[right_start:right_end],
            }
            for operation, left_start, left_end, right_start, right_end in matcher.get_opcodes()
            if operation != "equal"
        ]
        result = {
            "speakerId": track["speakerId"],
            "targetLocale": locale,
            "audioSha256": track["audioSha256"],
            "expectedTextSha256": hashlib.sha256(scripts[locale]["text"].encode()).hexdigest(),
            "recognized": transcription,
            "similarity": round(matcher.ratio(), 6),
            "differences": differences,
        }
        results.append(result)
        print(json.dumps({"speakerId": track["speakerId"], "targetLocale": locale, "similarity": result["similarity"]}), flush=True)
    receipt = {
        "schemaVersion": "sermon-multilingual-voice-demo-asr-screening-v1",
        "status": "machine_screening_only",
        "model": "Qwen/Qwen3-ASR-0.6B",
        "modelRevision": args.model_revision,
        "scriptJsonSha256": json_sha256(script),
        "coverage": 1,
        "trackCount": len(results),
        "reviewPriorityCount": sum(item["similarity"] < args.review_priority_threshold for item in results),
        "reviewPriorityThreshold": args.review_priority_threshold,
        "warning": "ASR differences may be recognition errors, pronunciation errors, homophones, or text-normalization differences. This never grants human listening approval.",
        "humanListeningStatus": "pending",
        "results": results,
    }
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--review-priority-threshold", type=float, default=0.85)
    args = parser.parse_args()
    receipt = screen(args)
    print(json.dumps({"receipt": str(args.root / "asr-screening.json"), "trackCount": receipt["trackCount"], "reviewPriorityCount": receipt["reviewPriorityCount"]}))


if __name__ == "__main__":
    main()
