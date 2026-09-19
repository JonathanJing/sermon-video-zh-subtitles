import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from scripts import sermon_pipeline as pipeline


class MFAProductionRoutingTests(unittest.TestCase):
    def test_default_reading_routes_to_mfa(self):
        args = SimpleNamespace(reading_segment_target_chars=420)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('scripts.mfa_alignment.align_reference_chunks', return_value=[{'source': 'mfa-forced-alignment'}]) as align:
                result = pipeline.reading_segments(args, [{'text': 'Hello.'}], root/'audio.wav', root)
            self.assertEqual(result[0]['source'], 'mfa-forced-alignment')
            self.assertEqual(align.call_args.args[2], root/'mfa')

    def test_mfa_failure_does_not_fall_back_to_estimated_times(self):
        with patch('scripts.mfa_alignment.align_reference_chunks', side_effect=RuntimeError('unaligned')):
            with self.assertRaisesRegex(RuntimeError, 'unaligned'):
                pipeline.reading_segments(SimpleNamespace(), [], Path('audio.wav'), Path('run'))

    def test_explicit_legacy_recovery_is_labelled_synthetic(self):
        result = pipeline.reading_segments(SimpleNamespace(reading_aligner='legacy', reading_segment_target_chars=420),
                                           [{'start': 0, 'end': 2, 'text': 'Hello.'}], Path('a.wav'), Path('run'))
        self.assertEqual(result[0]['timingQuality'], 'synthetic_not_for_subtitles')
