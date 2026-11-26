#!/usr/bin/env python3
"""Build the Layer 1 English source package once the English table has a human conclusion.

Inputs are the revised anchor manifest (the candidate with the reviewer's edits applied), the
word-level transcript, the review csv, and the decision the review page recorded. The package
binds the approved window, the transcript, the anchors and the approval receipt by byte and
JSON hashes, the way the published English comparison checks them
(tongxing_production/delivery/published_english_reference.py).

The approval is the reviewer's, never this script's: reviewer, time, checks and edits are read
from the decision record. With --rehearsal the same files are written but marked as a rehearsal:
humanApproval is false, the package is not eligible for translation, and nothing downstream
will accept it.

Agent-built source: there is no MFA alignment, so the transcript artifact is the whisper-1 word
stream. The package and the receipt say so (the field name mfaSegmentsSha256 is kept because
the consumers read it).

This is the 2026-11-21 week-11 builder with the episode-specific values turned into arguments.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

CHECKS = ("sourceIdentity", "transcriptCompleteness", "wordAlignment", "sentenceAndPauseBoundaries")


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def json_sha(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return sha_bytes(encoded)


def write(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def build(args) -> dict:
    root = args.root.resolve()
    rel = lambda path: str(Path(path).resolve().relative_to(root))

    def evidence(path: Path, value=None) -> dict:
        ref = {"path": rel(path), "sha256": sha(path)}
        if path.suffix == ".json":
            ref["jsonSha256"] = json_sha(value if value is not None else json.loads(path.read_text(encoding="utf-8")))
        return ref

    out_dir = args.out.parent
    anchors = json.loads(args.anchor.read_text(encoding="utf-8"))
    record = json.loads(args.decision.read_text(encoding="utf-8"))
    decision, reviewer = record["decision"], record["reviewer"]
    if decision["verdict"] != "approved" or decision.get("kind") != "english":
        raise SystemExit("the decision is not an approval of the English table")
    missing = [name for name in (*CHECKS, "window") if decision["checks"].get(name) is not True]
    if missing:
        raise SystemExit(f"the decision does not confirm: {', '.join(missing)}")
    human = not args.rehearsal
    who = f"{reviewer.get('name') or reviewer['login']} ({reviewer['source']}, review page)"
    if args.rehearsal:
        who = f"rehearsal, not a human review ({who})"

    units = [{"sourceUnitId": u["sourceUnitId"], "english": u["english"], "start": u["start"], "end": u["end"],
              "pauseAfterSeconds": u["boundary"]["pauseAfterSeconds"]} for u in anchors["sourceUnits"]]
    unit_ids = [u["sourceUnitId"] for u in units]
    media_sha, duration = anchors["input"]["mediaSha256"], anchors["input"]["mediaDurationSeconds"]

    aligned = out_dir / "aligned-words.json"
    aligned.write_bytes(args.words.read_bytes())
    decision_copy = out_dir / "english-review-decision.json"
    write(decision_copy, record)
    edits = decision["payload"].get("edits") or {}
    edit_counts = (len(edits.get("replace") or {}), len(edits.get("mergeWithPrevious") or []), len(edits.get("drop") or []))
    heard = len(decision["payload"].get("heardUnitIds") or [])
    scope = decision["payload"].get("approval") or {}
    candidate_units = int(scope.get("units") or len(anchors["sourceUnits"]))
    looked = int(scope.get("lookedAtUnits") or heard)
    by_default = scope.get("mode") == "default_approve_unreviewed"

    window = {"schemaVersion": "sermon-source-window-approval-v1", "sourceUrl": anchors["input"]["sourceUrl"],
              "mediaSha256": media_sha, "start": 0.0, "end": duration,
              "humanApproval": human, "status": "approved" if human else "rehearsal",
              "approvedBy": who, "approvedAt": record["receivedAt"],
              "note": (f"窗口按整段媒体 0–{duration:.3f} s 登记；句表单元覆盖 {units[0]['start']:.2f}–{units[-1]['end']:.2f} s，"
                       "之外的开头结尾不进句表、不配音。审核者在批准英文表的同一页勾选了「窗口正确」。")}
    window_path = out_dir / "window-approval.json"
    write(window_path, window)

    receipt = {"schemaVersion": "sermon-english-source-review-v1", "humanApproval": human, "reviewer": who,
               "reviewedAt": record["receivedAt"],
               "checks": {name: "approved" if human else "rehearsal" for name in CHECKS},
               "reviewedSourceUnitIds": unit_ids,
               "anchorManifestJsonSha256": json_sha(anchors), "alignedSegmentsSha256": sha(aligned),
               "reviewFile": rel(args.review_csv), "reviewFileSha256": sha(args.review_csv),
               "reviewScope": {"mode": scope.get("mode") or "page_checks", "candidateUnits": candidate_units, "heardUnits": heard,
                               "editedUnits": sum(edit_counts), "lookedAtUnits": looked,
                               "approvedByDefaultUnits": max(0, candidate_units - looked) if by_default else 0,
                               "flaggedUnits": scope.get("flaggedUnits"), "flaggedUnheard": scope.get("flaggedUnheard")},
               "decision": {"decisionId": record["decisionId"], "gateId": decision["gateId"], "revision": decision["revision"],
                            "candidateAnchorManifestJsonSha256": decision["bindings"].get("anchorManifestJsonSha256"),
                            "file": rel(decision_copy), "sha256": sha(decision_copy),
                            "authority": args.authority},
               "note": (f"英文表由审核者在审核页提交结论（{len(unit_ids)} 句；改字 {edit_counts[0]} 句、并入上一句 {edit_counts[1]} 句、"
                        f"删除 {edit_counts[2]} 句；听过原声 {heard} 句）。"
                        + (f"审核者没有逐句审完：听过或改过 {looked} 句，其余 {max(0, candidate_units - looked)} 句按默认批准"
                           "（用户 2026-11-25 决定：批准不要求全部审完，剩下的默认批准）。" if by_default else "")
                        + "被批准的是应用这些修改之后的句表。转写为 OpenAI whisper-1 词级时间与段文本，"
                        "gpt-4o-transcribe 第二遍作独立交叉核对；单讲员，未跑说话人区分；不是 MFA 对齐。"
                        + (f" 审核者备注：{decision['note']}" if decision.get("note") else "")
                        + (" 这是演练，不是人工审核，不能用于翻译或发布。" if args.rehearsal else ""))}
    receipt_path = out_dir / "english-approval-receipt.json"
    write(receipt_path, receipt)

    package = {
        "schemaVersion": "sermon-english-source-package-v1",
        "status": "ready_for_translation" if human else "rehearsal_not_for_translation",
        "translationEligible": human,
        "source": {"sourceUrl": anchors["input"]["sourceUrl"], "sourceUrlHash": sha_bytes(anchors["input"]["sourceUrl"].encode()),
                   "date": anchors["input"]["date"],
                   "approvedWindow": {**window, "evidence": evidence(window_path, window)},
                   "media": {"sha256": media_sha, "durationSeconds": duration, "file": rel(args.media)}},
        "transcript": {"model": args.timing_model, "textModel": args.text_model, "artifact": evidence(aligned),
                       "upload": rel(args.upload), "uploadSha256": sha(args.upload),
                       "rawText": rel(args.raw_text), "rawTextSha256": sha(args.raw_text),
                       "note": "whisper-1 提供词级时间，gpt-4o-transcribe 提供文本；不是 MFA 音素对齐。"},
        "anchors": {"artifact": evidence(args.anchor, anchors), "sourceUnitCount": len(units), "policy": anchors["policy"],
                    "input": {"mfaSegmentsSha256": sha(aligned),
                              "note": "字段名沿用正式 schema；实际绑定的是 whisper-1 词级转写，不是 MFA 段文件。"}},
        "units": units,
        "review": {**receipt, "evidence": evidence(receipt_path, receipt)},
        "evidence": [evidence(args.anchor, anchors), evidence(aligned), evidence(window_path, window),
                     evidence(receipt_path, receipt), evidence(args.review_csv), evidence(decision_copy, record)],
    }
    write(args.out, package)
    summary = {"out": str(args.out), "units": len(units), "jsonSha256": json_sha(package), "status": package["status"],
               "humanApproval": human, "receiptSha256": sha(receipt_path)}
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--anchor", type=Path, required=True, help="the revised anchor-manifest.json")
    parser.add_argument("--words", type=Path, required=True, help="words.json from the timing pass")
    parser.add_argument("--raw-text", type=Path, required=True, help="raw-gpt-4o-transcribe.txt")
    parser.add_argument("--upload", type=Path, required=True, help="the audio that was sent for transcription")
    parser.add_argument("--media", type=Path, required=True, help="the source media file")
    parser.add_argument("--review-csv", type=Path, required=True)
    parser.add_argument("--decision", type=Path, required=True, help="the decision record the review service stored")
    parser.add_argument("--authority", required=True, help="where the rule that a page decision is a formal conclusion is recorded")
    parser.add_argument("--root", type=Path, required=True, help="base for the relative evidence paths (the checkout root)")
    parser.add_argument("--out", type=Path, required=True, help="english-source.json; the receipts are written next to it")
    parser.add_argument("--timing-model", default="whisper-1")
    parser.add_argument("--text-model", default="gpt-4o-transcribe")
    parser.add_argument("--rehearsal", action="store_true", help="write everything, approve nothing")
    return parser


def main(argv=None) -> int:
    build(build_parser().parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
