#!/usr/bin/env python3
"""Bind reviewed short and long voice probes to one source and locale."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts import prepare_target_language_speech_job as speech
    from scripts import sermon_sentence_interpretation as interpretation
except ImportError:
    import prepare_target_language_speech_job as speech
    import sermon_sentence_interpretation as interpretation


def artifact(path: Path, *, json_artifact: bool) -> dict[str, str]:
    if not path.is_file():
        raise ValueError(f"Missing clip voice capability evidence: {path}")
    result = {"path": str(path.resolve()), "sha256": interpretation.sha256(path)}
    if json_artifact:
        result["jsonSha256"] = interpretation.json_sha256(speech._load(path))
    return result


def prepare(source_path: Path, adapter_path: Path, short_approval_path: Path,
            short_audio_path: Path, long_approval_path: Path, long_manifest_path: Path,
            long_audio_path: Path, out: Path) -> dict:
    if out.exists():
        raise ValueError("Clip voice capability receipt is immutable; choose a new path")
    source, adapter = speech._load(source_path), speech._load(adapter_path)
    receipt = {
        "schemaVersion": "sermon-clip-voice-capability-v1",
        "scope": "this_clip_locale_probe_capability_only",
        "englishSourcePackageJsonSha256": interpretation.json_sha256(source),
        "targetLocale": adapter["targetLocale"],
        "speakerId": adapter["speakerId"],
        "checkpointSha256": adapter["conditioningSha256"],
        "shortDemoApproval": artifact(short_approval_path, json_artifact=True),
        "shortDemoAudio": artifact(short_audio_path, json_artifact=False),
        "longProbeApproval": artifact(long_approval_path, json_artifact=True),
        "longProbeManifest": artifact(long_manifest_path, json_artifact=True),
        "longProbeAudio": artifact(long_audio_path, json_artifact=False),
    }
    speech.validate_clip_voice_capability(receipt, source, adapter)
    out.parent.mkdir(parents=True, exist_ok=True)
    interpretation.write_json(out, receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "adapter", "short-approval", "short-audio", "long-approval",
                 "long-manifest", "long-audio", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    receipt = prepare(args.source, args.adapter, args.short_approval, args.short_audio,
                      args.long_approval, args.long_manifest, args.long_audio, args.out)
    print(json.dumps({"status": "clip_probe_reviewed", "targetLocale": receipt["targetLocale"],
                      "receipt": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
