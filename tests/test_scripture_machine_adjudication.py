"""Machine adjudication: explicit references become exact pinned sentences; nothing is guessed.

Units are synthetic English sentences shaped like a sermon reading. Scripture
text comes from the pinned CUV library. The gate's own validator is used to
prove the receipt is otherwise admissible: only its role check is swapped, so
this file does not depend on when the gate starts accepting the machine role.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import cuv_scripture
from scripts import english_scripture_coverage as coverage_module
from scripts import scripture_adjudication as adjudication
from scripts import scripture_machine_adjudication as machine

LIBRARY = cuv_scripture.CuvLibrary.from_path()


def units(*rows):
    return [{'sourceUnitId': f'u{i + 1}', 'english': text, 'start': float(i), 'end': float(i + 1)}
            for i, text in enumerate(rows)]


# The reading is the 605 speaker's own wording (another translation than the pinned English edition).
READ_4_2 = 'Immediately I was in the Spirit, and there was a throne in heaven, and someone was seated on it.'
READ_4_3 = ('The one seated there had the appearance of jasper and carnelian stone, a rainbow that had the '
            'appearance of an emerald surrounded the throne.')
# Whole readings in the public-domain pinned English wording.
READ_3_16 = ('For God so loved the world, that he gave his one and only Son, that whoever believes in him '
             'should not perish, but have eternal life.')
READ_3_17 = ("For God didn't send his Son into the world to judge the world, but that the world should be "
             'saved through him.')
READ_8_2 = 'For the law of the Spirit of life in Christ Jesus made me free from the law of sin and of death.'
READING = units(
    'Their whole world was filled with chaos.',
    'And so God\'s Word, Revelation chapter 4, this is part of the vision.',
    f'Verse 2 and 3, John says, {READ_4_2}',
    READ_4_3,
    'I want you to notice, this should be comforting for you.',
)


def plan(all_units, size=2):
    ids = [u['sourceUnitId'] for u in all_units]
    return [{'translationGroupId': f'g{n + 1}', 'sourceUnitIds': ids[i:i + size]}
            for n, i in enumerate(range(0, len(ids), size))]


def source():
    return {'source': {'sourceId': 'synthetic'}}


def as_human(receipt):
    """The gate still refuses the machine role; everything else must pass it unchanged."""
    return dict(receipt, decidedByRole='human_reviewer')


class MachineAdjudicationTests(unittest.TestCase):
    def test_verse_mention_with_reading_signal_yields_one_exact_verse_per_unit(self):
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': READING}, plan(READING),
                                            target_locale='zh-Hans', flagged_units=['u3', 'u4'], library=LIBRARY)
        self.assertEqual([(c['sourceUnitIds'], c['classification'], c['reference']) for c in receipt['candidates']],
                         [(['u3'], 'direct_quote', 'REV 4:2'), (['u4'], 'direct_quote', 'REV 4:3')])
        self.assertEqual(receipt['candidates'][0]['exactSentence'], LIBRARY.lookup('REV 4:2')['text'])
        self.assertEqual(receipt['candidates'][1]['exactSentence'], LIBRARY.lookup('REV 4:3')['text'])
        self.assertEqual(receipt['decidedByRole'], machine.ROLE)
        self.assertEqual(set(receipt), adjudication.TOP_KEYS)
        self.assertFalse(basis['humanApproval'])
        self.assertEqual(basis['candidates'][0]['openedAt'], 'u3')
        self.assertIn('speech_verb', basis['candidates'][0]['readingSignals'])
        self.assertEqual(basis['candidates'][0]['quoteBoundary'], machine.QUOTE_BOUNDARY)
        self.assertTrue(basis['candidates'][0]['coverage']['wholeVerse'])
        self.assertEqual(basis['coverageEditionId'], 'eng-web')
        summary = adjudication.validate_receipt(as_human(receipt), target_locale='zh-Hans',
                                                bindings=receipt['bindings'], flagged_units=['u3', 'u4'],
                                                library=LIBRARY)
        self.assertEqual(summary['coveredUnits'], ['u3', 'u4'])
        self.assertEqual([q['canonicalRef'] for q in summary['quotes']], ['REV 4:2', 'REV 4:3'])

    def test_machine_receipt_passes_the_gate_as_machine_evidence(self):
        receipt, _ = machine.adjudicate(source(), {'sourceUnits': READING}, plan(READING),
                                        target_locale='zh-Hans', flagged_units=['u3', 'u4'], library=LIBRARY)
        inputs = {'source.json': source(), 'anchor.json': {'sourceUnits': READING}, 'group-plan.json': plan(READING)}
        summary = adjudication.validate_receipt(receipt, target_locale='zh-Hans', bindings=receipt['bindings'],
                                                flagged_units=['u3', 'u4'], library=LIBRARY, machine_inputs=inputs)
        self.assertEqual((summary['adjudicationKind'], summary['humanApproval'], summary['decidedByRole']),
                         ('machine', False, machine.ROLE))
        self.assertEqual([q['canonicalRef'] for q in summary['quotes']], ['REV 4:2', 'REV 4:3'])
        self.assertEqual((summary['generator']['reproduced'], summary['generator']['signatureCurrent'],
                          summary['generator']['version']), (True, True, machine.VERSION))
        # The role string admits nothing by itself: the gate re-derives the receipt from the bound inputs.
        with self.assertRaisesRegex(adjudication.AdjudicationError, 'machine_inputs_required'):
            adjudication.validate_receipt(receipt, target_locale='zh-Hans', bindings=receipt['bindings'],
                                          flagged_units=['u3', 'u4'], library=LIBRARY)
        tampered = dict(receipt, candidates=[dict(receipt['candidates'][0], classification='partial_direct_quote',
                                                  exactSentence=receipt['candidates'][0]['exactSentence'][:4]),
                                             receipt['candidates'][1]])
        with self.assertRaisesRegex(adjudication.AdjudicationError, 'machine_receipt_not_reproduced'):
            adjudication.validate_receipt(tampered, target_locale='zh-Hans', bindings=receipt['bindings'],
                                          flagged_units=['u3', 'u4'], library=LIBRARY, machine_inputs=inputs)
        human = adjudication.validate_receipt(as_human(receipt), target_locale='zh-Hans', bindings=receipt['bindings'],
                                              flagged_units=['u3', 'u4'], library=LIBRARY)
        self.assertEqual((human['adjudicationKind'], human['generator']), ('human', None))

    def test_discovery_flags_only_the_opening_unit_and_keeps_the_range_on_it(self):
        # Whether the reading runs into u4 is not in the text, so u4 is not claimed
        # (it could be commentary); explicit flags still split the range per unit.
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': READING}, plan(READING),
                                            target_locale='zh-Hans', library=LIBRARY)
        self.assertEqual(basis['flaggedUnits'], ['u3'])
        self.assertEqual(basis['flaggedUnitsSource'], 'discovered')
        # u3 alone reads only verse 2 of the two-verse range: a fragment, translated as spoken.
        self.assertEqual([(c['sourceUnitIds'], c['classification'], c['reference']) for c in receipt['candidates']],
                         [(['u3'], 'speaker_paraphrase', None)])
        self.assertEqual((basis['candidates'][0]['reference'], basis['candidates'][0]['quoteBoundary']),
                         ('REV 4:2-3', machine.FRAGMENT_BOUNDARY))
        self.assertFalse(basis['candidates'][0]['coverage']['wholeVerse'])
        rows = units('John 3:16-18 says, "for God so loved the world that he gave his only Son."',
                     'Lord, we thank you for this word.',
                     'Let us pray.')
        _, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows), target_locale='zh-Hans',
                                      library=LIBRARY)
        self.assertEqual(basis['discoveredUnits'], ['u1'])

    def test_flagged_unit_without_a_resolvable_reference_is_a_paraphrase_with_no_edition(self):
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': READING}, plan(READING),
                                            target_locale='zh-Hans', flagged_units=['u1'], library=LIBRARY)
        row = receipt['candidates'][0]
        self.assertEqual((row['classification'], row['editionId'], row['exactSentence'], row['reference']),
                         ('speaker_paraphrase', None, None, None))
        self.assertIn('no book, chapter and verse', basis['candidates'][0]['reason'])
        summary = adjudication.validate_receipt(as_human(receipt), target_locale='zh-Hans',
                                                bindings=receipt['bindings'], flagged_units=['u1'], library=LIBRARY)
        self.assertEqual(summary['quotes'], [])

    def test_one_unit_carrying_a_whole_range_is_a_single_range_quote(self):
        rows = units('Open to Revelation chapter 4.',
                     f'Verses 2 through 3 read, "{READ_4_2} {READ_4_3}"',
                     'Let us pray.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                            target_locale='zh-Hans', flagged_units=['u2'], library=LIBRARY)
        self.assertEqual([(c['sourceUnitIds'], c['reference']) for c in receipt['candidates']],
                         [(['u2'], 'REV 4:2-3')])
        self.assertEqual(receipt['candidates'][0]['exactSentence'], LIBRARY.lookup('REV 4:2-3')['text'])
        self.assertEqual(basis['candidates'][0]['layout'], 'one unit carries the whole range')
        adjudication.validate_receipt(as_human(receipt), target_locale='zh-Hans', bindings=receipt['bindings'],
                                      flagged_units=['u2'], library=LIBRARY)

    def test_several_chapters_in_one_mention_give_no_chapter_context(self):
        rows = units('Revelation 4 and 5 brought comfort to them.',
                     'Verse 2 says there is a throne.',
                     'This is good news.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                            target_locale='zh-Hans', flagged_units=['u2'], library=LIBRARY)
        self.assertEqual(receipt['candidates'][0]['classification'], 'speaker_paraphrase')
        self.assertEqual(basis['discoveredUnits'], [])

    def test_verse_mention_without_a_reading_signal_is_not_discovered(self):
        rows = units('We are in Revelation chapter 4 tonight.',
                     'Verse 2 is my favourite verse in the whole chapter.',
                     'Let us look at it together.')
        _, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                      target_locale='zh-Hans', flagged_units=['u2'], library=LIBRARY)
        self.assertEqual(basis['discoveredUnits'], [])
        # Supplied flags still resolve the reference, but the unit does not read the verse:
        # a fragment by coverage, translated as the speaker's own words.
        self.assertEqual((basis['candidates'][0]['decision'], basis['candidates'][0]['reference'],
                          basis['candidates'][0]['quoteBoundary']),
                         ('speaker_paraphrase', 'REV 4:2', machine.FRAGMENT_BOUNDARY))
        self.assertIn('fragment of REV 4:2', basis['candidates'][0]['reason'])

    def test_book_context_expires_after_the_window(self):
        filler = ['We keep walking through the story together.'] * machine.CONTEXT_WINDOW_UNITS
        rows = units('Revelation chapter 4 is our text.', *filler, 'Verse 2 says there is a throne.')
        last = rows[-1]['sourceUnitId']
        receipt, _ = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                        target_locale='zh-Hans', flagged_units=[last], library=LIBRARY)
        self.assertEqual(receipt['candidates'][0]['classification'], 'speaker_paraphrase')

    def test_unknown_or_repeated_flagged_units_are_refused(self):
        with self.assertRaisesRegex(machine.MachineAdjudicationError, 'flagged_unit_unknown'):
            machine.adjudicate(source(), {'sourceUnits': READING}, plan(READING),
                               target_locale='zh-Hans', flagged_units=['u9'], library=LIBRARY)
        with self.assertRaisesRegex(machine.MachineAdjudicationError, 'flagged_unit_repeated'):
            machine.adjudicate(source(), {'sourceUnits': READING}, plan(READING),
                               target_locale='zh-Hans', flagged_units=['u3', 'u3'], library=LIBRARY)

    def test_and_between_non_adjacent_verses_is_not_a_range(self):
        rows = units('Revelation chapter 4 is our text.',
                     'Verses 2 and 5 say there is a throne and there are elders.',
                     'Let us look at it.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                            target_locale='zh-Hans', flagged_units=['u2'], library=LIBRARY)
        self.assertEqual(receipt['candidates'][0]['classification'], 'speaker_paraphrase')
        self.assertEqual(basis['discoveredUnits'], [])
        # Adjacent verses joined by "and" remain a range, as in the 605 reading.
        rows = units('Revelation chapter 4 is our text.', 'Verses 2 and 3 say there is a throne.', 'Amen.')
        _, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                      target_locale='zh-Hans', flagged_units=['u2'], library=LIBRARY)
        self.assertEqual(basis['candidates'][0]['reference'], 'REV 4:2-3')

    def test_adjacent_units_with_their_own_references_are_separate_quotations(self):
        rows = units('We read two verses tonight.',
                     f'John 3:16 says, "{READ_3_16}"',
                     f'John 3:17 says, "{READ_3_17}"',
                     'Let us pray.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows, size=4),
                                            target_locale='zh-Hans', flagged_units=['u2', 'u3'], library=LIBRARY)
        self.assertEqual([(c['sourceUnitIds'], c['reference']) for c in receipt['candidates']],
                         [(['u2'], 'JOH 3:16'), (['u3'], 'JOH 3:17')])
        self.assertEqual(basis['discoveredUnits'], ['u2', 'u3'])
        self.assertEqual(receipt['candidates'][1]['exactSentence'], LIBRARY.lookup('JOH 3:17')['text'])

    def test_a_book_transition_without_a_chapter_clears_the_old_context(self):
        rows = units('John chapter 3 is where we start.',
                     'Now turn to Romans.',
                     'Verse 2 says we are not to be conformed.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                            target_locale='zh-Hans', flagged_units=['u3'], library=LIBRARY)
        self.assertEqual(receipt['candidates'][0]['classification'], 'speaker_paraphrase')
        self.assertEqual(basis['discoveredUnits'], [])
        # "John says" is a speaker, not a transition: the Revelation context survives it.
        _, basis = machine.adjudicate(source(), {'sourceUnits': READING}, plan(READING),
                                      target_locale='zh-Hans', flagged_units=['u3'], library=LIBRARY)
        self.assertEqual(basis['candidates'][0]['reference'], 'REV 4:2-3')

    def test_a_reading_signal_is_borrowed_only_from_a_unit_about_scripture(self):
        rows = units('A friend says this changed everything.',
                     'John 3:16 is our focus for next week.',
                     'Think about that this week.')
        _, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                      target_locale='zh-Hans', flagged_units=['u2'], library=LIBRARY)
        self.assertEqual(basis['discoveredUnits'], [])
        rows = units('Revelation chapter 4 is our text.',
                     'Listen to what the Scripture says.',
                     'Verse 2: at once I was in the Spirit and saw a throne.')
        _, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                      target_locale='zh-Hans', flagged_units=['u3'], library=LIBRARY)
        self.assertEqual(basis['discoveredUnits'], ['u3'])

    def test_chapter_numbers_spoken_as_words_resolve(self):
        rows = units('Open your Bibles.',
                     f'John chapter three, verse sixteen says, "{READ_3_16}"',
                     'Amen.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                            target_locale='zh-Hans', flagged_units=['u2'], library=LIBRARY)
        self.assertEqual(receipt['candidates'][0]['reference'], 'JOH 3:16')
        self.assertEqual(basis['candidates'][0]['quoteBoundary'], machine.QUOTE_BOUNDARY)

    def test_quotation_marks_bound_the_quotation_and_commentary_outside_them_never_counts(self):
        # A quoted fragment followed by commentary that echoes the verse: only the quoted span is measured.
        rows = units('John 3:16 says, "For God so loved the world." God loved us and gave his Son, and we can have '
                     'life through belief.', 'Amen.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                            target_locale='zh-Hans', flagged_units=['u1'], library=LIBRARY)
        self.assertEqual(receipt['candidates'][0]['classification'], 'speaker_paraphrase')
        self.assertTrue(basis['candidates'][0]['reason'].startswith('fragment of JOH 3:16'))
        self.assertEqual(basis['candidates'][0]['coverage']['spokenSpan'], machine.QUOTED_SPAN)
        # The whole verse inside the marks is admitted even with commentary after the closing mark.
        rows = units(f'John 3:16 says, "{READ_3_16}" That is the whole gospel in one sentence, friends.', 'Amen.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                            target_locale='zh-Hans', flagged_units=['u1'], library=LIBRARY)
        self.assertEqual((receipt['candidates'][0]['classification'], receipt['candidates'][0]['reference']),
                         ('direct_quote', 'JOH 3:16'))
        self.assertEqual(basis['candidates'][0]['coverage']['spokenSpan'], machine.QUOTED_SPAN)
        # An unbalanced mark leaves the boundary unknown: nothing is admitted.
        rows = units(f'John 3:16 says, "{READ_3_16} And that is good news.', 'Amen.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                            target_locale='zh-Hans', flagged_units=['u1'], library=LIBRARY)
        self.assertEqual(receipt['candidates'][0]['classification'], 'speaker_paraphrase')
        self.assertIn('quotation_boundary_unknown', basis['candidates'][0]['reason'])
        # Without marks the unit's remainder is the quotation, and a remainder far longer than the verse is not it.
        rows = units(f'John 3:16 says, {READ_3_16} That tells us God acted first, before we believed anything at '
                     'all, and that his love reached the whole world.', 'Amen.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                            target_locale='zh-Hans', flagged_units=['u1'], library=LIBRARY)
        self.assertEqual(receipt['candidates'][0]['classification'], 'speaker_paraphrase')
        self.assertEqual(basis['candidates'][0]['coverage']['spokenSpan'], machine.UNIT_REMAINDER)
        self.assertGreater(basis['candidates'][0]['coverage']['lengthRatio'],
                           coverage_module.WHOLE_VERSE_LENGTH_MAX)

    def test_unit_boundaries_are_not_taken_for_verse_boundaries(self):
        # Two units, two verses, but the first unit runs into verse 17: the range stays bound to both units.
        words = READ_3_17.split()
        rows = units(f'John 3:16 and 17 say, {READ_3_16} ' + ' '.join(words[:3]), ' '.join(words[3:]), 'Amen.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows, size=3),
                                            target_locale='zh-Hans', flagged_units=['u1', 'u2'], library=LIBRARY)
        self.assertEqual([(c['sourceUnitIds'], c['classification'], c['reference']) for c in receipt['candidates']],
                         [(['u1', 'u2'], 'direct_quote', 'JOH 3:16-17')])
        self.assertEqual(receipt['candidates'][0]['exactSentence'], LIBRARY.lookup('JOH 3:16-17')['text'])
        self.assertEqual(basis['candidates'][0]['layout'], 'several units in one translation group share the whole range')
        self.assertIn('u1 also covers JOH 3:17', basis['candidates'][0]['boundaryEvidence'])
        # Split across translation groups, the joint range cannot be bound to one group.
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows, size=1),
                                            target_locale='zh-Hans', flagged_units=['u1', 'u2'], library=LIBRARY)
        self.assertEqual([c['classification'] for c in receipt['candidates']],
                         ['speaker_paraphrase', 'speaker_paraphrase'])
        self.assertIn('several translation groups', basis['candidates'][0]['reason'])
        # Units that each read their own whole verse and nothing of the neighbour keep one verse per unit.
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': READING}, plan(READING),
                                            target_locale='zh-Hans', flagged_units=['u3', 'u4'], library=LIBRARY)
        self.assertEqual([c['reference'] for c in receipt['candidates']], ['REV 4:2', 'REV 4:3'])
        self.assertEqual(basis['candidates'][0]['layout'], 'one verse per unit')
        self.assertIn('no neighbouring verse', basis['candidates'][0]['boundaryEvidence'])

    def test_compound_spoken_numbers_name_chapters_and_verses(self):
        edition = coverage_module.CoverageEdition.from_path()
        for spoken, ref in (('Psalm chapter twenty-three, verse one says', 'PSA 23:1'),
                            ('Psalm one hundred nineteen verse one hundred five says', 'PSA 119:105')):
            rows = units(f'{spoken}, {edition.lookup(ref)["text"]}', 'Amen.')
            receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                                target_locale='zh-Hans', flagged_units=['u1'], library=LIBRARY)
            self.assertEqual((receipt['candidates'][0]['classification'], receipt['candidates'][0]['reference']),
                             ('direct_quote', ref), spoken)
        rows = units('Verses twenty twenty say something.', 'Amen.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                            target_locale='zh-Hans', flagged_units=['u1'], library=LIBRARY)
        self.assertEqual(receipt['candidates'][0]['classification'], 'speaker_paraphrase')

    def test_every_name_the_library_knows_for_a_book_is_parsed(self):
        # "Song of Solomon" and "Song of Songs" both name SOL in cuv_scripture; the pattern must know both.
        rows = units('Open your Bibles.',
                     'Song of Solomon chapter two, verse one says, "I am a rose of Sharon, a lily of the valleys."',
                     'Amen.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                            target_locale='zh-Hans', flagged_units=['u2'], library=LIBRARY)
        self.assertEqual((receipt['candidates'][0]['classification'], receipt['candidates'][0]['reference']),
                         ('direct_quote', 'SOL 2:1'))
        self.assertEqual(basis['discoveredUnits'], ['u2'])
        for name in ('Song of Solomon', 'Song of Songs'):
            self.assertEqual(cuv_scripture.normalize_book(name), 'SOL')
            self.assertEqual(machine._scan(units(f'{name} chapter 2'))[0]['book'], 'SOL', name)

    def test_spoken_ordinals_name_the_epistle_not_the_gospel(self):
        whole = coverage_module.CoverageEdition.from_path().lookup('1JO 3:16')['text']
        for spoken in ('First John 3:16 says', '1st John 3:16 says', '1 John 3:16 says'):
            rows = units(f'{spoken}, {whole}', 'Amen.')
            receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                                target_locale='zh-Hans', flagged_units=['u1'], library=LIBRARY)
            self.assertEqual((receipt['candidates'][0]['classification'], receipt['candidates'][0]['reference']),
                             ('direct_quote', '1JO 3:16'), spoken)
            self.assertEqual(receipt['candidates'][0]['exactSentence'], LIBRARY.lookup('1JO 3:16')['text'])

    def test_an_unresolved_verse_mention_opens_its_own_run_and_borrows_nothing(self):
        rows = units(f'John 3:16 says, {READ_3_16}',
                     'Verses 2 and 5 say something about the light.',
                     'Amen.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows, size=3),
                                            target_locale='zh-Hans', flagged_units=['u1', 'u2'], library=LIBRARY)
        self.assertEqual([(c['sourceUnitIds'], c['classification'], c['reference']) for c in receipt['candidates']],
                         [(['u1'], 'direct_quote', 'JOH 3:16'), (['u2'], 'speaker_paraphrase', None)])
        self.assertEqual(basis['candidates'][1]['reason'], 'no book, chapter and verse reference resolves for this unit')
        self.assertEqual(basis['candidates'][1]['sourceUnitIds'], ['u2'])

    def test_an_edition_pending_publisher_verification_supplies_no_quotation(self):
        from scripts import scripture_editions
        pending = scripture_editions.Edition(edition_id='NKRV-1998', verification=scripture_editions.PENDING,
                                             verses={('REV', 4, 2): 'x', ('REV', 4, 3): 'y'})
        with mock.patch.object(scripture_editions, 'load', return_value=pending):
            receipt, basis = machine.adjudicate(source(), {'sourceUnits': READING}, plan(READING),
                                                target_locale='ko', flagged_units=['u1', 'u3', 'u4'])
        # Adjudication still runs: the unresolved unit and the whole readings all become paraphrases,
        # and only the readings that would have been pinned name the pending edition as the reason.
        self.assertEqual([(c['sourceUnitIds'], c['classification'], c['editionId'], c['exactSentence'])
                          for c in receipt['candidates']],
                         [(['u1'], 'speaker_paraphrase', None, None), (['u3'], 'speaker_paraphrase', None, None),
                          (['u4'], 'speaker_paraphrase', None, None)])
        self.assertIn('no book, chapter and verse', basis['candidates'][0]['reason'])
        self.assertTrue(basis['candidates'][1]['reason'].startswith('edition_not_verified: NKRV-1998'))
        self.assertEqual(basis['candidates'][1]['reference'], 'REV 4:2')
        self.assertTrue(basis['candidates'][1]['coverage']['wholeVerse'])
        self.assertEqual(basis['candidates'][2]['editionVerification'], scripture_editions.PENDING)
        self.assertEqual((basis['editionId'], basis['editionVerification']), ('NKRV-1998', scripture_editions.PENDING))
        with mock.patch.object(scripture_editions, 'load', return_value=pending):
            summary = adjudication.validate_receipt(as_human(receipt), target_locale='ko',
                                                    bindings=receipt['bindings'], flagged_units=['u1', 'u3', 'u4'])
        self.assertEqual(summary['quotes'], [])

    def test_later_references_in_one_unit_set_the_context_and_the_unit_binds_no_verse(self):
        rows = units('We compared John 3:16, then turn to Romans chapter 8.',
                     f'Verse 2 says, "{READ_8_2}"',
                     'Amen.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows, size=3),
                                            target_locale='zh-Hans', flagged_units=['u1', 'u2'], library=LIBRARY)
        # The context carried forward is the last one spoken (Romans 8), never John 3.
        self.assertEqual([(c['sourceUnitIds'], c['classification'], c['reference']) for c in receipt['candidates']],
                         [(['u1'], 'speaker_paraphrase', None), (['u2'], 'direct_quote', 'ROM 8:2')])
        self.assertEqual(receipt['candidates'][1]['exactSentence'], LIBRARY.lookup('ROM 8:2')['text'])
        self.assertIn(machine.SEVERAL_REFERENCES, basis['candidates'][0]['evidence'])
        self.assertEqual(basis['discoveredUnits'], ['u2'])
        # A unit naming two verse references binds neither of them, not the first.
        rows = units(f'John 3:16 says, "{READ_3_16}" and verse 17 says, "{READ_3_17}"', 'Amen.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                            target_locale='zh-Hans', flagged_units=['u1'], library=LIBRARY)
        self.assertEqual(receipt['candidates'][0]['classification'], 'speaker_paraphrase')
        self.assertIn(machine.SEVERAL_REFERENCES, basis['candidates'][0]['evidence'])
        self.assertEqual(basis['discoveredUnits'], [])
        # "turn to Romans chapter 8" is one mention; the transition inside it is not a second event.
        scanned = machine._scan(units('Turn to Romans chapter 8.', 'Verse 2 says it.'))
        self.assertEqual((scanned[0]['book'], scanned[0]['chapter'], scanned[0]['evidence']),
                         ('ROM', 8, ["book and chapter mention: 'Romans chapter 8'"]))
        self.assertEqual((scanned[1]['book'], scanned[1]['chapter'], scanned[1]['verseRange']), ('ROM', 8, (2, 2)))
        # A chapter named after a transition completes it: "turn to Romans, chapter 8".
        scanned = machine._scan(units('Turn to Romans, chapter 8, verse 2.'))
        self.assertEqual((scanned[0]['book'], scanned[0]['chapter'], scanned[0]['verseRange']), ('ROM', 8, (2, 2)))

    def test_a_fragment_is_translated_as_the_speakers_words_and_a_whole_reading_is_pinned(self):
        fragment = units('Genesis chapter 1 is where it all starts.',
                         'Verse 1 says, "In the beginning, God."',
                         'Three words.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': fragment}, plan(fragment),
                                            target_locale='zh-Hans', flagged_units=['u2'], library=LIBRARY)
        row, why = receipt['candidates'][0], basis['candidates'][0]
        self.assertEqual((row['classification'], row['editionId'], row['exactSentence']),
                         ('speaker_paraphrase', None, None))
        self.assertEqual((why['reference'], why['quoteBoundary']), ('GEN 1:1', machine.FRAGMENT_BOUNDARY))
        self.assertFalse(why['coverage']['wholeVerse'])
        self.assertLess(why['coverage']['lengthRatio'], coverage_module.WHOLE_VERSE_LENGTH_MIN)
        self.assertIn("translated as the speaker's own words", why['reason'])
        adjudication.validate_receipt(as_human(receipt), target_locale='zh-Hans', bindings=receipt['bindings'],
                                      flagged_units=['u2'], library=LIBRARY)
        whole = units('Genesis chapter 1 is where it all starts.',
                      'Verse 1 says, "In the beginning, God created the heavens and the earth."',
                      'Everything begins with him.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': whole}, plan(whole),
                                            target_locale='zh-Hans', flagged_units=['u2'], library=LIBRARY)
        self.assertEqual((receipt['candidates'][0]['classification'], receipt['candidates'][0]['reference']),
                         ('direct_quote', 'GEN 1:1'))
        self.assertEqual(basis['candidates'][0]['coverage']['editionId'], 'eng-web')
        # Commentary about the verse, however long, is not a reading of it.
        talk = units('Genesis chapter 1 is where it all starts.',
                     'Verse 1 says that before anything existed God was already there, making everything we '
                     'see and everything we cannot see, with nothing but his word.',
                     'Amen.')
        receipt, _ = machine.adjudicate(source(), {'sourceUnits': talk}, plan(talk),
                                        target_locale='zh-Hans', flagged_units=['u2'], library=LIBRARY)
        self.assertEqual(receipt['candidates'][0]['classification'], 'speaker_paraphrase')

    def test_a_verse_the_english_edition_lacks_is_not_admitted(self):
        rows = units('Acts chapter 8 is our text.',
                     'Verse 37 says, "I believe that Jesus Christ is the Son of God."',
                     'Amen.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                            target_locale='zh-Hans', flagged_units=['u2'], library=LIBRARY)
        self.assertEqual(receipt['candidates'][0]['classification'], 'speaker_paraphrase')
        self.assertIn('ACT 8:37', basis['candidates'][0]['reason'])
        self.assertEqual(basis['candidates'][0]['reference'], 'ACT 8:37')

    def test_a_missing_english_edition_refuses_before_any_decision(self):
        with mock.patch.object(coverage_module, 'DATA_PATH', Path('/nonexistent/eng-web.json')), \
                mock.patch.object(machine, '_DEFAULT_COVERAGE', []):
            with self.assertRaisesRegex(machine.MachineAdjudicationError, 'english_edition_unavailable'):
                machine.adjudicate(source(), {'sourceUnits': READING}, plan(READING),
                                   target_locale='zh-Hans', flagged_units=['u3'], library=LIBRARY)

    def test_a_verse_read_across_translation_groups_falls_back_to_paraphrase(self):
        rows = units('Revelation chapter 4 is our text.',
                     'Verse 2 says, Immediately I was in the Spirit, and there was a throne in heaven,',
                     'and someone was seated on it.',
                     'Amen.')
        split = plan(rows, size=1)
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, split,
                                            target_locale='zh-Hans', flagged_units=['u2', 'u3'], library=LIBRARY)
        self.assertEqual([c['classification'] for c in receipt['candidates']],
                         ['speaker_paraphrase', 'speaker_paraphrase'])
        self.assertIn('several translation groups', basis['candidates'][0]['reason'])
        joined = [{'translationGroupId': 'g1', 'sourceUnitIds': ['u1']},
                  {'translationGroupId': 'g2', 'sourceUnitIds': ['u2', 'u3']},
                  {'translationGroupId': 'g3', 'sourceUnitIds': ['u4']}]
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, joined,
                                            target_locale='zh-Hans', flagged_units=['u2', 'u3'], library=LIBRARY)
        self.assertEqual([(c['sourceUnitIds'], c['reference']) for c in receipt['candidates']],
                         [(['u2', 'u3'], 'REV 4:2')])
        self.assertIn('one translation group', basis['candidates'][0]['layout'])
        adjudication.validate_receipt(as_human(receipt), target_locale='zh-Hans', bindings=receipt['bindings'],
                                      flagged_units=['u2', 'u3'], library=LIBRARY)

    def test_an_explicit_empty_manifest_list_is_not_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp) / 'fixture'
            fixture.mkdir()
            for name, value in (('source.json', source()), ('anchor.json', {'sourceUnits': READING}),
                                ('group-plan.json', plan(READING)),
                                ('fixture-manifest.json', {'sourceQuotationUnits': []})):
                (fixture / name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            with self.assertRaisesRegex(machine.MachineAdjudicationError, 'no_flagged_units'):
                machine.adjudicate_fixture(fixture, target_locale='zh-Hans', library=LIBRARY)
            with self.assertRaisesRegex(SystemExit, 'no_flagged_units'):
                machine.main([str(fixture), '--out', str(Path(temp) / 'receipt.json')])
            _, basis = machine.adjudicate_fixture(fixture, target_locale='zh-Hans', discover=True, library=LIBRARY)
            self.assertEqual(basis['flaggedUnits'], ['u3'])

    def test_cli_writes_receipt_and_basis_once_and_reads_flags_from_the_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp) / 'fixture'
            fixture.mkdir()
            for name, value in (('source.json', source()), ('anchor.json', {'sourceUnits': READING}),
                                ('group-plan.json', plan(READING)),
                                ('fixture-manifest.json', {'sourceQuotationUnits': ['u3', 'u4']})):
                (fixture / name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            out = Path(temp) / 'receipt.json'
            self.assertEqual(machine.main([str(fixture), '--out', str(out)]), 0)
            receipt = json.loads(out.read_text(encoding='utf-8'))
            basis = json.loads(out.with_suffix('.basis.json').read_text(encoding='utf-8'))
            self.assertEqual(basis['flaggedUnits'], ['u3', 'u4'])
            self.assertEqual(basis['flaggedUnitsSource'], 'supplied')
            self.assertEqual(basis['receiptSha256'], adjudication.receipt_sha256(receipt))
            with self.assertRaisesRegex(SystemExit, 'exists'):
                machine.main([str(fixture), '--out', str(out)])


if __name__ == '__main__':
    unittest.main()
