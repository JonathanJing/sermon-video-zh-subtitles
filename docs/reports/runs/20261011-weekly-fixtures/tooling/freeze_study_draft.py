#!/usr/bin/env python3
"""Freeze a delegated-agent study draft (outline or meditation) as a sermon-study-artifact-v1.

The v2 API generator cannot fit this sermon's units inside its request bound, so the
sections are drafted by the delegated agent from the approved target text and frozen
through the v1 producer path. The artifact stays human_pending: it is released only
with a sermon-study-review-v1 written by the human reviewer.

Usage: freeze_study_draft.py --locale ko --kind outline --sections sections.json --out artifact.json
sections.json: [{"title": ..., "body": ..., "sourceUnitIds": [...]}, ...]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts import study_artifacts as study  # noqa: E402
from scripts.delivery_contract import sha  # noqa: E402

PAGE_ID = "resi-20261011-54475d42"
PRODUCER = "delegated-agent-draft:claude-fable-5.1:2026-10-11 (user delegation '大纲，默想…同步做'; v2 API generator refused: provider_input_bound_exceeded at batchGroups=3)"
WL = ROOT / "artifacts/weekend-live"
SOURCE = WL / "layer1-54475d42/formal/english-source-package.json"
ANCHOR = WL / "layer1-54475d42/output4-rebuild4/anchor-manifest.json"
CANDIDATES = {"zh-Hans": WL / "layer2-54475d42/text-r12/zh-Hans/candidate.json",
              "ko": WL / "layer2-54475d42/recovered/ko/candidate.json",
              "es": WL / "layer2-54475d42/recovered/es/candidate.json"}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--locale", required=True, choices=list(CANDIDATES))
    ap.add_argument("--kind", required=True, choices=["outline", "meditation"])
    ap.add_argument("--sections", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    source = json.loads(SOURCE.read_text())
    candidate = json.loads(CANDIDATES[args.locale].read_text())
    anchor = json.loads(ANCHOR.read_text())
    units = {u["sourceUnitId"] for u in anchor["sourceUnits"]}
    sections = json.loads(args.sections.read_text())
    bad = [i for s in sections for i in s["sourceUnitIds"] if i not in units]
    if bad:
        raise SystemExit(f"unknown sourceUnitIds: {bad[:5]}")
    artifact = study.produce(args.kind, sections, page_id=PAGE_ID, locale=args.locale,
                             source_sha=sha(source), text_sha=sha(candidate), producer_identity=PRODUCER)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, ensure_ascii=False, indent=1))
    print(json.dumps({"out": str(args.out), "sections": len(sections), "artifactSha256": sha(artifact),
                      "review": "human_pending"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
