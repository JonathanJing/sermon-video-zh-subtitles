#!/usr/bin/env python3
"""Bind one user voice permission statement to one approved Dev clip candidate."""
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


def prepare(source_path: Path, candidate_path: Path, adapter_path: Path,
            user_attestation_path: Path, out: Path) -> dict:
    if out.exists():
        raise ValueError("Clip voice authorization is immutable; choose a new path")
    for path in (source_path, candidate_path, adapter_path, user_attestation_path):
        if not path.is_file():
            raise ValueError(f"Missing clip voice authorization input: {path}")
    source, candidate, adapter = (speech._load(path) for path in (
        source_path, candidate_path, adapter_path))
    receipt = {
        "schemaVersion": "sermon-clip-voice-authorization-v1",
        "scope": "this_clip_dev_audio_only",
        "englishSourcePackageJsonSha256": interpretation.json_sha256(source),
        "targetLanguageCandidateJsonSha256": interpretation.json_sha256(candidate),
        "targetLocale": candidate["targetLocale"],
        "speakerId": adapter["speakerId"],
        "voiceCheckpointSha256": adapter["conditioningSha256"],
        "userRightsAttestation": {
            "path": str(user_attestation_path.resolve()),
            "sha256": interpretation.sha256(user_attestation_path),
            "jsonSha256": interpretation.json_sha256(speech._load(user_attestation_path)),
        },
    }
    speech.validate_clip_voice_authorization(receipt, source, candidate, adapter)
    out.parent.mkdir(parents=True, exist_ok=True)
    interpretation.write_json(out, receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--user-attestation", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.source, args.candidate, args.adapter,
                     args.user_attestation, args.out)
    print(json.dumps({"status": "clip_bound", "targetLocale": result["targetLocale"],
                      "receipt": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
