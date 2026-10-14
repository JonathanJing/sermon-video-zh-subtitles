"""Real-model clip E2E entry: specification, budget accounting, stage order and Spark command shape (no network)."""
import json
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from scripts import clip_e2e_release as release
from scripts import clip_e2e_spark as spark
from scripts import run_clip_real_e2e as subject

ROOT = Path(__file__).resolve().parents[1]
DISPLAY = {"series": "[test] s", "title": "[test] t", "speaker": "Speaker", "scripture": "Rev 9", "summary": "[test] x"}


def spec_files(base: Path, **changes) -> Path:
    for name in ("clip.json", "registry.json", "ko-policy.json", "es-policy.json", "ko-att.json", "es-att.json",
                 "ko.py", "es.py"):
        (base / name).write_text("{}")
    spec = {"schemaVersion": subject.SPEC_SCHEMA, "name": "u101-test", "clipSpec": "clip.json", "locales": ["ko", "es"],
            "authorization": {"approvedBy": "Jony", "evidence": "chat 2026-10-14",
                              "defaultPass": "isolated-test default pass authorized by Jony; not a human review"},
            "budget": {"totalUsd": 30, "settledUsdBefore": 15.3},
            "layer2": {"policyTemplates": {"ko": "ko-policy.json", "es": "es-policy.json"},
                       "plugins": {"ko": "ko.py", "es": "es.py"}},
            "layer3": {"attestationTemplates": {"ko": "ko-att.json", "es": "es-att.json"}, "speakerRegistry": "registry.json"},
            "page": {"pageId": "mockup-dev-clip-test", "display": {"ko": DISPLAY, "es": DISPLAY}}}
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
        self.assertEqual(spec["layer2"]["backend"], "openai_api")
        self.assertEqual(spec["layer2"]["policyTemplates"]["ko"], str((self.base / "ko-policy.json").resolve()))
        self.assertEqual(spec["clipSpec"], str((self.base / "clip.json").resolve()))
        self.assertEqual((spec["qc"]["maxRevisions"], spec["openai"]["environment"], spec["layer3"]["maxEndLagSeconds"]),
                         (2, "dev", 120.0))
        self.assertEqual(spec["spark"]["sessionId"], "clip-e2e-u101-test")

    def test_unsafe_or_incomplete_specifications_are_refused(self):
        page = {"pageId": "dev-weekly", "display": {"ko": DISPLAY, "es": DISPLAY}}
        bad = [({"page": page}, "mockup- page"),
               ({"authorization": {"approvedBy": "Jony", "evidence": "chat", "defaultPass": "approved"}}, "not a human review"),
               ({"budget": {"totalUsd": 10, "settledUsdBefore": 12}}, "totalUsd > settledUsdBefore"),
               ({"locales": ["ko", "fr"]}, "locales must be"),
               ({"extra": 1}, "unknown run specification field"),
               ({"layer2": {"backend": "claude_cli", "policyTemplates": {"ko": "ko-policy.json", "es": "es-policy.json"},
                             "plugins": {"ko": "ko.py", "es": "es.py"}}}, "layer2.backend must be"),
               ({"layer3": {"attestationTemplates": {"ko": "ko-att.json"}, "speakerRegistry": "registry.json"}},
                "attestationTemplates missing a locale"),
               ({"page": {"pageId": "mockup-x", "display": {"ko": DISPLAY}}}, "display texts missing")]
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

    def test_a_run_directory_stays_bound_to_its_specification(self):
        other = spec_files(self.base, budget={"totalUsd": 40, "settledUsdBefore": 15.3})
        with self.assertRaisesRegex(ValueError, "another specification"):
            subject.Run(other, self.run_dir, publish=False)

    def test_audio_qc_mirror_creates_remote_parent_before_rsync(self):
        calls=[]
        with mock.patch.object(subject.subprocess, "run", side_effect=lambda args, **kwargs: calls.append(args)):
            subject.mirror_run_to_spark(self.run)
        self.assertEqual([args[0] for args in calls], ["ssh", "rsync"])
        self.assertIn("mkdir -p -- ", calls[0][-1])
        self.assertIn("/mac-artifacts/", calls[1][-1])

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

    def test_claude_subscription_list_price_is_separate_from_approved_dollars(self):
        self.run.spec["layer2"]["backend"] = "claude_cli_opus"
        subject.write(self.run_dir / "l2/.layer2-jobs.layer2-budget/x/a.result.json",
                      {"result": {"usage": {"costMicrousd": 200_000}}})
        subject.write(self.run_dir / "plans/qc-ko/qc-ko/.api-budget/source-budget.json", {"requests": {
            "a": {"status": "returned", "bounds": {"costMicrousd": 9_000},
                  "settlement": {"costStatus": "estimated_upper_bound", "costMicrousd": 3_000,
                                 "requestedModel": "gpt-6.1-sol"}}}})
        self.assertAlmostEqual(self.run.settled(), 15.303)
        self.assertAlmostEqual(self.run.claude_list_price_equivalent(), 0.2)

    def test_open_qc_caps_count_until_the_locale_finishes_audio(self):
        for locale in ("ko", "es"):
            subject.write(self.run_dir / f"plans/qc-{locale}/plan.json", {"stages": [{"capUsd": 5.525}]})
        self.assertAlmostEqual(self.run.open_qc_caps(), 11.05)
        self.run.mark("audio.ko", "done")
        self.run.mark("audio.es", "failed")
        self.assertEqual(self.run.open_qc_caps(), 0)

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
                                     ("audio", "es", "repo-test")])
            self.assertEqual(len(summary["stopped"]), 2)
            self.assertIn("layer4 needs every locale", summary["stopped"][1])
            # A resumed run skips finished stages and retries only what is left.
            calls.clear()
            subject.execute(self.run)
            self.assertEqual(calls, [("qc", "ko")])
            # A recorded terminal failure is reported, not retried.
            calls.clear()
            self.run.mark("qc.ko", "failed", outcome="requires_repair")
            summary = subject.execute(self.run)
            self.assertEqual(calls, [])
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

    def test_audio_repair_keeps_the_failed_render_and_checks_a_fresh_seed(self):
        locale, seed = "ko", 43
        source = self.run_dir / "l2/src"
        policy = self.run_dir / "l2/policy"
        waiver_dir = self.run_dir / "textqc-ko/out/ko"
        original = self.run_dir / "l3/ko"
        for folder in (source, policy, waiver_dir, original / "speech-job"):
            folder.mkdir(parents=True, exist_ok=True)
        candidate = self.run_dir / "l2/text/ko/candidate.json"
        files = [source / "source.json", source / "anchor.json", policy / "ko-policy-clip.json",
                 waiver_dir / "text-waiver-test.json", candidate,
                 self.run_dir / "l3/clip-timeline-map.json", original / "clip-voice-authorization.json",
                 original / "speech-job/job.json"]
        for path in files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}")
        self.run.mark("qc.ko", "done", candidate=str(candidate), waiverDir=str(waiver_dir))
        self.run.mark("audio.ko", "failed", qcStatus="requires_repair",
                      failedGroups=["g7"], nextActions={"g7": "resynthesize_new_seed"})
        original_state = dict(self.run.stages["audio.ko"])
        instructions = self.run_dir / "l3/ko-repair-instructions.json"
        instructions.write_text("{}")
        repair = self.run_dir / f"l3/ko-repair-seed-{seed}"
        rendered = repair / f"spark-ko-seed-{seed}-c/spark-output/speech-job"
        qc_out = self.run_dir / f"aqc/ko-seed-{seed}"
        calls = []

        def fake_sh(label, argv, **kwargs):
            calls.append((label, [str(arg) for arg in argv]))
            if label.startswith("render."):
                subject.write(repair / "dispatch.result.json", {"outcome": "known_terminal"})
            elif label.startswith("compact."):
                subject.write(repair / f"compact-ko-seed-{seed}-c.result.json", {"outcome": "known_terminal"})
            elif label.startswith("screen."):
                subject.write(repair / f"spark-ko-seed-{seed}-c/screen-v1.result.json", {"outcome": "known_terminal"})
                for name in ("job.json", "asr-screening-receipt-v1.json", "render-manifest-screened-v1.json"):
                    (rendered / name).parent.mkdir(parents=True, exist_ok=True)
                    (rendered / name).write_text("{}")
            elif label.startswith("package."):
                subject.write(repair / "audio-package.json", {})
            elif label.startswith("audio-qc."):
                subject.write(qc_out / "summary.json", {"locales": {locale: {"status": "audio_waiver_issued"}}})
            return mock.Mock(returncode=0)

        with mock.patch.object(self.run, "check"), mock.patch.object(self.run, "sh", side_effect=fake_sh), \
                mock.patch.object(subject, "mirror_run_to_spark"):
            subject.repair_audio(self.run, locale, seed, "repo-test", unit_instructions=instructions)
        self.assertEqual(self.run.stages["audio.ko"]["status"], "done")
        self.assertEqual(self.run.stages["audio.ko"]["repairedFrom"], ["g7"])
        self.assertEqual(self.run.stages["audio.ko"]["repairAttempts"][0]["status"], "done")
        self.assertEqual(original_state["status"], "failed")
        self.assertFalse((original / "audio-package.json").exists())
        self.assertIn("--seed", calls[0][1])
        self.assertEqual(calls[0][1][calls[0][1].index("--seed") + 1], str(seed))
        self.assertEqual(calls[0][1][calls[0][1].index("--unit-instructions") + 1], str(instructions))
        self.assertEqual(len(self.run.stages["audio.ko"]["repairAttempts"][0]["unitInstructionsSha256"]), 64)
        self.assertEqual([label.split(".")[0] for label, _ in calls],
                         ["render", "compact", "screen", "package", "audio-qc"])

    def test_layer4_resume_uses_bound_publish_and_later_browser_pass_without_redeploy(self):
        self.run.publish = True
        l4 = self.run_dir / "l4"
        page_id = self.run.spec["page"]["pageId"]
        subject.write(l4 / "prepare-result.json", {"status": "succeeded"})
        files = {"preparedManifestSha256": l4 / "work/prepared/preparation-manifest.json",
                 "baselineReceiptSha256": l4 / "baseline/baseline-receipt.json",
                 "baselineSealSha256": l4 / "baseline/seal-report.json"}
        inputs = {"pageId": page_id, "target": {"origin": subject.DEV_ORIGIN}, "contentMode": "machine_checked"}
        for field, path in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(field)
            inputs[field] = hashlib.sha256(path.read_bytes()).hexdigest()
        state = {"status": "diagnostic_dev_http_verified", "inputs": inputs,
                 "completedAt": "2026-10-14T12:00:00+00:00",
                 "stages": {name: {"status": "succeeded"} for name in
                            ("publish_assets", "verify_assets", "publish_catalog", "live_readback")}}
        subject.write(l4 / "workflow/workflow-state.json", state)
        subject.write(l4 / "workflow/run-report.json", {"status": state["status"], "inputs": inputs})
        subject.write(l4 / "browser-smoke.json", {"status": "fail", "pageId": page_id})
        passed = l4 / "browser-smoke-later.json"
        subject.write(passed, {"status": "pass", "pageId": page_id, "origin": subject.DEV_ORIGIN,
                               "checkedAt": "2026-10-14T12:01:00+00:00",
                               "locales": [{"locale": locale, "status": "pass"} for locale in ("ko", "es")]})
        with mock.patch.object(self.run, "sh", side_effect=AssertionError("must not deploy or resmoke")):
            subject.stage_layer4(self.run)
        self.assertEqual(self.run.stages["layer4"]["status"], "done")
        self.assertEqual(self.run.stages["layer4"]["smokeReceipt"], str(passed.resolve()))
        state["status"] = "running"
        subject.write(l4 / "workflow/workflow-state.json", state)
        with mock.patch.object(self.run, "sh", side_effect=AssertionError("must not deploy")), \
                self.assertRaisesRegex(subject.Stop, "needs reconciliation"):
            subject.stage_layer4(self.run)


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
        self.assertEqual(command[command.index("--seed") + 1], "42")
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
