#!/usr/bin/env python3
"""Prepare a multi-sentence phrase plan for the adaptive-pause Layer 3 POC."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_multilingual_prosody_poc import PLAN_SCHEMA, canonical_sha, read_object, write_json


SPEC_SCHEMA = "sermon-longform-adaptive-prosody-poc-spec-v1"


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _clone(value: object) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def prepare(base_plan_path: Path, anchor_path: Path, spec_path: Path, out: Path) -> dict[str, Any]:
    if out.exists():
        raise ValueError(f"Long-form prosody output already exists: {out}")
    base = read_object(base_plan_path)
    anchor = read_object(anchor_path)
    spec = read_object(spec_path)
    if base.get("schemaVersion") != PLAN_SCHEMA:
        raise ValueError("Long-form prosody POC requires a compatible Layer 3 plan")
    if anchor.get("schemaVersion") != "sermon-sentence-anchor-manifest-v2":
        raise ValueError("Long-form prosody POC requires Layer 1 word anchors")
    if spec.get("schemaVersion") != SPEC_SCHEMA:
        raise ValueError("Unsupported long-form adaptive-prosody spec")
    if spec.get("basePlanJsonSha256") != canonical_sha(base):
        raise ValueError("Long-form spec belongs to another base plan")
    if spec.get("anchorManifestJsonSha256") != canonical_sha(anchor):
        raise ValueError("Long-form spec belongs to another anchor manifest")

    base_units = base.get("units")
    sentence_specs = spec.get("sentences")
    if not isinstance(base_units, list) or not base_units:
        raise ValueError("Base plan has no units")
    if not isinstance(sentence_specs, list) or not sentence_specs:
        raise ValueError("Long-form spec has no sentences")
    if [row.get("sourceUnitId") for row in sentence_specs] != [row.get("sourceUnitId") for row in base_units]:
        raise ValueError("Long-form spec must cover base-plan units in order")

    anchor_by_id = {row["sourceUnitId"]: row for row in anchor.get("sourceUnits", [])}
    phrase_units: list[dict[str, Any]] = []
    for sentence_spec, base_unit in zip(sentence_specs, base_units):
        source_unit_id = base_unit["sourceUnitId"]
        anchor_unit = anchor_by_id.get(source_unit_id)
        if anchor_unit is None:
            raise ValueError(f"Missing Layer 1 unit: {source_unit_id}")
        if abs(float(base_unit["sourceStartSeconds"]) - float(anchor_unit["start"])) > 1e-6:
            raise ValueError(f"Base plan and anchor start differ: {source_unit_id}")
        if abs(float(base_unit["sourceEndSeconds"]) - float(anchor_unit["end"])) > 1e-6:
            raise ValueError(f"Base plan and anchor end differ: {source_unit_id}")
        phrases = sentence_spec.get("phrases")
        words = anchor_unit.get("words")
        if not isinstance(phrases, list) or not phrases or not isinstance(words, list) or not words:
            raise ValueError(f"Sentence has no phrases or words: {source_unit_id}")
        word_by_id = {word["wordId"]: word for word in words}
        flattened_ids: list[str] = []
        sentence_phrase_units = []
        for phrase_index, phrase in enumerate(phrases):
            phrase_ids = phrase.get("sourceWordIds")
            text = str(phrase.get("targetText", ""))
            instruct = str(phrase.get("instruct", "")).strip()
            if not isinstance(phrase_ids, list) or not phrase_ids or not text or not instruct:
                raise ValueError(f"Incomplete phrase in {source_unit_id}")
            if any(word_id not in word_by_id for word_id in phrase_ids):
                raise ValueError(f"Unknown Layer 1 word in {source_unit_id}")
            flattened_ids.extend(phrase_ids)
            first, last = word_by_id[phrase_ids[0]], word_by_id[phrase_ids[-1]]
            phrase_id = str(phrase.get("phraseId") or f"p{phrase_index + 1:02d}")
            start, end = float(first["start"]), float(last["end"])
            unit_index = len(phrase_units) + len(sentence_phrase_units)
            sentence_phrase_units.append({
                "unitIndex": unit_index,
                "sourceUnitId": f"{source_unit_id}-{phrase_id}",
                "parentSourceUnitId": source_unit_id,
                "sourceWordIds": phrase_ids,
                "sourceStartSeconds": start,
                "sourceEndSeconds": end,
                "sourceSpeechDurationSeconds": round(end - start, 6),
                "sourcePauseAfterSeconds": 0.0,
                "assemblyPauseAfterSeconds": 0.0,
                "targetText": text,
                "targetTextSha256": _text_sha(text),
                "targetDurationBudgetSeconds": round(end - start, 6),
                "instruct": instruct,
                "outputRelativePath": f"units/phrase-{unit_index:04d}.wav",
            })
        if flattened_ids != [word["wordId"] for word in words]:
            raise ValueError(f"Phrases must cover Layer 1 words in order: {source_unit_id}")
        if "".join(row["targetText"] for row in sentence_phrase_units) != base_unit["targetText"]:
            raise ValueError(f"Phrase text changed target sentence: {source_unit_id}")
        phrase_units.extend(sentence_phrase_units)

    plan = _clone(base)
    plan.update({
        "scope": "layer_3_longform_adaptive_phrase_anchor_shadow_poc",
        "status": "prepared_longform_adaptive_phrase_render_pending",
        "productionEligible": False,
        "humanApproval": False,
        "units": phrase_units,
    })
    plan["renderContract"].update({
        "generationMode": "one_call_per_internal_phrase_across_source_window",
        "pacePolicy": "natural_phrase_rate_no_time_stretch",
        "pausePolicy": "adaptive_source_start_anchor_fill_after_synthesis",
        "emphasisPolicy": "natural_language_phrase_local_emphasis",
    })
    plan["limitations"] = list(dict.fromkeys(plan.get("limitations", []) + [
        "phrase_boundaries_may_sound_discontinuous",
        "phrase_to_source_word_mapping_is_machine_poc_not_human_approved",
        "human_listening_required",
    ]))

    out.mkdir(parents=True)
    plan_path = out / "phrase-plan.json"
    write_json(plan_path, plan)
    manifest = {
        "schemaVersion": "sermon-longform-adaptive-prosody-poc-preparation-v1",
        "status": "prepared_longform_adaptive_phrase_render_pending",
        "productionEligible": False,
        "humanApproval": False,
        "basePlanJsonSha256": canonical_sha(base),
        "anchorManifestJsonSha256": canonical_sha(anchor),
        "specJsonSha256": canonical_sha(spec),
        "phrasePlan": {"path": plan_path.name, "jsonSha256": canonical_sha(plan)},
        "sentenceCount": len(base_units),
        "phraseCount": len(phrase_units),
        "humanListeningStatus": "pending",
    }
    write_json(out / "preparation-manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-plan", type=Path, required=True)
    parser.add_argument("--anchor", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.base_plan, args.anchor, args.spec, args.out)
    print(json.dumps({"status": result["status"], "sentenceCount": result["sentenceCount"], "phraseCount": result["phraseCount"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
