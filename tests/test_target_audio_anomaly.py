import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave

from scripts import target_audio_anomaly as subject
from scripts import target_audio_recovery as recovery
from tests import test_render_formal_target_language_speech as fixtures


def write_wave(path, samples, channels=1):
    with wave.open(str(path), 'wb') as handle:
        handle.setparams((channels, 2, 1000, 0, 'NONE', 'not compressed'))
        handle.writeframes(struct.pack('<' + 'h' * len(samples), *samples))


class AcousticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wav = self.root / 'test.wav'

    def test_measured_edges_do_not_mutate_or_authorize_trim(self):
        write_wave(self.wav, [0]*20 + [1200]*100 + [0]*30)
        before = self.wav.read_bytes()
        result = subject.measure_edges(self.wav)
        self.assertEqual(result['leadingLowEnergySeconds'], .02)
        self.assertEqual(result['trailingLowEnergySeconds'], .03)
        self.assertEqual(result['durationSeconds'], .15)
        self.assertIsNone(result['safeTrimSeconds'])
        self.assertEqual(self.wav.read_bytes(), before)

    def test_all_quiet_not_counted_twice(self):
        write_wave(self.wav, [0]*100)
        result = subject.measure_edges(self.wav)
        self.assertTrue(result['allLowEnergy'])
        self.assertEqual(result['leadingLowEnergySeconds'], .1)
        self.assertEqual(result['trailingLowEnergySeconds'], 0)
        self.assertIsNone(result['peakDbfs'])

    def test_stereo_activity_is_not_silence(self):
        write_wave(self.wav, [0, 1000]*100, channels=2)
        result = subject.measure_edges(self.wav)
        self.assertFalse(result['allLowEnergy'])
        self.assertEqual(result['leadingLowEnergySeconds'], 0)

    def test_truncated_wave_rejected(self):
        write_wave(self.wav, [1200]*100)
        self.wav.write_bytes(self.wav.read_bytes()[:-10])
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            subject.measure_edges(self.wav)


class PreservationTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.FormalRenderTests('test_two_units_full_decode_and_resume_without_synthesis')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.rows = self.f.render_units()
        self.wav = self.f.root / self.f.context['job']['units'][0]['outputRelativePath']

    def preserve(self):
        return subject.preserve(self.f.root, self.f.context['job'], 0, reason='operator observed repetition')

    def snapshot(self):
        return next((self.f.root / 'anomalies').glob('unit-0000-*'))

    def test_context_audio_intent_commit_retained_before_quarantine(self):
        original = self.wav.read_bytes()
        recovery.quarantine_unit(self.f.root, self.f.context['job'], 0, reason='repetition')
        destination = self.snapshot()
        receipt = json.loads((destination/'anomaly.json').read_text())
        context = json.loads((destination/'context.json').read_text())
        self.assertEqual(context['job'], self.f.context['job'])
        self.assertEqual(context['unit'], self.f.context['job']['units'][0])
        self.assertEqual((destination / receipt['saved'][0]['path']).read_bytes(), original)
        self.assertEqual(len(receipt['saved']), 4)
        self.assertFalse(self.wav.exists())
        self.assertFalse(receipt['grantsApproval'])
        import jsonschema
        schema = json.loads(Path('schemas/sermon-audio-anomaly-v1.schema.json').read_text())
        jsonschema.validate(receipt, schema)

    def test_snapshot_failure_preserves_original_and_receipts(self):
        original = self.wav.read_bytes()
        with patch.object(subject, '_sync_directory', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                recovery.quarantine_unit(self.f.root, self.f.context['job'], 0, reason='repetition')
        self.assertEqual(self.wav.read_bytes(), original)
        self.assertTrue((self.f.root/'receipts/unit-0000.render.json').is_file())

    def test_failed_rename_fsync_cannot_short_circuit_durability_on_resume(self):
        sync = subject._sync_directory
        def fail_after_rename(path):
            if Path(path).name == 'anomalies' and any(Path(path).glob('unit-*')):
                raise OSError('directory sync failure')
            return sync(path)
        with patch.object(subject, '_sync_directory', side_effect=fail_after_rename):
            with self.assertRaises(OSError):
                self.preserve()
        self.assertTrue(self.wav.exists())
        with patch.object(subject, '_sync_directory', side_effect=OSError('retry sync failure')):
            with self.assertRaises(OSError):
                recovery.quarantine_unit(self.f.root, self.f.context['job'], 0, reason='operator observed repetition')
        self.assertTrue(self.wav.exists())

    def test_failed_decode_retains_partial_without_commit(self):
        f = self.f
        recovery.quarantine_unit(f.root, f.context['job'], 0, reason='repair')
        with patch.object(fixtures.subject.integrity, 'probe_full_decode', side_effect=ValueError('failed decode')):
            with self.assertRaisesRegex(ValueError, 'failed decode'):
                f.render_units()
        receipts = [json.loads(p.read_text()) for p in (f.root/'anomalies').glob('*/anomaly.json')]
        self.assertTrue(any(r['reason'] == 'full_decode_failed:ValueError' for r in receipts))
        self.assertFalse((f.root/'receipts/unit-0000.render.json').exists())
        self.assertTrue(self.wav.with_suffix('.partial.wav').exists())

    def test_whole_track_assets_are_durable_before_any_deletion(self):
        f = self.f
        track = f.root/'prior-track.wav'; track.write_bytes(self.wav.read_bytes())
        manifest = f.root/'render-manifest.json'
        manifest.write_text(json.dumps({'track': {'path': track.name}}))
        sync = subject._sync_directory
        def fail_quarantine(path):
            if Path(path).parent.name == 'quarantine':
                raise OSError('whole track directory sync failed')
            return sync(path)
        with patch.object(subject, '_sync_directory', side_effect=fail_quarantine):
            with self.assertRaisesRegex(OSError, 'whole track'):
                recovery.quarantine_unit(f.root, f.context['job'], 0, reason='repair')
        self.assertTrue(track.exists()); self.assertTrue(manifest.exists()); self.assertTrue(self.wav.exists())
        receipt = recovery.quarantine_unit(f.root, f.context['job'], 0, reason='repair')
        self.assertFalse(track.exists()); self.assertFalse(manifest.exists()); self.assertFalse(self.wav.exists())
        self.assertTrue(any(Path(row['path']).name == track.name for row in receipt['saved']))

    def test_symlink_whole_track_is_refused_before_deletion(self):
        f = self.f
        track = f.root/'symlink-track.wav'; track.symlink_to(self.wav)
        manifest = f.root/'render-manifest.json'
        manifest.write_text(json.dumps({'track': {'path': track.name}}))
        with self.assertRaisesRegex(ValueError, 'symlink'):
            recovery.quarantine_unit(f.root, f.context['job'], 0, reason='repair')
        self.assertTrue(self.wav.exists()); self.assertTrue(manifest.exists())

    def test_dedup_and_corruption_refused(self):
        first = self.preserve()
        self.assertEqual(self.preserve(), first)
        self.assertEqual(len(list((self.f.root/'anomalies').glob('unit-*'))), 1)
        (self.snapshot()/first['saved'][0]['path']).write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'corrupted'):
            self.preserve()

    def test_symlink_destination_refused(self):
        with tempfile.TemporaryDirectory() as other:
            (self.f.root/'anomalies').symlink_to(other, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                self.preserve()
        self.assertTrue(self.wav.is_file())

    def test_tampered_receipt_refused_on_resume(self):
        self.preserve()
        path = self.snapshot()/'anomaly.json'
        data = json.loads(path.read_text()); data['grantsApproval'] = True
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'receipt corrupted'):
            self.preserve()

    def test_rehashed_receipt_cannot_drop_evidence_or_grant_approval(self):
        self.preserve()
        path = self.snapshot()/'anomaly.json'
        data = json.loads(path.read_text()); data['saved'] = data['saved'][:1]
        path.write_text(json.dumps(data))
        (self.snapshot()/'anomaly.json.sha256').write_text(subject.digest(path)+'\n')
        with self.assertRaisesRegex(ValueError, 'identity conflict'):
            self.preserve()

    def test_symlink_source_refused(self):
        data = self.wav.read_bytes(); self.wav.unlink()
        alternate = self.f.root/'alternate.wav'; alternate.write_bytes(data)
        self.wav.symlink_to(alternate)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.preserve()

    def test_decode_failure_still_retains_bytes(self):
        self.wav.write_bytes(b'invalid original WAV')
        receipt = self.preserve()
        self.assertEqual(receipt['acoustic']['status'], 'measurement_unavailable')
        self.assertEqual((self.snapshot()/receipt['saved'][0]['path']).read_bytes(), self.wav.read_bytes())

    def test_changed_source_during_copy_refused_without_deletion(self):
        copy = subject.shutil.copyfile
        def alter(source, target):
            result = copy(source, target)
            if Path(source).resolve() == self.wav.resolve():
                self.wav.write_bytes(self.wav.read_bytes() + b'changed')
            return result
        with patch.object(subject.shutil, 'copyfile', side_effect=alter):
            with self.assertRaisesRegex(ValueError, 'changed'):
                self.preserve()
        self.assertTrue(self.wav.exists())
        self.assertEqual(list((self.f.root/'anomalies').glob('unit-*')), [])

    def test_timing_risk_keeps_audio_and_separates_causes(self):
        self.rows[0]['durationSeconds'] = 30
        plan = fixtures.subject.schedule(self.f.context, self.rows, fixtures.subject.DEFAULT_POLICY)
        records = subject.preserve_timing_risk(self.f.root, self.f.context, self.rows, plan)
        self.assertEqual(records[0]['timing']['propagatedStartDelaySeconds'], 0)
        self.assertGreater(records[0]['timing']['ownSpanExcessSeconds'], 0)
        self.assertEqual(records[0]['timing']['rootCause'], 'not_determined')
        self.assertTrue(self.wav.is_file())
        self.assertEqual(len(fixtures.FakeSynth.calls), 2)

    def test_timing_group_mismatch_cannot_preserve_wrong_unit(self):
        plan = fixtures.subject.schedule(self.f.context, self.rows, fixtures.subject.DEFAULT_POLICY)
        self.rows[0]['textGroupId'] = 'wrong-group'
        with self.assertRaisesRegex(ValueError, 'group identity'):
            subject.preserve_timing_risk(self.f.root, self.f.context, self.rows, plan)
        self.assertFalse((self.f.root/'anomalies').exists())

    def test_diagnostic_parent_hash_does_not_change_model_identity(self):
        f = self.f
        actual = json.loads((f.root/'receipts/unit-0000.intent.json').read_text())
        actual['batchImplementationSha256'] = subject.digest(Path(fixtures.subject.__file__))
        prior = dict(actual, batchImplementationSha256='bf7fee0c5f9f4abcc24dfc5334fe0d95d9aba60db0a0de0a08b3d8a00d5d0a42')
        self.assertTrue(fixtures.subject._same_compatible_batch_repair_intent(prior, actual))
        prior['seed'] += 1
        self.assertFalse(fixtures.subject._same_compatible_batch_repair_intent(prior, actual))


if __name__ == '__main__':
    unittest.main()
