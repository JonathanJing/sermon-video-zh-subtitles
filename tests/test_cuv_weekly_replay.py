"""Offline CUV regression gates; real weekly evidence is opt-in and never committed.

CUV_WEEKLY_REPLAY_DIR=/path/to/cuv-translation-visual-v12 python -m unittest \
    discover -s tests -p test_cuv_weekly_replay.py
No API or media generation is permitted by these tests.
"""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from scripts import sermon_cuv_translation as mod


class CompactReplayGates(unittest.TestCase):
    def test_repeated_text_requires_explicit_exact_unicode_offset(self):
        full = '得胜的，我必赐福；得胜的，我必赐福。'
        part = {'text': '得胜的'}
        with self.assertRaisesRegex(ValueError, 'unambiguous'):
            mod.selected_part_span(part, full)
        second = full.rindex(part['text'])
        self.assertEqual((second, second + 3), mod.selected_part_span(
            dict(part, start=second, end=second + 3), full, explicit_offsets=True))
        for start, end in [(0, 2), (True, 4), (second, len(full) + 1)]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                mod.selected_part_span(dict(part, start=start, end=end), full, explicit_offsets=True)

    def test_offline_cache_miss_never_calls_model(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
                mod, 'chat_json', side_effect=AssertionError('NETWORK FORBIDDEN')) as api:
            with self.assertRaisesRegex(ValueError, 'Missing model evidence cache'):
                mod.cached_call(Path(tmp), 'fixture', 'test instruction', {'synthetic': True},
                                'fixture-identity', offline=True)
            api.assert_not_called()


@unittest.skipUnless(os.environ.get('CUV_WEEKLY_REPLAY_DIR'), 'external weekly evidence not supplied')
class RealWeeklyReplay(unittest.TestCase):
    def setUp(self):
        self.out = Path(os.environ['CUV_WEEKLY_REPLAY_DIR']).resolve()
        self.manifest = mod.read(self.out / 'cuv-manifest.json')
        self.network = mock.patch.object(mod, 'chat_json', side_effect=AssertionError('NETWORK FORBIDDEN'))
        self.api = self.network.start()
        self.addCleanup(self.network.stop)

    def snapshot(self):
        return {str(p.relative_to(self.out)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.out.rglob('*') if p.is_file()}

    def test_real_62_blocks_26_quotes_read_only(self):
        before = self.snapshot()
        self.assertEqual({'status': 'passed', 'blocks': 62, 'quotes': 26, 'humanApproval': False},
                         mod.validate(self.out))
        self.assertEqual(before, self.snapshot(), 'Offline replay modified evidence')
        self.api.assert_not_called()

    def test_missing_bound_frame_fails_without_model_call(self):
        mapping = mod.read(self.manifest['referenceMap']['path'])
        context = next(b['sourceContext'] for b in mapping['blocks'] if b.get('sourceContext'))
        frame = Path(context['frameBinding']['path'])
        original = mod.check_binding
        def reject_frame(binding):
            if Path(binding['path']) == frame:
                raise ValueError('Synthetic missing bound frame')
            return original(binding)
        with mock.patch.object(mod, 'check_binding', side_effect=reject_frame):
            with self.assertRaisesRegex(ValueError, 'Synthetic missing bound frame'):
                mod.audit_user_content('audit-quotes', {}, self.manifest)
        self.api.assert_not_called()

    def test_tampered_receipt_dependency_is_rejected(self):
        target = next(self.out.joinpath('cache').glob('select-*.json'))
        original = mod.read
        def altered(path):
            value = original(path)
            if Path(path) == target:
                value = dict(value, responseSha256='0' * 64)
            return value
        with mock.patch.object(mod, 'read', side_effect=altered):
            with self.assertRaisesRegex(ValueError, 'cache hash|request mismatch'):
                mod.validate(self.out)
        self.api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
