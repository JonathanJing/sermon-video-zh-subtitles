from __future__ import annotations

import csv
import hashlib
import json
import random
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .content_pack import CONTEXT_POLICIES, alignment_summary, load_pack, prompt_context, retrieve, sha256_file
from .ollama_client import OllamaClient


def read_asr_finals(session_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(session_dir) / "events.jsonl"
    finals: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("type") != "asr.final":
            continue
        segment_id = str(event.get("segmentId") or "")
        source_text = " ".join(str(event.get("sourceTextEn") or "").split())
        if not segment_id or not source_text or segment_id in seen:
            continue
        seen.add(segment_id)
        finals.append({
            "segmentId": segment_id,
            "sourceTextEn": source_text,
            "audioStartMs": event.get("audioStartMs"),
            "audioEndMs": event.get("audioEndMs"),
        })
    if not finals:
        raise ValueError(f"no asr.final events in {path}")
    return finals


def run_replay(
    segments: list[dict[str, Any]],
    policies: list[str],
    translate: Callable[[str, dict[str, Any]], dict[str, Any]],
    pack: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    invalid = [policy for policy in policies if policy not in CONTEXT_POLICIES]
    if invalid:
        raise ValueError(f"unsupported context policies: {', '.join(invalid)}")
    results: list[dict[str, Any]] = []
    cursors = {policy: None for policy in policies}
    for segment in segments:
        for policy in policies:
            hits = retrieve(
                pack, segment["sourceTextEn"], limit=5, cursor_sequence=cursors[policy]
            ) if pack and policy != "none" else []
            context = prompt_context(hits, policy=policy)
            translation = translate(segment["sourceTextEn"], context)
            alignment = alignment_summary(hits, cursors[policy])
            suggested = alignment.get("suggestedCursor")
            if isinstance(suggested, int):
                cursors[policy] = suggested
            results.append({
                **segment,
                "policy": policy,
                "effectivePolicy": policy if hits else "none",
                "contextHitIds": [hit["entryId"] for hit in hits],
                "alignment": alignment,
                **translation,
            })
    return results


def write_replay_artifacts(
    session_dir: str | Path,
    output_dir: str | Path,
    policies: list[str],
    results: list[dict[str, Any]],
    model: str,
    pack: dict[str, Any] | None,
    seed: int = 42,
) -> dict[str, Any]:
    session = Path(session_dir).resolve()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    events_path = session / "events.jsonl"
    audio_path = session / "asr-audio.wav"
    if not audio_path.is_file():
        audio_path = session / "recording.webm"
    labels = [chr(ord("A") + index) for index in range(len(policies))]
    shuffled = list(policies)
    random.Random(seed).shuffle(shuffled)
    label_to_policy = dict(zip(labels, shuffled, strict=True))
    policy_to_label = {policy: label for label, policy in label_to_policy.items()}
    run = {
        "schemaVersion": 1,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sourceSession": str(session),
        "sourceEventsSha256": sha256_file(events_path),
        "sourceAudio": str(audio_path) if audio_path.is_file() else None,
        "sourceAudioSha256": sha256_file(audio_path) if audio_path.is_file() else None,
        "model": model,
        "packVersion": pack.get("packVersion") if pack else None,
        "policies": policies,
        "blindLabelMapping": label_to_policy,
        "segmentCount": len({item["segmentId"] for item in results}),
        "resultCount": len(results),
        "qualityJudgment": "human_review_required",
    }
    (output / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (output / "results.jsonl").open("w", encoding="utf-8") as target:
        for item in results:
            target.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
    by_segment: dict[str, dict[str, Any]] = {}
    for item in results:
        row = by_segment.setdefault(item["segmentId"], {
            "segmentId": item["segmentId"],
            "sourceTextEn": item["sourceTextEn"],
        })
        row[policy_to_label[item["policy"]]] = item.get("targetTextZh", "")
    fields = ["segmentId", "sourceTextEn", *labels, "preferred", "errorTags", "reviewer", "notes"]
    with (output / "review.csv").open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(by_segment.values())
    return run


def default_output_dir(session_dir: str | Path) -> Path:
    digest = hashlib.sha256(str(Path(session_dir).resolve()).encode()).hexdigest()[:8]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("artifacts/replay-ab") / f"{stamp}-{digest}"


def ollama_translator(model: str, url: str) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    client = OllamaClient(model, url)
    return lambda source_text, context: client.translate(source_text, context)
