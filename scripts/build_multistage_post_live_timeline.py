#!/usr/bin/env python3
"""Locate sermon boundaries with coarse, transition, and fine timeline passes."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import build_post_live_timeline, review_prompts, sermon_pipeline  # noqa: E402


Classifier = Callable[[str, list[dict[str, Any]]], dict[str, Any]]


def main() -> int:
    args = parse_args()
    report = build_multistage_timeline(args)
    out = resolve_repo_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("artifacts/post-live-timeline/report.json"))
    parser.add_argument("--outdir", type=Path, default=Path("artifacts/post-live-timeline"))
    parser.add_argument("--coarse-chunk-seconds", type=float, default=120.0)
    parser.add_argument("--transition-chunk-seconds", type=float, default=30.0)
    parser.add_argument("--fine-chunk-seconds", type=float, default=5.0)
    parser.add_argument("--wide-margin-seconds", type=float, default=180.0)
    parser.add_argument("--fine-zone-radius-seconds", type=float, default=75.0)
    parser.add_argument("--transcription-model", default="gpt-transcribe")
    parser.add_argument("--classifier-model", default="gpt-5.6")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high"), default="high")
    parser.add_argument("--api-key-secret")
    return parser.parse_args()


def build_multistage_timeline(
    args: argparse.Namespace,
    *,
    classifier: Classifier | None = None,
) -> dict[str, Any]:
    source = resolve_repo_path(args.input)
    outdir = resolve_repo_path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    api_key = build_post_live_timeline.resolve_api_key(args.api_key_secret)
    classify = classifier or make_openai_classifier(
        api_key,
        model=args.classifier_model,
        reasoning_effort=args.reasoning_effort,
        cache_dir=outdir / "classifier",
    )

    coarse_dir = outdir / "coarse_120s"
    coarse = transcribe_absolute_chunks(
        api_key=api_key,
        source=source,
        outdir=coarse_dir,
        chunk_seconds=args.coarse_chunk_seconds,
        model=args.transcription_model,
        absolute_offset=0.0,
    )
    coarse_analysis = build_post_live_timeline.analyze_timeline(
        coarse,
        start_buffer_seconds=0.0,
        end_buffer_seconds=0.0,
    )
    coarse_selection = validate_transition_selection(classify("coarse", coarse), coarse)
    coarse_start = chunk_by_id(coarse, coarse_selection["startChunkId"])
    coarse_end = chunk_by_id(coarse, coarse_selection["endChunkId"])

    duration = sermon_pipeline.ffprobe_duration(source)
    wide_start = max(0.0, float(coarse_start["start"]) - args.wide_margin_seconds)
    wide_end = min(duration, float(coarse_end["end"]) + args.wide_margin_seconds)
    if wide_end <= wide_start:
        raise RuntimeError("Invalid wide candidate window")

    transition_dir = outdir / "transition_30s"
    transition_signature = f"candidate_{int(round(wide_start * 1000))}_{int(round(wide_end * 1000))}"
    signed_transition_dir = transition_dir / transition_signature
    transition_audio = signed_transition_dir / "candidate.m4a"
    sermon_pipeline.cut_chunk(source, transition_audio, wide_start, wide_end - wide_start)
    transition = transcribe_absolute_chunks(
        api_key=api_key,
        source=transition_audio,
        outdir=signed_transition_dir,
        chunk_seconds=args.transition_chunk_seconds,
        model=args.transcription_model,
        absolute_offset=wide_start,
    )
    write_json(transition_dir / "timeline_chunks.json", transition)
    write_json(
        transition_dir / "active_candidate.json",
        {"signature": transition_signature, "startSeconds": wide_start, "endSeconds": wide_end},
    )
    approximate = validate_transition_selection(classify("transition", transition), transition)

    start_anchor = chunk_by_id(transition, approximate["startChunkId"])
    end_anchor = chunk_by_id(transition, approximate["endChunkId"])
    start_zone = bounded_zone(start_anchor, args.fine_zone_radius_seconds, duration)
    end_zone = bounded_zone(end_anchor, args.fine_zone_radius_seconds, duration)

    start_fine = transcribe_zone(
        api_key=api_key,
        source=source,
        outdir=outdir / "start_fine_5s",
        zone=start_zone,
        chunk_seconds=args.fine_chunk_seconds,
        model=args.transcription_model,
    )
    end_fine = transcribe_zone(
        api_key=api_key,
        source=source,
        outdir=outdir / "end_fine_5s",
        zone=end_zone,
        chunk_seconds=args.fine_chunk_seconds,
        model=args.transcription_model,
    )
    fine_payload = [
        *[{**item, "boundaryZone": "start"} for item in start_fine],
        *[{**item, "boundaryZone": "end"} for item in end_fine],
    ]
    exact = validate_exact_selection(classify("exact", fine_payload), start_fine, end_fine)
    start_chunk = chunk_by_id(start_fine, exact["startChunkId"])
    start_seconds = float(start_chunk["start"])
    end_seconds = float(exact["endBoundarySeconds"])
    suggested = {
        "startSeconds": round(start_seconds, 3),
        "endSeconds": round(end_seconds, 3),
        "startTimecode": build_post_live_timeline.seconds_timecode(start_seconds),
        "endTimecode": build_post_live_timeline.seconds_timecode(end_seconds),
        "confidence": exact.get("confidence", "candidate_requires_review"),
        "method": "coarse_120s_transition_30s_fine_5s_gpt_semantic",
        "requiresOperatorReview": True,
    }
    return review_report(
        source,
        outdir,
        args,
        stages={
            "coarse": {
                "chunks": display_path(coarse_dir / "timeline_chunks.json"),
                "analysis": coarse_analysis,
                "semanticSelection": coarse_selection,
            },
            "wideCandidate": {"startSeconds": wide_start, "endSeconds": wide_end},
            "transition": {
                "chunks": display_path(transition_dir / "timeline_chunks.json"),
                "selection": approximate,
            },
            "startFine": {"zone": start_zone, "chunks": display_path(outdir / "start_fine_5s" / "timeline_chunks.json")},
            "endFine": {"zone": end_zone, "chunks": display_path(outdir / "end_fine_5s" / "timeline_chunks.json")},
            "exactSelection": exact,
        },
        suggested=suggested,
    )


def transcribe_absolute_chunks(
    *, api_key: str, source: Path, outdir: Path, chunk_seconds: float, model: str, absolute_offset: float
) -> list[dict[str, Any]]:
    chunks = build_post_live_timeline.transcribe_full_audio_chunks(
        api_key=api_key,
        source=source,
        outdir=outdir,
        chunk_seconds=chunk_seconds,
        model=model,
    )
    if absolute_offset:
        chunks = [
            {
                **item,
                "start": round(float(item["start"]) + absolute_offset, 3),
                "end": round(float(item["end"]) + absolute_offset, 3),
            }
            for item in chunks
        ]
    write_json(outdir / "timeline_chunks.json", chunks)
    return chunks


def transcribe_zone(*, api_key: str, source: Path, outdir: Path, zone: dict[str, float], chunk_seconds: float, model: str):
    signature = f"zone_{int(round(zone['startSeconds'] * 1000))}_{int(round(zone['endSeconds'] * 1000))}"
    signed_outdir = outdir / signature
    audio = signed_outdir / "zone.m4a"
    sermon_pipeline.cut_chunk(source, audio, zone["startSeconds"], zone["endSeconds"] - zone["startSeconds"])
    chunks = transcribe_absolute_chunks(
        api_key=api_key,
        source=audio,
        outdir=signed_outdir,
        chunk_seconds=chunk_seconds,
        model=model,
        absolute_offset=zone["startSeconds"],
    )
    write_json(outdir / "timeline_chunks.json", chunks)
    write_json(outdir / "active_zone.json", {"signature": signature, **zone})
    return chunks


def make_openai_classifier(api_key: str, *, model: str, reasoning_effort: str, cache_dir: Path) -> Classifier:
    def classify(stage: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        user_prompt = review_prompts.boundary_user_prompt(stage, chunks)
        serialized = json.dumps(
            {
                "promptVersion": review_prompts.BOUNDARY_PROMPT_VERSION,
                "system": review_prompts.BOUNDARY_SYSTEM_PROMPT,
                "user": user_prompt,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        cache = cache_dir / f"{stage}_{digest}.json"
        active_cache = cache_dir / f"{stage}.json"
        if cache.exists():
            parsed = read_json(cache)
            write_json(active_cache, parsed)
            return parsed
        payload = {
            "model": model,
            "reasoning_effort": reasoning_effort,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": review_prompts.BOUNDARY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }
        result = sermon_pipeline.chat_json(api_key, payload)
        parsed = json.loads(result["choices"][0]["message"]["content"])
        parsed["model"] = result.get("model", model)
        parsed["reasoningEffort"] = reasoning_effort
        parsed["promptVersion"] = review_prompts.BOUNDARY_PROMPT_VERSION
        parsed["inputSha256Prefix"] = digest
        write_json(cache, parsed)
        write_json(active_cache, parsed)
        return parsed

    return classify


def validate_transition_selection(selection: dict[str, Any], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    ids = {item["id"] for item in chunks}
    if selection.get("startChunkId") not in ids or selection.get("endChunkId") not in ids:
        raise RuntimeError("Transition classifier returned an unknown chunk id")
    start = chunk_by_id(chunks, selection["startChunkId"])
    end = chunk_by_id(chunks, selection["endChunkId"])
    if float(end["start"]) <= float(start["start"]):
        raise RuntimeError("Transition classifier returned a non-positive sermon window")
    return selection


def validate_exact_selection(selection: dict[str, Any], start_chunks: list[dict[str, Any]], end_chunks: list[dict[str, Any]]):
    start_ids = {item["id"] for item in start_chunks}
    if selection.get("startChunkId") not in start_ids:
        raise RuntimeError("Exact classifier returned an unknown start chunk id")
    end_seconds = float(selection.get("endBoundarySeconds", -1))
    if not end_chunks or not float(end_chunks[0]["start"]) <= end_seconds <= float(end_chunks[-1]["end"]):
        raise RuntimeError("Exact classifier returned an end boundary outside the fine zone")
    if end_seconds <= float(chunk_by_id(start_chunks, selection["startChunkId"])["start"]):
        raise RuntimeError("Exact classifier returned a non-positive sermon window")
    return {**selection, "endBoundarySeconds": round(end_seconds, 3)}


def chunk_by_id(chunks: list[dict[str, Any]], chunk_id: Any) -> dict[str, Any]:
    return next(item for item in chunks if item["id"] == chunk_id)


def bounded_zone(chunk: dict[str, Any], radius: float, duration: float) -> dict[str, float]:
    center = (float(chunk["start"]) + float(chunk["end"])) / 2
    return {"startSeconds": round(max(0.0, center - radius), 3), "endSeconds": round(min(duration, center + radius), 3)}


def review_report(source: Path, outdir: Path, args: argparse.Namespace, *, stages, suggested, reason=None):
    return {
        "schemaVersion": 2,
        "status": "requires_operator_review",
        "stage": "multistage_timeline_probed",
        "input": display_path(source),
        "transcriptionModel": args.transcription_model,
        "classifierModel": args.classifier_model,
        "reasoningEffort": args.reasoning_effort,
        "promptVersion": review_prompts.BOUNDARY_PROMPT_VERSION,
        "transcriptionPromptVersion": build_post_live_timeline.TIMELINE_TRANSCRIPTION_PROMPT_VERSION,
        "transcriptionLanguages": ["en"],
        "transcriptionKeywordCount": len(build_post_live_timeline.TIMELINE_TRANSCRIPTION_KEYWORDS),
        "suggestedWindow": suggested,
        "analysis": {"suggestedWindow": suggested},
        "stages": stages,
        "reason": reason,
        "nextAction": "Independently review the video and confirm local-audio start/end before generate-reviewed.",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
