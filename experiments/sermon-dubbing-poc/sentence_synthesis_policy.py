"""Self-contained sentence-level policy shared by local and Spark renderers."""
from __future__ import annotations

import re


SENTENCE_SYNTHESIS_POLICY = {
    "version": "complete_chinese_sentence_natural_pace_v1",
    "generationUnit": "one_complete_chinese_sentence_or_reviewed_clause",
    "internalSplices": "forbidden",
    "sourceWordPauses": "reference_only_not_synthesis_boundaries",
    "rate": "natural_no_time_stretch",
}


def sentence_parts(text, *, cuv_quotes=False):
    closers = "”’\"'」』" if cuv_quotes else "”’\"'"
    parts = re.findall(r"[^。！？]+[。！？]?[" + re.escape(closers) + r"]*", text)
    result = [part.strip() for part in parts if part.strip()]
    if "".join(result).replace(" ", "") != text.replace(" ", ""):
        raise ValueError("Sentence segmentation changed reviewed Chinese text")
    return result


def synthesis_segmentation(job):
    """An absent policy is the immutable legacy flow mode, not an upgrade."""
    policy = job.get("synthesisPolicy")
    if policy is None:
        return "flow"
    if policy != SENTENCE_SYNTHESIS_POLICY:
        raise ValueError("Unsupported or altered synthesis policy")
    return "sentence"


def validate_synthesis_policy(job):
    if synthesis_segmentation(job) != "sentence":
        return
    expected = []
    cuv_quotes = job.get("pronunciationRuleVersion") == "chinese-sermon-pronunciation-v3"
    for block in job["blocks"]:
        parts = sentence_parts(block["zh"], cuv_quotes=cuv_quotes)
        for index, text in enumerate(parts):
            if len(text) > 180:
                raise ValueError(f"Block {block['id']} needs a reviewed sentence break")
            expected.append({"id": len(expected), "blockId": block["id"], "text": text,
                             "gapAfterSeconds": .45 if index == len(parts) - 1 else .18})
    units = job.get("units")
    if not isinstance(units, list) or len(units) != len(expected):
        raise ValueError("New synthesis job must render intact Chinese sentences or reviewed clauses")
    for unit, plain in zip(units, expected):
        if any(unit.get(key) != value for key, value in plain.items()):
            raise ValueError("New synthesis job must render intact Chinese sentences or reviewed clauses")
        if "spokenText" in unit and (not isinstance(unit["spokenText"], str) or not unit["spokenText"].strip()):
            raise ValueError("Spoken text must be nonempty")
