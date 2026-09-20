import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('poster', Path(__file__).resolve().parents[1] / 'scripts/build_sermon_poster.py')
poster = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(poster)


class PosterTests(unittest.TestCase):
    def setUp(self):
        self.week = dict(id='2026-09-20-same_video-id', title='耶稣的应许 · 系列｜正式播放版',
                         series='系列', sourceLabel='正式播放版', date='2026-09-20',
                         speaker='Eric Geiger', scripture='启示录 2–3 章', humanContentReview='approved')

    def brief(self, weeks=None, page=None):
        return poster.make_brief({'weeks': weeks if weeks is not None else [self.week]},
                                 page or self.week['id'], 'https://example.web.app', '同行')

    def test_exact_week_and_title(self):
        result = self.brief()
        self.assertEqual(result['title'], '耶稣的应许')
        self.assertEqual(result['qrURL'], 'https://example.web.app/?week=2026-09-20-same_video-id')
        self.assertEqual(result['reviewLabel'], '已审核')

    def test_ambiguous_or_missing_page_rejected(self):
        for weeks in ([], [self.week, self.week]):
            with self.assertRaises(ValueError):
                self.brief(weeks)

    def test_missing_metadata_rejected(self):
        del self.week['speaker']
        with self.assertRaises(ValueError):
            self.brief()

    def test_unapproved_not_promoted(self):
        self.week.pop('humanContentReview')
        self.week['audioStatus'] = 'full_reviewed'
        self.assertEqual(self.brief()['reviewLabel'], '试听待审')

    def test_url_payload_encoded(self):
        self.week['id'] = 'week&other=1'
        self.assertTrue(self.brief()['qrURL'].endswith('week=week%26other%3D1'))

    def test_qr_requires_both_exact_payloads(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            for name in ('poster.png', 'poster-preview.png'):
                (out / name).write_bytes(b'fixture')
            checks = [{'file': n, 'passed': True, 'payload': 'expected'} for n in ('poster.png', 'poster-preview.png')]
            poster.write(out / 'qr-validation.json', {'checks': checks})
            self.assertEqual(len(poster.verify_outputs(out, 'expected')), 3)
            checks[1]['payload'] = 'wrong-week'
            poster.write(out / 'qr-validation.json', {'checks': checks})
            with self.assertRaises(ValueError):
                poster.verify_outputs(out, 'expected')
            poster.write(out / 'qr-validation.json', {'checks': checks[:1]})
            with self.assertRaises(ValueError):
                poster.verify_outputs(out, 'expected')


if __name__ == '__main__':
    unittest.main()
