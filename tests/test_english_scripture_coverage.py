"""The pinned public-domain English edition decides only whether a quotation covers a whole verse.

Synthetic verses use the pinned edition's own public-domain wording. The real
library is loaded once to prove the pinned hash, the 605 reading and the
footnote-only verses behave as the adjudicator relies on.
"""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts import cuv_scripture
from scripts import english_scripture_coverage as coverage
from scripts.build_scripture_index import BOOKS

GEN_1_1 = 'In the beginning, God created the heavens and the earth.'
GEN_1_2 = ('Now the earth was formless and empty. Darkness was on the surface of the deep and '
           "God's Spirit was hovering over the surface of the waters.")
# The 605 speaker's own wording of Revelation 4:2 (another translation than the pinned edition).
SPOKEN_4_2 = 'Immediately I was in the Spirit, and there was a throne in heaven, and someone was seated on it.'
# A synthetic verse whose meaning turns on a negation.
GEN_1_3 = "You shall not go up after them. Don't follow their road, but circle around behind them."


def synthetic_edition():
    data = {'schemaVersion': 1, 'purpose': coverage.PURPOSE, 'edition': {'id': 'test-edition'},
            'chapters': {'GEN': {'1': [{'verse': 1, 'text': GEN_1_1}, {'verse': 2, 'text': GEN_1_2},
                                       {'verse': 3, 'text': GEN_1_3}]}}}
    return coverage.CoverageEdition(data, expected_content_sha256=None)


LIBRARY_TO_USFX = {library: usfx for usfx, library in coverage.USFX_TO_LIBRARY.items()}


def usfx_document(overrides=None):
    """One chapter with one verse for every canonical book, in USFX codes."""
    books = []
    for code in BOOKS:
        body = (overrides or {}).get(code) or f'<c id="1"/><v id="1"/>{code} one. <ve/>'
        books.append(f'<book id="{LIBRARY_TO_USFX.get(code, code)}">{body}</book>')
    return '<usfx>' + ''.join(books) + '</usfx>'


class PlainTextTests(unittest.TestCase):
    def test_footnotes_references_and_tags_are_removed_and_entities_unescaped(self):
        fragment = ('<w>In</w> the <f caller="+">footnote <ft>words</ft></f>beginning,&#160;'
                    '<x caller="-">Gen 2:4</x> God <vp>1a</vp>created &amp; <wj>made</wj>   all.')
        self.assertEqual(coverage._plain(fragment), 'In the beginning, God created & made all.')

    def test_content_tokens_drop_function_words_and_stem_lightly(self):
        self.assertEqual(coverage.content_tokens(GEN_1_1), ['begin', 'god', 'creat', 'heaven', 'earth'])
        self.assertEqual(coverage.content_tokens("The Lord's armies, cities, stopped, holy"),
                         ['lord', 'army', 'city', 'stop', 'holy'])
        self.assertEqual(coverage.content_tokens('and the of to I you behold'), [])
        # Negations are content words, and a contracted one reads as the spoken one.
        self.assertEqual(coverage.content_tokens("You shall not go; don't go; won't go; no one goes"),
                         ['not', 'go', 'not', 'go', 'not', 'go', 'no', 'one', 'goe'])
        self.assertEqual(coverage.negation_count(coverage.content_tokens('never, nor, neither, none, without')), 5)

    def test_same_token_allows_a_short_prefix_difference_only(self):
        self.assertTrue(coverage._same('creat', 'create'))
        self.assertTrue(coverage._same('heaven', 'heaven'))
        self.assertFalse(coverage._same('god', 'gods'))  # too short to trust a prefix
        self.assertFalse(coverage._same('throne', 'thrones' + 'xx'))
        self.assertFalse(coverage._same('spirit', 'spring'))


