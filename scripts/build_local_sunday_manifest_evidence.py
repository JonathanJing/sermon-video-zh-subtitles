#!/usr/bin/env python3
"""Build local Sunday manifest evidence from an offline run artifact tree."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.promote_sunday_manifest import promote_manifest
from scripts.validate_sunday_manifest import validate_manifest_contract
from scripts.validate_offline_chain import parse_playback_js, validate_offline_chain


DEFAULT_SOURCE_RUN_ROOT = REPO_ROOT / "artifacts" / "evidence" / "offline-export-contract"
DEFAULT_OUT_ROOT = REPO_ROOT / "artifacts" / "evidence" / "manifest-promotion-guard"
DEFAULT_OFFLINE_CHAIN_VALIDATION_OUT = REPO_ROOT / "artifacts" / "evidence" / "offline-chain-validation.json"


def main() -> int:
    args = parse_args()
    report = build_local_sunday_manifest_evidence(
        sunday=args.sunday,
        source_run_root=resolve_repo_path(args.source_run_root),
        source_manifest=resolve_repo_path(args.source_manifest) if args.source_manifest else None,
        out_root=resolve_repo_path(args.out_root),
        validation_out=resolve_repo_path(args.validation_out) if args.validation_out else None,
        offline_chain_validation_out=(
            resolve_repo_path(args.offline_chain_validation_out) if args.offline_chain_validation_out else None
        ),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sunday", required=True, help="Sunday date, YYYY-MM-DD.")
    parser.add_argument(
        "--source-run-root",
        type=Path,
        default=DEFAULT_SOURCE_RUN_ROOT,
        help="Run root containing web/ and artifacts/ outputs.",
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        help="Source run cloud-manifest.json. Defaults to <source-run-root>/artifacts/cloud-manifest.json.",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=DEFAULT_OUT_ROOT,
        help="Local evidence root to receive copied playback/caption artifacts and promoted manifest.",
    )
    parser.add_argument(
        "--validation-out",
        type=Path,
        default=REPO_ROOT / "artifacts" / "evidence" / "sunday-manifest-validation.json",
        help="Where to write validate_sunday_manifest.py-compatible report.",
    )
    parser.add_argument(
        "--offline-chain-validation-out",
        type=Path,
        default=DEFAULT_OFFLINE_CHAIN_VALIDATION_OUT,
        help="Where to write validate_offline_chain.py-compatible report when source report.json is available.",
    )
    return parser.parse_args()


def build_local_sunday_manifest_evidence(
    *,
    sunday: str,
    source_run_root: Path,
    source_manifest: Path | None,
    out_root: Path,
    validation_out: Path | None,
    offline_chain_validation_out: Path | None = DEFAULT_OFFLINE_CHAIN_VALIDATION_OUT,
) -> dict[str, Any]:
    source_manifest = source_manifest or source_run_root / "artifacts" / "cloud-manifest.json"
    manifest = read_json(source_manifest)
    copied_outputs = copy_manifest_outputs(manifest, source_run_root=source_run_root, out_root=out_root)
    copied_report = copy_source_report(source_run_root=source_run_root, out_root=out_root)
    staged_manifest = dict(manifest)
    staged_manifest["outputs"] = copied_outputs
    staged_manifest.update(route_metadata_for_manifest(staged_manifest, copied_report, out_root))
    staged_manifest["apiKeyMaterialIncluded"] = False
    staged_manifest["secretResourceNamesIncluded"] = False

    run_manifest = out_root / "artifacts" / "cloud-manifest.json"
    promoted_manifest_path = out_root / "cloud-manifest.json"
    write_json(run_manifest, staged_manifest)

    promoted = promote_manifest(
        staged_manifest,
        sunday=sunday,
        source_manifest=display_path(run_manifest),
        destination_manifest=display_path(promoted_manifest_path),
        source_mode="youtube-live-archive",
        readiness_state="published",
        realtime_draft_model="gpt-realtime-translate",
        offline_asr_model="gpt-4o-transcribe",
        offline_translation_model="gpt-5.5-mini",
        stable_correction_model="gpt-5.5-mini",
    )
    write_json(promoted_manifest_path, promoted)

    validation = validate_manifest_contract(
        manifest=promoted,
        manifest_uri=display_path(promoted_manifest_path) or str(promoted_manifest_path),
        sunday=sunday,
        expected_readiness="published",
        expected_source_mode="youtube-live-archive",
        require_readable_artifacts=True,
    )
    if validation_out:
        write_json(validation_out, validation)

    offline_chain_validation = build_offline_chain_validation(
        source_report=copied_report,
        out_root=out_root,
        manifest_path=promoted_manifest_path,
        validation_out=offline_chain_validation_out,
    )

    return {
        "schemaVersion": 1,
        "status": "ok" if validation["status"] == "ok" and offline_chain_validation["status"] in {"ok", "skipped"} else "failed",
        "artifactLocation": "local_contract",
        "sunday": sunday,
        "sourceRunRoot": display_path(source_run_root),
        "sourceManifest": display_path(source_manifest),
        "sourceReport": display_path(copied_report),
        "runManifest": display_path(run_manifest),
        "promotedManifest": display_path(promoted_manifest_path),
        "validationReport": display_path(validation_out) if validation_out else None,
        "offlineChainValidationReport": display_path(offline_chain_validation_out) if offline_chain_validation_out else None,
        "validation": {
            "status": validation["status"],
            "failedChecks": validation["failedChecks"],
            "outputs": validation["outputs"],
            "playback": validation["playback"],
            "captions": validation["captions"],
        },
        "offlineChainValidation": {
            "status": offline_chain_validation["status"],
            "failedChecks": offline_chain_validation.get("failedChecks", []),
            "offlineRoute": offline_chain_validation.get("offlineRoute"),
            "translation": offline_chain_validation.get("translation"),
        },
        "copiedOutputs": [
            {"localPath": item["localPath"], "uri": display_path(Path(item["gcsUri"]))}
            for item in copied_outputs
        ],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def copy_manifest_outputs(manifest: dict[str, Any], *, source_run_root: Path, out_root: Path) -> list[dict[str, str]]:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise SystemExit("source manifest must include outputs")
    copied: list[dict[str, str]] = []
    for item in outputs:
        if not isinstance(item, dict):
            continue
        local_path = str(item.get("localPath") or "")
        if not local_path:
            continue
        source = source_run_root / local_path
        destination = out_root / local_path
        if not source.is_file():
            raise SystemExit(f"source output is missing: {display_path(source)}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append({"localPath": local_path, "gcsUri": str(destination.resolve())})
    if not copied:
        raise SystemExit("source manifest had no copyable outputs")
    return copied


def copy_source_report(*, source_run_root: Path, out_root: Path) -> Path | None:
    source = source_run_root / "artifacts" / "report.json"
    if not source.is_file():
        return None
    destination = out_root / "artifacts" / "report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def route_metadata_for_manifest(manifest: dict[str, Any], report_path: Path | None, out_root: Path) -> dict[str, Any]:
    report = read_json(report_path) if report_path and report_path.is_file() else {}
    playback = read_playback_from_manifest(manifest, out_root)
    route = report.get("offline_route") if isinstance(report.get("offline_route"), dict) else {}
    source_kind = (
        nested(report, "caption_source", "kind")
        or route.get("selectedSourceKind")
        or playback.get("offlineSourceKind")
        or manifest.get("offlineSourceKind")
    )
    metadata: dict[str, Any] = {}
    if source_kind:
        metadata["offlineSourceKind"] = source_kind
    if route:
        metadata["offlineRoute"] = {
            "strategy": route.get("strategy"),
            "decision": route.get("decision"),
            "selectedSourceKind": route.get("selectedSourceKind"),
            "asrFallbackRequired": route.get("asrFallbackRequired"),
            "audioExtractionAttempted": route.get("audioExtractionAttempted"),
            "fallbackReason": route.get("fallbackReason"),
        }
    elif isinstance(manifest.get("offlineRoute"), dict):
        metadata["offlineRoute"] = manifest["offlineRoute"]
    elif isinstance(playback.get("offlineRoute"), dict):
        metadata["offlineRoute"] = playback["offlineRoute"]
    return metadata


def read_playback_from_manifest(manifest: dict[str, Any], out_root: Path) -> dict[str, Any]:
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), list) else []
    playback_output = next(
        (
            item
            for item in outputs
            if isinstance(item, dict) and item.get("localPath") == "web/playback-simulation.generated.js"
        ),
        None,
    )
    if not playback_output:
        return {}
    path = out_root / str(playback_output.get("localPath"))
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        return parse_playback_js(text)
    except SystemExit:
        return {}


def nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def build_offline_chain_validation(
    *,
    source_report: Path | None,
    out_root: Path,
    manifest_path: Path,
    validation_out: Path | None,
) -> dict[str, Any]:
    if not source_report:
        report = {
            "schemaVersion": 1,
            "status": "skipped",
            "reason": "source artifacts/report.json was not available",
            "failedChecks": [],
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
        }
        if validation_out:
            write_json(validation_out, report)
        return report

    playback_path = out_root / "web" / "playback-simulation.generated.js"
    zh_vtt_path = out_root / "artifacts" / "sermon.zh.live-aligned.vtt"
    zh_srt_path = out_root / "artifacts" / "sermon.zh.live-aligned.srt"
    report_text = source_report.read_text(encoding="utf-8")
    playback_text = playback_path.read_text(encoding="utf-8")
    zh_vtt_text = zh_vtt_path.read_text(encoding="utf-8")
    zh_srt_text = zh_srt_path.read_text(encoding="utf-8")
    manifest_text = manifest_path.read_text(encoding="utf-8")
    validation = validate_offline_chain(
        report=json.loads(report_text),
        report_text=report_text,
        report_uri=display_path(source_report) or str(source_report),
        playback=parse_playback_js(playback_text),
        playback_text=playback_text,
        playback_uri=display_path(playback_path) or str(playback_path),
        zh_vtt_text=zh_vtt_text,
        zh_vtt_uri=display_path(zh_vtt_path) or str(zh_vtt_path),
        zh_srt_text=zh_srt_text,
        zh_srt_uri=display_path(zh_srt_path) or str(zh_srt_path),
        manifest=json.loads(manifest_text),
        manifest_text=manifest_text,
        manifest_uri=display_path(manifest_path) or str(manifest_path),
    )
    if validation_out:
        write_json(validation_out, validation)
    return validation


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{display_path(path)} must contain a JSON object")
    return data


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def display_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
