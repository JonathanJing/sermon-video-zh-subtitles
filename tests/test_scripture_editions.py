"""Pinned ko and es verse libraries: hash checks, exact lookup, ambiguity refusal.

The texts live in the ignored artifacts directory. These tests skip when the files
are absent, so they never fail a clean checkout.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts import scripture_editions as editions

HAVE = {name: (editions.DOWNLOAD_DIR / spec['file']).is_file() for name, spec in editions.EDITIONS.items()}


@unittest.skipUnless(HAVE['NKRV-1998'], 'NKRV-1998 file not in artifacts/scripture-downloads')
class Nkrv1998Tests(unittest.TestCase):
    def test_revelation_3_16_is_exact_and_claims_third_party_status(self):
        ed = editions.load('NKRV-1998')
        text = ed.lookup('REV 3:16')['text']
        self.assertEqual(text, '네가 이같이 미지근하여 뜨겁지도 아니하고 차지도 아니하니 내 입에서 너를 토하여 버리리라')
        self.assertEqual(ed.verification, editions.PENDING)
        self.assertEqual(ed.verify_text('REV 3:16', text)['editionId'], 'NKRV-1998')

    def test_book_order_maps_korean_labels_to_usfm(self):
        ed = editions.load('NKRV-1998')
        self.assertEqual(len(ed.verses), 31077)
        self.assertIn(('REV', 3, 16), ed.verses)
        self.assertIn(('GEN', 1, 1), ed.verses)


@unittest.skipUnless(HAVE['RVR60-1960'], 'RVR60-1960 file not in artifacts/scripture-downloads')
class Rvr60Tests(unittest.TestCase):
    def test_revelation_3_16_is_exact(self):
        ed = editions.load('RVR60-1960')
        self.assertEqual(ed.lookup('REV 3:16')['text'],
                         'Pero por cuanto eres tibio, y no frío ni caliente, te vomitaré de mi boca.')
        self.assertEqual(ed.verification, editions.PENDING)

    def test_ambiguous_verses_are_refused_not_guessed(self):
        ed = editions.load('RVR60-1960')
        self.assertIn(('NEH', 7, 73), ed.ambiguous)
        with self.assertRaisesRegex(editions.EditionError, 'ambiguous'):
            ed.lookup('NEH 7:73')
        with self.assertRaisesRegex(editions.EditionError, 'ambiguous'):
            ed.verify_text('PSA 57:3', 'anything')

    def test_removed_duplicate_chapters_are_identical_to_the_source(self):
        # The unique file is the source with five identical one-chapter duplicates removed.
        source = editions.DOWNLOAD_DIR / 'RVR60-1960.json'
        if not source.is_file():
            self.skipTest('source file not present')
        self.assertEqual(editions._sha256(source), editions.EDITIONS['RVR60-1960']['sourceSha256'])


class VerificationTests(unittest.TestCase):
    def test_unknown_edition_is_refused(self):
        with self.assertRaisesRegex(editions.EditionError, 'unknown pinned edition'):
            editions.load('NOPE-0000')

    @unittest.skipUnless(HAVE['NKRV-1998'], 'NKRV-1998 file not in artifacts/scripture-downloads')
    def test_changed_bytes_are_refused_before_indexing(self):
        with tempfile.TemporaryDirectory() as temp:
            copy = Path(temp) / 'NKRV-1998.json'
            shutil.copy(editions.DOWNLOAD_DIR / 'NKRV-1998.json', copy)
            with copy.open('ab') as stream:
                stream.write(b' ')
            with self.assertRaisesRegex(editions.EditionError, 'hash differs'):
                editions.load('NKRV-1998', directory=Path(temp))

    def test_missing_file_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(editions.EditionError, 'not available'):
                editions.load('NKRV-1998', directory=Path(temp))


if __name__ == '__main__':
    unittest.main()
