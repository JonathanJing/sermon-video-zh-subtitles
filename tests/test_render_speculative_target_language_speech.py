"""Synthetic checks for human-pending pre-render and formal unit admission."""
from __future__ import annotations

import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import render_formal_target_language_speech as formal
from scripts import render_speculative_target_language_speech as subject
from tests import test_prepare_target_language_speech_job as speech_fixture
from tests import test_render_formal_target_language_speech as formal_fixture


class FakeSynth:
    calls = []

    def __init__(self, checkpoint: Path, **kwargs):
        pass

    def __call__(self, text, language, speaker, *, seed):
        self.calls.append((text, language, speaker, seed))
        return [0.03] * 1280, 16000


class SpeculativeRenderTests(unittest.TestCase):
    def setUp(self):
        fixture = speech_fixture.TargetLanguageSpeechJobTests(
            "test_korean_candidate_and_prepared_job_match_published_contracts")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        fixture.candidate["status"] = "machine_review_pass_human_review_pending"
        fixture.candidate["humanReview"] = {
            "translation": "pending", "reviewer": None, "reviewedAt": None,
            "reviewedGroupIds": [],
        }
        speech_fixture.write_json(fixture.candidate_path, fixture.candidate)
        self.paths = {
            "source": fixture.source_package_path, "anchor": fixture.anchor_path,
            "candidate": fixture.candidate_path, "policy": fixture.policy_path,
            "adapter": fixture.adapter_path, "registry": fixture.registry_path,
        }
        self.policies = fixture.root / "operation-policies.json"
        policies = {
            "normalization": {"policy": "exact_human_approved_target_text_no_rewrite"},
            "asrScreening": {"policy": "synthetic"},
            "subtitle": {"policy": "synthetic"},
        }
        for name, field in (("normalization", "normalizationPolicySha256"),
                            ("asrScreening", "asrScreeningPolicySha256"),
                            ("subtitle", "subtitlePolicySha256")):
            fixture.adapter[field] = subject.identity.json_sha256(policies[name])
        speech_fixture.write_json(fixture.adapter_path, fixture.adapter)
        speech_fixture.write_json(self.policies, policies)
        self.checkpoint_map = fixture.root / "checkpoint-map.json"
        speech_fixture.write_json(self.checkpoint_map, {
            "schemaVersion": "sermon-speaker-checkpoint-map-v1",
            "checkpoints": [{"speakerId": fixture.adapter["speakerId"],
                             "checkpointRef": fixture.adapter["conditioningRef"],
                             "path": str(fixture.root / "checkpoint")}],
        })
        (fixture.root / "checkpoint").mkdir()
        self.out = fixture.root / "speculative"
        FakeSynth.calls = []

    def render(self, **kwargs):
        with patch.object(subject.demos, "validate_checkpoint",
                          return_value=self.fixture.root / "checkpoint"):
            return subject.render(self.paths, self.checkpoint_map, self.policies,
                                  self.out, synth_factory=FakeSynth, **kwargs)

    def test_pending_translation_renders_selected_units_without_formal_package(self):
        result = self.render(group_ids=["g1"])
        self.assertEqual(result["renderedGroupIds"], ["g1"])
        self.assertEqual(len(FakeSynth.calls), 1)
        manifest = subject.formal.package.read_object(self.out / "manifest.json")
        self.assertFalse(manifest["synthesisEligible"])
        self.assertFalse(manifest["releaseEligible"])
        self.assertFalse((self.out / "job.json").exists())
        self.assertFalse((self.out / "render-manifest.json").exists())
        self.assertEqual(self.render(group_ids=["g1"])["renderedGroupIds"], ["g1"])
        self.assertEqual(len(FakeSynth.calls), 1)
        self.assertEqual(self.render(group_ids=["g2"])["renderedGroupIds"], ["g2"])
        self.assertEqual(len(FakeSynth.calls), 2)

    def test_verified_adapter_with_unreviewed_locale_is_preview_only(self):
        self.fixture.adapter["capabilityStatus"] = "verified"
        speech_fixture.write_json(self.fixture.adapter_path, self.fixture.adapter)
        with self.assertRaisesRegex(ValueError, "production authorization or human-reviewed"):
            subject.speech.validate_adapter(self.fixture.adapter, "ko", self.fixture.registry)
        result = self.render(group_ids=["g1"])
        self.assertEqual(result["status"], "preview_only")
        self.assertFalse((self.out / "job.json").exists())

    def test_approved_or_failed_machine_candidate_cannot_enter_preview_lane(self):
        self.fixture.candidate["status"] = "human_translation_approved"
        self.fixture.candidate["humanReview"]["translation"] = "approved"
        speech_fixture.write_json(self.fixture.candidate_path, self.fixture.candidate)
        with self.assertRaisesRegex(ValueError, "human-pending"):
            self.render()
        self.fixture.candidate["status"] = "machine_review_pass_human_review_pending"
        self.fixture.candidate["humanReview"]["translation"] = "pending"
        self.fixture.candidate["modelReview"]["status"] = "fail"
        speech_fixture.write_json(self.fixture.candidate_path, self.fixture.candidate)
        with self.assertRaisesRegex(ValueError, "Independent model review"):
            self.render()

    def test_tampered_preview_audio_fails_closed(self):
        self.render(group_ids=["g1"])
        (self.out / "units/unit-0000.wav").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "audio changed"):
            self.render(group_ids=["g1"])

    def test_chinese_only_voice_purpose_cannot_render_korean_preview(self):
        self.fixture.adapter["authorizationPurpose"] = "chinese_dubbing"
        speech_fixture.write_json(self.fixture.adapter_path, self.fixture.adapter)
        with self.assertRaisesRegex(ValueError, "demo/Chinese voice purpose"):
            self.render(group_ids=["g1"])

    def test_committed_partial_audio_resumes_without_synthesis(self):
        self.render(group_ids=["g1"])
        audio = self.out / "units/unit-0000.wav"
        audio.rename(self.out / "units/unit-0000.partial.wav")
        self.render(group_ids=["g1"])
        self.assertTrue(audio.is_file())
        self.assertEqual(len(FakeSynth.calls), 1)

    def test_missing_predecessors_remain_unknown_and_explicit_root_is_known(self):
        from scripts import sermon_log_profile as profile
        logs = self.fixture.root / 'predecessor-accounting'
        with profile.session(logs,'legacy-render',work_kind='engineering',evidence_mode='synthetic') as legacy:
            self.render(group_ids=['g1'])
        with profile.session(logs,'root-render',work_kind='engineering',evidence_mode='synthetic') as root:
            self.render(group_ids=['g1'],predecessor_spans=[])
        rows, errors = subject.accounting.read_events(logs)
        self.assertFalse(errors)
        entries = {row['runId']:row for row in rows if row['event']=='stage_started' and row['stage']=='preview.validate_inputs'}
        self.assertIsNone(entries[legacy['runId']]['dependsOn'])
        self.assertEqual(entries[root['runId']]['dependsOn'],[])