class CoverageMeasureTests(unittest.TestCase):
    def test_a_whole_reading_covers_the_verse_and_is_as_long(self):
        measure = coverage.coverage(synthetic_edition(), 'GEN 1:1', GEN_1_1)
        self.assertEqual(measure['editionId'], 'test-edition')
        self.assertEqual(measure['canonicalRef'], 'GEN 1:1')
        self.assertEqual(measure['verseTextSha256'], coverage.sha256(GEN_1_1.encode('utf-8')))
        self.assertEqual((measure['verseContentWords'], measure['coveredContentWords'],
                          measure['spokenContentWords']), (5, 5, 5))
        self.assertEqual((measure['verseCoverage'], measure['lengthRatio'], measure['wholeVerse']), (1.0, 1.0, True))
        self.assertEqual(measure['thresholds'], {'verseCoverageMin': coverage.WHOLE_VERSE_COVERAGE_MIN,
                                                 'lengthRatioMin': coverage.WHOLE_VERSE_LENGTH_MIN,
                                                 'lengthRatioMax': coverage.WHOLE_VERSE_LENGTH_MAX})

    def test_a_reading_with_a_negation_missing_or_added_is_never_whole(self):
        edition = synthetic_edition()
        whole = coverage.coverage(edition, 'GEN 1:3', GEN_1_3)
        self.assertEqual((whole['negations'], whole['negationMismatch'], whole['wholeVerse']),
                         ({'verse': 2, 'spoken': 2}, False, True))
        reversed_reading = coverage.coverage(edition, 'GEN 1:3',
                                             'You shall go up after them. Follow their road, but circle around behind them.')
        self.assertEqual((reversed_reading['negations'], reversed_reading['negationMismatch'],
                          reversed_reading['wholeByMeasure'], reversed_reading['wholeVerse']),
                         ({'verse': 2, 'spoken': 0}, True, True, False))
        # Another translation's wording of the same negations still counts them.
        spoken = "Do not go up after them. Do not follow their road, but circle around behind them."
        same = coverage.coverage(edition, 'GEN 1:3', spoken)
        self.assertEqual((same['negationHeads'], same['negationMismatch']),
                         ({'verse': ['go', 'follow'], 'spoken': ['go', 'follow']}, False))
        # As many negations, but moved to other words: the reading says something else.
        moved = coverage.coverage(edition, 'GEN 1:3',
                                  "You shall go up after them. Don't follow their road, but don't circle around behind them.")
        self.assertEqual((moved['negations'], moved['negationHeads']['spoken'], moved['negationMismatch'],
                          moved['wholeByMeasure'], moved['wholeVerse']),
                         ({'verse': 2, 'spoken': 2}, ['follow', 'circle'], True, True, False))
        self.assertTrue(coverage.negations_match(['go', 'follow'], ['follow', 'go']))
        self.assertFalse(coverage.negations_match(['go', 'follow'], ['go']))
        added = coverage.coverage(edition, 'GEN 1:1', 'In the beginning, God did not create the heavens and the earth.')
        self.assertEqual((added['negations']['spoken'], added['negationMismatch'], added['wholeByMeasure'],
                          added['wholeVerse']), (1, True, True, False))

    def test_a_span_much_longer_than_the_verse_carries_more_than_the_verse(self):
        measure = coverage.coverage(synthetic_edition(), 'GEN 1:1',
                                    f'{GEN_1_1} That tells us creation was deliberate, ordered and good from the start.')
        self.assertEqual(measure['verseCoverage'], 1.0)
        self.assertGreater(measure['lengthRatio'], coverage.WHOLE_VERSE_LENGTH_MAX)
        self.assertFalse(measure['wholeVerse'])

    def test_a_fragment_is_too_short_even_when_its_words_are_the_verses(self):
        measure = coverage.coverage(synthetic_edition(), 'GEN 1:1', 'In the beginning, God.')
        self.assertEqual((measure['coveredContentWords'], measure['spokenContentWords']), (2, 2))
        self.assertEqual(measure['verseCoverage'], 0.4)
        self.assertEqual(measure['lengthRatio'], 0.4)
        self.assertFalse(measure['wholeVerse'])

    def test_commentary_as_long_as_the_verse_does_not_cover_it(self):
        measure = coverage.coverage(synthetic_edition(), 'GEN 1:1',
                                    'God made everything and then he rested, which tells us something about work.')
        self.assertEqual(measure['coveredContentWords'], 1)
        self.assertGreaterEqual(measure['lengthRatio'], 1.0)
        self.assertFalse(measure['wholeVerse'])

    def test_a_range_joins_its_verses_so_one_verse_spoken_is_a_fragment_of_the_range(self):
        edition = synthetic_edition()
        self.assertEqual(edition.lookup('GEN 1:1-2')['text'], f'{GEN_1_1} {GEN_1_2}')
        whole = coverage.coverage(edition, 'GEN 1:1-2', f'{GEN_1_1} {GEN_1_2}')
        self.assertTrue(whole['wholeVerse'])
        partial = coverage.coverage(edition, 'GEN 1:1-2', GEN_1_1)
        self.assertFalse(partial['wholeVerse'])
        self.assertLess(partial['lengthRatio'], coverage.WHOLE_VERSE_LENGTH_MIN)

    def test_a_reference_the_edition_lacks_fails_closed(self):
        edition = synthetic_edition()
        for ref in ('GEN 1:4', 'GEN 1:3-4', 'GEN 2:1', 'EXO 1:1'):
            with self.assertRaisesRegex(coverage.CoverageError, 'Missing verse'):
                coverage.coverage(edition, ref, GEN_1_1)
        self.assertTrue(issubclass(coverage.CoverageError, cuv_scripture.CuvError))

    def test_an_edition_with_a_changed_hash_or_shape_is_refused(self):
        data = {'schemaVersion': 1, 'purpose': coverage.PURPOSE, 'chapters': {}}
        with self.assertRaisesRegex(coverage.CoverageError, 'content hash mismatch'):
            coverage.CoverageEdition(data)
        with self.assertRaisesRegex(coverage.CoverageError, 'unexpected shape'):
            coverage.CoverageEdition(dict(data, purpose='display'), expected_content_sha256=None)
        with self.assertRaisesRegex(coverage.CoverageError, 'unavailable'):
            coverage.CoverageEdition.from_path(Path('/nonexistent/eng-web.coverage.json'))


