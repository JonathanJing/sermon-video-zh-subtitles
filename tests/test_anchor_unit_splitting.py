import unittest

from tongxing_production.source import sentence_interpretation as anchors


def words(spec):
    """spec: list of (text, gap_before_seconds)."""
    out, cursor = [], 0.0
    for text, gap in spec:
        cursor += gap
        out.append({'text': text, 'start': cursor, 'end': cursor + 0.4})
        cursor += 0.4
    return out


class AnchorUnitSplittingTests(unittest.TestCase):
    def split(self, spec, max_seconds):
        return anchors._split_long_sentence(words(spec), max_seconds=max_seconds,
                                            min_unit_seconds=1.0, pause_seconds=0.3)

    def test_comma_without_pause_is_not_chosen_over_an_audible_break(self):
        spec = [('he', 0.0), ('said', 0.1), ('that', 0.1), ('is', 0.1),
                ('the', 0.1), ('most', 0.1), ('antiquated,', 0.1),
                ('outdated', 0.5), ('thing', 0.1), ('and', 0.1),
                ('then', 0.1), ('he', 0.1), ('left', 0.1)]
        parts, unresolved = self.split(spec, max_seconds=8.0)
        self.assertFalse(unresolved)
        self.assertNotEqual(parts[0][-1]['text'], 'antiquated,')

    def test_open_quotation_comma_is_not_a_boundary(self):
        spec = [('they', 0.0), ('said', 0.1), ('"the', 0.1), ('most', 0.1),
                ('antiquated,', 0.4), ('outdated', 0.1), ('thing"', 0.5),
                ('and', 0.5), ('then', 0.1), ('he', 0.1), ('left', 0.1),
                ('the', 0.1), ('room', 0.1), ('quickly', 0.1), ('today', 0.1)]
        parts, unresolved = self.split(spec, max_seconds=4.5)
        self.assertFalse(unresolved)
        self.assertTrue(parts[0][-1]['text'].endswith('thing"'))

    def test_weak_only_span_still_splits_without_marking_unresolved(self):
        spec = [('one', 0.0), ('two,', 0.1), ('three', 0.1), ('four,', 0.1),
                ('five', 0.1), ('six', 0.1)]
        parts, unresolved = self.split(spec, max_seconds=2.5)
        self.assertFalse(unresolved)
        self.assertGreater(len(parts), 1)


def timed_words(spec, chunk='chunk-0000'):
    """spec: list of (text, gap_before_seconds, duration_seconds) with stable word IDs."""
    out, cursor = [], 0.0
    for number, (text, gap, duration) in enumerate(spec, start=1):
        cursor += gap
        out.append({'wordId': f'{chunk}-w{number:04d}', 'text': text, 'start': round(cursor, 3),
                    'end': round(cursor + duration, 3)})
        cursor += duration
    return out


