#!/usr/bin/env python3
"""Split overlong Layer 2 speech utterances without changing reviewed text.

The model evidence stays immutable. The output has the same evidence schema, and
the companion receipt binds both files and records every changed group. This is
only a speech-segmentation transform; it cannot repair a translation.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re


MAX_CHARS = 180
MAX_UTTERANCES = 4
PUNCTUATION_BREAK = re.compile(r"[,;:.!?，。；：！？]\s*")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def split_one(value: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Prefer a clause boundary, then a word boundary; retain every character."""
    parts = []
    remaining = value
    while len(remaining) > max_chars:
        lower = max(1, max_chars // 2)
        punctuation = [match.end() for match in PUNCTUATION_BREAK.finditer(remaining)
                       if lower <= match.end() <= max_chars]
        spaces = [index + 1 for index, char in enumerate(remaining[:max_chars])
                  if char.isspace() and lower <= index + 1 <= max_chars]
        boundary = max(punctuation) if punctuation else (max(spaces) if spaces else None)
        if boundary is None or not remaining[:boundary].strip() or not remaining[boundary:].strip():
            raise ValueError("No safe punctuation or word boundary within the utterance limit")
        parts.append(remaining[:boundary])
        remaining = remaining[boundary:]
    parts.append(remaining)
    if any(not part.strip() or len(part) > max_chars for part in parts):
        raise ValueError("Segmentation produced an empty or overlong utterance")
    if "".join(parts) != value:
        raise ValueError("Segmentation changed reviewed text")
    return parts


def segment_evidence(evidence: dict) -> tuple[dict, list[dict]]:
    output = copy.deepcopy(evidence)
    changes = []
    for group in output["groups"]:
        before = group["targetUtterances"]
        if not isinstance(before, list) or not before or not all(
                isinstance(item, str) and item.strip() for item in before):
            raise ValueError("Invalid model utterances")
        after = [piece for item in before for piece in split_one(item)]
        if len(after) > MAX_UTTERANCES:
            raise ValueError(f"Too many utterances after splitting {group['translationGroupId']}")
        if "".join(before) != "".join(after):
            raise ValueError("Segmentation changed reviewed text")
        if after != before:
            changes.append({
                "translationGroupId": group["translationGroupId"],
                "sourceUnitIds": group["sourceUnitIds"],
                "targetTextSha256": sha256("".join(before).encode("utf-8")),
                "beforeLengths": [len(item) for item in before],
                "afterLengths": [len(item) for item in after],
            })
            group["targetUtterances"] = after
    return output, changes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists() or args.receipt.exists():
        parser.error("Use new immutable output paths")
    raw = args.evidence.read_bytes()
    evidence = json.loads(raw)
    output, changes = segment_evidence(evidence)
    serialized = (json.dumps(output, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    receipt = {
        "schemaVersion": "sermon-target-language-utterance-segmentation-v1",
        "sourceEvidenceSha256": sha256(raw),
        "segmentedEvidenceSha256": sha256(serialized),
        "targetLocale": evidence["targetLocale"],
        "englishSourcePackageJsonSha256": evidence["englishSourcePackageJsonSha256"],
        "anchorManifestSha256": evidence["anchorManifestSha256"],
        "translationPolicySha256": evidence["translationPolicySha256"],
        "maxCharsPerUtterance": MAX_CHARS,
        "maxUtterancesPerGroup": MAX_UTTERANCES,
        "reviewedTextChanged": False,
        "changedGroups": changes,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(serialized)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(json.dumps({"changedGroups": len(changes), "evidence": str(args.out),
                      "receipt": str(args.receipt)}))


if __name__ == "__main__":
    main()
