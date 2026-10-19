#!/usr/bin/env python3
"""Machine-screen representative sentence TTS without granting listening approval."""
from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path
import re
from typing import Any, Callable

try:
    from scripts.render_sentence_interpretation_tts import JOB_SCHEMA, sha256, write_json
except ImportError:  # Direct execution via ``python scripts/...``.
    from render_sentence_interpretation_tts import JOB_SCHEMA, sha256, write_json


MODEL = "mlx-community/Qwen3-ASR-0.6B-8bit"
REVISION = "89e96d92ba34aca20b3e29fb10cc284097d1219f"
SCHEMA = "sermon-sentence-natural-tts-representative-asr-v1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def normalize(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text)).lower()


def default_model_loader() -> Any:
    from huggingface_hub import snapshot_download
    from mlx_audio.stt.utils import load_model
    return load_model(snapshot_download(repo_id=MODEL, revision=REVISION))


def screen(job_path: Path, render: Path, out: Path, indices: list[int], *,
           model_loader: Callable[[], Any] = default_model_loader) -> dict[str, Any]:
    job = json.loads(job_path.read_text(encoding="utf-8"))
    _require(job.get("purposeSchemaVersion") == JOB_SCHEMA, "Not a sentence natural-TTS job")
    identity = json.loads((render / "identity.json").read_text(encoding="utf-8"))
    _require(identity.get("jobSha256") == sha256(job_path), "Render identity belongs to another job")
    _require(indices and len(indices) == len(set(indices)), "Screening indices must be unique and nonempty")
    _require(all(0 <= index < len(job["units"]) for index in indices), "Screening index is out of range")
    model = model_loader()
    results = []
    for index in indices:
        unit = job["units"][index]
        audio = render / f"unit-{index:04d}.wav"
        renderer_receipt = json.loads(audio.with_suffix(".json").read_text(encoding="utf-8"))
        _require(renderer_receipt.get("unit") == unit
                 and renderer_receipt.get("identity") == identity
                 and renderer_receipt.get("sha256") == sha256(audio),
                 f"Changed or unbound audio unit: {index}")
        recognized = model.generate(str(audio), language="Chinese", max_tokens=1024).text
        expected_normal = normalize(unit["text"])
        recognized_normal = normalize(recognized)
        matcher = difflib.SequenceMatcher(None, expected_normal, recognized_normal, autojunk=False)
        differences = [{
            "kind": operation,
            "expected": expected_normal[a:b],
            "recognized": recognized_normal[c:d],
            "context": expected_normal[max(0, a - 8):min(len(expected_normal), b + 8)],
        } for operation, a, b, c, d in matcher.get_opcodes() if operation != "equal"]
        result = {
            "unitId": index,
            "translationGroupId": unit["translationGroupId"],
            "blockId": unit["blockId"],
            "audioSha256": sha256(audio),
            "expected": unit["text"],
            "recognized": recognized,
            "similarity": round(matcher.ratio(), 6),
            "differences": differences,
        }
        results.append(result)
        write_json(out / f"unit-{index:04d}.json", {
            "schemaVersion": SCHEMA,
            "model": MODEL,
            "revision": REVISION,
            "humanListeningReview": "pending",
            **result,
        })
        print(json.dumps({
            "unit": index,
            "similarity": result["similarity"],
            "differences": len(differences),
        }, ensure_ascii=False), flush=True)
    report = {
        "schemaVersion": SCHEMA,
        "status": "representative_machine_screening_only",
        "model": MODEL,
        "revision": REVISION,
        "jobSha256": sha256(job_path),
        "samplePolicy": "first_longest_dense_terminology",
        "screenedUnits": len(results),
        "expectedUnits": len(job["units"]),
        "humanListeningReview": "pending",
        "warning": "ASR differences may be recognition errors or homophones; matching text does not prove naturalness.",
        "results": results,
    }
    write_json(out / "representative-asr-screening.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--render", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--indices", required=True, help="Comma-separated zero-based unit indices")
    args = parser.parse_args()
    indices = [int(value) for value in args.indices.split(",") if value.strip()]
    report = screen(args.job, args.render, args.out, indices)
    print(json.dumps({
        "screenedUnits": report["screenedUnits"],
        "expectedUnits": report["expectedUnits"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
