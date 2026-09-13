"""Freeze selected existing model-reviewed blocks and their real saved audio receipts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
POC = HERE.parent
ROOT = POC.parents[1]
sys.path[:0] = [str(POC), str(ROOT)]
from poc import sha256
from quality_harness import load_suite, evaluate
from weekly_dubbing import validate_frozen

BLOCKS = (1, 2, 9, 10, 17, 38, 42, 53)
TERMS = {1: [["优胜美地"], ["半圆顶"]], 2: [["英尺"], ["小时"]], 9: [["埃里克"], ["锁骨"]],
         10: [["树林"]], 17: [["亚萨"], ["沙洛姆"], ["毫无缺失"], ["毫无破损"]],
         38: [["神的国"], ["降服"]], 42: [["我的肉体"], ["避难所"]], 53: [["疑惑"], ["耶稣"]]}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def reference(path, output):
    return {"path": os.path.relpath(path.resolve(), output.resolve()), "sha256": sha256(path)}


def snapshot(work, suite, output):
    job = read(work / "job.json")
    validate_frozen(job)
    blocks = {block["id"]: block for block in job["blocks"]}
    rows = []
    for block_id in BLOCKS:
        block = blocks[block_id]
        units = [unit for unit in job["units"] if unit["blockId"] == block_id]
        receipts = [read(work / f'audio/unit-screening/unit-{unit["id"]:04d}.json') for unit in units]
        rows.append({"id": f"l8ucqF9uA9A-block-{block_id}", "blockId": block_id, "en": block["en"],
                     "sourceSha256": hashlib.sha256(block["en"].encode()).hexdigest(), "zh": block["zh"],
                     "spokenZh": "".join(unit.get("spokenText", unit["text"]) for unit in units),
                     "recognizedZh": "".join(receipt["recognized"] for receipt in receipts),
                     "unitEvidence": [{"unitId": unit["id"],
                                       "audio": reference(work / f'render/unit-{unit["id"]:04d}.wav', output),
                                       "screening": reference(work / f'audio/unit-screening/unit-{unit["id"]:04d}.json', output)} for unit in units]})
    return {"schemaVersion": "saturday-quality-output-v2", "suiteSha256": sha256(suite),
            "identity": f'existing-production-{work.name}; review={job["spokenReview"]["model"]}; pronunciation={job["pronunciationRuleVersion"]}',
            "jobEvidence": reference(work / "job.json", output), "samples": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-work", type=Path, default=ROOT / "artifacts/sermon-dubbing/2026-09-06-live-fallback-v3-numbers")
    parser.add_argument("--known-issue-work", type=Path, default=ROOT / "artifacts/sermon-dubbing/2026-09-06-live-fallback-v2-spoken")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.out_dir.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error("Choose a new empty directory; frozen baselines are never replaced")
    current = args.current_work.resolve()
    job = read(current / "job.json")
    validate_frozen(job)
    out.mkdir(parents=True, exist_ok=True)
    samples = []
    by_id = {block["id"]: block for block in job["blocks"]}
    for block_id in BLOCKS:
        block = by_id[block_id]
        samples.append({"id": f"l8ucqF9uA9A-block-{block_id}", "en": block["en"],
                        "sourceSha256": hashlib.sha256(block["en"].encode()).hexdigest(),
                        "referenceChineseSha256": hashlib.sha256(block["zh"].encode()).hexdigest(),
                        "provenance": {"kind": "model_reviewed", "jobBlockId": block_id, "model": job["spokenReview"]["model"],
                                       "humanApproval": False, "reviewArtifactSha256": job["inputs"]["spokenScriptReview"]["sha256"]},
                        "constraints": {"terms": TERMS[block_id], "forbiddenZh": [],
                                        "numbers": [{"source": "5,300", "value": 5300, "checkRecognized": True},
                                                    {"source": "3,000", "value": 3000, "checkRecognized": True}] if block_id == 2 else []}})
    suite = {"schemaVersion": "saturday-quality-suite-v2", "corpusKind": "existing_model_reviewed_sermon",
             "sourceUrl": job["sourceUrl"], "serviceDate": job["week"], "humanAcceptance": "not_evaluated",
             "pronunciationRuleVersion": job["pronunciationRuleVersion"], "requireAudioEvidence": False,
             "modelReviewEvidence": reference(current / "job.json", out), "samples": samples}
    write(out / "suite.json", suite)
    write(out / "baseline-v3.json", snapshot(current, out / "suite.json", out))
    write(out / "known-issue-v2.json", snapshot(args.known_issue_work.resolve(), out / "suite.json", out))
    load_suite(out / "suite.json")
    result = evaluate(out / "suite.json", out / "baseline-v3.json")
    bad = evaluate(out / "suite.json", out / "known-issue-v2.json")
    write(out / "freeze-receipt.json", {"schemaVersion": "sermon-quality-baseline-freeze-v1", "suiteSha256": sha256(out / "suite.json"),
                                         "baselineSha256": sha256(out / "baseline-v3.json"), "knownIssueSha256": sha256(out / "known-issue-v2.json"),
                                         "sampleIds": [sample["id"] for sample in samples], "baselinePassed": result["passed"],
                                         "knownIssuePassed": bad["passed"], "knownIssueRules": bad["violations"],
                                         "reviewType": "model", "humanApproval": False, "newModelCalls": 0})
    print(json.dumps({"baselinePassed": result["passed"], "knownIssuePassed": bad["passed"], "outDir": str(out)}, ensure_ascii=False))
    return 0 if result["passed"] and not bad["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
