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


if __name__ == '__main__':
    unittest.main()
