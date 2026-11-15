"""Offline tests for the Vision-based composition lint; no render or model is used."""
import json
import os
import sys
import tempfile
from pathlib import Path
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.delivery.posters import composition


def box(x, y, w, h, confidence=0.8):
    return dict(x=x, y=y, w=w, h=h, confidence=confidence)


class CompositionTests(unittest.TestCase):
    def test_subject_inside_the_safe_area_is_ok(self):
        result = composition.classify([box(0.30, 0.35, 0.40, 0.30)])
        self.assertEqual(result['placement'], 'ok')
        self.assertEqual(result['bandTopRatio'], 0.35)
        self.assertEqual(result['bandBottomRatio'], 0.65)
        self.assertEqual(result['warnings'], [])

    def test_subject_below_the_safe_area_is_low(self):
        result = composition.classify([box(0.30, 0.15, 0.40, 0.35)])
        self.assertEqual(result['placement'], 'low')
        self.assertIn('subject_covered_by_footer', result['warnings'])

    def test_subject_touching_the_footer_is_edge(self):
        result = composition.classify([box(0.30, 0.28, 0.40, 0.31)])
        self.assertEqual(result['placement'], 'edge')
        self.assertIn('subject_touches_footer', result['warnings'])

    def test_subject_above_the_title_area_is_high(self):
        result = composition.classify([box(0.30, 0.60, 0.40, 0.25)])
        self.assertEqual(result['placement'], 'high')
        self.assertIn('subject_too_high_for_title_area', result['warnings'])

    def test_multiple_objects_union_into_one_band(self):
        result = composition.classify([box(0.05, 0.35, 0.30, 0.25), box(0.65, 0.35, 0.30, 0.25)])
        self.assertEqual(result['placement'], 'ok')
        self.assertEqual(result['horizontalSpan'], [0.05, 0.95])

    def test_low_confidence_or_empty_boxes_are_unknown(self):
        self.assertEqual(composition.classify([])['placement'], 'unknown')
        self.assertEqual(composition.classify([box(0.3, 0.4, 0.3, 0.2, 0.1)])['placement'], 'unknown')

    def test_missing_artwork_is_an_error(self):
        with self.assertRaisesRegex(composition.CompositionError, 'does not exist'):
            composition.analyse('/tmp/definitely-not-a-poster.png')

    def test_missing_swift_reports_unknown_instead_of_guessing(self):
        with tempfile.TemporaryDirectory() as temporary:
            art = Path(temporary) / 'art.png'
            art.write_bytes(b'not analysed by vision')
            with mock.patch.dict(os.environ, {'SERMON_SWIFT': '/nonexistent/swift'}, clear=False):
                result = composition.analyse(art)
        self.assertEqual(result['placement'], 'unknown')
        self.assertIn('Vision', result['reason'])

    def test_injected_boxes_skip_vision(self):
        with tempfile.TemporaryDirectory() as temporary:
            art = Path(temporary) / 'art.png'
            art.write_bytes(b'injected')
            result = composition.analyse(art, objects=[box(0.30, 0.35, 0.40, 0.30)])
        self.assertEqual(result['placement'], 'ok')
        self.assertEqual(result['objects'], 1)


if __name__ == '__main__':
    unittest.main()
