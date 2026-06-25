#!/usr/bin/env python3
"""Generate traceable sermon notes and quote candidates with OpenAI."""

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
NOTE_SLICE_TARGET_MS = 5 * 60 * 1000
NOTE_SLICE_MAX_CHARS = 900
NOTE_SLICE_MIN_CHARS = 120
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_REASONING_EFFORT = "medium"


def main() -> int:
    args = parse_args()
    validate_secret_resource_name(args.api_key_secret)
    simulation = read_simulation(args.input)
    slices = build_note_slices(simulation.get("segments") or [], max_slices=args.max_slices)
    if not slices:
        raise SystemExit("No caption text available for note generation.")

    api_key = access_secret(args.api_key_secret)
    request_payload = build_openai_request(
        slices=slices,
        simulation=simulation,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
    )
    raw_response = request_openai_notes(request_payload, api_key=api_key)
    insights = normalize_insights(
        parse_json_object(extract_response_text(raw_response)),
        slices=slices,
        simulation=simulation,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        api_key_secret=args.api_key_secret,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.model_output_dir.mkdir(parents=True, exist_ok=True)
    insights_path = args.out_dir / "openai-notes.json"
    model_output_path = args.model_output_dir / "openai-notes-output.jsonl"
    insights_path.write_text(json.dumps(insights, ensure_ascii=False, indent=2), encoding="utf-8")
    write_jsonl(model_output_path, [{"request": public_request_trace(request_payload), "response": raw_response}])

    uploads: list[dict[str, str]] = []
    if args.gcs_bucket:
        uploads = publish_named_files_to_gcs(
            files=[
                ("insights/openai-notes.json", insights_path),
                ("model-output/openai-notes-output.jsonl", model_output_path),
            ],
            bucket=args.gcs_bucket,
            prefix=args.gcs_prefix,
            dry_run=args.gcs_dry_run,
        )

    if args.manifest:
        manifest_upload = update_run_manifest(
            manifest_path=args.manifest,
            uploads=uploads,
            insights=insights,
            gcs_bucket=args.gcs_bucket,
            gcs_prefix=args.gcs_prefix,
            dry_run=args.gcs_dry_run,
        )
        if manifest_upload:
            uploads.append(manifest_upload)

    summary = {
        "status": "ok",
        "model": args.model,
        "reasoningEffort": args.reasoning_effort,
        "sliceCount": len(slices),
        "out": str(insights_path),
        "modelOutputJsonl": str(model_output_path),
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "uploads": uploads,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("web/playback-simulation.generated.js"),
        help="Input JS file defining window.SERMON_PLAYBACK_SIMULATION.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("artifacts/insights"),
        help="Directory for generated note and quote JSON.",
    )
    parser.add_argument(
        "--model-output-dir",
        type=Path,
        default=Path("artifacts/model-output"),
        help="Directory for raw model output traces.",
    )
    parser.add_argument("--manifest", type=Path, help="Optional run cloud-manifest.json to update.")
    parser.add_argument(
        "--api-key-secret",
        required=True,
        help="Google Secret Manager resource name for the OpenAI key.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT, choices=["minimal", "low", "medium", "high"])
    parser.add_argument("--max-slices", type=int, default=0, help="Maximum note slices to send. Use 0 for all.")
    parser.add_argument("--gcs-bucket", help="Optional GCS bucket for generated insight artifacts.")
    parser.add_argument("--gcs-prefix", default="poc/openai-notes", help="GCS object prefix for generated artifacts.")
    parser.add_argument("--gcs-dry-run", action="store_true")
    args = parser.parse_args()
    args.input = resolve_repo_path(args.input)
    args.out_dir = resolve_repo_path(args.out_dir)
    args.model_output_dir = resolve_repo_path(args.model_output_dir)
    args.manifest = resolve_repo_path(args.manifest) if args.manifest else None
    args.max_slices = None if args.max_slices == 0 else args.max_slices
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


def build_note_slices(segments: list[dict[str, Any]], max_slices: int | None = None) -> list[dict[str, Any]]:
    slices: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for item in note_segment_parts(segments):
        if current is None:
            current = create_note_slice(item)
            continue
        combined_chars = current["charCount"] + len(item["text"]) + 1
        combined_duration = max(current["endMs"], item["endMs"]) - current["startMs"]
        should_split = (
            combined_chars > NOTE_SLICE_MAX_CHARS
            or combined_duration > NOTE_SLICE_TARGET_MS
            and current["charCount"] >= NOTE_SLICE_MIN_CHARS
        )
        if should_split:
            slices.append(finalize_note_slice(current, len(slices)))
            current = create_note_slice(item)
            if max_slices and len(slices) >= max_slices:
                return slices[:max_slices]
            continue
        add_item_to_note_slice(current, item)
    if current:
        slices.append(finalize_note_slice(current, len(slices)))
    return slices[:max_slices] if max_slices else slices


def note_segment_parts(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    sorted_segments = sorted(segments, key=lambda segment: segment_start(segment))
    for index, segment in enumerate(sorted_segments):
        text = note_text_for_segment(segment)
        if not text:
            continue
        for part_index, part in enumerate(split_note_text(text)):
            parts.append(
                {
                    "segment": segment,
                    "index": index,
                    "partIndex": part_index,
                    "text": part,
                    "startMs": segment_start(segment),
                    "endMs": segment_end(segment),
                }
            )
    return parts


def create_note_slice(item: dict[str, Any]) -> dict[str, Any]:
    note_slice = {
        "startMs": item["startMs"],
        "endMs": item["endMs"],
        "texts": [],
        "segmentIds": [],
        "refs": [],
        "charCount": 0,
    }
    add_item_to_note_slice(note_slice, item)
    return note_slice


def add_item_to_note_slice(note_slice: dict[str, Any], item: dict[str, Any]) -> None:
    note_slice["startMs"] = min(note_slice["startMs"], item["startMs"])
    note_slice["endMs"] = max(note_slice["endMs"], item["endMs"])
    note_slice["texts"].append(item["text"])
    note_slice["charCount"] += len(item["text"])
    segment = item["segment"]
    segment_id = str(segment.get("id") or f"segment-{item['index']}")
    if segment_id not in note_slice["segmentIds"]:
        note_slice["segmentIds"].append(segment_id)
    for ref in segment_refs(segment):
        if ref and ref not in note_slice["refs"]:
            note_slice["refs"].append(ref)


def finalize_note_slice(note_slice: dict[str, Any], index: int) -> dict[str, Any]:
    text = compact_text(" ".join(note_slice["texts"]))
    return {
        "index": index + 1,
        "startMs": note_slice["startMs"],
        "endMs": note_slice["endMs"],
        "text": text,
        "charCount": len(text),
        "segmentIds": note_slice["segmentIds"],
        "refs": note_slice["refs"],
    }


def note_text_for_segment(segment: dict[str, Any]) -> str:
    return compact_text(segment.get("zh") or segment.get("draft") or segment.get("text") or segment.get("en") or "")


def split_note_text(text: str) -> list[str]:
    chunks: list[str] = []
    remaining = compact_text(text)
    while len(remaining) > NOTE_SLICE_MAX_CHARS:
        break_at = note_text_break_index(remaining, NOTE_SLICE_MAX_CHARS)
        chunks.append(remaining[:break_at].strip())
        remaining = remaining[break_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def note_text_break_index(text: str, limit: int) -> int:
    floor = max(NOTE_SLICE_MIN_CHARS, limit - 240)
    for index in range(min(limit, len(text)), floor, -1):
        if text[index - 1] in "。！？；，,":
            return index
    return min(limit, len(text))


def segment_start(segment: dict[str, Any]) -> int:
    return max(0, int(segment.get("startMs") or 0) + int(segment.get("offsetMs") or 0))


def segment_end(segment: dict[str, Any]) -> int:
    duration = max(300, int(segment.get("endMs") or 0) - int(segment.get("startMs") or 0))
    return segment_start(segment) + duration


def segment_refs(segment: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    raw_refs = segment.get("refs") if isinstance(segment.get("refs"), list) else []
    for ref in raw_refs:
        if isinstance(ref, dict):
            label = str(ref.get("title") or ref.get("canonicalRef") or "").strip()
        else:
            label = str(ref or "").strip()
        if label:
            refs.append(label)
    ref = str(segment.get("ref") or "").strip()
    if ref:
        refs.append(ref)
    return refs


def compact_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def access_secret(resource_name: str) -> str:
    match = SECRET_RESOURCE_RE.fullmatch(resource_name)
    if not match:
        raise SystemExit("Invalid Secret Manager resource name.")
    proc = subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            match.group("version") or "latest",
            "--secret",
            match.group("secret"),
            "--project",
            match.group("project"),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    value = proc.stdout.strip()
    if not value:
        raise SystemExit(f"Secret {resource_name} returned an empty value.")
    return value


def build_openai_request(
    slices: list[dict[str, Any]],
    simulation: dict[str, Any],
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    return {
        "model": model,
        "reasoning": {"effort": reasoning_effort},
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "You create traceable Simplified Chinese sermon notes for church review. "
                            "Use only the supplied caption slices. Do not invent quotes, Bible references, or facts. "
                            "Every quote must cite a sourceSliceIndex and sourceSegmentId."
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Return strict JSON with this shape: "
                            "{\"summaryZh\":\"...\",\"outlineZh\":[{\"title\":\"...\",\"points\":[\"...\"]}],"
                            "\"scriptureRefs\":[\"...\"],\"applicationQuestionsZh\":[\"...\"],"
                            "\"quotes\":[{\"textZh\":\"...\",\"sourceSliceIndex\":1,\"sourceSegmentId\":\"...\","
                            "\"sourceTextZh\":\"...\",\"startMs\":0,\"endMs\":0}]}.\n"
                            "Generate 3-6 outline sections, 3-5 application questions, and 5-8 quote candidates when sourceable.\n"
                            f"Sermon title: {simulation.get('sermonTitle') or simulation.get('title') or ''}\n"
                            f"Slices:\n{json.dumps(slices, ensure_ascii=False)}"
                        ),
                    }
                ],
            },
        ],
        "text": {"format": {"type": "json_object"}},
    }


def request_openai_notes(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )
    if response.status_code >= 400:
        raise SystemExit(f"OpenAI notes request failed with HTTP {response.status_code}: {safe_error_message(response)}")
    return response.json()


def safe_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:400]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or "unknown error")
    return str(data)[:400]


