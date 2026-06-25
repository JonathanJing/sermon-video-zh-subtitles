#!/usr/bin/env python3
"""Translate playback simulation segments with OpenAI.

This E2E helper reads the browser playback simulation generated from a live
archive, translates English segments to Chinese through OpenAI, and writes a new
simulation artifact. API key material is read at runtime from Google Secret
Manager and is never written to generated files.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
JS_PREFIX = "window.SERMON_PLAYBACK_SIMULATION = "
SECRET_RESOURCE_RE = re.compile(
    r"^projects/(?P<project>[^/\s]+)/secrets/(?P<secret>[^/\s]+)(?:/versions/(?P<version>[^/\s]+))?$"
)


def main() -> int:
    args = parse_args()
    validate_secret_resource_name(args.api_key_secret)
    simulation = read_simulation(args.input)
    if args.sanitize_only:
        sanitized = sanitize_public_simulation(simulation)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(render_js(sanitized), encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": "ok",
                    "mode": "sanitize-only",
                    "out": str(args.out),
                    "apiKeyMaterialIncluded": False,
                    "secretResourceNamesIncluded": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    candidates = translation_candidates(simulation, args.max_segments)
    if not candidates:
        raise SystemExit("No English segments need translation.")

    api_key = access_secret(args.api_key_secret)
    translations: list[dict[str, Any]] = []
    for batch in batched(candidates, args.batch_size):
        translations.extend(translate_batch(batch, api_key=api_key, model=args.model))

    translated = apply_translations(
        simulation=simulation,
        translations=translations,
        model=args.model,
        api_key_secret=args.api_key_secret,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_js(translated), encoding="utf-8")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = args.out_dir / "openai-translation-output.jsonl"
    write_jsonl(jsonl_path, translations)
    report_path = args.out_dir / "openai-translation-report.json"
    report = build_report(
        original=simulation,
        translated=translated,
        translations=translations,
        model=args.model,
        api_key_secret=args.api_key_secret,
        jsonl_path=jsonl_path,
        out_path=args.out,
    )
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    uploads = []
    if args.gcs_bucket:
        uploads = publish_files_to_gcs(
            files=[args.out, jsonl_path, report_path],
            bucket=args.gcs_bucket,
            prefix=args.gcs_prefix,
            dry_run=args.gcs_dry_run,
        )

    summary = {
        "status": "ok",
        "model": args.model,
        "translatedSegments": report["translatedSegments"],
        "totalSegments": report["totalSegments"],
        "out": str(args.out),
        "report": str(report_path),
        "jsonl": str(jsonl_path),
        "apiKeyMaterialIncluded": False,
        "uploads": uploads,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Translate web playback simulation segments with OpenAI."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("web/playback-simulation.generated.js"),
        help="Input JS file defining window.SERMON_PLAYBACK_SIMULATION.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("web/playback-simulation.generated.js"),
        help="Output JS file. Defaults to replacing the browser simulation artifact.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("artifacts/openai-translation-e2e"),
        help="Directory for translation report and JSONL model output.",
    )
    parser.add_argument(
        "--api-key-secret",
        required=True,
        help="Google Secret Manager resource name for the OpenAI key.",
    )
    parser.add_argument(
        "--model",
        default="gpt-5.5-mini",
        help="OpenAI chat-completions model used for translation.",
    )
    parser.add_argument(
        "--max-segments",
        type=int,
        default=80,
        help="Maximum candidate segments to translate. Use 0 for all candidates.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Segments per OpenAI request.",
    )
    parser.add_argument(
        "--gcs-bucket",
        help="Optional GCS bucket for generated translated artifacts.",
    )
    parser.add_argument(
        "--gcs-prefix",
        default="poc/openai-translation-e2e",
        help="GCS object prefix for translated artifacts.",
    )
    parser.add_argument("--gcs-dry-run", action="store_true")
    parser.add_argument(
        "--sanitize-only",
        action="store_true",
        help="Only remove server-side secret references from a playback JS file; do not call OpenAI.",
    )
    args = parser.parse_args()
    args.input = resolve_repo_path(args.input)
    args.out = resolve_repo_path(args.out)
    args.out_dir = resolve_repo_path(args.out_dir)
    if args.max_segments == 0:
        args.max_segments = None
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")
    return args


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def validate_secret_resource_name(value: str) -> None:
    if not SECRET_RESOURCE_RE.fullmatch(value):
        raise SystemExit(
            "--api-key-secret must be a Google Secret Manager resource name like "
            "projects/PROJECT_ID/secrets/openai-api-key/versions/latest. Do not pass raw API key material."
        )


def read_simulation(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith(JS_PREFIX):
        raise SystemExit(f"{path} does not look like a playback simulation JS file.")
    payload = text.removeprefix(JS_PREFIX).strip()
    if payload.endswith(";"):
        payload = payload[:-1]
    return json.loads(payload)


def render_js(simulation: dict[str, Any]) -> str:
    return JS_PREFIX + json.dumps(simulation, ensure_ascii=False, indent=2) + ";\n"


def translation_candidates(
    simulation: dict[str, Any],
    max_segments: int | None,
) -> list[dict[str, str]]:
    candidates = []
    for segment in simulation.get("segments") or []:
        source = str(segment.get("en") or "").strip()
        if not source:
            continue
        if segment.get("translationStatus") == "ready" and not str(segment.get("zh", "")).startswith("AI 中文待生成"):
            continue
        candidates.append(
            {
                "id": str(segment.get("id")),
                "en": source,
                "ref": str(segment.get("ref") or ""),
                "note": str(segment.get("note") or ""),
            }
        )
    return candidates[:max_segments] if max_segments else candidates


def access_secret(resource_name: str) -> str:
    match = SECRET_RESOURCE_RE.fullmatch(resource_name)
    if not match:
        raise SystemExit("Invalid Secret Manager resource name.")
    project = match.group("project")
    secret = match.group("secret")
    version = match.group("version") or "latest"
    proc = subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            version,
            "--secret",
            secret,
            "--project",
            project,
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    value = proc.stdout.strip()
    if not value:
        raise SystemExit(f"Secret {resource_name} returned an empty value.")
    return value


def batched(items: list[dict[str, str]], size: int) -> list[list[dict[str, str]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def translate_batch(batch: list[dict[str, str]], api_key: str, model: str) -> list[dict[str, Any]]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You translate English Christian sermon captions into Simplified Chinese for live church attendees. "
                    "Prioritize readability, low latency, faithful meaning, and accurate Bible/person/theology terms. "
                    "Do not add commentary. Return strict JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Translate each segment. Preserve ids. Return exactly this JSON shape: "
                    "{\"segments\":[{\"id\":\"...\",\"zh\":\"...\",\"draft\":\"...\",\"ref\":\"...\",\"note\":\"...\"}]}.\n"
                    "Use natural Chinese punctuation. Keep Bible references in English if explicit, e.g. Numbers 16.\n"
                    f"Segments:\n{json.dumps(batch, ensure_ascii=False)}"
                ),
            },
        ],
        "response_format": {"type": "json_object"},
    }
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=90,
    )
    if response.status_code >= 400:
        message = safe_error_message(response)
        raise SystemExit(f"OpenAI request failed with HTTP {response.status_code}: {message}")
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    parsed = parse_json_object(content)
    segments = parsed.get("segments")
    if not isinstance(segments, list):
        raise SystemExit("OpenAI response did not include a segments array.")
    return [normalize_translation(item) for item in segments]


def safe_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:400]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or "unknown error")
    return str(data)[:400]


def parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Could not parse OpenAI JSON response: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("OpenAI response JSON was not an object.")
    return parsed


def normalize_translation(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise SystemExit("OpenAI segment item was not an object.")
    segment_id = str(item.get("id") or item.get("segment_id") or item.get("segmentId") or "").strip()
    zh = str(
        item.get("zh")
        or item.get("zh_text")
        or item.get("zhText")
        or item.get("translation")
        or item.get("chinese")
        or item.get("text")
        or ""
    ).strip()
    if not segment_id or not zh:
        raise SystemExit(
            "OpenAI segment item missing id or Chinese text. "
            f"Received keys: {', '.join(sorted(str(key) for key in item.keys()))}"
        )
    return {
        "id": segment_id,
        "zh": zh,
        "draft": str(item.get("draft") or zh).strip(),
        "ref": str(item.get("ref") or "").strip(),
        "note": str(item.get("note") or "OpenAI translation E2E output.").strip(),
    }


def apply_translations(
    simulation: dict[str, Any],
    translations: list[dict[str, Any]],
    model: str,
    api_key_secret: str,
) -> dict[str, Any]:
    by_id = {item["id"]: item for item in translations}
    translated_count = 0
    for segment in simulation.get("segments") or []:
        item = by_id.get(str(segment.get("id")))
        if not item:
            continue
        segment["zh"] = item["zh"]
        segment["draft"] = item["draft"]
        if item["ref"]:
            segment["ref"] = item["ref"]
        segment["note"] = item["note"]
        segment["confidence"] = max(int(segment.get("confidence") or 0), 84)
        segment["translationStatus"] = "ready"
        translated_count += 1

    simulation["generatedFrom"] = "openai-translation-e2e"
    simulation["translationStatus"] = "ready" if translated_count else simulation.get("translationStatus")
    simulation["translationProvider"] = {
        "provider": "openai",
        "model": model,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "translatedSegments": translated_count,
    }
    return sanitize_public_simulation(simulation)


def sanitize_public_simulation(simulation: dict[str, Any]) -> dict[str, Any]:
    """Remove server-side secret references before writing browser JS."""
    secrets = simulation.get("secrets")
    if isinstance(secrets, dict):
        secrets.pop("apiKeySecret", None)
        secrets["apiKeyMaterialIncluded"] = False
        secrets["secretResourceNamesIncluded"] = False

    provider = simulation.get("translationProvider")
    if isinstance(provider, dict):
        provider.pop("apiKeySecret", None)
        provider["apiKeyMaterialIncluded"] = False
        provider["secretResourceNamesIncluded"] = False
    return simulation


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def build_report(
    original: dict[str, Any],
    translated: dict[str, Any],
    translations: list[dict[str, Any]],
    model: str,
    api_key_secret: str,
    jsonl_path: Path,
    out_path: Path,
) -> dict[str, Any]:
    total_segments = len(translated.get("segments") or [])
    translated_ids = {item["id"] for item in translations}
    return {
        "schemaVersion": 1,
        "status": "ok",
        "model": model,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "serverSideSecretConfigured": bool(api_key_secret),
        "live": translated.get("live"),
        "sermonCandidate": translated.get("sermonCandidate"),
        "sermonStart": translated.get("sermonStart"),
        "sourceTranslationStatus": original.get("translationStatus"),
        "translationStatus": translated.get("translationStatus"),
        "totalSegments": total_segments,
        "translatedSegments": len(translated_ids),
        "output": safe_display_path(out_path),
        "modelOutputJsonl": safe_display_path(jsonl_path),
    }


def safe_display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.name


def publish_files_to_gcs(
    files: list[Path],
    bucket: str,
    prefix: str,
    dry_run: bool = False,
) -> list[dict[str, str]]:
    uploads = []
    clean_bucket = normalize_gcs_bucket(bucket)
    clean_prefix = normalize_gcs_prefix(prefix)
    for file_path in files:
        rel = safe_display_path(file_path)
        gcs_uri = f"gs://{clean_bucket}/{clean_prefix}/{rel}" if clean_prefix else f"gs://{clean_bucket}/{rel}"
        command = ["gcloud", "storage", "cp", str(file_path), gcs_uri]
        print("$ " + " ".join(command))
        if not dry_run:
            subprocess.run(command, cwd=REPO_ROOT, check=True)
        uploads.append({"localPath": rel, "gcsUri": gcs_uri})
    return uploads


def normalize_gcs_bucket(bucket: str) -> str:
    clean = bucket.strip()
    if clean.startswith("gs://"):
        clean = clean[5:]
    clean = clean.strip("/")
    if not clean or "/" in clean:
        raise SystemExit("--gcs-bucket must be a bucket name, not a path.")
    return clean


def normalize_gcs_prefix(prefix: str) -> str:
    clean = prefix.strip().strip("/")
    if "\\" in clean:
        raise SystemExit("--gcs-prefix must use forward slashes.")
    if any(part in {".", ".."} for part in clean.split("/") if part):
        raise SystemExit("--gcs-prefix cannot contain . or .. path segments.")
    return clean


if __name__ == "__main__":
    raise SystemExit(main())
