#!/usr/bin/env python3
"""Package generated multilingual voice-demo WAVs as verified MP3 auditions."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
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


def collect_tracks(root: Path, registry: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    manifest_paths = [root / "manifest.json", root / "vietnamese-manifest.json"]
    manifests = []
    tracks = []
    for path in manifest_paths:
        manifest = read_object(path, "voice demo manifest")
        if manifest.get("schemaVersion") != "sermon-multilingual-voice-demo-manifest-v1":
            raise ValueError(f"Unsupported voice demo manifest: {path}")
        if manifest.get("fullDecodeCoverage") != 1 or manifest.get("humanListeningStatus") != "pending":
            raise ValueError(f"Unexpected generation gate state: {path}")
        entries = manifest.get("tracks")
        if not isinstance(entries, list) or manifest.get("trackCount") != len(entries):
            raise ValueError(f"Manifest track count is invalid: {path}")
        manifests.append({"path": path.name, "sha256": file_sha256(path)})
        tracks.extend(entries)
    expected = {
        (speaker["speakerId"], capability["targetLocale"])
        for speaker in registry.get("speakers", [])
        for capability in speaker.get("localeCapabilities", [])
        if capability.get("status") != "unsupported"
    }
    actual = [(track.get("speakerId"), track.get("targetLocale")) for track in tracks]
    if len(actual) != len(set(actual)):
        raise ValueError("Voice demo manifests contain duplicate speaker/locale tracks")
    if set(actual) != expected:
        missing = sorted(expected - set(actual))
        extra = sorted(set(actual) - expected)
        raise ValueError(f"Voice demo track matrix differs from registry; missing={missing}, extra={extra}")
    for track in tracks:
        wav = root / str(track.get("file", ""))
        if not wav.is_file() or file_sha256(wav) != track.get("audioSha256"):
            raise ValueError(f"Generated WAV is missing or changed: {track.get('speakerId')}/{track.get('targetLocale')}")
        if track.get("fullDecode") != "pass":
            raise ValueError("Every source WAV must have passed full decode")
    return tracks, manifests


def _duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(result.stdout).get("format", {}).get("duration")
    if value is None or float(value) <= 0:
        raise ValueError(f"Encoded MP3 has no positive duration: {path}")
    return float(value)


def package(root: Path, registry_path: Path) -> dict[str, Any]:
    root = root.resolve()
    registry = read_object(registry_path, "Speaker Voice Registry")
    tracks, manifests = collect_tracks(root, registry)
    delivery_path = root / "delivery-manifest.json"
    if delivery_path.exists():
        raise ValueError("Delivery manifest already exists; preserve the completed package")
    screening_path = root / "asr-screening.json"
    screening = read_object(screening_path, "ASR screening") if screening_path.is_file() else None
    if screening is not None:
        if screening.get("coverage") != 1 or screening.get("trackCount") != len(tracks):
            raise ValueError("ASR screening does not cover the complete demo matrix")
        screening_results = {
            (item["speakerId"], item["targetLocale"]): item for item in screening.get("results", [])
        }
        if len(screening_results) != len(tracks):
            raise ValueError("ASR screening results are incomplete or duplicated")
    else:
        screening_results = {}
    delivered = []
    for track in sorted(tracks, key=lambda item: (item["speakerId"], item["targetLocale"])):
        source = root / track["file"]
        destination = root / "mp3" / track["speakerId"] / f"{track['targetLocale']}.mp3"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise ValueError(f"Refusing to overwrite existing MP3: {destination}")
        subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-n", "-i", str(source),
            "-map", "0:a:0", "-ac", "1", "-ar", "44100", "-b:a", "128k", str(destination),
        ], check=True)
        subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-i", str(destination), "-map", "0:a:0", "-f", "null", "-",
        ], check=True)
        asr = screening_results.get((track["speakerId"], track["targetLocale"]))
        delivered.append({
            "speakerId": track["speakerId"],
            "displayName": track["displayName"],
            "targetLocale": track["targetLocale"],
            "adapter": track.get("adapter", "qwen3_tts_sft"),
            "capabilityStatus": track["capabilityStatus"],
            "sourceWav": {"path": track["file"], "sha256": track["audioSha256"]},
            "mp3": {
                "path": str(destination.relative_to(root)),
                "sha256": file_sha256(destination),
                "durationSeconds": round(_duration(destination), 6),
                "codec": "mp3",
                "sampleRate": 44100,
                "channels": 1,
                "bitrate": "128k",
                "fullDecode": "pass",
            },
            "machineScreening": track["machineScreening"] if asr is None else screening["status"],
            "asrScreening": None if asr is None else {
                "similarity": asr["similarity"],
                "reviewPriority": asr["similarity"] < screening["reviewPriorityThreshold"],
            },
            "humanListeningStatus": track["humanListeningStatus"],
        })
    manifest = {
        "schemaVersion": "sermon-multilingual-voice-demo-delivery-v1",
        "status": "encoded_and_fully_decoded",
        "scope": "voice_capability_audition_not_sermon_translation",
        "registry": {"path": str(registry_path), "sha256": file_sha256(registry_path)},
        "sourceManifests": manifests,
        "speakerCount": len({track["speakerId"] for track in delivered}),
        "targetLocales": sorted({track["targetLocale"] for track in delivered}),
        "trackCount": len(delivered),
        "fullDecodeCoverage": 1,
        "machineScreening": {
            "status": "not_run" if screening is None else screening["status"],
            "receipt": None if screening is None else {
                "path": screening_path.name,
                "sha256": file_sha256(screening_path),
            },
            "reviewPriorityCount": None if screening is None else screening["reviewPriorityCount"],
        },
        "humanListeningStatus": "pending",
        "tracks": delivered,
    }
    delivery_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    args = parser.parse_args()
    manifest = package(args.root, args.registry.resolve())
    print(json.dumps({"delivery": str(args.root / "delivery-manifest.json"), "trackCount": manifest["trackCount"]}))


if __name__ == "__main__":
    main()
