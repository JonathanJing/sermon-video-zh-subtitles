"""Offline regression checks over frozen examples; never a publication approval."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

from spoken_text import SUPPORTED_VERSIONS, cardinal, spoken_text

SUITE_SCHEMA = "saturday-quality-suite-v1"
SUITE_SCHEMA_V2 = "saturday-quality-suite-v2"
OUTPUT_SCHEMA = "saturday-quality-output-v1"
OUTPUT_SCHEMA_V2 = "saturday-quality-output-v2"
REPORT_SCHEMA = "saturday-quality-comparison-v1"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def text_hash(text):
    return digest(text.encode("utf-8"))


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def load_suite(path):
    suite = read(path)
    require(suite.get("schemaVersion") in {SUITE_SCHEMA, SUITE_SCHEMA_V2}, "unsupported suite schema")
    version2 = suite["schemaVersion"] == SUITE_SCHEMA_V2
    require(suite.get("pronunciationRuleVersion") in SUPPORTED_VERSIONS, "unsupported pronunciation rules")
    require(type(suite.get("requireAudioEvidence")) is bool, "requireAudioEvidence must be boolean")
    samples = suite.get("samples")
    require(isinstance(samples, list) and bool(samples), "suite must have samples")
    ids = []
    for sample in samples:
        require(isinstance(sample, dict) and nonempty(sample.get("id")), "invalid sample")
        ids.append(sample["id"])
        require(nonempty(sample.get("en")), "sample English is missing")
        require(sample.get("sourceSha256") == text_hash(sample["en"]), "sample source hash mismatch")
        provenance = sample.get("provenance", {})
        require(provenance.get("kind") in ({"model_reviewed"} if version2 else {"synthetic_fixture", "human_reviewed"}), "sample provenance required")
        if provenance["kind"] == "human_reviewed":
            require(all(nonempty(provenance.get(k)) for k in ("reviewedBy", "reviewedAt", "evidenceReference")),
                    "human reviewed sample needs a reviewer, time and evidence reference")
        constraints = sample.get("constraints")
        require(isinstance(constraints, dict), "sample constraints required")
        for key in ("terms", "numbers", "forbiddenZh"):
            require(isinstance(constraints.get(key), list), "constraint lists required")
        for alternatives in constraints["terms"]:
            require(isinstance(alternatives, list) and alternatives and all(nonempty(x) for x in alternatives), "invalid terms")
        for number in constraints["numbers"]:
            if version2:
                require(isinstance(number, dict) and nonempty(number.get("source")) and
                        type(number.get("value")) is int and 0 <= number["value"] < 10000 and
                        type(number.get("checkRecognized")) is bool, "invalid canonical number rule")
                require(re.fullmatch(r"[0-9]+(?:,[0-9]{3})*", number["source"]) is not None and
                        int(number["source"].replace(",", "")) == number["value"], "canonical number differs from English source value")
            else:
                require(isinstance(number, dict) and all(nonempty(number.get(k)) for k in ("source", "display", "spoken")), "invalid number rule")
            require(number_present(sample["en"], number["source"]) if version2 else number["source"] in sample["en"], "number rule not bound to source English")
        require(all(nonempty(x) for x in constraints["forbiddenZh"]), "invalid forbidden text")
    require(len(set(ids)) == len(ids), "duplicate suite sample IDs")
    if version2:
        job = verified_job(suite.get("modelReviewEvidence"), Path(path).parent)
        by_id = {block["id"]: block for block in job["blocks"]}
        for sample in samples:
            provenance = sample["provenance"]
            block = by_id.get(provenance.get("jobBlockId"))
            require(block and sample["en"] == block["en"] and
                    sample.get("referenceChineseSha256") == text_hash(block["zh"]), "sample differs from model-reviewed source job")
            require(provenance.get("model") == job["spokenReview"]["model"] and provenance.get("humanApproval") is False and
                    provenance.get("reviewArtifactSha256") == job["inputs"]["spokenScriptReview"]["sha256"], "model review identity must remain machine-labelled and bound")
    return suite


def verified_reference(ref, base):
    require(isinstance(ref, dict) and nonempty(ref.get("path")) and nonempty(ref.get("sha256")), "hash-bound local reference required")
    path = (base / ref["path"]).resolve()
    from poc import sha256
    require(sha256(path) == ref["sha256"], "frozen reference bytes changed")
    return path


def verified_job(ref, base):
    job = read(verified_reference(ref, base))
    from weekly_dubbing import validate_frozen
    validate_frozen(job)
    review = job.get("spokenReview", {})
    require(review.get("reviewType") == "model" and review.get("humanApproval") is False and
            review.get("status") == "approved_for_synthesis", "a validated model-reviewed production job is required")
    return job


def verify_recorded_output(output, base):
    job = verified_job(output.get("jobEvidence"), base)
    blocks = {block["id"]: block for block in job["blocks"]}
    measurements = []
    for row in output["samples"]:
        block = blocks.get(row.get("blockId"))
        require(block and row.get("en") == block["en"] and row.get("zh") == block["zh"], "saved output differs from its production job")
        units = [unit for unit in job["units"] if unit["blockId"] == row["blockId"]]
        refs = row.get("unitEvidence")
        require(isinstance(refs, list) and [ref.get("unitId") for ref in refs] == [unit["id"] for unit in units], "complete recorded unit evidence required")
        recognized = []
        for unit, ref in zip(units, refs):
            audio = verified_reference(ref.get("audio"), base)
            screening = read(verified_reference(ref.get("screening"), base))
            expected = unit.get("spokenText", unit["text"])
            identity = screening.get("identity", {})
            require(screening.get("unitId") == unit["id"] and screening.get("blockId") == row["blockId"] and
                    identity.get("audioSha256") == ref["audio"]["sha256"] and identity.get("expected") == expected and
                    nonempty(identity.get("model")) and nonempty(identity.get("revision")) and nonempty(screening.get("recognized")), "ASR receipt is not bound to original audio and speech input")
            recognized.append(screening["recognized"])
            measurements.append({"sampleId": row["id"], "unitId": unit["id"], "audioSha256": ref["audio"]["sha256"],
                                 "asrSimilarity": screening.get("similarity"), "reportedDifferences": len(screening.get("differences", []))})
        require(row.get("spokenZh") == "".join(unit.get("spokenText", unit["text"]) for unit in units) and
                row.get("recognizedZh") == "".join(recognized), "saved speech or recognition changed")
    return measurements


def number_present(text, spelling):
    # Avoid matching 5300 in 15300 or 三千 inside 三千五百.
    return isinstance(text, str) and re.search(r"(?<![0-9零一二三四五六七八九十百千万亿.,])" + re.escape(spelling) +
                                             r"(?![0-9零一二三四五六七八九十百千万亿.,])", text) is not None


def evidence_check(evidence, base, samples):
    """Read existing report formats and their bytes; does not rerun ASR or listen."""
    names = {"job", "naturalAudio", "asrScreening", "timing", "syncedAssembly", "syncedAudio"}
    require(isinstance(evidence, dict) and set(evidence) == names, "incomplete evidence bundle")
    paths = {}
    for name in sorted(names):
        ref = evidence[name]
        require(isinstance(ref, dict) and nonempty(ref.get("path")), "invalid evidence reference")
        path = (base / ref["path"]).resolve()
        require(digest(path.read_bytes()) == ref.get("sha256"), "evidence bytes changed: " + name)
        paths[name] = path
    job, screening, timing, assembly = (read(paths[k]) for k in ("job", "asrScreening", "timing", "syncedAssembly"))
    job_hash = evidence["job"]["sha256"]
    require(job.get("schemaVersion") == "sermon-weekly-dubbing-job-v1" and isinstance(job.get("units"), list) and job["units"], "invalid evidence job")
    blocks = {str(block["id"]): block for block in job.get("blocks", [])}
    for sample in samples:
        block = blocks.get(str(sample.get("blockId")))
        require(block is not None and all(block.get(key) == sample.get(key) for key in ("en", "zh")), "audio job text differs from saved output")
    require(all(report.get("jobSha256") == job_hash for report in (screening, timing, assembly)), "evidence job mismatch")
    results = screening.get("results", [])
    matching = [row for row in results if row.get("sha256") == evidence["naturalAudio"]["sha256"]]
    require(len(matching) == 1, "missing or ambiguous natural audio screening")
    result = matching[0]
    require(result.get("fullDecode") == "pass" and type(result.get("screenedUnits")) is int and type(result.get("expectedUnits")) is int and result.get("screenedUnits") == result.get("expectedUnits") == len(job["units"]), "incomplete audio screening")
    require(timing.get("schemaVersion") == "sermon-video-sync-budget-v1" and timing.get("status") == "natural_timing_fits" and timing.get("failures") == [], "timing did not pass")
    require(assembly.get("fullDecode") == "pass" and assembly.get("sha256") == evidence["syncedAudio"]["sha256"]
            and assembly.get("timingReportSha256") == evidence["timing"]["sha256"]
            and assembly.get("sourceNaturalMp3Sha256") == evidence["naturalAudio"]["sha256"], "synchronized assembly mismatch")
    return {"status": "checked_saved_reports", "screenedUnits": result["screenedUnits"],
            "asrReviewCandidates": len(result.get("reviewCandidates", [])), "humanAcceptance": "not_evaluated"}


def evaluate(suite_path, output_path):
    suite_path, output_path = Path(suite_path), Path(output_path)
    suite = load_suite(suite_path)
    output = read(output_path)
    violations = []

    def fail(sample, rule):
        violations.append({"sampleId": sample, "rule": rule})

    require(output.get("schemaVersion") == (OUTPUT_SCHEMA_V2 if suite["schemaVersion"] == SUITE_SCHEMA_V2 else OUTPUT_SCHEMA), "unsupported output schema")
    require(output.get("suiteSha256") == digest(suite_path.read_bytes()), "output bound to different suite")
    require(nonempty(output.get("identity")), "output model/prompt/run identity required")
    rows = output.get("samples")
    require(isinstance(rows, list), "output samples must be a list")
    require(all(isinstance(row, dict) and nonempty(row.get("id")) for row in rows), "invalid output sample")
    measurements = verify_recorded_output(output, output_path.parent) if suite["schemaVersion"] == SUITE_SCHEMA_V2 else []
    counts = Counter(row["id"] for row in rows)
    expected = {sample["id"] for sample in suite["samples"]}
    for sid in sorted(expected - counts.keys()):
        fail(sid, "missing_sample")
    for sid in sorted(counts.keys() - expected):
        fail(sid, "unexpected_sample")
    for sid, count in sorted(counts.items()):
        if count != 1:
            fail(sid, "duplicate_sample_id")
    by_id = {row["id"]: row for row in rows}
    seen_zh = {}
    for sample in suite["samples"]:
        sid = sample["id"]
        if sid not in by_id:
            continue
        row = by_id[sid]
        if row.get("en") != sample["en"] or row.get("sourceSha256") != sample["sourceSha256"]:
            fail(sid, "source_changed")
        zh, spoken = row.get("zh"), row.get("spokenZh")
        if not nonempty(zh) or not re.search(r"[\u3400-\u9fff]", zh):
            fail(sid, "missing_chinese")
            continue
        if not nonempty(spoken) or spoken != spoken_text(zh, version=suite["pronunciationRuleVersion"]):
            fail(sid, "spoken_text_mismatch")
        normalized = re.sub(r"\W+", "", zh)
        if normalized in seen_zh:
            fail(sid, "duplicate_chinese_segment")
        seen_zh[normalized] = sid
        sentences = [re.sub(r"\s+", "", s) for s in re.split(r"[。！？!?；;]+", zh) if s.strip()]
        if len(sentences) != len(set(sentences)):
            fail(sid, "duplicate_chinese_sentence")
        constraints = sample["constraints"]
        for alternatives in constraints["terms"]:
            if not any(term in zh for term in alternatives):
                fail(sid, "missing_term:" + "|".join(alternatives))
        for number in constraints["numbers"]:
            if suite["schemaVersion"] == SUITE_SCHEMA_V2:
                expected = cardinal(number["value"])
                displays = {number["source"], str(number["value"]), expected}
                if not any(number_present(zh, value) for value in displays):
                    fail(sid, "canonical_number_display:" + str(number["value"]))
                if not number_present(spoken, expected):
                    fail(sid, "canonical_number_spoken:" + str(number["value"]))
                if number["checkRecognized"] and not any(number_present(row.get("recognizedZh"), value) for value in displays):
                    fail(sid, "canonical_number_recognized:" + str(number["value"]))
            elif not re.search(r"(?<![0-9.,])" + re.escape(number["display"]) + r"(?![0-9.,])", zh) or not isinstance(spoken, str) or number["spoken"] not in spoken:
                fail(sid, "number_constraint:" + number["source"])
        for forbidden in constraints["forbiddenZh"]:
            if forbidden in zh:
                fail(sid, "forbidden_text:" + forbidden)
    evidence_result = {"status": "not_provided", "humanAcceptance": "not_evaluated"}
    if output.get("evidence") is not None:
        try:
            evidence_result = evidence_check(output["evidence"], output_path.parent, rows)
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
            fail("__evidence__", "invalid_saved_evidence")
            evidence_result = {"status": "invalid", "error": str(exc), "humanAcceptance": "not_evaluated"}
    elif suite["requireAudioEvidence"]:
        fail("__evidence__", "missing_saved_evidence")
    return {"passed": not violations, "identity": output["identity"], "outputSha256": digest(output_path.read_bytes()),
            "expectedSamples": len(expected), "observedSamples": len(rows), "violations": violations,
            "evidence": evidence_result, "recordedAudioMeasurements": measurements, "humanAcceptance": "not_evaluated"}


def compare(suite_path, baseline_path, candidate_path):
    baseline, candidate = (evaluate(suite_path, path) for path in (baseline_path, candidate_path))
    keys = lambda result: {(v["sampleId"], v["rule"]) for v in result["violations"]}
    old, new = keys(baseline), keys(candidate)
    return {"schemaVersion": REPORT_SCHEMA, "suiteSha256": digest(Path(suite_path).read_bytes()),
            "passed": baseline["passed"] and candidate["passed"], "baseline": baseline, "candidate": candidate,
            "regressions": [{"sampleId": sid, "rule": rule} for sid, rule in sorted(new - old)],
            "resolved": [{"sampleId": sid, "rule": rule} for sid, rule in sorted(old - new)],
            "scope": "offline_deterministic_regression_only", "humanAcceptance": "not_evaluated"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("suite", "baseline", "candidate", "out"):
        parser.add_argument("--" + arg, type=Path, required=True)
    args = parser.parse_args()
    inputs = [args.suite, args.baseline, args.candidate]
    def references(value):
        if isinstance(value, dict):
            if isinstance(value.get("path"), str) and "sha256" in value:
                yield value["path"]
            for nested in value.values():
                yield from references(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from references(nested)
    for path in (args.suite, args.baseline, args.candidate):
        try:
            inputs.extend(path.parent / ref for ref in references(read(path)))
            evidence = read(path).get("evidence", {})
            if isinstance(evidence, dict):
                inputs.extend(path.parent / ref["path"] for ref in evidence.values()
                              if isinstance(ref, dict) and isinstance(ref.get("path"), str))
        except (OSError, ValueError, AttributeError):
            pass  # Normal validation below reports malformed input.
    if any(args.out.resolve() == path.resolve() or
           (args.out.exists() and path.exists() and args.out.samefile(path)) for path in inputs):
        print(json.dumps({"passed": False, "inputError": "Report must not overwrite frozen inputs or evidence"}))
        return 2
    try:
        report = compare(args.suite, args.baseline, args.candidate)
        code = 0 if report["passed"] else 1
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        report = {"schemaVersion": REPORT_SCHEMA, "passed": False, "inputError": str(exc), "humanAcceptance": "not_evaluated"}
        code = 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "report": str(args.out)}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