class FormalAdmissionTests(unittest.TestCase):
    def setUp(self):
        fixture = formal_fixture.FormalRenderTests(
            "test_two_units_full_decode_and_resume_without_synthesis")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.spec_root = fixture.root.parent / "speculative"
        self.spec_root.mkdir()
        pending = copy.deepcopy(fixture.context["candidate"])
        pending["status"] = "machine_review_pass_human_review_pending"
        pending["humanReview"] = {"translation": "pending", "reviewer": None,
                                  "reviewedAt": None, "reviewedGroupIds": []}
        context = dict(fixture.context, candidate=pending)
        preview_adapter = copy.deepcopy(context["adapter"])
        preview_adapter["authorizationPurpose"] = "multilingual_voice_demo"
        preview_adapter["capabilityStatus"] = "unverified_poc"
        context["adapter"] = preview_adapter
        subject.formal.write_json_atomic(self.spec_root / "candidate.json", pending)
        for name in ("source", "anchor", "policy", "adapter", "registry"):
            subject.formal.write_json_atomic(self.spec_root / f"{name}.json", context[name])
        subject.formal.write_json_atomic(self.spec_root / "manifest.json", {
            "schemaVersion": subject.MANIFEST_VERSION, "status": "preview_only",
            "synthesisEligible": False, "releaseEligible": False,
            "targetLocale": pending["targetLocale"],
            "candidateJsonSha256": subject.identity.json_sha256(pending),
            "sourceJsonSha256": subject.identity.json_sha256(context["source"]),
            "anchorJsonSha256": subject.identity.json_sha256(context["anchor"]),
            "translationPolicySha256": pending["translationPolicySha256"],
        })
        for index, group in enumerate(pending["groups"]):
            sound = subject.sound_identity(context, index, seed=42,
                                           dtype="bfloat16", attention="sdpa",
                                           instruct=None)
            audio = self.spec_root / f"units/unit-{index:04d}.wav"
            audio.parent.mkdir(exist_ok=True)
            formal.write_pcm16(audio, [0.03] * 1280, 16000)
            subject.formal.write_json_atomic(
                self.spec_root / f"receipts/unit-{index:04d}.json", {
                    "schemaVersion": subject.UNIT_VERSION, "status": "preview_only",
                    "candidateJsonSha256": subject.identity.json_sha256(pending),
                    "soundIdentity": sound, "audioSha256": subject.identity.sha256(audio),
                    "durationSeconds": 0.08, "fullDecode": "pass",
                })
        FakeSynth.calls = []

    def formal_render(self, context=None):
        return formal.render_units(context or self.fixture.context, self.fixture.paths,
                                   self.fixture.root,
                                   self.fixture.root / "checkpoint-map.json",
                                   speculative_from=self.spec_root,
                                   synth_factory=FakeSynth)

    def test_same_audio_is_reused_only_after_formal_job_validation(self):
        # Admission is called by render() after checked_context; this unit test
        # checks the per-unit identity and fresh formal receipt separately.
        rows = self.formal_render()
        self.assertEqual(len(rows), 2)
        self.assertEqual(FakeSynth.calls, [])
        for row in rows:
            receipt = formal.package.read_object(self.fixture.root / row["receipt"]["path"])
            self.assertEqual(receipt["fullDecode"], "pass")

    def test_verified_demo_adapter_with_unreviewed_locale_reuses_preview_audio(self):
        adapter_path = self.spec_root / "adapter.json"
        adapter = formal.package.read_object(adapter_path)
        adapter["capabilityStatus"] = "verified"
        formal.write_json_atomic(adapter_path, adapter)
        rows = self.formal_render()
        self.assertEqual(len(rows), 2)
        self.assertEqual(FakeSynth.calls, [])

    def test_previous_admission_renderer_audio_is_reused_with_same_sound_intent(self):
        for index in range(2):
            path = self.spec_root / f"receipts/unit-{index:04d}.json"
            receipt = formal.package.read_object(path)
            receipt["soundIdentity"]["rendererSha256"] = next(iter(
                formal.COMPATIBLE_PREVIEW_ADMISSION_RENDERER_SHA256))
            formal.write_json_atomic(path, receipt)
        self.formal_render()
        self.assertEqual(FakeSynth.calls, [])

    def test_unknown_preview_renderer_is_not_reused(self):
        path = self.spec_root / "receipts/unit-0000.json"
        receipt = formal.package.read_object(path)
        receipt["soundIdentity"]["rendererSha256"] = "0" * 64
        formal.write_json_atomic(path, receipt)
        self.formal_render()
        self.assertEqual(len(FakeSynth.calls), 1)

    def test_changed_text_resynthesizes_only_changed_unit(self):
        self.fixture.context["candidate"]["groups"][1]["targetText"] = "Revised text."
        self.fixture.context["job"]["units"][1]["text"] = "Revised text."
        with patch.object(formal.integrity, "build_receipt",
                          return_value={"fullDecode": "pass", "durationSeconds": 0.08}):
            self.formal_render()
        self.assertEqual(len(FakeSynth.calls), 1)
        self.assertEqual(FakeSynth.calls[0][0], "Revised text.")

    def test_changed_audio_hash_is_rejected(self):
        (self.spec_root / "units/unit-0000.wav").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            self.formal_render()

    def test_formal_entrypoint_still_rejects_pending_translation(self):
        pending = formal.package.read_object(self.spec_root / "candidate.json")
        formal.write_json_atomic(self.fixture.paths["candidate"], pending)
        with self.assertRaises(ValueError):
            formal.render(self.fixture.paths,
                          self.fixture.root / "checkpoint-map.json",
                          self.fixture.root / "operation-policies.json",
                          speculative_from=self.spec_root,
                          synth_factory=FakeSynth)
        self.assertFalse((self.fixture.root / "render-manifest.json").exists())

    def test_changed_candidate_snapshot_is_rejected(self):
        (self.spec_root / "candidate.json").write_text("{}")
        with self.assertRaises(ValueError):
            self.formal_render()

    def test_new_approved_unit_after_preview_is_cache_miss(self):
        unit = {"translationGroupId": "g3", "sourceUnitIds": ["block-00-u003"]}
        expected = formal._intent(self.fixture.context, self.fixture.paths, 1,
                                  seed=42, dtype="bfloat16", attention="sdpa",
                                  instruct=None)
        expected.update(unitIndex=2, groupId="g3",
                        sourceUnitIds=unit["sourceUnitIds"])
        self.assertIsNone(formal._reusable_speculative_audio(
            self.spec_root, unit, 2, expected))




