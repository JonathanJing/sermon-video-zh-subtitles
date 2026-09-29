#!/usr/bin/env python3
"""Create a source-bound, arm-blind scoring sheet for Layer 2 comparisons."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


SCORE_FIELDS = ("omissionOrDistortion", "negationNumberName",
                "scriptureOrQuotation", "addedMeaning", "naturalness1to5",
                "editMinutes", "criticalError", "evidence")


def blank_score() -> dict:
    return {field: None for field in SCORE_FIELDS}


def build(sheet: dict, sha256: str) -> dict:
    if sheet.get("schemaVersion") != "layer2-ab-blind-review-v1":
        raise ValueError("unsupported blind review sheet")
    groups = sheet.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("blind review sheet has no paired groups")
    ratings = []
    codes = set()
    for group in groups:
        options = group.get("options")
        if not isinstance(options, list) or len(options) != 3:
            raise ValueError("paired group must contain three anonymous options")
        for option in options:
            code = option.get("code")
            if not isinstance(code, str) or not code or code in codes:
                raise ValueError("invalid or duplicate anonymous code")
            codes.add(code)
            ratings.append({"translationGroupId": group["translationGroupId"],
                            "code": code, "reviews": []})
    return {"schemaVersion": "layer2-ab-blind-scores-v2",
            "targetLocale": sheet["targetLocale"],
            "sourceSheetSha256": sha256, "ratedOptions": 0,
            "ratings": ratings, "adjudications": [],
            "blindingKeyOpenedAt": None}


def migrate_v1(scores: dict, template: dict) -> dict:
    """Copy a v1 sheet into independent per-reviewer records without losing scores."""
    if scores.get("schemaVersion") != "layer2-ab-blind-scores-v1":
        raise ValueError("migration requires a v1 scoring sheet")
    if (scores.get("targetLocale") != template["targetLocale"]
            or scores.get("sourceSheetSha256") != template["sourceSheetSha256"]
            or len(scores.get("ratings", [])) != len(template["ratings"])):
        raise ValueError("v1 scoring sheet does not match the blind source")
    old = {(row["translationGroupId"], row["code"]): row
           for row in scores["ratings"]}
    if len(old) != len(template["ratings"]):
        raise ValueError("duplicate v1 scoring option")
    for row in template["ratings"]:
        previous = old.get((row["translationGroupId"], row["code"]))
        if previous is None:
            raise ValueError("v1 scoring option does not match the blind source")
        reviewer = previous.get("reviewerId")
        draft = previous.get("draft")
        reviewed = previous.get("reviewed")
        if reviewer is None:
            if draft != blank_score() or reviewed != blank_score():
                raise ValueError("v1 score has no reviewer identity")
        else:
            if not isinstance(reviewer, str) or not reviewer.strip():
                raise ValueError("invalid v1 reviewer identity")
            row["reviews"].append({"reviewerId": reviewer, "draft": draft,
                                   "reviewed": reviewed})
    template["ratedOptions"] = scores.get("ratedOptions", 0)
    template["adjudications"] = scores.get("adjudications", [])
    template["blindingKeyOpenedAt"] = scores.get("blindingKeyOpenedAt")
    return template


def ignored_or_external(path: Path) -> bool:
    root = Path(__file__).resolve().parents[2]
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        return True
    return subprocess.run(["git", "check-ignore", "-q", str(resolved)],
                          cwd=root, check=False).returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--migrate-from", type=Path,
                        help="Copy existing v1 scores into a new v2 file without overwriting either")
    args = parser.parse_args()
    if not ignored_or_external(args.out):
        parser.error("scoring sheet must stay in an ignored or external directory")
    raw = args.sheet.read_bytes()
    template = build(json.loads(raw), hashlib.sha256(raw).hexdigest())
    if args.migrate_from is not None:
        template = migrate_v1(json.loads(args.migrate_from.read_text(encoding="utf-8")), template)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(template, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"targetLocale": template["targetLocale"],
                      "options": len(template["ratings"]), "out": str(args.out)}))


if __name__ == "__main__":
    main()
