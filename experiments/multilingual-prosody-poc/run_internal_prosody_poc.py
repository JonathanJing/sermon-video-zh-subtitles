#!/usr/bin/env python3
"""Prepare bound whole-unit and phrase-level internal-prosody POC plans.

The whole-unit plan tests whether one natural-language instruction can place
emphasis and pauses inside a sentence.  The phrase plan keeps the same target
text but derives exact deterministic gaps from the Layer 1 word timeline.
Neither path changes words, time-stretches audio, or claims listening approval.
"""
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


SPEC_SCHEMA = "sermon-internal-prosody-poc-spec-v1"


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _clone(value: object) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _selected_plan(base: dict[str, Any], unit: dict[str, Any]) -> dict[str, Any]:
    plan = _clone(base)
    plan["scope"] = "layer_3_internal_emphasis_and_pause_shadow_poc"
    plan["status"] = "prepared_internal_prosody_render_pending"
    plan["productionEligible"] = False
    plan["humanApproval"] = False
    plan["sourceWindow"] = {
        "startSeconds": unit["sourceStartSeconds"],
        "endSeconds": unit["sourceEndSeconds"],
        "durationSeconds": unit["sourceSpeechDurationSeconds"],
    }
    plan["limitations"] = list(dict.fromkeys(plan.get("limitations", []) + [
        "natural_language_emphasis_is_probabilistic",
        "human_listening_required",
    ]))
    return plan


