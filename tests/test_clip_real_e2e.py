"""Real-model clip E2E entry: specification, budget accounting, stage order and Spark command shape (no network)."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from scripts import clip_e2e_release as release
from scripts import clip_e2e_spark as spark
from scripts import run_clip_real_e2e as subject

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ("ko", "es", "zh-Hans")
DISPLAY = {"series": "[test] s", "title": "[test] t", "speaker": "Speaker", "scripture": "Rev 9", "summary": "[test] x"}


def spec_files(base: Path, **changes) -> Path:
    for name in ("clip.json", "registry.json", *[f"{k}-{kind}" for k in ("ko", "es", "zh-Hans")
                                                  for kind in ("policy.json", "att.json", "plugin.py")]):
        (base / name).write_text("{}")
    spec = {"schemaVersion": subject.SPEC_SCHEMA, "name": "u101-test", "clipSpec": "clip.json", "locales": ["ko", "es", "zh-Hans"],
            "authorization": {"approvedBy": "Jony", "evidence": "chat 2026-10-14",
                              "defaultPass": "isolated-test default pass authorized by Jony; not a human review"},
            "budget": {"totalUsd": 30, "settledUsdBefore": 15.3},
            "layer2": {"policyTemplates": {k: f"{k}-policy.json" for k in LOCALES},
                       "plugins": {k: f"{k}-plugin.py" for k in LOCALES}},
            "layer3": {"attestationTemplates": {k: f"{k}-att.json" for k in LOCALES}, "speakerRegistry": "registry.json"},
            "page": {"pageId": "mockup-dev-clip-test", "display": {k: DISPLAY for k in LOCALES}}}
    for key, value in changes.items():
        spec[key] = value
    path = base / "spec.json"
    path.write_text(json.dumps(spec))
    return path


class SpecificationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)

    def test_paths_resolve_beside_the_specification_and_defaults_apply(self):
        spec = subject.load_spec(spec_files(self.base))
        self.assertEqual(spec["layer2"]["policyTemplates"]["ko"], str((self.base / "ko-policy.json").resolve()))
        self.assertEqual(spec["clipSpec"], str((self.base / "clip.json").resolve()))
        self.assertEqual((spec["qc"]["maxRevisions"], spec["openai"]["environment"], spec["layer3"]["maxEndLagSeconds"]),
                         (2, "dev", 120.0))
        self.assertEqual(spec["spark"]["sessionId"], "clip-e2e-u101-test")

    def test_unsafe_or_incomplete_specifications_are_refused(self):
        page = {"pageId": "dev-weekly", "display": {k: DISPLAY for k in LOCALES}}
        bad = [({"page": page}, "mockup- page"),
               ({"authorization": {"approvedBy": "Jony", "evidence": "chat", "defaultPass": "approved"}}, "not a human review"),
               ({"budget": {"totalUsd": 10, "settledUsdBefore": 12}}, "totalUsd > settledUsdBefore"),
               ({"locales": ["ko", "es"]}, "the Dev publisher joins all three"),
               ({"page": {"pageId": "mockup-x", "display": {k: DISPLAY for k in LOCALES},
                          "baselineCachePublic": "public"}}, "go together"),
               ({"extra": 1}, "unknown run specification field"),
               ({"layer3": {"attestationTemplates": {"ko": "ko-att.json", "es": "es-att.json"},
                            "speakerRegistry": "registry.json"}},
                "attestationTemplates missing a locale"),
               ({"page": {"pageId": "mockup-x", "display": {"ko": DISPLAY, "es": DISPLAY}}}, "display texts missing")]
        for changes, message in bad:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                subject.load_spec(spec_files(self.base, **changes))

    def test_the_run_directory_must_be_mirrorable_under_artifacts(self):
        with self.assertRaisesRegex(ValueError, "under artifacts/"):
            subject.Run(spec_files(self.base), self.base / "run", publish=False)


class RunTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        (ROOT / "artifacts").mkdir(exist_ok=True)
        self.run_dir = Path(tempfile.mkdtemp(prefix="test-clip-e2e-", dir=ROOT / "artifacts"))
        self.addCleanup(shutil.rmtree, self.run_dir, True)
        self.run = subject.Run(spec_files(self.base), self.run_dir, publish=False)

    def test_clip_inputs_are_bound_to_the_clip_specification(self):
        from scripts.build_dev_180s_simulated_inputs import TEST_ROOT
        clip_sha = __import__("hashlib").sha256(Path(self.run.spec["clipSpec"]).read_bytes()).hexdigest()
        folder = TEST_ROOT / f"clip-e2e-{self.run.spec['name']}-{clip_sha[:12]}"
        folder.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, folder, True)
        (folder / "clip-spec.sha256").write_text("0" * 64)
        with self.assertRaisesRegex(ValueError, "another clip specification"):
            subject.stage_inputs(self.run)

    def test_a_run_directory_stays_bound_to_its_specification(self):
        other = spec_files(self.base, budget={"totalUsd": 40, "settledUsdBefore": 15.3})
        with self.assertRaisesRegex(ValueError, "another specification"):
            subject.Run(other, self.run_dir, publish=False)

    def test_settled_spend_counts_layer2_results_priced_qc_and_unpriced_reservations(self):
        subject.write(self.run_dir / "l2/.layer2-jobs.layer2-budget/x/a.result.json",
                      {"result": {"usage": {"costMicrousd": 200_000}}})
        subject.write(self.run_dir / "plans/qc-ko/qc-ko/.api-budget/source-budget.json", {"requests": {
            "a": {"status": "returned", "bounds": {"costMicrousd": 9_000},
                  "settlement": {"costStatus": "estimated_upper_bound", "costMicrousd": 3_000, "requestedModel": "m"}},
            "b": {"status": "returned", "bounds": {"costMicrousd": 13_500},
                  "settlement": {"costStatus": "unknown", "reasonCode": "missing_or_invalid_token_counts",
                                 "requestedModel": "gpt-transcribe"}},
            "c": {"status": "returned", "bounds": {"costMicrousd": 50_000},
                  "settlement": {"costStatus": "reused", "costMicrousd": 0}}}})
        self.assertAlmostEqual(self.run.settled(), 15.3 + 0.2 + 0.003 + 0.0135)

    def test_open_qc_caps_count_until_the_locale_finishes_audio(self):
        for locale in LOCALES:
            subject.write(self.run_dir / f"plans/qc-{locale}/plan.json", {"stages": [{"capUsd": 5.525}]})
        self.assertAlmostEqual(self.run.open_qc_caps(), 16.575)
        self.run.mark("audio.ko", "done")
        self.run.mark("audio.es", "failed")
        self.assertAlmostEqual(self.run.open_qc_caps(), 5.525)

    def test_one_locale_stopping_does_not_stop_the_others_and_layer4_needs_all(self):
        calls = []
        record = lambda name: (lambda run, *args: (calls.append((name, *args[:1])), run.mark(name, "done")))

        def qc(run, locale):
            calls.append(("qc", locale))
            if locale == "ko":
                raise subject.Stop("qc.ko: requires_repair after 2 revision(s)")
            run.mark("qc." + locale, "done")

        def audio(run, locale, code):
            calls.append(("audio", locale, code))
            run.mark("audio." + locale, "done")
        with mock.patch.object(subject, "stage_inputs", record("inputs")), \
                mock.patch.object(subject, "stage_layer2_setup", record("layer2-setup")), \
                mock.patch.object(subject, "stage_layer2", record("layer2")), \
                mock.patch.object(subject, "stage_qc", qc), mock.patch.object(subject, "stage_audio", audio), \
                mock.patch.object(subject, "ensure_session", lambda run: setattr(run, "session_up", True)), \
                mock.patch.object(subject, "finish_session", lambda run: setattr(run, "session_up", False)), \
                mock.patch.object(subject, "stage_code", lambda run: "repo-test"), \
                mock.patch.object(subject, "stage_layer4", record("layer4")), \
                mock.patch.object(subject, "stage_report", record("report")):
            summary = subject.execute(self.run)
            self.assertEqual(calls, [("inputs",), ("layer2-setup",), ("layer2",), ("qc", "ko"), ("qc", "es"),
                                     ("qc", "zh-Hans"), ("audio", "es", "repo-test"), ("audio", "zh-Hans", "repo-test"),
                                     ("report",)])
            self.assertEqual(len(summary["stopped"]), 2)
            self.assertIn("layer4 needs every locale", summary["stopped"][1])
            # A resumed run skips finished stages and retries only what is left.
            calls.clear()
            subject.execute(self.run)
            self.assertEqual(calls, [("qc", "ko"), ("report",)])  # every invocation leaves a report
            # A recorded terminal failure is reported, not retried.
            calls.clear()
            self.run.mark("qc.ko", "failed", outcome="requires_repair")
            summary = subject.execute(self.run)
            self.assertEqual(calls, [("report",)])
            self.assertIn("qc.ko: failed earlier", summary["stopped"][0])

    def test_qc_never_rechecks_an_unchanged_candidate_and_resumes_into_its_revision(self):
        checks, revisions = [], []

        def text_qc(run, locale, candidate, out_name):
            checks.append((str(candidate), out_name))
            passed = str(candidate).endswith("r1/candidate.json")
            return {"status": "text_waiver_issued" if passed else "requires_repair", "failedGroups": [] if passed else ["g8"],
                    "receipt": "receipt.json", "waiverDir": "waivers" if passed else None}

        def revise(run, locale, receipt, number):
            revisions.append(number)
            return self.run_dir / f"l2-{locale}-r{number}/candidate.json"
        self.run.mark("qc.ko", "running", candidate=str(self.run_dir / "l2/text/ko/candidate.json"), history=[
            {"candidate": str(self.run_dir / "l2/text/ko/candidate.json"), "out": "out", "status": "requires_repair",
             "failedGroups": ["g8"], "receipt": "receipt.json", "waiverDir": None}])
        with mock.patch.object(subject.Run, "plan", lambda *a, **k: None), \
                mock.patch.object(subject, "text_qc", text_qc), mock.patch.object(subject, "revise", revise):
            subject.stage_qc(self.run, "ko")
        self.assertEqual(revisions, [1])
        # The recorded requires_repair of the first candidate is not checked again.
        self.assertEqual(checks, [(str(self.run_dir / "l2-ko-r1/candidate.json"), "out-r1")])
        self.assertEqual(self.run.stages["qc.ko"]["status"], "done")


class ReviewFixTests(unittest.TestCase):
    """Behaviour asked for in the review of #403."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)

    def test_approvers_and_approval_quotes_never_enter_command_logs(self):
        shown = subject.redacted(["plan", "--approved-by", "Jony", "--evidence", "chat quote", "--total-usd", "30"])
        self.assertEqual(shown, ["plan", "--approved-by", "<redacted>", "--evidence", "<redacted>", "--total-usd", "30"])

    def test_a_spark_stage_is_skipped_only_after_an_accepted_known_result(self):
        result = self.base / "compact.result.json"
        self.assertFalse(subject.spark_result(result))
        result.write_text(json.dumps({"exitCode": 0, "outcome": "known_terminal"}))
        self.assertTrue(subject.spark_result(result))
        for bad in ({"exitCode": 1, "outcome": "known_terminal"}, {"exitCode": 0, "outcome": "unknown", "readback": "failed"}):
            result.write_text(json.dumps(bad))
            with self.subTest(result=bad), self.assertRaisesRegex(subject.Stop, "reconcile"):
                subject.spark_result(result)
        result.write_text(json.dumps({"exitCode": 1, "outcome": "known_terminal"}))
        self.assertTrue(subject.spark_result(result, accept=(0, 1)))  # render: its own screen flagged units

    def test_a_failed_readback_records_an_unknown_outcome(self):
        session = mock.Mock()
        path = self.base / "screen.result.json"
        code = spark.finish(session, {"jobId": "j"}, 0, "known_terminal", path, {"phase": "screen"}, read_back=False)
        self.assertEqual((code, json.loads(path.read_text())), (3, {"exitCode": 0, "outcome": "unknown", "readback": "failed"}))
        session.end_job.assert_called_once_with({"jobId": "j"}, process_exited=True, outcome="unknown")

    def test_the_session_is_held_on_the_runtime_host(self):
        runtime = spark.load_runtime()
        env = {"SPARK_EXCLUSIVE_SESSION_ID": "clip-e2e-x", "SPARK_EXCLUSIVE_SESSION_OWNER": "clip-e2e-x",
               "SPARK_EXCLUSIVE_HOST": "someone@elsewhere"}
        with mock.patch.dict("os.environ", env), self.assertRaisesRegex(ValueError, "spark_session_host_differs"):
            spark.main(["screen", "--locale", "ko", "--stage", runtime["stageRoot"] + "/clip-e2e-x", "--code", "repo-x",
                        "--job", "job.json"])

    def test_a_qc_repair_revision_gets_its_own_layer2_budget_root(self):
        from types import SimpleNamespace
        from scripts import canonical_layer2_budget as budget
        jobs = self.base / "l2" / "layer2-jobs"
        first = SimpleNamespace(job_root=jobs, auto_repair={"routingVersion": "v"}, sha256="a" * 64)
        revision = SimpleNamespace(job_root=jobs, auto_repair={"backTranslationQc": {"ko": "qc.json"}}, sha256="b" * 64)
        self.assertEqual(budget.budget_root(first), self.base / "l2" / ".layer2-jobs.layer2-budget")
        self.assertEqual(budget.budget_root(revision), budget.budget_root(first) / ("revision-" + "b" * 16))