def extract_response_text(response: dict[str, Any]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict):
                text = content.get("text") or content.get("output_text")
                if isinstance(text, str) and text.strip():
                    return text
    raise SystemExit("OpenAI notes response did not include output text.")


def parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Could not parse OpenAI notes JSON response: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("OpenAI notes response JSON was not an object.")
    return parsed


def normalize_insights(
    data: dict[str, Any],
    slices: list[dict[str, Any]],
    simulation: dict[str, Any],
    model: str,
    reasoning_effort: str,
    api_key_secret: str,
) -> dict[str, Any]:
    quotes = normalize_quotes(data.get("quotes"), slices)
    return {
        "schemaVersion": 1,
        "status": "ready",
        "generatedFrom": "openai-notes",
        "provider": "openai",
        "model": model,
        "reasoningEffort": reasoning_effort,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "serverSideSecretConfigured": bool(api_key_secret),
        "sermonTitle": simulation.get("sermonTitle"),
        "sourceTranslationStatus": simulation.get("translationStatus"),
        "sourceSegmentCount": len(simulation.get("segments") or []),
        "sliceCount": len(slices),
        "slices": summarize_slices(slices),
        "summaryZh": compact_text(data.get("summaryZh") or data.get("summary_zh") or data.get("summary") or ""),
        "outlineZh": normalize_outline(data.get("outlineZh") or data.get("outline_zh") or data.get("outline")),
        "scriptureRefs": normalize_string_list(data.get("scriptureRefs") or data.get("scripture_refs")),
        "applicationQuestionsZh": normalize_string_list(
            data.get("applicationQuestionsZh") or data.get("application_questions_zh") or data.get("applicationQuestions")
        ),
        "quotes": quotes,
        "traceability": {
            "allQuotesHaveSource": all(bool(item.get("sourceSegmentId")) for item in quotes),
            "quoteCount": len(quotes),
        },
    }


