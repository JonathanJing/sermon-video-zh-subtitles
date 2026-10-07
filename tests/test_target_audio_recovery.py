import json
import os
import unittest
from unittest.mock import patch
from tests import test_render_formal_target_language_speech as fixtures
from scripts import target_audio_recovery as recovery
from scripts import validate_target_language_audio_unit as integrity


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.FormalRenderTests('test_two_units_full_decode_and_resume_without_synthesis')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_context_single_admission_and_dependency_write_rejected(self):
        with patch.object(integrity, '_load_job', wraps=integrity._load_job) as load:
            context = integrity.ValidatedJobContext(self.f.paths['job'])
            self.f.context['receiptContext'] = context
            self.f.render_units()
            self.assertEqual(load.call_count, 1)
            path = self.f.paths['candidate']
            st = path.stat()
            path.write_bytes(path.read_bytes() + b' ')
            os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
            with self.assertRaisesRegex(ValueError, 'Frozen dependency changed'):
                context.check()

    def test_assembly_only_never_loads_model_on_miss_or_hit(self):
        f = self.f
        with self.assertRaisesRegex(ValueError, 'requires all committed units'):
            fixtures.subject.render_units(f.context, f.paths, f.root, f.root / 'map.json',
                                           assembly_only=True, synth_factory=lambda *a, **k: self.fail('model loaded'))
        rows = f.render_units()
        actual = fixtures.subject.render_units(f.context, f.paths, f.root, f.root / 'map.json',
                                               assembly_only=True, synth_factory=lambda *a, **k: self.fail('model loaded'))
        self.assertEqual(rows, actual)

    def test_quarantine_preserves_wave_and_sparse_resume(self):
        f = self.f
        f.render_units()
        wav = f.root / f.context['job']['units'][1]['outputRelativePath']
        original = wav.read_bytes()
        receipt = recovery.quarantine_unit(f.root, f.context['job'], 1, reason='audible repetition')
        self.assertFalse(wav.exists())
        from pathlib import Path
        self.assertEqual(Path(receipt['saved'][0]['path']).read_bytes(), original)
        before = len(fixtures.FakeSynth.calls)
        f.render_units()
        self.assertEqual(len(fixtures.FakeSynth.calls) - before, 1)

    def test_diagnostics_separate_own_overflow_and_propagation(self):
        f = self.f
        rows = f.render_units()
        rows[0]['durationSeconds'] = 30
        plan = fixtures.subject.schedule(f.context, rows, fixtures.subject.DEFAULT_POLICY)
        result = recovery.diagnose(f.context, rows, plan)
        self.assertEqual(result['units'][0]['classification'], 'single_unit_overflow')
        self.assertEqual(result['evidenceKind'], 'measured')
        self.assertFalse(result['automaticToleranceChange'])

    def test_context_rejects_corrupt_receipt_and_audio(self):
        f = self.f
        f.context['receiptContext'] = integrity.ValidatedJobContext(f.paths['job'])
        f.render_units()
        receipt = f.root / 'receipts/unit-0000.json'
        data = json.loads(receipt.read_text()); data['targetTextSha256'] = '0' * 64
        receipt.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'another job, text, path, or audio'):
            f.render_units()

    def test_adjudication_is_exactly_bound_and_never_approval(self):
        f = self.f
        row = f.render_units()[0]
        track = row['audio']
        detail = recovery.bind_adjudication(row, track, reason='asr_misrecognition', evidence='Compared full utterance', corrected_transcript='correct', artifact_root=f.root)
        recovery.validate_adjudication(detail, row, track, artifact_root=f.root)
        self.assertFalse(detail['grantsApproval'])
        changed = dict(row, targetTextSha256='0'*64)
        with self.assertRaisesRegex(ValueError, 'binding changed'):
            recovery.validate_adjudication(detail, changed, track, artifact_root=f.root)

    def test_reserve_failure_contains_measured_and_unknown_fields(self):
        from scripts.spark_tts_replica_pool import ReplicaPool, ReplicaPoolError
        events = []
        pool = ReplicaPool('unused', factory=lambda: None, engine_kwargs={}, memory_reader=lambda: 1,
                           telemetry=events.append)
        with self.assertRaises(ReplicaPoolError): pool._guard()
        self.assertEqual(events[0]['memAvailableBytes'], 1)
        self.assertEqual(events[0]['reserveBytes'], 24 * 1024**3)
        self.assertEqual(events[0]['gpuPeakStatus'], 'unknown')

    def test_formal_entry_threads_context_into_each_receipt(self):
        f = self.f
        checkpoint_map = f.root / 'checkpoint-map.json'
        policy = f.root / 'operations.json'
        checkpoint_map.write_text(json.dumps({'checkpoints':[{'speakerId':f.context['job']['adapter']['speakerId'], 'path':str(f.context['checkpoint'])}]})); policy.write_text('{}')
        with patch.object(fixtures.subject, 'checked_context', return_value=f.context), \
             patch.object(fixtures.subject, 'assemble', return_value={'ok': True}), \
             patch.object(integrity, '_load_job', wraps=integrity._load_job) as load:
            result = fixtures.subject.render(f.paths, checkpoint_map, policy, synth_factory=fixtures.FakeSynth)
        self.assertEqual(result, {'ok': True})
        self.assertEqual(load.call_count, 1)

    def test_locked_synthesis_budget_counts_complete_batch_window(self):
        f = self.f
        with self.assertRaisesRegex(ValueError, 'budget exceeded at locked admission'):
            fixtures.subject.render_units(f.context, f.paths, f.root, f.root/'map.json',
                batch_size=2, max_synthesis_units=1,
                synth_factory=lambda *a, **kw: self.fail('model loaded over budget'))
        self.assertEqual(fixtures.FakeSynth.calls, [])

    def test_checkpoint_directory_membership_and_tokenizer_are_frozen(self):
        f = self.f
        model = f.root/'model-snapshot'; model.mkdir()
        token = model/'tokenizer.json'; token.write_text('{}')
        snapshot = integrity.ValidatedJobContext(f.paths['job'], extra_directories=[model])
        (model/'added-config.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'directory changed'):
            snapshot.check()
        (model/'added-config.json').unlink()
        token.write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError, 'dependency changed'):
            snapshot.check()
