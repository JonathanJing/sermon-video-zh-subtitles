import unittest

from tongxing_production.source import review_sheet as rs


class ProposalTests(unittest.TestCase):
    def test_rule_readings(self):
        cases = {'144,000,': 'one hundred forty four thousand', '70th?': 'seventieth', '2nd': 'second',
                 '21st': 'twenty first', '1.5': 'one point five', '100%': 'one hundred percent',
                 '5:9': 'five nine', '$20': 'twenty dollars'}
        for token, words in cases.items():
            with self.subTest(token=token):
                self.assertEqual(' '.join(rs.propose_spoken_form(token)['words']), words)
        before = rs.propose_spoken_form('$1.5', 'million')
        self.assertEqual(before['words'], ['one', 'point', 'five'])
        self.assertEqual(before['rule'], 'currency_before_magnitude')
        for token in ('007', '1/2', '1,000,000,000'):
            self.assertIsNone(rs.propose_spoken_form(token), token)

    def test_items_group_tokens_and_leave_unsafe_ones_to_the_person(self):
        refs = [{'id': 'c0', 'text': 'In 2nd place, 007 won 1.5 points.'}, {'id': 'c1', 'text': 'Then 2nd again.'}]
        items = rs.spoken_form_items(refs, {'1.5': ['one', 'point', 'five']})
        by = {i['token']: i for i in items}
        self.assertEqual(set(by), {'2nd', '007'})
        self.assertEqual(by['2nd']['rows'], ['c0', 'c1'])
        self.assertEqual(by['007']['default'], {'action': 'words', 'words': None})


class CrossCheckTests(unittest.TestCase):
    def test_dash_spellings_are_not_disagreements_and_partial_tokens_keep_their_shared_words(self):
        refs = [{'id': 'c0', 'start': 0, 'end': 10, 'text': 'And so—and then I remember one of—I shared it.'}]
        items = rs.cross_check(refs, 'And so, and then I remember I shared it.', 'second', [], 0.0)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual((item['asr'], item['alternative']), ('one of—I', 'I'))
        decided = {'decisions': {item['id']: {'action': 'take_alternative'}}}
        sheet = {'items': items}
        derived = rs.derive(sheet, decided, {}, refs)
        self.assertEqual(derived['corrected'][0]['text'], 'And so—and then I remember I shared it.')
        self.assertEqual(derived['rowsWithChangedText'], ['c0'])

    def test_filler_only_disagreements_are_grouped(self):
        refs = [{'id': 'c0', 'start': 0, 'end': 10, 'text': 'So um we go now.'}]
        items = rs.cross_check(refs, 'So we go now.', 'second', [], 0.0)
        self.assertEqual([i['class'] for i in items], ['filler'])


class DerivationCheckTests(unittest.TestCase):
    def manifest(self, sentences):
        return {'sourceUnits': [{'sourceSentenceId': sid, 'english': text, 'sourceWordIds': [sid + '-w'], 'start': 0, 'end': 1}
                                for sid, text in sentences]}

    def test_changes_outside_the_decided_rows_are_reported(self):
        spec = self.manifest([('c0-s001', 'a'), ('c1-s001', 'b')])
        final = self.manifest([('c0-s001', 'a2'), ('c1-s001', 'b2')])
        refs = [{'id': 'c0', 'text': 'a'}, {'id': 'c1', 'text': 'b'}]
        check = rs.derivation_check(speculative_refs=refs, final_refs=refs, speculative_manifest=spec,
                                    final_manifest=final, allowed_rows={'c0'}, override_sentences=set())
        self.assertFalse(check['withinConfirmation'])
        self.assertEqual(check['unexpectedSentences'], ['c1-s001'])


if __name__ == '__main__':
    unittest.main()
