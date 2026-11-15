"""Offline tests for the design drafter: the model is faked, no call is made."""
import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.delivery.posters import draft_design, design

TEMPLATE = """Create one text-free portrait 2:3 background.
Title: {{title}}
Series: {{series}}
Scripture: {{scripture}}
Central message: {{central_message}}
Tension: {{tension}}
Response: {{response}}
Visual concept: {{visual_concept}}
Primary subject: {{primary_subject}}
Setting: {{setting}}
Supporting element: {{supporting_element}}
Mood: {{mood}}
Color and light: {{color_and_light}}
Meaning to preserve: {{meaning_to_preserve}}
Meaning NOT to imply: {{meaning_to_avoid}}
FIXED POSTER STYLE AND COMPOSITION:
upper 40% quiet, subject 40-66%, bottom third quiet.
Absolutely NO text, letters, scripture inscriptions.
"""
CONTEXT = dict(pageId='page', locale='zh-Hans', title='耶稣为属祂的人盖印',
               series='启示录：耶稣带来的安慰与盼望', scripture='启示录 14 章',
               speaker='Eric Geiger', date='2026-11-01',
               sourceIdentitySha256='a' * 64, contentSha256='b' * 64,
               cues={'g1': '祂给你盖印。', 'g2': '房子会倒，但你很安全，你有标记。'})


def candidate(cid, tier, term, group, scores):
    return dict(id=cid, concept=cid + ' concept', primarySubject=cid + ' subject',
                supportingElement='', anchorTier=tier, anchorTerm=term,
                evidence=[dict(textGroupId=group, tier=tier, quote='model must not control this')],
                scores=dict(zip(design.SCORE_AXES, scores)), risks=['risk'])


def model_output(chosen='seal'):
    return dict(centralMessage='耶稣盖印属祂的人', tension='风暴与审判', response='信靠并安息',
                candidates=[candidate('seal', 'title', '印', 'g1', [2, 2, 2, 2, 2, 2]),
                            candidate('shelter', 'illustration', '避难所', 'g2', [1, 2, 1, 1, 1, 0])],
                choice=dict(candidateId=chosen, why='title names the seal', rejected=[dict(candidateId='shelter', reason='illustration')]),
                promptFields=dict(visualConcept='一枚封蜡', primarySubject='一枚封蜡', setting='暖白信纸',
                                  supportingElement='', mood='安静', colorAndLight='暗酒红与暖白',
                                  meaningToPreserve='印记表示归属', meaningToAvoid='不画文字'))


class DraftTests(unittest.TestCase):
    def assemble(self, output=None, chosen='seal'):
        return draft_design.assemble(output or model_output(chosen), CONTEXT, TEMPLATE,
                                     'docs/prompts/template.txt')

    def test_draft_fills_quotes_from_published_text_and_validates(self):
        normalized, prompt = self.assemble()
        self.assertEqual(normalized['candidates'][0]['evidence'][0]['quote'], '祂给你盖印。')
        self.assertEqual(normalized['choice']['candidateId'], 'seal')
        self.assertEqual(normalized['userChoice']['status'], 'pending')
        self.assertIn('耶稣为属祂的人盖印', prompt)
        self.assertNotIn('{{', prompt)
        self.assertEqual(normalized['validation']['warnings'], ['user choice is pending'])

    def test_model_cannot_invent_evidence_text(self):
        normalized, _ = self.assemble()
        self.assertNotIn('model must not control this',
                         normalized['candidates'][0]['evidence'][0]['quote'])

    def test_unknown_evidence_group_is_rejected(self):
        output = model_output()
        output['candidates'][0]['evidence'][0]['textGroupId'] = 'not-a-real-group'
        with self.assertRaisesRegex(draft_design.DraftError, 'textGroupId'):
            self.assemble(output)

    def test_choosing_an_illustration_anchor_is_rejected(self):
        with self.assertRaisesRegex(design.DesignError, 'illustration'):
            self.assemble(chosen='shelter')

    def test_anchor_term_must_be_anchored(self):
        output = model_output()
        output['candidates'][0]['anchorTerm'] = '龙卷风'
        with self.assertRaisesRegex(design.DesignError, 'anchor term'):
            self.assemble(output)

    def test_prompt_includes_cues_history_and_template(self):
        prompt = draft_design.build_prompt(CONTEXT, TEMPLATE, '| 11-01 | 启14 | 封蜡 | title | 印 | 采纳 |')
        self.assertIn('g1', prompt)
        self.assertIn('祂给你盖印。', prompt)
        self.assertIn('封蜡', prompt)
        self.assertIn('FIXED POSTER STYLE', prompt)
        self.assertIn('title|keyverse|passage|illustration', prompt)

    def test_missing_prompt_field_is_rejected(self):
        output = model_output()
        del output['promptFields']['mood']
        with self.assertRaises(KeyError):
            self.assemble(output)


if __name__ == '__main__':
    unittest.main()