class SparkTests(unittest.TestCase):
    def test_tracked_runtime_is_valid_and_a_stage_must_sit_under_its_root(self):
        runtime = spark.load_runtime()
        with self.assertRaisesRegex(ValueError, "stage_outside_runtime_stage_root"):
            spark.main(["screen", "--locale", "ko", "--stage", "/tmp/elsewhere", "--code", "repo-x",
                        "--job", "job.json"])
        self.assertTrue(runtime["stageRoot"].startswith(runtime["remoteHome"]))

    def test_render_command_holds_each_flag_once_after_the_prefix(self):
        runtime = spark.load_runtime()
        blob = lambda name: "/work/blobs/" + name
        tail = spark.render_command(runtime, "/stage", "repo-x", blob, "/work/output/ko-raw/speech-job",
                                    max_end_lag=120.0, unit_instructions=None)
        command = [*spark.RENDER_PREFIX, *tail]
        self.assertEqual(command.count("--user"), 1)
        self.assertEqual(command.count("1000:1000"), 1)
        self.assertEqual(tail[0], "--tmpfs")
        self.assertIn(runtime["images"]["tts"], command)
        self.assertEqual(command[command.index("--max-end-lag-seconds") + 1], "120.0")
        self.assertNotIn("--unit-instructions", command)

    def test_mirrored_paths_must_be_under_the_mirror_root(self):
        root = ROOT / "artifacts"
        self.assertEqual(spark.mirrored(root / "x/y.json", root), str((root / "x/y.json").resolve()))
        with self.assertRaisesRegex(ValueError, "not under the mirrored artifacts root"):
            spark.mirrored("/tmp/elsewhere.json", root)


class ReleaseTests(unittest.TestCase):
    def test_release_refuses_a_shared_page_an_unlabelled_pass_or_missing_texts(self):
        common = dict(date="2026-10-11", locales=["ko"], source_path=Path("s"), anchor_path=Path("a"), lanes={},
                      display={"ko": DISPLAY})
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(ValueError, "isolated mockup-/dev- page"):
                release.prepare(Path(out), page_id="weekly-page", default_pass="x; not a human review", **common)
            with self.assertRaisesRegex(ValueError, "not a human review"):
                release.prepare(Path(out), page_id="mockup-x", default_pass="approved", **common)
            with self.assertRaisesRegex(ValueError, "display texts incomplete"):
                release.prepare(Path(out), page_id="mockup-x", default_pass="x; not a human review",
                                **{**common, "display": {"ko": {"title": "t"}}})


if __name__ == "__main__":
    unittest.main()