def prepare(base_plan_path: Path, anchor_path: Path, spec_path: Path, out: Path) -> dict[str, Any]:
    if out.exists():
        raise ValueError(f"Internal-prosody output already exists: {out}")
    base = read_object(base_plan_path)
    anchor = read_object(anchor_path)
    spec = read_object(spec_path)
    if base.get("schemaVersion") != PLAN_SCHEMA:
        raise ValueError("Internal prosody POC requires a compatible Layer 3 plan")
    if anchor.get("schemaVersion") != "sermon-sentence-anchor-manifest-v2":
        raise ValueError("Internal prosody POC requires Layer 1 word anchors")
    if spec.get("schemaVersion") != SPEC_SCHEMA:
        raise ValueError("Unsupported internal-prosody spec")
    if spec.get("basePlanJsonSha256") != canonical_sha(base):
        raise ValueError("Internal-prosody spec belongs to another base plan")
    if spec.get("anchorManifestJsonSha256") != canonical_sha(anchor):
        raise ValueError("Internal-prosody spec belongs to another anchor manifest")

    source_unit_id = spec.get("sourceUnitId")
    base_units = [unit for unit in base.get("units", []) if unit.get("sourceUnitId") == source_unit_id]
    anchor_units = [unit for unit in anchor.get("sourceUnits", []) if unit.get("sourceUnitId") == source_unit_id]
    if len(base_units) != 1 or len(anchor_units) != 1:
        raise ValueError("Selected source unit must exist exactly once in both inputs")
    base_unit, anchor_unit = base_units[0], anchor_units[0]
    if abs(float(base_unit["sourceStartSeconds"]) - float(anchor_unit["start"])) > 1e-6:
        raise ValueError("Base plan and anchor start differ")
    if abs(float(base_unit["sourceEndSeconds"]) - float(anchor_unit["end"])) > 1e-6:
        raise ValueError("Base plan and anchor end differ")

    phrases = spec.get("phrases")
    words = anchor_unit.get("words")
    if not isinstance(phrases, list) or len(phrases) < 2 or not isinstance(words, list) or not words:
        raise ValueError("Internal prosody POC requires at least two phrases and Layer 1 words")
    word_by_id = {word["wordId"]: word for word in words}
    flattened_ids: list[str] = []
    phrase_units = []
    for index, phrase in enumerate(phrases):
        phrase_ids = phrase.get("sourceWordIds")
        text = str(phrase.get("targetText", "")).strip()
        instruct = str(phrase.get("instruct", "")).strip()
        if not isinstance(phrase_ids, list) or not phrase_ids or not text or not instruct:
            raise ValueError("Every phrase needs target text, instruction, and source words")
        if any(word_id not in word_by_id for word_id in phrase_ids):
            raise ValueError("Phrase references an unknown Layer 1 word")
        flattened_ids.extend(phrase_ids)
        first, last = word_by_id[phrase_ids[0]], word_by_id[phrase_ids[-1]]
        next_start = (float(word_by_id[phrases[index + 1]["sourceWordIds"][0]]["start"])
                      if index + 1 < len(phrases) else float(last["end"]))
        pause = max(0.0, next_start - float(last["end"]))
        start, end = float(first["start"]), float(last["end"])
        phrase_id = str(phrase.get("phraseId") or f"p{index + 1:02d}")
        phrase_units.append({
            "unitIndex": index,
            "sourceUnitId": f"{source_unit_id}-{phrase_id}",
            "parentSourceUnitId": source_unit_id,
            "sourceWordIds": phrase_ids,
            "sourceStartSeconds": start,
            "sourceEndSeconds": end,
            "sourceSpeechDurationSeconds": round(end - start, 6),
            "sourcePauseAfterSeconds": round(pause, 6),
            "assemblyPauseAfterSeconds": round(pause, 6) if index + 1 < len(phrases) else 0.0,
            "targetText": text,
            "targetTextSha256": _text_sha(text),
            "targetDurationBudgetSeconds": round(end - start, 6),
            "instruct": instruct,
            "outputRelativePath": f"units/phrase-{index:02d}.wav",
        })
    if flattened_ids != [word["wordId"] for word in words]:
        raise ValueError("Phrase source words must cover the selected Layer 1 unit in order")
    if "".join(unit["targetText"] for unit in phrase_units) != base_unit["targetText"]:
        raise ValueError("Phrase text must concatenate to the unchanged target sentence")

    whole_plan = _selected_plan(base, base_unit)
    whole_unit = _clone(base_unit)
    whole_unit.update({
        "unitIndex": 0,
        "assemblyPauseAfterSeconds": 0.0,
        "instruct": str(spec.get("wholeUnitInstruct", "")).strip(),
        "outputRelativePath": "units/unit-0000.wav",
    })
    if not whole_unit["instruct"]:
        raise ValueError("Whole-unit instruction is required")
    whole_plan["renderContract"].update({
        "generationMode": "one_call_for_selected_source_unit",
        "pacePolicy": "same_model_existing_pace_instruction_plus_internal_prosody",
        "pausePolicy": "natural_language_internal_pause_request",
        "emphasisPolicy": "natural_language_selected_word_emphasis",
    })
    whole_plan["units"] = [whole_unit]

    phrase_plan = _selected_plan(base, base_unit)
    phrase_plan["renderContract"].update({
        "generationMode": "one_call_per_internal_phrase",
        "pacePolicy": "natural_phrase_rate_no_time_stretch",
        "pausePolicy": "deterministic_copy_of_layer1_intra_unit_word_gaps",
        "emphasisPolicy": "natural_language_phrase_local_emphasis",
    })
    phrase_plan["units"] = phrase_units
    phrase_plan["limitations"] = list(dict.fromkeys(phrase_plan["limitations"] + [
        "phrase_boundaries_may_sound_discontinuous",
    ]))

    out.mkdir(parents=True)
    whole_path = out / "whole-unit-plan.json"
    phrase_path = out / "phrase-plan.json"
    write_json(whole_path, whole_plan)
    write_json(phrase_path, phrase_plan)
    manifest = {
        "schemaVersion": "sermon-internal-prosody-poc-preparation-v1",
        "status": "prepared_same_model_internal_prosody_render_pending",
        "productionEligible": False,
        "humanApproval": False,
        "sourceUnitId": source_unit_id,
        "targetText": base_unit["targetText"],
        "basePlanJsonSha256": canonical_sha(base),
        "anchorManifestJsonSha256": canonical_sha(anchor),
        "specJsonSha256": canonical_sha(spec),
        "wholeUnitPlan": {"path": whole_path.name, "jsonSha256": canonical_sha(whole_plan)},
        "phrasePlan": {"path": phrase_path.name, "jsonSha256": canonical_sha(phrase_plan)},
        "derivedInternalPausesSeconds": [unit["assemblyPauseAfterSeconds"] for unit in phrase_units[:-1]],
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
    print(json.dumps({"status": result["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
