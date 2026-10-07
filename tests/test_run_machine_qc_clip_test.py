"""The local machine-QC clip driver: discovery, preflight, ledger, calibration and waiver."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts import machine_quality_release_basis as basis
from scripts import machine_repair_ledger as ledger
from scripts import run_machine_qc_clip_test as driver
from scripts import sermon_sentence_interpretation as interpretation
from scripts import build_english_source_package as english_source
from tests import auto_qc_fixtures as qc_fixtures
from tests import test_build_english_source_package as source_fixtures
from tests import test_prepare_target_language_speech_job as speech_fixtures

LOCALE = "ko"


def synthetic_run(test: unittest.TestCase, root: Path, *, human_approved: bool = False) -> Path:
    """A Dev run with a real English source package and a model-reviewed ko candidate."""
    source = source_fixtures.EnglishSourcePackageTests()
    source.setUp()
    test.addCleanup(source.doCleanups)
    segments = []
    for index, text in enumerate(qc_fixtures.ENGLISH):
        words = text.split()
        start = index * 6.0
        segments.append({"id": index, "referenceChunkId": "block-1", "text": text,
                         "start": start, "end": start + len(words) * .3,
                         "sentenceBoundarySource": "frozen_reference_punctuation",
                         "wordTimes": [{"text": word, "start": start + n * .3, "end": start + (n + 1) * .3}
                                       for n, word in enumerate(words)]})
    source_fixtures.write_json(source.segments_path, segments)
    anchor = interpretation.build_anchor_manifest(segments, source_path=source.segments_path,
                                                  unit_policy=interpretation.UNIT_POLICY_V2)
    source_fixtures.write_json(source.manifest_path, anchor)
    review_path = source.root / "review.json"
    source_fixtures.write_json(review_path, {
        "schemaVersion": english_source.REVIEW_SCHEMA_VERSION,
        "alignedSegmentsSha256": english_source.file_sha256(source.segments_path),
        "anchorManifestJsonSha256": interpretation.json_sha256(anchor), "humanApproval": True,
        "reviewedBy": "Synthetic fixture reviewer", "reviewedAt": "2026-09-30T00:00:00Z",
        "reviewedSourceUnitIds": [u["sourceUnitId"] for u in anchor["sourceUnits"]],
        "checks": {name: "approved" for name in english_source.APPROVED_CHECKS}})
    package = source.build(review_path=review_path)
    policy = qc_fixtures.policy(LOCALE)
    units = anchor["sourceUnits"]
    test.assertEqual(len(units), len(qc_fixtures.ENGLISH))
    groups = [speech_fixtures.TargetLanguageSpeechJobTests.group(f"g{i:03d}", unit["sourceUnitId"], text)
              for i, (unit, text) in enumerate(zip(units, qc_fixtures.TARGET[LOCALE]), start=1)]
    ids = [group["translationGroupId"] for group in groups]
    candidate = {"schemaVersion": "sermon-target-language-candidate-v2", "sourceLocale": "en",
                 "targetLocale": LOCALE, "englishSourcePackageJsonSha256": basis.json_sha256(package),
                 "anchorManifestSha256": basis.json_sha256(anchor),
                 "translationPolicySha256": basis.json_sha256(policy),
                 "status": "human_translation_approved" if human_approved else basis.MACHINE_PENDING_CANDIDATE,
                 "releaseEligible": False, "groups": groups,
                 "modelReview": {"status": "pass", "reviewedGroupIds": ids},
                 "humanReview": {"translation": "pending", "reviewer": None, "reviewedAt": None,
                                 "reviewedGroupIds": []}}
    run = root / "run"
    for name, value in (("source-package.json", package), ("anchor-manifest.json", anchor),
                        ("policy/ko.json", policy),
                        ("diagnostic-previews/ko/native-1/candidate.json", candidate)):
        path = run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return run


class MachineQcClipDriverTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_driver(self, run, *extra):
        return driver.main(["--run-dir", str(run), "--out", str(self.root / "out"), "--locales", LOCALE,
                            "--text-backend", "fake", *extra])

    def summary(self):
        return json.loads((self.root / "out/summary.json").read_text(encoding="utf-8"))["locales"][LOCALE]

    def test_fake_backend_reaches_text_waiver_and_records_ledger(self):
        run = synthetic_run(self, self.root)
        self.assertEqual(self.run_driver(run), 0)
        row = self.summary()
        self.assertEqual(row["status"], "text_waiver_issued", row.get("reason"))
        self.assertEqual(row["calibrationCoverage"]["untestableKinds"], [])
        waiver = json.loads(Path(row["textWaiver"]).read_text(encoding="utf-8"))
        self.assertFalse(waiver["humanApproval"])
        self.assertEqual(waiver["reviewKind"], "machine_quality_waiver")
        candidate = json.loads(Path(row["paths"]["candidate"]).read_text(encoding="utf-8"))
        basis.validate_text_waiver(waiver, candidate=candidate)
        timings = (self.root / "out/timings.tsv").read_text(encoding="utf-8")
        for stage in ("discover", "ko.text-qc", "ko.calibration", "ko.text-waiver"):
            self.assertIn(f"\n{stage}\tpass\t", timings)

    def test_rerun_resumes_without_a_second_ledger_entry(self):
        run = synthetic_run(self, self.root)
        self.assertEqual(self.run_driver(run), 0)
        self.assertEqual(self.run_driver(run), 0)
        anchor = json.loads((run / "anchor-manifest.json").read_text(encoding="utf-8"))
        package = json.loads((run / "source-package.json").read_text(encoding="utf-8"))
        lineage = ledger.lineage("text", LOCALE, basis.json_sha256(package), basis.json_sha256(anchor))
        self.assertEqual(len(ledger.load(self.root / "out/state/repair-ledger", lineage)), 1)

    def test_preflight_explains_a_human_approved_candidate(self):
        run = synthetic_run(self, self.root, human_approved=True)
        self.assertEqual(self.run_driver(run, "--preflight-only"), 2)
        row = self.summary()
        self.assertEqual(row["status"], "blocked")
        self.assertTrue(any("status is 'human_translation_approved'" in p for p in row["problems"]))

    def test_prefetch_issues_each_request_once_and_in_dependency_order(self):
        calls = []

        class Judge(driver.FakeJudge):
            def __init__(self, groups):
                super().__init__(groups)
                self.done = {}

            def key(self, *request):
                return json.dumps(request, sort_keys=True)

            def cached(self, *request):
                return self.done.get(self.key(*request))

            def __call__(self, *request):
                calls.append(request[0])
                self.done[self.key(*request)] = value = super().__call__(*request)
                return value

        groups = qc_fixtures.groups(LOCALE)
        judge = Judge({LOCALE: groups})
        issued = driver.prefetch(judge, lambda call: [driver.text_qc.back_translate(g, LOCALE, call)
                                                      for g in groups], workers=4)
        self.assertEqual(issued, 2 * len(groups))
        self.assertEqual(calls[:len(groups)], ["back_translator"] * len(groups))
        before = len(calls)
        [driver.text_qc.back_translate(g, LOCALE, judge.cached) for g in groups]
        self.assertEqual(len(calls), before)

    def test_codex_judge_uses_sol_medium_and_a_per_request_cache(self):
        from unittest.mock import patch
        from scripts import sermon_codex_transport as codex
        seen = []

        def fake_call(prompt, **options):
            seen.append(options)
            return {"english": "x"}

        with patch.object(driver.subprocess, "check_output", return_value="codex-cli 9.9.9\n"), \
                patch.object(codex, "call_json", side_effect=fake_call):
            judge = driver.CodexJudge(self.root / "calls")
            judge("back_translator", "sys", "본문", {"type": "object"})
            judge("back_translator", "sys", "다른 본문", {"type": "object"})
        self.assertEqual(judge.identity["model"], codex.TEXT_MODEL)
        self.assertEqual(judge.identity["modelRevision"], "codex-cli 9.9.9")
        self.assertEqual([(o["model"], o["reasoning"]) for o in seen], [(codex.TEXT_MODEL, "medium")] * 2)
        self.assertNotEqual(seen[0]["output_dir"], seen[1]["output_dir"])
        self.assertIsNone(judge.cached("back_translator", "sys", "본문", {"type": "object"}))


if __name__ == "__main__":
    unittest.main()