class ClauseStableSplittingTests(unittest.TestCase):
    """The v2 policy the production stage runs. Patterns are the 2026-10-18 episode's rejections."""

    def split(self, spec, max_seconds=8.0):
        parts, unresolved = anchors._split_clause_stable(
            timed_words(spec), max_seconds=max_seconds, min_unit_seconds=1.5, pause_seconds=0.35)
        return [' '.join(w['text'] for w in part) for part, _ in parts], unresolved

    def test_comma_after_filler_is_not_a_boundary_and_the_denial_stays_whole(self):
        spec = [('You', 0, .3), ('know,', 0, .3), ('I', .1, 1.5), ('am', 0, .5), ('not', 0, .3),
                ('a', 0, .2), ('firm,', .3, .5), ('like,', .2, .4), ('yes,', 0, .4), ("I'm", 0, .3),
                ('100%', 0, .7), ('confident', 0, .5), ('that', 0, .3), ("there's", .35, .3),
                ('a', 0, .2), ('future', 0, .4), ('seven-year', 0, .7), ('tribulation', 0, .5), ('period.', 0, .5)]
        texts, unresolved = self.split(spec)
        self.assertEqual(len(texts), 1)
        self.assertTrue(unresolved)

    def test_comma_inside_a_noun_list_is_not_chosen_over_the_audible_clause_break(self):
        spec = [('And', 0, .4), ("God's", .1, .4), ('people,', 0, .5), ('or', 0, .2), ('the', 0, .1),
                ('two', 0, .3), ('witnesses,', 0, .8), ('who', .4, .1), ('have', 0, .2), ('been', 0, .1),
                ('attacked', 0, .5), ('by', 0, .2), ('Rome,', 0, .5), ('the', 0, .1), ('beast,', 0, .7),
                ('by', .28, .8), ('Nero,', .52, .5), ('the', 0, .1), ('Roman', 0, .3), ('Empire,', 0, .6),
                ('they', .32, .3), ('are', 0, .4), ('harmed,', .3, .5), ('but', 0, .2), ('yet', 0, .4),
                ('we', .09, .2), ('know', 0, .1), ('that', 0, .2), ('they', 0, .4), ('rise', 0, .4), ('again.', 0, .6)]
        texts, unresolved = self.split(spec)
        self.assertFalse(unresolved)
        self.assertEqual(texts[0], "And God's people, or the two witnesses,")
        self.assertTrue(any(text.startswith('who have been attacked by Rome, the beast, by Nero, the Roman Empire,')
                            for text in texts))
        self.assertFalse(any(text.endswith('by') or text.endswith('Nero,') for text in texts))

    def test_long_pause_after_punctuation_allows_a_short_opening_unit(self):
        spec = [('Yeah,', 0, .2), ('the', 0, .1), ('timestamps,', 0, .4), ('again,', 0, .2),
                ('you', 1.68, .5), ('would', 0, .1), ('say', 0, .2), ('the', 0, .1), ('number', 0, .4),
                ('characterizes', 0, .7), ('the', 0, .1), ('whole', 0, .7), ('sort', .87, .2), ('of', 0, .3),
                ('inter-advent', .31, 1.4), ('age.', 0, .6)]
        texts, unresolved = self.split(spec)
        self.assertFalse(unresolved)
        self.assertEqual(texts[0], 'Yeah, the timestamps, again,')
        self.assertFalse(any(text.endswith('the whole') for text in texts))

    def test_pause_after_a_relative_contraction_or_filler_is_not_a_boundary(self):
        spec = [('So', 0, .1), ('I', 0, .4), ('think,', 0, .3), ('and', 0, .4), ('again,', 0, .5),
                ("I'm", .64, .3), ('not', 0, .1), ('a', 0, .1), ('postmillennial,', 0, .5), ('but', .11, .2),
                ('to', 0, .1), ('represent', 0, .6), ('the', 0, .1), ('postmillennial', 0, .6), ('view,', 0, .3),
                ('Kenneth', .51, .3), ('Gentry,', 0, .4), ("who's,", 0, .3), ('I', .03, .1), ('mean,', 0, .2),
                ('one', 0, .1), ('of', 0, .1), ('the', 0, .1), ('preeminent', 0, .6), ('scholars,', 0, .5),
                ('a', 0, .1), ('postmillennial', 0, .4), ('scholar,', 0, .5), ('just', .13, .3),
                ('incredible', 0, .8), ('work', 0, .2), ('that', 0, .1), ('he', 0, .1), ('wrote.', 0, .4)]
        texts, unresolved = self.split(spec)
        self.assertFalse(unresolved)
        self.assertTrue(texts[0].endswith('the postmillennial view,'), texts)

    def test_comma_before_a_clause_opener_is_used_when_nothing_audible_fits_the_target(self):
        spec = [('He', 0, .4)] + [(f'w{i}', 0, .5) for i in range(12)] + [('said,', 0, .5), ('but', 0, .3)] + \
               [(f'v{i}', 0, .5) for i in range(6)] + [('end.', 0, .4)]
        texts, unresolved = self.split(spec)
        self.assertFalse(unresolved)
        self.assertEqual(len(texts), 2)
        self.assertTrue(texts[0].endswith('said,'))

    def test_function_word_before_a_pause_cannot_end_a_unit(self):
        spec = [('We', 0, .4)] + [(f'w{i}', 0, .5) for i in range(12)] + [('by', 0, .3)] + \
               [(f'v{i}', .5 if i == 0 else 0, .5) for i in range(8)] + [('end.', 0, .4)]
        texts, unresolved = self.split(spec)
        self.assertTrue(unresolved)
        self.assertEqual(len(texts), 1)


    def test_operator_accepted_boundary_may_omit_punctuation_and_pause(self):
        spec = [('they', 0.0), ('walked', 0.1), ('the', 0.1), ('whole', 0.1),
                ('sort', 0.1), ('of', 0.1), ('age', 0.1),
                ('where', 0.1), ('he', 0.1), ('left', 0.1), ('today', 0.1)]
        words_list = words(spec)
        segments = [{'id': 0, 'referenceChunkId': 'block-00',
                     'text': 'they walked the whole sort of age where he left today',
                     'start': 0.0, 'end': words_list[-1]['end'],
                     'sentenceBoundarySource': 'frozen_reference_punctuation',
                     'wordTimes': [{'text': w['text'], 'start': w['start'], 'end': w['end']}
                                   for w in words_list]}]
        accepted = [w['text'] for w in words_list]
        word_id = 'block-00-w0007'  # after "age"
        overrides = {'block-00-s001': {'splitAfter': [word_id],
                                       'acceptDependentBoundaryAfter': [word_id]}}
        manifest = anchors.build_anchor_manifest(
            segments, source_path=self._source(segments), unit_policy=anchors.UNIT_POLICY_V2,
            max_unit_seconds=3.0, boundary_overrides=overrides)
        parts = [u['english'] for u in manifest['sourceUnits']]
        self.assertEqual(parts[0], 'they walked the whole sort of age')

    def _source(self, segments):
        import json, tempfile, pathlib
        path = pathlib.Path(tempfile.mkdtemp())/'segments.json'
        path.write_text(json.dumps(segments))
        self._source_path = path
        return path

if __name__ == '__main__':
    unittest.main()
