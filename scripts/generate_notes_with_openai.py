#!/usr/bin/env python3
"""Generate traceable sermon-interpretation content and an optional PDF."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.cloud import access_secret as cloud_access_secret
from backend.cloud import upload_file_to_gcs
from scripts import review_prompts
from scripts.render_sermon_interpretation_pdf import render_interpretation_pdf

JS_PREFIX = "window.SERMON_PLAYBACK_SIMULATION = "
SECRET_RESOURCE_RE = re.compile(
    r"^projects/(?P<project>[^/\s]+)/secrets/(?P<secret>[^/\s]+)(?:/versions/(?P<version>[^/\s]+))?$"
)
NOTE_SLICE_TARGET_MS = 5 * 60 * 1000
NOTE_SLICE_MAX_CHARS = 900
NOTE_SLICE_MIN_CHARS = 120
DEFAULT_MODEL = "gpt-5.6"
DEFAULT_REASONING_EFFORT = "high"
SRT_TIMESTAMP_RE = re.compile(
    r"^\s*(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{3})"
)


def main() -> int:
    args = parse_args()
    if args.api_key_secret:
        validate_secret_resource_name(args.api_key_secret)
    simulation = read_note_source(args)
    slices = build_note_slices(simulation.get("segments") or [], max_slices=args.max_slices)
    if not slices:
        raise SystemExit("No caption text available for note generation.")

    api_key = resolve_api_key(args.api_key_secret)
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

    companion_pdf = None
    companion_qa = None
    if args.pdf_out:
        companion_pdf = args.pdf_out
        companion_qa = args.pdf_qa_out or companion_pdf.with_suffix(".qa.json")
        qa = render_interpretation_pdf(insights, companion_pdf, font_path=args.font_path)
        companion_qa.parent.mkdir(parents=True, exist_ok=True)
        companion_qa.write_text(json.dumps(qa, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        if qa.get("status") != "pass":
            raise SystemExit(f"Sermon interpretation PDF QA did not pass; inspect {companion_qa}")

    uploads: list[dict[str, str]] = []
    if args.gcs_bucket:
        uploads = publish_named_files_to_gcs(
            files=[
                ("insights/openai-notes.json", insights_path),
                ("model-output/openai-notes-output.jsonl", model_output_path),
                *(
                    [
                        ("artifacts/sermon_interpretation_zh.pdf", companion_pdf),
                        ("artifacts/sermon_interpretation_zh.qa.json", companion_qa),
                    ]
                    if companion_pdf and companion_qa
                    else []
                ),
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
        "promptVersion": review_prompts.NOTES_PROMPT_VERSION,
        "sliceCount": len(slices),
        "out": str(insights_path),
        "interpretationPdf": str(companion_pdf) if companion_pdf else None,
        "interpretationQa": str(companion_qa) if companion_qa else None,
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
        "--srt-input",
        type=Path,
        help="Optional SRT caption file to use directly for note generation instead of playback simulation JS.",
    )
    parser.add_argument(
        "--srt-lang",
        default="zh",
        choices=["zh", "en"],
        help="Language of --srt-input captions. Chinese SRT text is used as zh; English SRT text is used as en.",
    )
    parser.add_argument(
        "--secondary-srt-input",
        type=Path,
        help="Optional aligned secondary-language SRT; normally English when --srt-lang=zh.",
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
    parser.add_argument("--api-key-secret", help="Optional Google Secret Manager resource name for the OpenAI key.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT, choices=["minimal", "low", "medium", "high"])
    parser.add_argument("--max-slices", type=int, default=0, help="Maximum note slices to send. Use 0 for all.")
    parser.add_argument("--gcs-bucket", help="Optional GCS bucket for generated insight artifacts.")
    parser.add_argument("--gcs-prefix", default="poc/openai-notes", help="GCS object prefix for generated artifacts.")
    parser.add_argument("--gcs-dry-run", action="store_true")
    parser.add_argument("--pdf-out", type=Path, help="Optional sermon interpretation PDF output path.")
    parser.add_argument("--pdf-qa-out", type=Path, help="Optional interpretation PDF QA JSON output path.")
    parser.add_argument("--font-path", type=Path, help="Optional CJK font for the interpretation PDF.")
    parser.add_argument("--sermon-title", help="Operator-confirmed sermon title.")
    parser.add_argument("--speaker", help="Operator-confirmed speaker name.")
    parser.add_argument("--sermon-date", help="Sunday slice date, YYYY-MM-DD.")
    parser.add_argument(
        "--source-label",
        default="本材料基于所选直播或归档版本整理；其他场次的具体措辞可能不同。",
        help="Visible source-scope statement printed in the interpretation PDF.",
    )
    args = parser.parse_args()
    args.input = resolve_repo_path(args.input)
    args.srt_input = resolve_repo_path(args.srt_input) if args.srt_input else None
    args.secondary_srt_input = resolve_repo_path(args.secondary_srt_input) if args.secondary_srt_input else None
    args.out_dir = resolve_repo_path(args.out_dir)
    args.model_output_dir = resolve_repo_path(args.model_output_dir)
    args.manifest = resolve_repo_path(args.manifest) if args.manifest else None
    args.pdf_out = resolve_repo_path(args.pdf_out) if args.pdf_out else None
    args.pdf_qa_out = resolve_repo_path(args.pdf_qa_out) if args.pdf_qa_out else None
    args.font_path = resolve_repo_path(args.font_path) if args.font_path else None
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


def read_note_source(args: argparse.Namespace) -> dict[str, Any]:
    if args.srt_input:
        simulation = read_srt_simulation(args.srt_input, lang=args.srt_lang)
        if args.secondary_srt_input:
            secondary_lang = "en" if args.srt_lang == "zh" else "zh"
            secondary = read_srt_simulation(args.secondary_srt_input, lang=secondary_lang)
            simulation["segments"] = merge_aligned_segments(
                simulation.get("segments") or [],
                secondary.get("segments") or [],
            )
    else:
        simulation = read_simulation(args.input)
    simulation["sermonTitle"] = args.sermon_title or simulation.get("sermonTitle")
    simulation["speaker"] = args.speaker or simulation.get("speaker")
    simulation["sermonDate"] = args.sermon_date or simulation.get("sermonDate")
    simulation["sourceLabel"] = args.source_label
    return simulation


def merge_aligned_segments(
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(primary) != len(secondary):
        raise SystemExit(
            f"Aligned SRT inputs must contain the same cue count: primary={len(primary)} secondary={len(secondary)}"
        )
    merged: list[dict[str, Any]] = []
    for index, (left, right) in enumerate(zip(primary, secondary, strict=True), start=1):
        if abs(int(left.get("startMs") or 0) - int(right.get("startMs") or 0)) > 1500:
            raise SystemExit(f"Aligned SRT cue {index} starts differ by more than 1.5 seconds")
        item = dict(left)
        if right.get("zh"):
            item["zh"] = right["zh"]
        if right.get("en"):
            item["en"] = right["en"]
        merged.append(item)
    return merged


def read_srt_simulation(path: Path, *, lang: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    segments = segments_from_srt(text, lang=lang)
    return {
        "schemaVersion": 2,
        "artifactType": "sermon_interpretation",
        "sermonTitle": path.stem,
        "translationStatus": "ready" if lang == "zh" else "source",
        "sourceCaptionFormat": "srt",
        "sourceCaptionPath": safe_display_path(path),
        "sourceLanguage": lang,
        "segments": segments,
    }


def segments_from_srt(text: str, *, lang: str) -> list[dict[str, Any]]:
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n").strip())
    segments: list[dict[str, Any]] = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        timestamp_index = next((index for index, line in enumerate(lines) if SRT_TIMESTAMP_RE.match(line)), -1)
        if timestamp_index < 0:
            continue
        match = SRT_TIMESTAMP_RE.match(lines[timestamp_index])
        if not match:
            continue
        caption_text = clean_srt_caption_text(" ".join(lines[timestamp_index + 1 :]))
        if not caption_text:
            continue
        segment = {
            "id": f"srt-{len(segments) + 1:04d}",
            "startMs": parse_srt_timestamp(match.group("start")),
            "endMs": parse_srt_timestamp(match.group("end")),
            "source": "srt",
        }
        if lang == "en":
            segment["en"] = caption_text
        else:
            segment["zh"] = caption_text
            segment["translationStatus"] = "ready"
        segments.append(segment)
    return segments


def parse_srt_timestamp(value: str) -> int:
    hours, minutes, rest = value.replace(",", ".").split(":")
    seconds, millis = rest.split(".")
    return (
        int(hours) * 60 * 60 * 1000
        + int(minutes) * 60 * 1000
        + int(seconds) * 1000
        + int(millis)
    )


def clean_srt_caption_text(text: str) -> str:
    text = re.sub(r"</?[^>]+>", "", text)
    text = re.sub(r"\{\\[^}]+\}", "", text)
    return compact_text(text)


def safe_display_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


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
        "segmentEvidence": [],
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
        note_slice["segmentEvidence"].append(
            {
                "id": segment_id,
                "startMs": segment_start(segment),
                "endMs": segment_end(segment),
                "textZh": compact_text(segment.get("zh") or segment.get("draft") or segment.get("text") or ""),
                "textEn": compact_text(segment.get("en") or ""),
            }
        )
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
        "segmentEvidence": note_slice["segmentEvidence"],
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
    try:
        return cloud_access_secret(resource_name)
    except RuntimeError as exc:
        raise SystemExit(str(exc))


def resolve_api_key(resource_name: str | None) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        return api_key
    if resource_name:
        return access_secret(resource_name)
    raise SystemExit("OPENAI_API_KEY is not set and --api-key-secret was not provided.")


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
                        "text": review_prompts.NOTES_SYSTEM_PROMPT,
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
                            "{\"centralMessageZh\":\"...\",\"centralMessageSourceSliceIndexes\":[1],"
                            "\"summaryZh\":\"...\",\"summarySourceSliceIndexes\":[1,2],"
                            "\"outlineZh\":[{\"title\":\"...\",\"points\":[\"...\"],\"sourceSliceIndexes\":[1]}],"
                            "\"scriptureRefs\":[\"...\"],"
                            "\"scriptureContextZh\":[{\"reference\":\"...\",\"explanation\":\"...\","
                            "\"sourceSliceIndexes\":[1]}],"
                            "\"theologicalInsightsZh\":[{\"title\":\"...\",\"explanation\":\"...\","
                            "\"sourceSliceIndexes\":[1]}],"
                            "\"illustrationsZh\":[{\"title\":\"...\",\"function\":\"...\","
                            "\"sourceSliceIndexes\":[1]}],"
                            "\"pastoralDistinctionsZh\":[{\"title\":\"...\",\"explanation\":\"...\","
                            "\"sourceSliceIndexes\":[1]}],"
                            "\"reflectionQuestionsZh\":[{\"question\":\"...\",\"sourceSliceIndexes\":[1]}],"
                            "\"smallGroupGuideZh\":[{\"section\":\"...\",\"guidance\":\"...\","
                            "\"sourceSliceIndexes\":[1]}],"
                            "\"responsePrayerZh\":\"...\",\"responsePrayerSourceSliceIndexes\":[1],"
                            "\"quotes\":[{\"textZh\":\"...\",\"sourceSliceIndex\":1,\"sourceSegmentId\":\"...\","
                            "\"sourceTextZh\":\"...\",\"sourceTextEn\":\"...\",\"startMs\":0,\"endMs\":0}]}.\n"
                            "Generate one central message, a concise summary, 3-8 outline sections, explicit Scripture context, "
                            "3-8 theological insights, sermon-illustration analysis when present, 2-6 pastoral distinctions, "
                            "5-8 reflection questions, a 3-6 item small-group guide, and a concise response prayer. "
                            "Every non-quote item must cite valid sourceSliceIndexes and remain directly grounded in those slices. "
                            "Reflection questions, group guidance, and prayer are AI-assisted responses, not speaker quotations. "
                            "Generate up to 6 exact quote excerpts copied contiguously from one cited segmentEvidence.textZh; "
                            "fewer or zero is correct when exact citation is unavailable.\n"
                            "Required fields must be present. Use empty arrays, not invented filler, when evidence is absent.\n"
                            f"<sermon_title>{simulation.get('sermonTitle') or simulation.get('title') or ''}</sermon_title>\n"
                            f"<caption_slices>{json.dumps(slices, ensure_ascii=False)}</caption_slices>"
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
    valid_slice_indexes = {
        int(item.get("index") or 0)
        for item in slices
        if int(item.get("index") or 0) > 0
    }
    quotes = normalize_quotes(data.get("quotes"), slices)
    central_message = compact_text(
        data.get("centralMessageZh")
        or data.get("central_message_zh")
        or data.get("centralMessage")
        or ""
    )
    central_message_sources = normalize_source_indexes(
        data.get("centralMessageSourceSliceIndexes"),
        valid_slice_indexes,
    )
    summary = compact_text(data.get("summaryZh") or data.get("summary_zh") or data.get("summary") or "")
    summary_sources = normalize_source_indexes(
        data.get("summarySourceSliceIndexes"),
        valid_slice_indexes,
    )
    outline = normalize_outline(
        data.get("outlineZh") or data.get("outline_zh") or data.get("outline"),
        valid_slice_indexes=valid_slice_indexes,
    )
    scripture_context = normalize_scripture_context(
        data.get("scriptureContextZh"),
        valid_slice_indexes,
    )
    theological_insights = normalize_explanation_items(
        data.get("theologicalInsightsZh"),
        valid_slice_indexes,
    )
    illustrations = normalize_illustrations(
        data.get("illustrationsZh"),
        valid_slice_indexes,
    )
    pastoral_distinctions = normalize_explanation_items(
        data.get("pastoralDistinctionsZh"),
        valid_slice_indexes,
    )
    reflection_questions = normalize_reflection_questions(
        data.get("reflectionQuestionsZh"),
        valid_slice_indexes,
    )
    small_group_guide = normalize_small_group_guide(
        data.get("smallGroupGuideZh"),
        valid_slice_indexes,
    )
    response_prayer = compact_text(data.get("responsePrayerZh") or "")
    response_prayer_sources = normalize_source_indexes(
        data.get("responsePrayerSourceSliceIndexes"),
        valid_slice_indexes,
    )
    missing_sources = missing_interpretation_source_paths(
        central_message=central_message,
        central_message_sources=central_message_sources,
        summary=summary,
        summary_sources=summary_sources,
        outline=outline,
        scripture_context=scripture_context,
        theological_insights=theological_insights,
        illustrations=illustrations,
        pastoral_distinctions=pastoral_distinctions,
        reflection_questions=reflection_questions,
        small_group_guide=small_group_guide,
        response_prayer=response_prayer,
        response_prayer_sources=response_prayer_sources,
    )
    return {
        "schemaVersion": 2,
        "status": "ready",
        "generatedFrom": "openai-notes",
        "artifactType": "sermon_interpretation",
        "provider": "openai",
        "model": model,
        "reasoningEffort": reasoning_effort,
        "promptVersion": review_prompts.NOTES_PROMPT_VERSION,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "serverSideSecretConfigured": bool(api_key_secret or os.environ.get("OPENAI_API_KEY")),
        "sermonTitle": simulation.get("sermonTitle"),
        "speaker": simulation.get("speaker"),
        "sermonDate": simulation.get("sermonDate"),
        "sourceLabel": simulation.get("sourceLabel"),
        "sourceTranslationStatus": simulation.get("translationStatus"),
        "sourceSegmentCount": len(simulation.get("segments") or []),
        "sliceCount": len(slices),
        "slices": summarize_slices(slices),
        "centralMessageZh": central_message,
        "centralMessageSourceSliceIndexes": central_message_sources,
        "summaryZh": summary,
        "summarySourceSliceIndexes": summary_sources,
        "outlineZh": outline,
        "scriptureRefs": normalize_string_list(data.get("scriptureRefs") or data.get("scripture_refs")),
        "scriptureContextZh": scripture_context,
        "theologicalInsightsZh": theological_insights,
        "illustrationsZh": illustrations,
        "pastoralDistinctionsZh": pastoral_distinctions,
        "reflectionQuestionsZh": reflection_questions,
        "smallGroupGuideZh": small_group_guide,
        "responsePrayerZh": response_prayer,
        "responsePrayerSourceSliceIndexes": response_prayer_sources,
        "quotes": quotes,
        "traceability": {
            "allInterpretationItemsHaveSource": not missing_sources,
            "missingSourcePaths": missing_sources,
            "allQuotesHaveSource": all(bool(item.get("sourceSegmentId")) for item in quotes),
            "allQuotesAreExactExcerpts": all(bool(item.get("exactSourceMatch")) for item in quotes),
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
            "segmentEvidence": item.get("segmentEvidence") or [],
            "refs": item["refs"],
        }
        for item in slices
    ]


def normalize_outline(
    value: Any,
    *,
    valid_slice_indexes: set[int] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    outline = []
    for item in value:
        if isinstance(item, dict):
            title = compact_text(item.get("title") or item.get("heading") or "")
            points = normalize_string_list(item.get("points") or item.get("children"))
            source_indexes = normalize_source_indexes(
                item.get("sourceSliceIndexes"),
                valid_slice_indexes,
            )
        else:
            title = compact_text(item)
            points = []
            source_indexes = []
        if title or points:
            outline.append(
                {
                    "title": title,
                    "points": points,
                    "sourceSliceIndexes": source_indexes,
                }
            )
    return outline


def normalize_source_indexes(
    value: Any,
    valid_slice_indexes: set[int] | None,
) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            index = int(item)
        except (TypeError, ValueError):
            continue
        if index <= 0:
            continue
        if valid_slice_indexes is not None and index not in valid_slice_indexes:
            continue
        if index not in result:
            result.append(index)
    return result


def normalize_scripture_context(
    value: Any,
    valid_slice_indexes: set[int],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        reference = compact_text(item.get("reference") or item.get("ref") or "")
        explanation = compact_text(item.get("explanation") or item.get("context") or "")
        if reference or explanation:
            result.append(
                {
                    "reference": reference,
                    "explanation": explanation,
                    "sourceSliceIndexes": normalize_source_indexes(
                        item.get("sourceSliceIndexes"),
                        valid_slice_indexes,
                    ),
                }
            )
    return result


def normalize_explanation_items(
    value: Any,
    valid_slice_indexes: set[int],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = compact_text(item.get("title") or item.get("heading") or "")
        explanation = compact_text(item.get("explanation") or item.get("body") or "")
        if title or explanation:
            result.append(
                {
                    "title": title,
                    "explanation": explanation,
                    "sourceSliceIndexes": normalize_source_indexes(
                        item.get("sourceSliceIndexes"),
                        valid_slice_indexes,
                    ),
                }
            )
    return result


def normalize_illustrations(
    value: Any,
    valid_slice_indexes: set[int],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = compact_text(item.get("title") or item.get("illustration") or "")
        function = compact_text(item.get("function") or item.get("explanation") or "")
        if title or function:
            result.append(
                {
                    "title": title,
                    "function": function,
                    "sourceSliceIndexes": normalize_source_indexes(
                        item.get("sourceSliceIndexes"),
                        valid_slice_indexes,
                    ),
                }
            )
    return result


def normalize_reflection_questions(
    value: Any,
    valid_slice_indexes: set[int],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            question = compact_text(item.get("question") or item.get("text") or "")
            sources = normalize_source_indexes(
                item.get("sourceSliceIndexes"),
                valid_slice_indexes,
            )
        else:
            question = compact_text(item)
            sources = []
        if question:
            result.append({"question": question, "sourceSliceIndexes": sources})
    return result


def normalize_small_group_guide(
    value: Any,
    valid_slice_indexes: set[int],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        section = compact_text(item.get("section") or item.get("title") or "")
        guidance = compact_text(item.get("guidance") or item.get("body") or "")
        if section or guidance:
            result.append(
                {
                    "section": section,
                    "guidance": guidance,
                    "sourceSliceIndexes": normalize_source_indexes(
                        item.get("sourceSliceIndexes"),
                        valid_slice_indexes,
                    ),
                }
            )
    return result


def missing_interpretation_source_paths(
    *,
    central_message: str,
    central_message_sources: list[int],
    summary: str,
    summary_sources: list[int],
    outline: list[dict[str, Any]],
    scripture_context: list[dict[str, Any]],
    theological_insights: list[dict[str, Any]],
    illustrations: list[dict[str, Any]],
    pastoral_distinctions: list[dict[str, Any]],
    reflection_questions: list[dict[str, Any]],
    small_group_guide: list[dict[str, Any]],
    response_prayer: str,
    response_prayer_sources: list[int],
) -> list[str]:
    missing: list[str] = []
    if central_message and not central_message_sources:
        missing.append("centralMessageSourceSliceIndexes")
    if summary and not summary_sources:
        missing.append("summarySourceSliceIndexes")
    for field, items in (
        ("outlineZh", outline),
        ("scriptureContextZh", scripture_context),
        ("theologicalInsightsZh", theological_insights),
        ("illustrationsZh", illustrations),
        ("pastoralDistinctionsZh", pastoral_distinctions),
        ("reflectionQuestionsZh", reflection_questions),
        ("smallGroupGuideZh", small_group_guide),
    ):
        for index, item in enumerate(items):
            if not item.get("sourceSliceIndexes"):
                missing.append(f"{field}[{index}].sourceSliceIndexes")
    if response_prayer and not response_prayer_sources:
        missing.append("responsePrayerSourceSliceIndexes")
    return missing


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
        source_slice_index = positive_int(
            item.get("sourceSliceIndex") or item.get("source_slice_index")
        )
        if source_slice_index is None:
            continue
        source_slice = by_index.get(source_slice_index)
        source_segment_id = compact_text(item.get("sourceSegmentId") or item.get("source_segment_id"))
        evidence_by_id = {
            compact_text(evidence.get("id")): evidence
            for evidence in (source_slice or {}).get("segmentEvidence") or []
            if isinstance(evidence, dict)
        }
        evidence = evidence_by_id.get(source_segment_id)
        source_text_zh = compact_text((evidence or {}).get("textZh"))
        text = strip_quote_wrappers(text)
        if not text or not source_segment_id or not source_text_zh or compact_text(text) not in source_text_zh:
            continue
        quotes.append(
            {
                "textZh": text,
                "sourceSliceIndex": source_slice_index,
                "sourceSegmentId": source_segment_id,
                "sourceTextZh": source_text_zh,
                "sourceTextEn": compact_text((evidence or {}).get("textEn")),
                "startMs": int((evidence or {}).get("startMs") or 0),
                "endMs": int((evidence or {}).get("endMs") or 0),
                "exactSourceMatch": True,
            }
        )
    return quotes


def positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def strip_quote_wrappers(value: str) -> str:
    text = compact_text(value)
    pairs = (("“", "”"), ("‘", "’"), ('"', '"'), ("'", "'"))
    for left, right in pairs:
        if len(text) >= 2 and text.startswith(left) and text.endswith(right):
            return compact_text(text[len(left) : -len(right)])
    return text


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
        command = ["upload_file_to_gcs.py", "--source", str(file_path), "--destination", gcs_uri]
        print("$ " + " ".join(command))
        if not dry_run:
            upload_file_to_gcs(file_path, gcs_uri)
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
