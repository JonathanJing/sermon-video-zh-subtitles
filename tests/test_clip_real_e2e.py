"""Real-model clip E2E entry: specification, budget accounting, stage order and Spark command shape (no network)."""
import json
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

from scripts import clip_e2e_release as release
from scripts import clip_e2e_spark as spark
from scripts import run_clip_real_e2e as subject
from scripts import plan_run_budgets as budgets
from scripts import produce_target_language_candidate as producer
from scripts import target_language_policy as target_policy
from scripts import run_target_language_models as language_models

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

    def test_clip_voice_attestation_is_derived_from_bound_source_permission(self):
        full = {"source": {"sourceId": "sermon-1", "media": {"sha256": "full-media"},
                           "approvedWindow": {"startSeconds": 10.0, "endSeconds": 30.0}}}
        clip_source = {"source": {"sourceId": "sermon-1"}}
        template = {"schemaVersion": "sermon-source-user-voice-attestation-v2",
                    "permissionClaimed": True, "userStatement": "Produce the authorized TTS",
                    "sourceId": "sermon-1", "sourceMediaSha256": "full-media",
                    "approvedWindow": {"startSeconds": 10.0, "endSeconds": 30.0},
                    "targetLocales": ["es"], "speakerId": "speaker-1",
                    "voiceCheckpointSha256": "voice-1"}
        source_path = self.base / "full.json"
        source_path.write_text(json.dumps(full))
        template_path = self.base / "permission.json"
        template_path.write_text(json.dumps(template))
        clip_path = self.base / "clip.json"
        clip_path.write_text(json.dumps({"sourceId": "sermon-1", "approvedWindowStartSeconds": 10.0,
                                         "englishSourcePackage": {"path": str(source_path)}}))
        l2 = self.base / "l2"
        (l2 / "src").mkdir(parents=True)
        (l2 / "src/source.json").write_text(json.dumps(clip_source))
        run = SimpleNamespace(dir=self.base / "run", l2=l2,
                              spec={"clipSpec": str(clip_path),
                                    "layer3": {"attestationTemplates": {"es": str(template_path)}},
                                    "authorization": {"evidence": "Continue isolated Dev E2E"}})
        result = json.loads(subject.attestation(run, "es").read_text())
        self.assertEqual(result["schemaVersion"], "sermon-clip-user-rights-attestation-v1")
        self.assertEqual(result["scope"], "isolated-clip-test-dev-app-and-audio_only")
        self.assertEqual(result["userStatement"], template["userStatement"])
        self.assertEqual(result["derivedFrom"]["sha256"], hashlib.sha256(template_path.read_bytes()).hexdigest())
        template["approvedWindow"]["endSeconds"] = 31.0
        template_path.write_text(json.dumps(template))
        shutil.rmtree(run.dir)
        with self.assertRaisesRegex(ValueError, "not bound"):
            subject.attestation(run, "es")

    def test_paths_resolve_beside_the_specification_and_defaults_apply(self):
        spec = subject.load_spec(spec_files(self.base))
        self.assertEqual(spec["layer2"]["backend"], "openai_api")
        self.assertEqual(spec["layer2"]["policyTemplates"]["ko"], str((self.base / "ko-policy.json").resolve()))
        self.assertEqual(spec["clipSpec"], str((self.base / "clip.json").resolve()))
        self.assertEqual((spec["qc"]["maxRevisions"], spec["openai"]["environment"], spec["layer3"]["maxEndLagSeconds"]),
                         (2, "dev", 120.0))
        self.assertEqual(spec["spark"]["sessionId"], "clip-e2e-u101-test")

    def test_group_acceptance_is_scoped_to_a_run_locale(self):
        spec = subject.load_spec(spec_files(self.base, qc={
            "maxRevisions": 0, "humanAcceptanceByLocale": {"ko": "ko-acceptance.json"}}))
        self.assertEqual(spec["qc"]["humanAcceptanceByLocale"]["ko"],
                         str((self.base / "ko-acceptance.json").resolve()))
        with self.assertRaisesRegex(ValueError, "humanAcceptanceByLocale"):
            subject.load_spec(spec_files(self.base, qc={
                "maxRevisions": 0, "humanAcceptanceByLocale": {"fr": "fr-acceptance.json"}}))

    def test_raised_repair_fraction_is_scoped_to_named_dev_locales(self):
        base = json.loads(spec_files(self.base).read_text())
        layer2 = {**base["layer2"], "repairSpendFractionByLocale": {"ko": 0.30}}
        spec = subject.load_spec(spec_files(self.base, schemaVersion=subject.SCOPED_REPAIR_SPEC_SCHEMA,
                                            layer2=layer2))
        self.assertEqual(spec["layer2"]["repairSpendFractionByLocale"], {"ko": 0.30})
        with self.assertRaisesRegex(ValueError, "specification v2"):
            subject.load_spec(spec_files(self.base, layer2=layer2))
        for bad in ({"fr": 0.30}, {"ko": 0.31}, {"ko": True}):
            with self.assertRaisesRegex(ValueError, "repairSpendFractionByLocale"):
                subject.load_spec(spec_files(self.base, schemaVersion=subject.SCOPED_REPAIR_SPEC_SCHEMA,
                    layer2={**base["layer2"],
                    "repairSpendFractionByLocale": bad}))
        with self.assertRaisesRegex(ValueError, "only supported in isolated Dev runs"):
            subject.load_spec(spec_files(self.base, schemaVersion=subject.SCOPED_REPAIR_SPEC_SCHEMA,
                                         layer2=layer2, openai={"environment": "prod"}))

    def test_single_locale_qc_revision_drops_other_locale_repair_allowances(self):
        base = {"routingVersion": "layer2-auto-repair-routing-v1", "groupWorkers": 8,
                "maxActiveLocales": 3, "repairSpendFractionByLocale": {"ko": 0.30, "zh-Hans": 0.30}}
        ko = subject.revision_repair_binding(base, "ko", "/qc-ko.json")
        es = subject.revision_repair_binding(base, "es", "/qc-es.json")
        self.assertEqual(ko["repairSpendFractionByLocale"], {"ko": 0.30})
        self.assertNotIn("repairSpendFractionByLocale", es)
        self.assertEqual(ko["backTranslationQc"], {"ko": "/qc-ko.json"})
        self.assertEqual(es["maxActiveLocales"], 1)

    def test_source_specific_audio_bindings_are_resolved_per_locale(self):
        raw = json.loads(spec_files(self.base).read_text())
        (self.base / "eric-adapter.json").write_text("{}")
        (self.base / "capability.json").write_text("{}")
        (self.base / "runtime.json").write_text("{}")
        (self.base / "operation-policies.json").write_text("{}")
        raw["layer3"]["adapters"] = {"es": "eric-adapter.json"}
        raw["layer3"]["capabilities"] = {"es": "capability.json"}
        raw["layer3"]["audioOperationPolicies"] = "operation-policies.json"
        raw["layer3"]["reuseAudioFrom"] = {"es": {"runDir": "prior-audio",
            "packageSha256": "a" * 64, "screeningSha256": "b" * 64}}
        raw["spark"] = {"runtimeConfig": "runtime.json"}
        path = self.base / "source-specific.json"
        path.write_text(json.dumps(raw))
        loaded = subject.load_spec(path)
        self.assertEqual(loaded["layer3"]["adapters"]["es"], str((self.base / "eric-adapter.json").resolve()))
        self.assertEqual(loaded["layer3"]["capabilities"]["es"], str((self.base / "capability.json").resolve()))
        self.assertEqual(loaded["spark"]["runtimeConfig"], str((self.base / "runtime.json").resolve()))
        self.assertEqual(loaded["layer3"]["audioOperationPolicies"],
                         str((self.base / "operation-policies.json").resolve()))
        self.assertEqual(loaded["layer3"]["reuseAudioFrom"]["es"]["runDir"],
                         str((self.base / "prior-audio").resolve()))
        raw["layer3"]["reuseAudioFrom"]["es"]["packageSha256"] = "invalid"
        path.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError, "reuseAudioFrom"):
            subject.load_spec(path)
        raw["layer3"]["reuseAudioFrom"]["es"]["packageSha256"] = "a" * 64
        raw["layer3"]["capabilities"] = {"fr": "capability.json"}
        path.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError, "layer3.capabilities"):
            subject.load_spec(path)

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

    def test_claude_cap_is_scoped_to_a_valid_claude_run(self):
        layer2 = {"backend": "claude_cli_opus", "claudeListPriceCapUsdPerLocale": 20,
                  "policyTemplates": {"ko": "ko-policy.json", "es": "es-policy.json"},
                  "plugins": {"ko": "ko.py", "es": "es.py"}}
        self.assertEqual(subject.load_spec(spec_files(self.base, layer2=layer2))["layer2"]
                         ["claudeListPriceCapUsdPerLocale"], 20)
        for invalid in (0, float('nan'), 101):
            layer2["claudeListPriceCapUsdPerLocale"] = invalid
            with self.assertRaisesRegex(ValueError, 'claudeListPriceCapUsdPerLocale'):
                subject.load_spec(spec_files(self.base, layer2=layer2))

    def test_plan_profile_override_does_not_mutate_weekly_policy(self):
        original = {"layer2": {"claudeCliListPriceCapUsdPerLocale": {"clip": 8, "week": 200}}}
        scoped = budgets.with_clip_claude_cap(original, scale="clip", backend="claude_cli_opus", cap=20)
        self.assertEqual((scoped["layer2"]["claudeCliListPriceCapUsdPerLocale"]["clip"],
                          original["layer2"]["claudeCliListPriceCapUsdPerLocale"]["clip"]), (20, 8))
        with self.assertRaisesRegex(ValueError, 'requires a clip'):
            budgets.with_clip_claude_cap(original, scale="week", backend="claude_cli_opus", cap=20)
        self.assertEqual(budgets.layer2_ledger_scope('clip', 'claude_cli_opus'), 'locale')
        self.assertEqual(budgets.layer2_ledger_scope('clip', 'openai_api'), 'run')

    def test_source_bound_plugin_rebases_only_from_its_frozen_weekly_binding(self):
        old_source, old_anchor = 'a' * 64, 'b' * 64
        plugin = self.base / 'weekly.py'
        plugin.write_text(f"SOURCE_SHA256 = '{old_source}'\nANCHOR_SHA256 = '{old_anchor}'\n")
        policy = self.base / 'weekly-policy.json'
        policy.write_text(json.dumps({'sourceScope': {'englishSourcePackageJsonSha256': old_source,
            'anchorManifestSha256': old_anchor}, 'languageReview': {
            'pluginImplementationSha256': producer.plugin_implementation_sha256(plugin)}}))
        source, anchor = {'source': 'clip'}, {'anchor': 'clip'}
        output = subject.clip_plugin(plugin, policy, source, anchor, self.base / 'clip.py')
        self.assertIn(target_policy.canonical_sha256(source), output.read_text())
        self.assertIn(target_policy.canonical_sha256(anchor), output.read_text())
        self.assertIn(old_source, plugin.read_text())
        policy.write_text(policy.read_text().replace(old_source, 'c' * 64))
        with self.assertRaisesRegex(ValueError, 'SOURCE_SHA256 differs'):
            subject.clip_plugin(plugin, policy, source, anchor, self.base / 'other.py')

    def test_register_rules_keep_general_and_only_in_clip_source_entries(self):
        table = [{'sourceUnitId': '0-u100', 'sourceTerm': 'A'},
                 {'sourceUnitId': '0-u304', 'sourceTerm': 'Yahweh'}]
        rules = ['Speak naturally.', 'At 0-u100 use an older form.',
                 'Keep complete utterances. Exact source-unit contextual name interpretations as data: '
                 + json.dumps(table) + '. At 0-u400 use another form.']
        kept = subject.scoped_register_rules(rules, {'0-u304'})
        self.assertEqual(len(kept), 2)
        self.assertIn('0-u304', kept[1])
        self.assertNotIn('0-u100', ' '.join(kept))
        self.assertNotIn('0-u400', ' '.join(kept))

    def test_claude_repair_reuses_only_next_round_in_same_job(self):
        prior = self.base / 'repair-rounds/round-001'
        self.assertTrue(language_models.cli_same_job_repair(prior, prior.parent / 'round-002', {'groups': []}))
        self.assertFalse(language_models.cli_same_job_repair(prior, prior.parent / 'round-003', {'groups': []}))
        self.assertFalse(language_models.cli_same_job_repair(prior, self.base / 'other/repair-rounds/round-002', {'groups': []}))
        self.assertFalse(language_models.cli_same_job_repair(prior, prior.parent / 'round-002', None))

    def test_claude_qc_revision_stays_in_same_run_locale_and_next_revision(self):
        prior = self.base / 'run/l2/text/ko/repair-rounds/round-002'
        next_round = self.base / 'run/l2-ko-r1/text/ko/repair-rounds/round-004'
        brief = {'schemaVersion': language_models.PARTIAL_REPAIR_SCHEMA_V2,
                 'groups': [{'backTranslationQc': {'targetTextSha256': 'a' * 64}}]}
        self.assertTrue(language_models.cli_same_job_repair(prior, next_round, brief))
        self.assertFalse(language_models.cli_same_job_repair(prior,
                         self.base / 'other/l2-ko-r1/text/ko/repair-rounds/round-004', brief))
        self.assertFalse(language_models.cli_same_job_repair(prior,
                         self.base / 'run/l2-es-r1/text/es/repair-rounds/round-004', brief))
        self.assertFalse(language_models.cli_same_job_repair(prior,
                         self.base / 'run/l2-ko-r2/text/ko/repair-rounds/round-004', brief))
        self.assertFalse(language_models.cli_same_job_repair(prior, next_round,
                         {'schemaVersion': language_models.PARTIAL_REPAIR_SCHEMA_V2, 'groups': [{}]}))

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

    def test_text_qc_passes_the_bound_group_acceptance(self):
        receipt = self.run_dir / "ko-acceptance.json"
        self.run.spec["qc"]["humanAcceptanceByLocale"] = {"ko": str(receipt)}
        for rel in ("l2/src/source.json", "l2/src/anchor.json", "l2/policy/ko-policy-clip.json",
                    "l2/text/ko/candidate.json"):
            subject.write(self.run_dir / rel, {})
        calls = []
        def fake_sh(label, argv, **kwargs):
            calls.append(argv)
            out = self.run_dir / "textqc-ko/out"
            subject.write(out / "summary.json", {"locales": {"ko": {
                "status": "text_waiver_issued", "failedGroups": [], "textQcReceipt": "head.json"}}})
            subject.write(out / "ko/text-waiver-test.json", {})
        with mock.patch.object(self.run, "check"), mock.patch.object(self.run, "sh", side_effect=fake_sh):
            result = subject.text_qc(self.run, "ko", self.run_dir / "l2/text/ko/candidate.json", "out")
        self.assertEqual(result["status"], "text_waiver_issued")
        self.assertEqual(calls[0][-2:], ["--human-acceptance", f"ko={receipt}"])

    def test_audio_qc_mirror_creates_remote_parent_before_rsync(self):
        calls=[]
        with mock.patch.object(subject.subprocess, "run", side_effect=lambda args, **kwargs: calls.append(args)):
            subject.mirror_run_to_spark(self.run)
        self.assertEqual([args[0] for args in calls], ["ssh", "rsync"])
        self.assertIn("mkdir -p -- ", calls[0][-1])
        self.assertIn("/mac-artifacts/", calls[1][-1])

    def test_audio_qc_creates_new_remote_output_before_checkpoint_upload(self):
        mirror_root = (ROOT / "artifacts").resolve()
        run_root = self.run_dir.resolve()
        args = SimpleNamespace(locale="es", stage="/stage", mirror_root=str(mirror_root),
                               run_dir=str(run_root), out=str(run_root / "aqc/es"),
                               audio_package=str(run_root / "l3/es/audio-package.json"),
                               state_dir=str(run_root / "state"),
                               api_budget_authorization=str(run_root / "authorization.json"),
                               prior_budget_plan=None, human_acceptance=None, allow_busy=False)
        digest = "a" * 64
        runtime = {"openaiEnvFile": "/secret", "modelRoot": "/model",
                   "asrSnapshot": "asr", "asrRevision": digest,
                   "speaker": {"id": "speaker", "checkpointRef": "checkpoint"}}
        calls = []
        def stop_after_upload(local, destination):
            calls.append(("put", destination))
            raise RuntimeError("stop before dispatch")
        remote = SimpleNamespace(
            out=lambda _: "\n".join(("env-ok", "mirror-ok", digest, "12345")),
            run=lambda argv: calls.append(("run", argv)),
            put=stop_after_upload)
        with self.assertRaisesRegex(RuntimeError, "stop before dispatch"):
            spark.audio_qc(args, runtime, remote, None)
        self.assertEqual([kind for kind, _ in calls], ["run", "put"])
        self.assertEqual(calls[0][1], ["mkdir", "-p", "/stage/mac-artifacts/" +
                                           str((run_root / "aqc/es").relative_to(mirror_root))])

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

    def test_qc_records_failed_revision_job_without_rechecking_original_candidate(self):
        candidate = str(self.run_dir / "l2/text/ko/candidate.json")
        self.run.mark("qc.ko", "running", candidate=candidate, history=[
            {"candidate": candidate, "out": "out", "status": "requires_repair",
             "failedGroups": ["g8"], "receipt": "receipt.json", "waiverDir": None}])
        with mock.patch.object(subject.Run, "plan", lambda *a, **k: None), \
                mock.patch.object(subject, "text_qc", side_effect=AssertionError("QC repeated")), \
                mock.patch.object(subject, "revise", side_effect=subject.Stop(
                    'layer2-ko-r1: failed_durable_job')):
            with self.assertRaises(subject.Stop):
                subject.stage_qc(self.run, "ko")
        self.assertEqual(self.run.stages["qc.ko"]["status"], "failed")
        self.assertEqual(self.run.stages["qc.ko"]["history"][0]["candidate"], candidate)

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
                mock.patch.object(subject, "mirror_run_to_spark"), \
                mock.patch("scripts.render_formal_target_language_speech.validate_operation_policies"):
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
        with_capability = spark.render_command(runtime, "/stage", "repo-x", blob,
                                                "/work/output/ko-raw/speech-job",
                                                max_end_lag=120.0, unit_instructions=None,
                                                clip_voice_capability=True)
        self.assertEqual(with_capability[with_capability.index("--clip-voice-capability") + 1],
                         "/work/blobs/clip-voice-capability")

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
