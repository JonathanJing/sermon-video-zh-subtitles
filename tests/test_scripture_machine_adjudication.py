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

from scripts import cuv_scripture
from scripts import scripture_adjudication as adjudication
from scripts import scripture_machine_adjudication as machine

LIBRARY = cuv_scripture.CuvLibrary.from_path()


def units(*rows):
    return [{'sourceUnitId': f'u{i + 1}', 'english': text, 'start': float(i), 'end': float(i + 1)}
            for i, text in enumerate(rows)]


READING = units(
    'Their whole world was filled with chaos.',
    'And so God\'s Word, Revelation chapter 4, this is part of the vision.',
    'Verse 2 and 3, John says, at once I was in the Spirit and saw a throne in heaven.',
    'The one seated there looked like precious stone, and a rainbow surrounded the throne.',
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
        summary = adjudication.validate_receipt(as_human(receipt), target_locale='zh-Hans',
                                                bindings=receipt['bindings'], flagged_units=['u3', 'u4'],
                                                library=LIBRARY)
        self.assertEqual(summary['coveredUnits'], ['u3', 'u4'])
        self.assertEqual([q['canonicalRef'] for q in summary['quotes']], ['REV 4:2', 'REV 4:3'])

    def test_machine_role_is_still_refused_by_the_unchanged_gate(self):
        receipt, _ = machine.adjudicate(source(), {'sourceUnits': READING}, plan(READING),
                                        target_locale='zh-Hans', flagged_units=['u3', 'u4'], library=LIBRARY)
        with self.assertRaisesRegex(adjudication.AdjudicationError, 'decided_by_not_human'):
            adjudication.validate_receipt(receipt, target_locale='zh-Hans', bindings=receipt['bindings'],
                                          flagged_units=['u3', 'u4'], library=LIBRARY)

    def test_discovery_flags_the_opening_unit_and_one_continuation_per_verse(self):
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': READING}, plan(READING),
                                            target_locale='zh-Hans', library=LIBRARY)
        self.assertEqual(basis['flaggedUnits'], ['u3', 'u4'])
        self.assertEqual(basis['flaggedUnitsSource'], 'discovered')
        self.assertEqual([c['reference'] for c in receipt['candidates']], ['REV 4:2', 'REV 4:3'])

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
                     'Verses 2 through 3 read, "at once I was in the Spirit, and the one seated there shone."',
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
        # Supplied flags still resolve: a reference exists even without a reading verb.
        self.assertEqual(basis['candidates'][0]['decision'], 'direct_quote')

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
        receipt, _ = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                        target_locale='zh-Hans', flagged_units=['u2'], library=LIBRARY)
        self.assertEqual(receipt['candidates'][0]['reference'], 'REV 4:2-3')

    def test_adjacent_units_with_their_own_references_are_separate_quotations(self):
        rows = units('We read two verses tonight.',
                     'John 3:16 says, "God loved the world."',
                     'John 3:17 says, "God sent his Son to save."',
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
        receipt, _ = machine.adjudicate(source(), {'sourceUnits': READING}, plan(READING),
                                        target_locale='zh-Hans', flagged_units=['u3'], library=LIBRARY)
        self.assertEqual(receipt['candidates'][0]['reference'], 'REV 4:2-3')

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
                     'John chapter three, verse sixteen says, "God loved the world."',
                     'Amen.')
        receipt, basis = machine.adjudicate(source(), {'sourceUnits': rows}, plan(rows),
                                            target_locale='zh-Hans', flagged_units=['u2'], library=LIBRARY)
        self.assertEqual(receipt['candidates'][0]['reference'], 'JOH 3:16')
        self.assertEqual(basis['candidates'][0]['quoteBoundary'], machine.QUOTE_BOUNDARY)

    def test_a_verse_read_across_translation_groups_falls_back_to_paraphrase(self):
        rows = units('Revelation chapter 4 is our text.',
                     'Verse 2 says, at once I was in the Spirit',
                     'and I saw a throne standing in heaven.',
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
            self.assertEqual(basis['flaggedUnits'], ['u3', 'u4'])

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