def summarize_slices(slices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "index": item["index"],
            "startMs": item["startMs"],
            "endMs": item["endMs"],
            "charCount": item["charCount"],
            "segmentIds": item["segmentIds"],
            "refs": item["refs"],
        }
        for item in slices
    ]


def normalize_outline(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    outline = []
    for item in value:
        if isinstance(item, dict):
            title = compact_text(item.get("title") or item.get("heading") or "")
            points = normalize_string_list(item.get("points") or item.get("children"))
        else:
            title = compact_text(item)
            points = []
        if title or points:
            outline.append({"title": title, "points": points})
    return outline


def normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [compact_text(item) for item in value if compact_text(item)]


def normalize_quotes(value: Any, slices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    by_index = {item["index"]: item for item in slices}
    quotes = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = compact_text(item.get("textZh") or item.get("text_zh") or item.get("quote") or item.get("text"))
        source_slice_index = int(item.get("sourceSliceIndex") or item.get("source_slice_index") or 0)
        source_slice = by_index.get(source_slice_index)
        source_segment_id = compact_text(item.get("sourceSegmentId") or item.get("source_segment_id"))
        if not source_segment_id and source_slice and source_slice["segmentIds"]:
            source_segment_id = source_slice["segmentIds"][0]
        if not text or not source_segment_id:
            continue
        quotes.append(
            {
                "textZh": text,
                "sourceSliceIndex": source_slice_index or None,
                "sourceSegmentId": source_segment_id,
                "sourceTextZh": compact_text(item.get("sourceTextZh") or item.get("source_text_zh")),
                "startMs": int(item.get("startMs") or item.get("start_ms") or (source_slice or {}).get("startMs") or 0),
                "endMs": int(item.get("endMs") or item.get("end_ms") or (source_slice or {}).get("endMs") or 0),
            }
        )
    return quotes


def public_request_trace(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": payload.get("model"),
        "reasoning": payload.get("reasoning"),
        "input": payload.get("input"),
        "text": payload.get("text"),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def publish_named_files_to_gcs(
    files: list[tuple[str, Path]],
    bucket: str,
    prefix: str,
    dry_run: bool = False,
) -> list[dict[str, str]]:
    uploads = []
    clean_bucket = normalize_gcs_bucket(bucket)
    clean_prefix = normalize_gcs_prefix(prefix)
    for local_path, file_path in files:
        object_name = f"{clean_prefix}/{local_path}" if clean_prefix else local_path
        gcs_uri = f"gs://{clean_bucket}/{object_name}"
        command = ["gcloud", "storage", "cp", str(file_path), gcs_uri]
        print("$ " + " ".join(command))
        if not dry_run:
            subprocess.run(command, cwd=REPO_ROOT, check=True)
        uploads.append({"localPath": local_path, "gcsUri": gcs_uri})
    return uploads


def update_run_manifest(
    manifest_path: Path,
    uploads: list[dict[str, str]],
    insights: dict[str, Any],
    gcs_bucket: str | None,
    gcs_prefix: str,
    dry_run: bool = False,
) -> dict[str, str] | None:
    if not manifest_path.exists():
        raise SystemExit(f"Manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("apiKeyMaterialIncluded") is True or manifest.get("secretResourceNamesIncluded") is True:
        raise SystemExit("Refusing to update manifest that contains secret flags.")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        outputs = []
    by_path = {str(item.get("localPath")): item for item in outputs if isinstance(item, dict)}
    for upload in uploads:
        by_path[str(upload["localPath"])] = dict(upload)
    manifest["outputs"] = list(by_path.values())
    manifest["insightsStatus"] = insights.get("status", "ready")
    manifest["insightsProvider"] = {
        "provider": "openai",
        "model": insights["model"],
        "reasoningEffort": insights["reasoningEffort"],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }
    manifest["apiKeyMaterialIncluded"] = False
    manifest["secretResourceNamesIncluded"] = False
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2)
    if "apiKeySecret" in rendered or "/secrets/" in rendered:
        raise SystemExit("Refusing to write manifest with secret references.")
    manifest_path.write_text(rendered, encoding="utf-8")
    if not gcs_bucket:
        return None
    return publish_named_files_to_gcs(
        files=[("artifacts/cloud-manifest.json", manifest_path)],
        bucket=gcs_bucket,
        prefix=gcs_prefix,
        dry_run=dry_run,
    )[0]


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
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode)
