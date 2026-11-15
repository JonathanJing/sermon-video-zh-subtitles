"""Offline tests for the poster design contract; no release, model or render is used."""
import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.delivery.posters import design

PROMPT = ('CONTENT BRIEF ...\nFIXED POSTER STYLE AND COMPOSITION:\n...\n'
          'Absolutely NO text, letters, scripture inscriptions.\n')
CONTEXT = dict(pageId='page', locale='zh-Hans', title='耶稣为属祂的人盖印',
               sourceIdentitySha256='a' * 64, contentSha256='b' * 64,
               cues={'translation-asr-u0163': '祂给你盖印。',
                     'translation-asr-u0445': '房子会倒，但你很安全，你有标记。',
                     'translation-asr-u0189': '耶稣站在锡安山上。'})


def candidate(cid, tier, term, group, quote, scores):
    return dict(id=cid, concept=cid + ' concept', primarySubject=cid + ' subject',
                supportingElement='', anchorTier=tier, anchorTerm=term,
                evidence=[dict(textGroupId=group, quote=quote, tier=tier)],
                scores=dict(zip(design.SCORE_AXES, scores)))


def valid_design():
    return dict(schemaVersion=design.SCHEMA, pageId='page', title='耶稣为属祂的人盖印',
                sourceIdentitySha256='a' * 64, contentSha256='b' * 64,
                candidates=[
                    candidate('seal', 'title', '印', 'translation-asr-u0163', '祂给你盖印。', [2, 2, 2, 2, 2, 2]),
                    candidate('shelter', 'illustration', '避难所', 'translation-asr-u0445',
                              '房子会倒，但你很安全，你有标记。', [1, 2, 1, 1, 1, 0]),
                    candidate('zion', 'passage', '锡安山', 'translation-asr-u0189', '耶稣站在锡安山上。', [2, 2, 1, 1, 1, 1]),
                ],
                choice=dict(candidateId='seal', why='the title names the seal'),
                artPrompt=PROMPT,
                userChoice=dict(status='confirmed', candidateId='seal', color='dark burgundy'))


class DesignContractTests(unittest.TestCase):
    def validate(self, value=None):
        return design.validate_design(value or valid_design(), CONTEXT)

    def test_valid_design_is_normalized_with_computed_totals(self):
        result = self.validate()
        totals = {row['id']: row['total'] for row in result['candidates']}
        self.assertEqual(totals, {'seal': 12, 'shelter': 6, 'zion': 8})
        self.assertEqual(result['choice']['total'], 12)
        self.assertEqual(result['validation']['chosenTier'], 'title')
        self.assertEqual(result['validation']['warnings'], [])

    def test_illustration_only_subject_is_rejected(self):
        value = valid_design()
        value['choice']['candidateId'] = 'shelter'
        with self.assertRaisesRegex(design.DesignError, 'illustration'):
            self.validate(value)

    def test_anchor_term_must_appear_in_title_or_anchored_quote(self):
        value = valid_design()
        value['candidates'][0]['anchorTerm'] = '龙卷风'
        value['candidates'][0]['evidence'][0]['quote'] = '祂给你盖印。'
        with self.assertRaisesRegex(design.DesignError, 'anchor term'):
            self.validate(value)

    def test_evidence_quote_must_be_the_exact_published_text(self):
        value = valid_design()
        value['candidates'][0]['evidence'][0]['quote'] = '祂给你盖印'
        with self.assertRaisesRegex(design.DesignError, 'exact published text'):
            self.validate(value)

    def test_unknown_evidence_group_is_rejected(self):
        value = valid_design()
        value['candidates'][0]['evidence'][0]['textGroupId'] = 'translation-asr-u9999'
        with self.assertRaisesRegex(design.DesignError, 'not in the published content'):
            self.validate(value)

    def test_lower_score_cannot_win_without_an_override_reason(self):
        value = valid_design()
        value['choice']['candidateId'] = 'zion'
        with self.assertRaisesRegex(design.DesignError, 'highest score'):
            self.validate(value)
        value['choice']['overrideReason'] = 'the user asked for the landscape motif this week'
        self.assertEqual(self.validate(value)['choice']['total'], 8)

    def test_placeholders_and_missing_template_markers_are_rejected(self):
        value = valid_design()
        value['artPrompt'] = PROMPT.replace('CONTENT BRIEF', 'CONTENT BRIEF {{title}}')
        with self.assertRaisesRegex(design.DesignError, 'placeholders'):
            self.validate(value)
        value = valid_design()
        value['artPrompt'] = 'a seal on paper'
        with self.assertRaisesRegex(design.DesignError, 'template'):
            self.validate(value)

    def test_pending_user_choice_is_allowed_but_warned(self):
        value = valid_design()
        value['userChoice'] = dict(status='pending')
        result = self.validate(value)
        self.assertEqual(result['validation']['warnings'], ['user choice is pending'])

    def test_duplicate_ids_and_bad_scores_are_rejected(self):
        value = valid_design()
        value['candidates'][1]['id'] = 'seal'
        with self.assertRaisesRegex(design.DesignError, 'unique'):
            self.validate(value)
        value = valid_design()
        value['candidates'][0]['scores']['directness'] = 3
        with self.assertRaisesRegex(design.DesignError, '0-2'):
            self.validate(value)

    def test_design_cannot_reuse_another_week_binding(self):
        value = valid_design()
        value['contentSha256'] = 'c' * 64
        with self.assertRaisesRegex(design.DesignError, 'contentSha256'):
            self.validate(value)


if __name__ == '__main__':
    unittest.main()