class SourceParsingTests(unittest.TestCase):
    def test_parse_keeps_verse_text_skips_footnote_only_verses_and_maps_codes(self):
        parsed = coverage.parse_usfx(usfx_document({
            'LUK': '<c id="17"/><v id="35"/>Two women. <ve/><v id="36"/><f caller="+">only a note</f><ve/>',
            'JOH': '<c id="3"/><v id="16"/>For God so loved. <ve/><c id="4"/><v id="1"/>Therefore. <ve/>',
        }))
        self.assertEqual(parsed.pop('_emptyVerses'), ['LUK 17:36'])
        self.assertEqual(set(parsed), set(BOOKS))
        self.assertEqual(parsed['LUK'], {'17': [{'verse': 35, 'text': 'Two women.'}]})
        self.assertEqual(parsed['JOH'], {'3': [{'verse': 16, 'text': 'For God so loved.'}],
                                         '4': [{'verse': 1, 'text': 'Therefore.'}]})
        self.assertEqual(parsed['SOL'], {'1': [{'verse': 1, 'text': 'SOL one.'}]})

    def test_parse_refuses_duplicate_verses_and_an_incomplete_canon(self):
        with self.assertRaisesRegex(coverage.CoverageError, 'duplicate verse GEN 1:1'):
            coverage.parse_usfx(usfx_document({'GEN': '<c id="1"/><v id="1"/>A <ve/><v id="1"/>B <ve/>'}))
        with self.assertRaisesRegex(coverage.CoverageError, 'exactly the 66 canonical books'):
            coverage.parse_usfx('<usfx><book id="GEN"><c id="1"/><v id="1"/>A <ve/></book></usfx>')

    def test_build_refuses_a_source_file_whose_hash_differs_from_the_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'eng-web.usfx.xml'
            source.write_text(usfx_document(), encoding='utf-8')
            with self.assertRaisesRegex(coverage.CoverageError, 'hash differs'):
                coverage.build(source, Path(tmp) / 'out.json', Path(tmp) / 'provenance.json')
            self.assertFalse((Path(tmp) / 'out.json').exists())


class PinnedLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.edition = coverage.CoverageEdition.from_path()
        cls.data = json.loads(coverage.DATA_PATH.read_text(encoding='utf-8'))
        cls.provenance = json.loads(coverage.PROVENANCE_PATH.read_text(encoding='utf-8'))

    def test_library_and_provenance_carry_the_pinned_identity(self):
        self.assertEqual(cuv_scripture.canonical_hash(self.data), coverage.LIBRARY_CONTENT_SHA256)
        self.assertEqual(self.provenance['libraryContentSha256'], coverage.LIBRARY_CONTENT_SHA256)
        self.assertEqual(self.provenance['libraryFileSha256'], coverage.sha256(coverage.DATA_PATH.read_bytes()))
        self.assertEqual(self.provenance['sourceFileSha256'], coverage.SOURCE_FILE_SHA256)
        self.assertEqual(self.provenance['sourceCommit'], coverage.SOURCE_COMMIT)
        self.assertEqual(self.provenance['license'], 'Public Domain')
        self.assertEqual(self.data['edition']['sourceUrl'], coverage.SOURCE_URL)
        self.assertEqual(self.data['books'], list(BOOKS))
        self.assertEqual(self.data['verseCount'], self.provenance['verseEntryCount'])
        self.assertEqual(self.data['verseCount'],
                         sum(len(rows) for book in self.data['chapters'].values() for rows in book.values()))
        self.assertEqual(self.data['footnoteOnlyVerses'],
                         ['LUK 17:36', 'ACT 8:37', 'ACT 15:34', 'ACT 24:7', 'ROM 16:25'])

    def test_the_605_reading_in_another_translation_is_a_whole_verse(self):
        measure = coverage.coverage(self.edition, 'REV 4:2', SPOKEN_4_2)
        self.assertTrue(measure['wholeVerse'], measure)
        self.assertGreaterEqual(measure['verseCoverage'], coverage.WHOLE_VERSE_COVERAGE_MIN)
        self.assertGreaterEqual(measure['lengthRatio'], coverage.WHOLE_VERSE_LENGTH_MIN)

    def test_one_verse_spoken_of_a_two_verse_range_is_a_fragment(self):
        measure = coverage.coverage(self.edition, 'REV 4:2-3', SPOKEN_4_2)
        self.assertFalse(measure['wholeVerse'], measure)

    def test_each_verse_of_a_range_must_be_read_through_its_own_words(self):
        verse16, verse17 = (self.edition.lookup(ref)['text'] for ref in ('JOH 3:16', 'JOH 3:17'))
        twice = coverage.coverage(self.edition, 'JOH 3:16-17', f'{verse16} {verse16}')
        # One verse read twice satisfies the joined range's coverage and length, but not verse 17's own words.
        self.assertGreaterEqual(twice['verseCoverage'], coverage.WHOLE_VERSE_COVERAGE_MIN)
        self.assertTrue(coverage.WHOLE_VERSE_LENGTH_MIN <= twice['lengthRatio'] <= coverage.WHOLE_VERSE_LENGTH_MAX)
        self.assertEqual((twice['unreadVerses'], twice['wholeByMeasure'], twice['wholeVerse']),
                         (['JOH 3:17'], False, False))
        self.assertEqual([(row['canonicalRef'], row['basis'], row['read']) for row in twice['verses']],
                         [('JOH 3:16', 'exclusive_words', True), ('JOH 3:17', 'exclusive_words', False)])
        both = coverage.coverage(self.edition, 'JOH 3:16-17', f'{verse16} {verse17}')
        self.assertEqual((both['unreadVerses'], both['wholeVerse']), ([], True))
        self.assertEqual(coverage.coverage(self.edition, 'JOH 3:16', verse16)['verses'], [])

    def test_a_reversed_direction_is_never_whole(self):
        verse = self.edition.lookup('GEN 35:1')['text']
        self.assertIn('go up to', verse)
        turned = coverage.coverage(self.edition, 'GEN 35:1', verse.replace('go up to', 'go down to'))
        self.assertEqual((turned['reversedDirections'], turned['wholeByMeasure'], turned['negationMismatch'],
                          turned['wholeVerse']), ([['up', 'down']], True, False, False))
        # Leaving the direction out does not reverse it.
        omitted = coverage.coverage(self.edition, 'GEN 35:1', verse.replace('go up to', 'go to'))
        self.assertEqual((omitted['reversedDirections'], omitted['wholeVerse']), ([], True))
        self.assertEqual(coverage.reversed_directions(coverage.all_tokens('He ascended before them'),
                                                      coverage.all_tokens('He descended after them')),
                         [['before', 'after'], ['ascend', 'descend']])
        # Both members on both sides in the same order is no reversal; the other order is a swap.
        self.assertEqual(coverage.reversed_directions(coverage.all_tokens('in and out'),
                                                      coverage.all_tokens('in and out')), [])
        self.assertEqual(coverage.reversed_directions(coverage.all_tokens('in and out'),
                                                      coverage.all_tokens('out and in')), [['in', 'out']])

    def test_a_swapped_pair_is_a_reversed_direction(self):
        # WEB Matthew 25:33 names both sides; reading the sheep on the left and the goats on the right
        # turns the verse around although every word of it is spoken.
        verse = self.edition.lookup('MAT 25:33')['text']
        swapped = verse.replace('right hand', 'LEFT hand').replace('on the left', 'on the right').replace('LEFT', 'left')
        self.assertNotEqual(swapped, verse)
        measure = coverage.coverage(self.edition, 'MAT 25:33', swapped)
        self.assertEqual(measure['reversedDirections'], [['right', 'left']])
        self.assertTrue(measure['wholeByMeasure'], measure)
        self.assertFalse(measure['wholeVerse'])
        self.assertTrue(coverage.coverage(self.edition, 'MAT 25:33', verse)['wholeVerse'])
        # The same order, a repeated member, or one side only is not a swap.
        self.assertEqual(coverage.reversed_directions(coverage.all_tokens('right then left'),
                                                      coverage.all_tokens('right, right, then left')), [])
        self.assertEqual(coverage.reversed_directions(coverage.all_tokens('right then left'),
                                                      coverage.all_tokens('on the right')), [])
        self.assertEqual(coverage.reversed_directions(coverage.all_tokens('right then left'),
                                                      coverage.all_tokens('left, then right')), [['right', 'left']])
        # Repeating the pair in the verse's order is not a swap; naming them the other way round first is.
        self.assertEqual(coverage.reversed_directions(coverage.all_tokens('right then left'),
                                                      coverage.all_tokens('right, left, right, left')), [])
        self.assertEqual(coverage.reversed_directions(coverage.all_tokens('right then left'),
                                                      coverage.all_tokens('left, right, then left')), [['right', 'left']])
        # Keeping the words in order but moving what each side places turns the verse around too:
        # the goats on his right hand and the sheep on the left.
        moved = verse.replace('sheep', 'GOATS').replace('goats', 'sheep').replace('GOATS', 'goats')
        self.assertNotEqual(moved, verse)
        measure = coverage.coverage(self.edition, 'MAT 25:33', moved)
        self.assertEqual(measure['reversedDirections'], [['sheep right goat', 'goat right sheep']])
        self.assertTrue(measure['wholeByMeasure'], measure)
        self.assertFalse(measure['wholeVerse'])
        # A word said between each animal and its side does not hide the move, nor does placing them
        # after their sides instead of before.
        for reading, expected in (
                ('He will set the goats standing on his right hand, but the sheep standing on the left.',
                 ['sheep right goat', 'goat right sheep']),
                ('On his right hand he will set the goats, and on his left the sheep.',
                 ['sheep right hand', 'hand left sheep'])):
            with self.subTest(reading=reading):
                self.assertEqual(coverage.reversed_directions(coverage.all_tokens(verse),
                                                              coverage.all_tokens(reading)), [expected])
        # The same placements in other words or another sentence shape, or a side said with nothing
        # placed on it, are not a swap.
        for reading in ('He will put the sheep at his right and the goats at his left.',
                        'The sheep go on the right hand, but the goats on the left.',
                        'On the right, on the left: he will set the sheep and the goats.',
                        'On his right hand he will set the sheep, and on his left the goats.',
                        'He will set on his right hand the sheep, but the goats on the left.',
                        'He will set the sheep standing on his right hand, but the goats standing on the left.'):
            with self.subTest(reading=reading):
                self.assertEqual(coverage.reversed_directions(coverage.all_tokens(verse),
                                                              coverage.all_tokens(reading)), [])

    def test_a_negation_keeps_its_spelling_through_stemming(self):
        # "nothing" stemmed to "noth" would escape the negation count; a negation word is never stemmed.
        verse = self.edition.lookup('JOH 15:5')['text']
        self.assertIn('nothing', coverage.content_tokens(verse))
        self.assertEqual(coverage.all_tokens('He never fails; nobody knows; nothing without him'),
                         ['he', 'never', 'fail', 'nobody', 'know', 'nothing', 'without', 'him'])
        self.assertTrue(coverage.coverage(self.edition, 'JOH 15:5', verse)['wholeVerse'])
        turned = coverage.coverage(self.edition, 'JOH 15:5', verse.replace('do nothing', 'do something'))
        self.assertTrue(turned['wholeByMeasure'], turned)
        self.assertTrue(turned['negationMismatch'])
        self.assertFalse(turned['wholeVerse'])

    def test_half_a_verse_is_a_fragment(self):
        half = ' '.join(self.edition.lookup('JOH 3:16')['text'].split()[:8])
        measure = coverage.coverage(self.edition, 'JOH 3:16', half)
        self.assertFalse(measure['wholeVerse'], measure)

    def test_footnote_only_verses_fail_closed(self):
        for ref in ('LUK 17:36', 'ACT 8:37', 'LUK 17:35-36'):
            with self.assertRaisesRegex(coverage.CoverageError, 'Missing verse'):
                self.edition.lookup(ref)
        self.assertEqual(self.edition.lookup('LUK 17:35')['canonicalRef'], 'LUK 17:35')

    def test_cli_verify_and_check_report_the_measure(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(coverage.main(['verify']), 0)
        self.assertEqual(json.loads(out.getvalue()),
                         {'status': 'verified', 'editionId': 'eng-web',
                          'libraryContentSha256': coverage.LIBRARY_CONTENT_SHA256})
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(coverage.main(['check', 'REV 4:2', SPOKEN_4_2]), 0)
        self.assertTrue(json.loads(out.getvalue())['wholeVerse'])
        with self.assertRaisesRegex(SystemExit, 'refused: Missing verse'):
            coverage.main(['check', 'ACT 8:37', 'anything'])


if __name__ == '__main__':
    unittest.main()
