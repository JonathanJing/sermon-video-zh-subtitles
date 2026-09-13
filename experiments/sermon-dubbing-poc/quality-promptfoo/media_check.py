"""Read-only decode, duration and existing acoustic-timing revalidation; no synthesis."""
import argparse
from functools import partial
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
POC = HERE.parent
ROOT = POC.parents[1]
sys.path[:0] = [str(POC), str(ROOT)]
from poc import probe, sha256
from scripts.sermon_execution_harness import bounded_process


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decode(path, expected_hash, expected_duration, *, tolerance=.25):
    require(path.is_file() and sha256(path) == expected_hash, "media_hash_mismatch")
    bounded_process(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-f", "null", "-"],
                    timeout=300, check=True, capture_output=True, text=True)
    info = probe(path, process_runner=partial(bounded_process, timeout=60))
    require(type(expected_duration) in (float, int) and expected_duration > 0, "expected_duration_missing")
    delta = abs(info["durationSeconds"] - expected_duration)
    require(delta <= tolerance, "decoded_duration_differs_from_bound_report")
    require(sha256(path) == expected_hash, "media_changed_during_check")
    return {"sha256": expected_hash, "fullDecode": "pass", "durationSeconds": info["durationSeconds"],
            "expectedDurationSeconds": expected_duration, "durationDeltaSeconds": round(delta, 6)}


def check_media(work):
    work = Path(work).resolve()
    result = {"schemaVersion": "sermon-quality-media-check-v1", "status": "fail", "checks": {},
              "humanListening": "not_performed", "humanAcceptance": "not_evaluated", "modelCalls": 0}
    try:
        from weekly_dubbing import validate_frozen
        from check_weekly_timing import load_anchors, load_placements, budgets, anchor_review_type
        job = read(work / "job.json")
        job_hash = sha256(work / "job.json")
        result["jobSha256"] = job_hash
        validate_frozen(job)
        render = read(work / "render/report.json")
        screening = read(work / "audio/asr-screening.json")
        timing = read(work / "synchronization/report.json")
        assembly = read(work / "synchronization/assembly.json")
        require(all(report.get("jobSha256") == job_hash for report in (render, screening, timing, assembly)), "reports_bound_to_different_job")
        require(len(render.get("cues", [])) == len(job["units"]) and
                [cue["text"] for cue in render["cues"]] == [unit["text"] for unit in job["units"]], "render_text_or_unit_coverage_changed")
        result["checks"]["naturalWav"] = decode(work / "render/chinese.raw.wav", render["sha256"], render["durationSeconds"])
        natural_hash = assembly["sourceNaturalMp3Sha256"]
        matching = [row for row in screening.get("results", []) if row.get("sha256") == natural_hash]
        require(len(matching) == 1, "natural_screening_missing_or_ambiguous")
        natural = matching[0]
        require(natural.get("fullDecode") == "pass" and natural.get("screenedUnits") == natural.get("expectedUnits") == len(job["units"]), "screening_unit_coverage_changed")
        result["checks"]["naturalMp3"] = decode(work / "audio/zh-natural.mp3", natural_hash, natural["durationSeconds"])
        result["checks"]["sourceClip"] = decode(Path(job["inputs"]["sourceAudio"]["path"]), job["inputs"]["sourceAudio"]["sha256"], job["sourceDurationSeconds"])
        require(assembly.get("sourceNaturalWavSha256") == render["sha256"] and
                assembly.get("timingReportSha256") == sha256(work / "synchronization/report.json"), "synchronized_assembly_evidence_changed")
        anchors, approval_hash = load_anchors(work, job, job_hash)
        placements, placement_hash = load_placements(work, job, render, anchors)
        require(timing.get("alignmentSha256") == sha256(work / "source-alignment/report.json") and
                timing.get("anchorReviewSha256") == approval_hash and timing.get("placementReviewSha256") == placement_hash, "timing_review_evidence_changed")
        rows, failures = budgets(job["blocks"], anchors, render["cues"], job["sourceDurationSeconds"], placements)
        require(timing.get("blocks") == rows and timing.get("failures") == failures, "saved_timing_differs_from_recomputed_budgets")
        require(not failures and timing.get("status") == "natural_timing_fits", "natural_speech_does_not_fit_timing")
        result["checks"]["synchronizedMp3"] = decode(work / "synchronization/zh-synced.mp3", assembly["sha256"], job["sourceDurationSeconds"])
        require(abs(result["checks"]["synchronizedMp3"]["durationSeconds"] - assembly["durationSeconds"]) <= .25, "synchronized_assembly_duration_changed")
        result["checks"]["timing"] = {"status": "pass", "blocks": len(rows), "failures": [], "anchorReviewType": anchor_review_type(work),
                                      "timingReportSha256": sha256(work / "synchronization/report.json")}
        result["asrReviewCandidateCount"] = len(natural.get("reviewCandidates", []))
        result["status"] = "pass"
    except Exception as exc:
        result["errorType"] = type(exc).__name__
        # Preserve only fixed validation codes; never echo subprocess stderr or command args.
        result["reason"] = str(exc) if isinstance(exc, ValueError) else "media_validation_could_not_complete"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.resolve().is_relative_to(args.work.resolve()):
        parser.error("Write the check outside the original production job to preserve it")
    if args.out.exists():
        parser.error("Use a new output report; prior evidence is preserved")
    report = check_media(args.work)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.out.chmod(0o600)
    print(json.dumps({"status": report["status"], "report": str(args.out)}, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
