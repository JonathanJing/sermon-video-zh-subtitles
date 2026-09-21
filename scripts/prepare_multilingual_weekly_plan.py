#!/usr/bin/env python3
"""Compile one Layer 1 package into independent per-locale Layer 2/3 lanes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


PLAN_SCHEMA_VERSION = "sermon-multilingual-weekly-plan-v1"
SOURCE_SCHEMA_VERSION = "sermon-english-source-package-v1"
REGISTRY_SCHEMA_VERSION = "sermon-speaker-voice-registry-v1"


def read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def json_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_registry(registry: dict[str, Any]) -> None:
    if registry.get("schemaVersion") != REGISTRY_SCHEMA_VERSION:
        raise ValueError("Unsupported Speaker Voice Registry schema")
    locales = registry.get("supportedTargetLocales")
    if not isinstance(locales, list) or not locales or len(locales) != len(set(locales)):
        raise ValueError("Registry target locales must be non-empty and unique")
    speakers = registry.get("speakers")
    if not isinstance(speakers, list) or not speakers:
        raise ValueError("Registry must contain speakers")
    ids = [speaker.get("speakerId") for speaker in speakers if isinstance(speaker, dict)]
    keys = [speaker.get("speakerKey") for speaker in speakers if isinstance(speaker, dict)]
    refs = [speaker.get("checkpoint", {}).get("checkpointRef") for speaker in speakers if isinstance(speaker, dict)]
    if len(ids) != len(speakers) or any(not value for value in ids + keys + refs):
        raise ValueError("Every speaker needs a speakerId, speakerKey, and checkpointRef")
    if len(ids) != len(set(ids)) or len(keys) != len(set(keys)) or len(refs) != len(set(refs)):
        raise ValueError("Speaker IDs, keys, and checkpoint refs must be unique")
    for speaker in speakers:
        capabilities = speaker.get("localeCapabilities")
        capability_locales = [item.get("targetLocale") for item in capabilities or [] if isinstance(item, dict)]
        if not capabilities or len(capability_locales) != len(capabilities):
            raise ValueError(f"Speaker {speaker['speakerId']} has invalid locale capabilities")
        if len(capability_locales) != len(set(capability_locales)):
            raise ValueError(f"Speaker {speaker['speakerId']} repeats a locale capability")
        if any(locale not in locales for locale in capability_locales):
            raise ValueError(f"Speaker {speaker['speakerId']} uses an unregistered locale")


def select_speaker(registry: dict[str, Any], speaker_id: str) -> dict[str, Any]:
    matches = [speaker for speaker in registry["speakers"] if speaker["speakerId"] == speaker_id]
    if len(matches) != 1:
        raise ValueError(f"Speaker is not uniquely registered: {speaker_id}")
    return matches[0]


def select_capability(speaker: dict[str, Any], locale: str) -> dict[str, Any]:
    matches = [item for item in speaker["localeCapabilities"] if item["targetLocale"] == locale]
    if len(matches) != 1 or matches[0]["status"] == "unsupported":
        raise ValueError(f"Speaker {speaker['speakerId']} does not support locale {locale}")
    return matches[0]


def _check_gate(
    source: dict[str, Any],
    speaker: dict[str, Any],
    capability: dict[str, Any],
    locale: str,
    mode: str,
) -> None:
    authorization = speaker.get("authorization", {})
    if authorization.get("status") != "authorized":
        raise ValueError(f"Speaker {speaker['speakerId']} is not authorized")
    purposes = set(authorization.get("purposes", []))
    if mode == "production":
        if source.get("status") != "ready_for_translation" or source.get("translationEligible") is not True:
            raise ValueError("Production planning requires a ready_for_translation Layer 1 package")
        required_purpose = "chinese_dubbing" if locale == "zh-Hans" else "multilingual_dubbing"
        if required_purpose not in purposes:
            raise ValueError(f"Production voice authorization is missing for {locale}")
        if capability.get("status") != "human_reviewed":
            raise ValueError(f"Production voice capability is not human reviewed for {locale}")
    else:
        if source.get("status") not in {"candidate_ready_for_translation", "ready_for_translation"}:
            raise ValueError("Shadow planning requires a translation-eligible Layer 1 candidate")
        if source.get("candidateTranslationEligible") is not True:
            raise ValueError("Layer 1 candidateTranslationEligible must be true")
        if "multilingual_voice_demo" not in purposes and "multilingual_dubbing" not in purposes:
            raise ValueError(f"Shadow voice authorization is missing for {locale}")


def voice_resolution(registry: dict[str, Any], speaker: dict[str, Any], capability: dict[str, Any]) -> dict[str, Any]:
    override = capability.get("adapterOverride")
    if isinstance(override, dict):
        return {
            "capability": capability["status"],
            "adapter": override["adapter"],
            "model": override["model"],
            "revision": override["revision"],
            "conditioningRef": override["conditioningRef"],
        }
    return {
        "capability": capability["status"],
        "adapter": "qwen3_tts_sft",
        "model": registry["baseModel"]["model"],
        "revision": registry["baseModel"]["revision"],
        "conditioningRef": speaker["checkpoint"]["checkpointRef"],
    }


def prepare_plan(
    source: dict[str, Any],
    registry: dict[str, Any],
    *,
    speaker_id: str,
    target_locales: list[str],
    mode: str,
) -> dict[str, Any]:
    if source.get("schemaVersion") != SOURCE_SCHEMA_VERSION:
        raise ValueError("Unsupported English Source Package schema")
    if mode not in {"shadow", "production"}:
        raise ValueError("mode must be shadow or production")
    validate_registry(registry)
    if not target_locales or len(target_locales) != len(set(target_locales)):
        raise ValueError("Target locales must be non-empty and unique")
    if any(locale not in registry["supportedTargetLocales"] for locale in target_locales):
        raise ValueError("Plan requested a locale outside the registry")
    speaker = select_speaker(registry, speaker_id)
    capabilities = {locale: select_capability(speaker, locale) for locale in target_locales}
    for locale, capability in capabilities.items():
        _check_gate(source, speaker, capability, locale, mode)

    source_hash = json_sha256(source)
    registry_hash = json_sha256(registry)
    identity = {
        "mode": mode,
        "englishSourcePackageJsonSha256": source_hash,
        "speakerRegistryJsonSha256": registry_hash,
        "speakerId": speaker_id,
        "targetLocales": target_locales,
    }
    plan_id = f"multilingual-weekly-{json_sha256(identity)[:24]}"
    lanes = []
    for locale in target_locales:
        layer2_id = f"{plan_id}:layer2:{locale}"
        layer3_id = f"{plan_id}:layer3:{locale}"
        voice = voice_resolution(registry, speaker, capabilities[locale])
        lanes.append({
            "targetLocale": locale,
            "voice": voice,
            "layer2": {
                "nodeId": layer2_id,
                "status": "ready",
                "leaseKey": f"layer2:{source['packageId']}:{locale}",
                "dependsOn": [source["packageId"]],
            },
            "layer3": {
                "nodeId": layer3_id,
                "status": "waiting_for_layer2_gate",
                "leaseKey": f"layer3:{source['packageId']}:{locale}:{speaker_id}",
                "dependsOn": [layer2_id, voice["conditioningRef"]],
            },
        })
    return {
        "schemaVersion": PLAN_SCHEMA_VERSION,
        "planId": plan_id,
        "mode": mode,
        "englishSourcePackage": {
            "packageId": source["packageId"],
            "jsonSha256": source_hash,
            "downstreamInvalidationKey": source["downstreamInvalidationKey"],
            "status": source["status"],
        },
        "speakerRegistry": {"registryId": registry["registryId"], "jsonSha256": registry_hash},
        "speaker": {
            "speakerId": speaker_id,
            "speakerKey": speaker["speakerKey"],
            "checkpointRef": speaker["checkpoint"]["checkpointRef"],
            "checkpointSha256": speaker["checkpoint"]["checkpointSha256"],
        },
        "scheduling": {
            "localeBarrier": "none",
            "layer2Dispatch": "all_locales_after_layer1",
            "layer3Dispatch": "per_locale_after_layer2_gate",
            "gpuPolicy": "single_worker_checkpoint_affinity",
            "voiceTrainingPolicy": "separate_cached_dependency",
        },
        "lanes": lanes,
        "invalidation": {
            "layer1": "all_locale_lanes",
            "layer2": "same_locale_layer3_and_layer4",
            "voiceCheckpoint": "dependent_layer3_and_layer4_only",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--english-source-package", type=Path, required=True)
    parser.add_argument("--speaker-registry", type=Path, required=True)
    parser.add_argument("--speaker-id", required=True)
    parser.add_argument("--target-locale", action="append", dest="target_locales", required=True)
    parser.add_argument("--mode", choices=("shadow", "production"), default="shadow")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source = read_object(args.english_source_package, "English Source Package")
    registry = read_object(args.speaker_registry, "Speaker Voice Registry")
    plan = prepare_plan(
        source,
        registry,
        speaker_id=args.speaker_id,
        target_locales=args.target_locales,
        mode=args.mode,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        raise ValueError(f"Refusing to overwrite an existing plan: {args.out}")
    args.out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"plan": str(args.out), "planId": plan["planId"], "lanes": len(plan["lanes"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