class DiagnosticPreviewTests(unittest.TestCase):
    """Actual strict machine candidate + original pending Source; fake local TTS."""
    def setUp(self):
        import json
        from tests import test_sermon_diagnostic_context as context_fixture
        self.preview = SpeculativeRenderTests()
        self.preview.setUp(); self.addCleanup(self.preview.doCleanups)
        self.diag = context_fixture.DiagnosticContextTests()
        self.diag.setUp(); self.addCleanup(self.diag.doCleanups)
        with self.diag.f.f.session():
            result = self.diag.run_locale(self.diag.context)
        self.assertEqual(result['status'], 'waiting_human', result)
        candidates = list((self.diag.f.f.root / 'locale/machine-candidates').glob('*/candidate.json'))
        self.candidate = json.loads(candidates[0].read_text())
        self.rubric = self.diag.rubric
        self.context = self.diag.context
        self.f = self.preview.fixture
        for name, value in (('source', self.diag.source), ('anchor', self.diag.anchor),
                            ('policy', self.diag.policy), ('candidate', self.candidate)):
            speech_fixture.write_json(self.preview.paths[name], value)
        capability = next(row for row in self.f.registry['speakers'][0]['localeCapabilities']
                          if row['targetLocale'] == 'zh-Hans')
        self.f.adapter.update(targetLocale='zh-Hans', languageParameter=capability['modelLanguage'],
            capabilityEvidenceSha256=subject.identity.json_sha256(capability['reviewEvidence']))
        speech_fixture.write_json(self.f.adapter_path, self.f.adapter)
        FakeSynth.calls = []

    def render(self, **overrides):
        options = dict(strict_rubric=self.rubric, diagnostic_context=self.context,
                       deadline_monotonic=subject._monotonic() + 60)
        options.update(overrides)
        return self.preview.render(**options)

    def test_pending_source_and_candidate_stay_unapproved_in_scoped_preview(self):
        before = {key: path.read_bytes() for key, path in self.preview.paths.items()}
        result = self.render()
        self.assertEqual(result['status'], 'preview_only')
        self.assertEqual(len(FakeSynth.calls), 2)
        self.assertEqual({key: path.read_bytes() for key, path in self.preview.paths.items()}, before)
        manifest = formal.package.read_object(self.preview.out / 'manifest.json')
        self.assertEqual(manifest['schemaVersion'], subject.SCOPED_MANIFEST_VERSION)
        self.assertFalse(manifest['productionEligible'])
        self.assertEqual(manifest['humanAcceptance'], 'pending')
        self.assertEqual(manifest['diagnosticContextSha256'], subject.identity.json_sha256(self.context))
        saved_source = formal.package.read_object(self.preview.out / 'source.json')
        self.assertEqual(saved_source, self.diag.source)
        self.assertFalse(saved_source['review']['humanApproval'])
        self.assertFalse(saved_source['source']['approvedWindow']['humanApproval'])
        self.assertFalse(saved_source['translationEligible'])
        self.assertEqual(formal.package.read_object(self.preview.out / 'candidate.json'), self.candidate)
        self.assertFalse((self.preview.out / 'job.json').exists())
        self.render()
        self.assertEqual(len(FakeSynth.calls), 2)

    def test_context_and_original_deadline_are_mandatory_for_pending_source(self):
        for overrides in ({'diagnostic_context': None}, {'deadline_monotonic': None},
                          {'strict_rubric': None}, {'deadline_monotonic': float('nan')},
                          {'deadline_monotonic': subject._monotonic() - 1}):
            with self.subTest(overrides=overrides), self.assertRaises((ValueError, TimeoutError)):
                self.render(**overrides)
        self.assertFalse(self.preview.out.exists())
        self.assertEqual(FakeSynth.calls, [])

    def test_context_rubric_and_checkpoint_drift_never_reuses_preview(self):
        self.render(group_ids=['g1'])
        for overrides in ({'diagnostic_context': dict(self.context, simulationAuthorizationRef='f' * 64)},
                          {'strict_rubric': dict(self.rubric, rubricId='changed')}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.render(group_ids=['g1'], **overrides)
        self.f.adapter['conditioningSha256'] = 'f' * 64
        speech_fixture.write_json(self.f.adapter_path, self.f.adapter)
        with self.assertRaises(ValueError): self.render(group_ids=['g1'])
        self.assertEqual(len(FakeSynth.calls), 1)

    def test_failed_machine_verdict_or_revoked_voice_is_not_simulated(self):
        changed = copy.deepcopy(self.candidate)
        changed['groups'][0]['semanticReview']['status'] = 'fail'
        speech_fixture.write_json(self.preview.paths['candidate'], changed)
        with self.assertRaisesRegex(ValueError, 'Semantic review'): self.render()
        speech_fixture.write_json(self.preview.paths['candidate'], self.candidate)
        self.f.registry['speakers'][0]['authorization']['status'] = 'revoked'
        self.f.adapter['registryJsonSha256'] = subject.identity.json_sha256(self.f.registry)
        speech_fixture.write_json(self.f.registry_path, self.f.registry)
        speech_fixture.write_json(self.f.adapter_path, self.f.adapter)
        with self.assertRaises(ValueError): self.render()
        self.assertEqual(FakeSynth.calls, [])

    def test_actual_checkpoint_validator_failure_blocks_before_tts(self):
        with patch.object(subject.demos, 'validate_checkpoint', side_effect=ValueError('fixture checkpoint mismatch')):
            with self.assertRaisesRegex(ValueError, 'checkpoint mismatch'):
                subject.render(self.preview.paths, self.preview.checkpoint_map, self.preview.policies,
                    self.preview.out, strict_rubric=self.rubric, diagnostic_context=self.context,
                    deadline_monotonic=subject._monotonic() + 60, synth_factory=FakeSynth)
        self.assertEqual(FakeSynth.calls, [])

    def test_expired_model_result_is_not_committed_and_cannot_restart_same_unit(self):
        clock = [0.]
        class LateSynth(FakeSynth):
            def __call__(self, *args, **kwargs):
                result = super().__call__(*args, **kwargs)
                clock[0] = 11.
                return result
        with patch.object(subject, '_monotonic', side_effect=lambda: clock[0]), \
             patch.object(subject.demos, 'validate_checkpoint', return_value=self.f.root / 'checkpoint'):
            with self.assertRaises(TimeoutError):
                subject.render(self.preview.paths, self.preview.checkpoint_map, self.preview.policies,
                    self.preview.out, strict_rubric=self.rubric, diagnostic_context=self.context,
                    deadline_monotonic=10., synth_factory=LateSynth)
            self.assertFalse((self.preview.out / 'receipts/unit-0000.json').exists())
            self.assertTrue((self.preview.out / 'receipts/unit-0000.attempt.json').exists())
            clock[0] = 0.
            with self.assertRaisesRegex(ValueError, 'requires reconciliation'):
                self.render(deadline_monotonic=10.)
        self.assertEqual(len(FakeSynth.calls), 1)

    def test_late_model_load_does_not_begin_inference(self):
        clock = [0.]
        class LateLoad(FakeSynth):
            def __init__(self, *args, **kwargs):
                clock[0] = 11.
        with patch.object(subject, '_monotonic', side_effect=lambda: clock[0]), \
             patch.object(subject.demos, 'validate_checkpoint', return_value=self.f.root / 'checkpoint'):
            with self.assertRaises(TimeoutError):
                subject.render(self.preview.paths, self.preview.checkpoint_map, self.preview.policies,
                    self.preview.out, strict_rubric=self.rubric, diagnostic_context=self.context,
                    deadline_monotonic=10., synth_factory=LateLoad)
        self.assertEqual(FakeSynth.calls, [])

    def test_log_failure_after_model_return_blocks_implicit_second_synthesis(self):
        real = subject.local_observation.record
        def fail_completed(*args, **kwargs):
            if kwargs['status'] == 'completed':
                raise subject.accounting.AccountingWriteError('synthetic log failure')
            return real(*args, **kwargs)
        with patch.object(subject.local_observation, 'record', side_effect=fail_completed):
            with self.assertRaises(subject.accounting.AccountingWriteError): self.render(group_ids=['g1'])
        with self.assertRaisesRegex(ValueError, 'requires reconciliation'): self.render(group_ids=['g1'])
        self.assertEqual(len(FakeSynth.calls), 1)

    def test_cache_duration_mismatch_blocks_without_synthesis_or_measured_workload(self):
        self.render(group_ids=['g1'])
        receipt_path = self.preview.out / 'receipts/unit-0000.json'
        receipt = formal.package.read_object(receipt_path)
        for invalid in (999.0, None, True, '0.08'):
            with self.subTest(duration=invalid):
                formal.write_json_atomic(receipt_path, dict(receipt, durationSeconds=invalid))
                with patch.object(subject.accounting, 'record_workload') as record:
                    with self.assertRaisesRegex(ValueError, 'duration.*requires reconciliation'):
                        self.render(group_ids=['g1'])
                record.assert_not_called()
                self.assertEqual(len(FakeSynth.calls), 1)
        formal.write_json_atomic(receipt_path, receipt)
        with patch.object(subject.accounting, 'record_workload') as record:
            self.render(group_ids=['g1'])
        measured = subject.integrity.probe_full_decode(self.preview.out / 'units/unit-0000.wav')
        self.assertEqual(record.call_args.args[1]['audioSeconds'], measured['durationSeconds'])
        self.assertTrue(record.call_args.args[1]['cacheHit'])
        self.assertEqual(len(FakeSynth.calls), 1)

    def test_cold_and_cache_accounting_contains_real_unit_dag_and_unknown_tokens(self):
        import json
        from scripts import sermon_log_profile as profile
        log_root = self.f.root / 'preview-accounting'
        with profile.session(log_root, 'preview-test', work_kind='production', evidence_mode='synthetic') as cold:
            self.render()
        with profile.session(log_root, 'preview-test', work_kind='production', evidence_mode='synthetic') as warm:
            self.render()
        rows, errors = subject.accounting.read_events(log_root)
        self.assertFalse(errors)
        cold_rows = [row for row in rows if row['runId'] == cold['runId']]
        warm_rows = [row for row in rows if row['runId'] == warm['runId']]
        starts = {row['spanId']: row for row in cold_rows if row['event'] == 'stage_started'}
        models = [row for row in starts.values() if row['executorType'] == 'production_model']
        self.assertEqual(len(models), 2)
        first_commit = next(row for row in starts.values() if row['stage'] == 'preview.zh-Hans.0000.commit')
        second = next(row for row in starts.values() if row['stage'] == 'preview.zh-Hans.0001.cache_admission')
        self.assertEqual(second['dependsOn'], [first_commit['spanId']])
        observations = [row['fields'] for row in cold_rows if row.get('code') == subject.local_observation.CODE]
        self.assertEqual([row['status'] for row in observations], ['started', 'completed', 'started', 'completed'])
        self.assertTrue(all(row['model'] == self.f.adapter['model'] and row['providerTokens'] is None
                            and row['providerCostUsd'] is None for row in observations))
        self.assertFalse(any(row.get('executorType') == 'production_model' for row in warm_rows))
        metrics = [row['metrics'] for row in warm_rows if row['event'] == 'workload']
        self.assertEqual(len(metrics), 2)
        self.assertTrue(all(row['cacheHit'] and row['providerInputTokens'] is None
                            and row['previewOnly'] and row['humanAcceptancePending'] and not row['productionEligible']
                            and row['fullDecodePassed'] and not row['providerTokensApplicable'] and row['cacheManifestSha256']
                            and row['cacheUnitReceiptSha256'] for row in metrics))
        self.assertEqual(len(FakeSynth.calls), 2)
        self.assertFalse(any(row['event'] == 'api_attempt' for row in rows))
        self.assertNotIn(self.candidate['groups'][0]['targetText'], json.dumps(rows, ensure_ascii=False))

    def test_scoped_attempt_reservation_is_exclusive_and_durable_before_model_load(self):
        from concurrent.futures import ThreadPoolExecutor
        path = self.f.root / 'one-attempt.json'
        def reserve(_):
            try:
                subject._reserve_model_attempt(path, {'status': 'model_outcome_uncommitted'})
                return 'reserved'
            except ValueError:
                return 'reconciliation'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, range(2)))
        self.assertEqual(sorted(results), ['reconciliation', 'reserved'])
        self.assertEqual(formal.package.read_object(path), {'status': 'model_outcome_uncommitted'})


if __name__ == '__main__':
    unittest.main()
