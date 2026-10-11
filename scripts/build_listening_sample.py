#!/usr/bin/env python3
"""Build the post-publication listening sample sheet for one locale.

    python3 scripts/build_listening_sample.py \
        --audio-package artifacts/weekend-live/layer3-<run>/ko/audio-package-c5.json \
        --candidate artifacts/weekend-live/layer2-<run>/recovered/ko/candidate.json \
        --anchors artifacts/weekend-live/layer1-<run>/output4/anchor-manifest.json \
        --audio-qc artifacts/weekend-live/text-qc-<run>/state-v3/qc-receipts/audio/ko/<lineage>/entry-000001.json \
        --out artifacts/weekend-live/listening-<run>/ko

The sheet lists every unit the machine checks flagged plus a seeded random
sample of the rest (10 by default), each with the published translation, the
frozen English, the unit audio path and a blank verdict cell. It replaces the
small-hours "listened, passed" statement with ten minutes on Monday: the
operator fills the verdict column and records the outcome with
record_decision.py, binding the sheet's JSON manifest by hash.

Bindings: the candidate must be the one the audio package names
(targetLanguageCandidateJsonSha256), and every unit's text hash must match its
group's text; the anchor manifest is recorded by hash. The sheet is a review
aid, not a receipt: it does not change any package or waiver.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts import sermon_sentence_interpretation as identity
except ImportError:  # pragma: no cover - direct CLI runs from scripts/
    import sermon_sentence_interpretation as identity

SCHEMA = "sermon-listening-sample-v1"
FLAGGED_STATUSES = {"fail", "requires_review", "pending_secondary_asr", "pending_primary_asr"}


def read(path: Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def flagged_groups(receipts) -> dict[str, list[str]]:
    """Group id → reasons, from audio QC receipts (results) and screening receipts (units/flagged)."""
    reasons: dict[str, list[str]] = {}
    for receipt in receipts:
        rows = receipt.get("results") or receipt.get("units") or receipt.get("flagged") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            group = row.get("groupId") or row.get("textGroupId")
            status = row.get("status")
            if not isinstance(group, str) or status not in FLAGGED_STATUSES:
                continue
            reason = status + (": " + ", ".join(row["issues"]) if row.get("issues") else "")
            reasons.setdefault(group, []).append(reason)
    return reasons


def build(package: dict, candidate: dict, *, anchors: dict | None = None, receipts=(), sample_size: int = 10,
          seed: str | None = None, now=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")) -> dict:
    package_sha = identity.json_sha256(package)
    candidate_sha = identity.json_sha256(candidate)
    if candidate_sha != package.get("targetLanguageCandidateJsonSha256"):
        raise ValueError("The candidate is not the one the audio package was rendered from")
    groups = {group["translationGroupId"]: group for group in candidate.get("groups", [])}
    english = {}
    if anchors is not None:
        english = {row["translationGroupId"]: row.get("targetEnglish", "")
                   for row in anchors.get("translationRequests", []) if isinstance(row, dict)}
    units = package.get("units") or []
    if not units:
        raise ValueError("The audio package has no units")
    rows = []
    for index, unit in enumerate(units):
        group = groups.get(unit.get("textGroupId"))
        if group is None:
            raise ValueError(f"Unit {unit.get('textGroupId')} has no group in the candidate")
        text = group.get("targetText", "")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != unit.get("targetTextSha256"):
            raise ValueError(f"Unit {unit['textGroupId']} text differs from the candidate group")
        rows.append({"index": index, "groupId": unit["textGroupId"], "text": text,
                     "english": english.get(unit["textGroupId"], ""), "audioPath": unit["audio"]["path"],
                     "audioSha256": unit["audio"]["sha256"], "textSha256": unit["targetTextSha256"],
                     "durationSeconds": unit.get("durationSeconds")})
    flagged = flagged_groups(receipts)
    if not 0 <= sample_size <= len(rows):
        raise ValueError("sample size must be between 0 and the unit count")
    seed = seed or package_sha
    pool = [row["groupId"] for row in rows if row["groupId"] not in flagged]
    chosen = set(random.Random(seed).sample(pool, min(sample_size, len(pool))))
    selected = []
    for row in rows:
        if row["groupId"] in flagged:
            selected.append({**row, "reason": "flagged", "flags": flagged[row["groupId"]]})
        elif row["groupId"] in chosen:
            selected.append({**row, "reason": "random"})
    return {"schemaVersion": SCHEMA, "builtAt": now(), "targetLocale": package.get("targetLocale"),
            "packageId": package.get("packageId"), "audioPackageJsonSha256": package_sha,
            "targetLanguageCandidateJsonSha256": candidate_sha,
            "anchorManifestJsonSha256": identity.json_sha256(anchors) if anchors is not None else None,
            "seed": seed, "sampleSize": sample_size, "unitCount": len(rows),
            "flaggedCount": sum(row["reason"] == "flagged" for row in selected),
            "rows": selected, "humanApproval": False, "scope": "review_aid_not_a_receipt"}


def markdown(sample: dict) -> str:
    lines = [f"# 听审抽样 · {sample['targetLocale']} · {sample['packageId']}", "",
             f"音频包 `{sample['audioPackageJsonSha256'][:12]}`，候选 `{sample['targetLanguageCandidateJsonSha256'][:12]}`，"
             f"共 {sample['unitCount']} 句；机器标记 {sample['flaggedCount']} 句全部列出，另随机抽 {sample['sampleSize']} 句"
             f"（种子 `{sample['seed'][:12]}`）。每行听一遍音频，在「结论」填 `通过` 或 `问题：…`；"
             "填完用 `record_decision.py --evidence <本表的 .json>` 记录结果。本表是复核辅助，不是收据。", "",
             "| 序 | 组 | 译文 | 英文 | 音频 | 秒 | 来源 | 结论 |", "|---|---|---|---|---|---|---|---|"]
    for row in sample["rows"]:
        source = "机器标记：" + "；".join(row["flags"]) if row["reason"] == "flagged" else "随机"
        cell = lambda value: str(value).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {row['index'] + 1} | `{row['groupId']}` | {cell(row['text'])} | {cell(row['english'])} | "
                     f"`{row['audioPath']}` | {row['durationSeconds']} | {cell(source)} | [ ] |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audio-package", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--anchors", type=Path, help="Layer 1 anchor manifest, for the English column")
    parser.add_argument("--audio-qc", type=Path, action="append", default=[], help="Audio QC receipt entry; repeatable")
    parser.add_argument("--screening", type=Path, action="append", default=[], help="ASR screening receipt; repeatable")
    parser.add_argument("--sample-size", type=int, default=10)
    parser.add_argument("--seed", help="Defaults to the audio package hash, so the same package samples the same units")
    parser.add_argument("--out", type=Path, required=True, help="Directory for listening-sample.md and .json (must not exist)")
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error("output directory already exists: " + str(args.out))
    sample = build(read(args.audio_package), read(args.candidate),
                   anchors=read(args.anchors) if args.anchors else None,
                   receipts=[read(path) for path in [*args.audio_qc, *args.screening]],
                   sample_size=args.sample_size, seed=args.seed)
    args.out.mkdir(parents=True)
    (args.out / "listening-sample.json").write_text(json.dumps(sample, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (args.out / "listening-sample.md").write_text(markdown(sample), encoding="utf-8")
    print(json.dumps({"locale": sample["targetLocale"], "rows": len(sample["rows"]), "flagged": sample["flaggedCount"],
                      "sheet": str(args.out / "listening-sample.md")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
