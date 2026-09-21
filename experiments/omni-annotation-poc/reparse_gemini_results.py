#!/usr/bin/env python3
"""Reparse retained Gemini responses without making another API request."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from schema import extract_json, validate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    durations = {item["windowId"]: float(item["durationSeconds"])
                 for item in manifest["windows"]}
    repaired = 0
    for primary in sorted(args.results.glob("*.result.json")):
        if not primary.name.endswith(".result.json") or primary.name.endswith(".reparsed.result.json"):
            continue
        result = json.loads(primary.read_text(encoding="utf-8"))
        if not result.get("validationErrors"):
            continue
        case_id = result["caseId"]
        window_id = case_id.rsplit("-retry", 1)[0]
        response_path = args.results / f"{case_id}.response.json"
        if not response_path.is_file():
            continue
        response = json.loads(response_path.read_text(encoding="utf-8"))
        try:
            analysis = extract_json(response.get("text", ""))
            errors = validate(analysis, durations[window_id])
            parse_error = None
        except Exception as exc:
            analysis = None
            errors = ["invalid_json"]
            parse_error = f"{type(exc).__name__}: {exc}"
        reparsed = dict(result)
        reparsed.update({
            "analysis": analysis, "validationErrors": errors, "parseError": parse_error,
            "reparsedFrom": str(primary.resolve()),
            "reparsePolicy": "retained_response_no_new_api_request",
        })
        out = args.results / f"{case_id}.reparsed.result.json"
        out.write_text(json.dumps(reparsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if not errors:
            repaired += 1
    print(json.dumps({"repairedValidResults": repaired}))


if __name__ == "__main__":
    main()
