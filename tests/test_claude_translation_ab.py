"""Sol versus Opus A/B runner: interleaved arms, resumable, blind key rotates."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.experiments import claude_translation_ab as ab


def content(group, text='好。'):
    return {'translationGroupId': group, 'sourceUnitIds': [group + '-u1'], 'targetUtterances': [text],
            'coverage': [{'sourceUnitId': group + '-u1', 'targetText': text}]}


def review(group, draft, status='pass'):
    checks = {name: 'pass' for name in ab.SEMANTIC_CHECKS}
    if status == 'fail':
        checks['completeMeaning'] = 'fail'
    return {**content(group, draft['targetUtterances'][0]),
            'semanticReview': {'status': status, 'checks': checks, 'evidence': 'checked',
                               'uncertainty': [], 'issues': ['omission'] if status == 'fail' else []}}


class FakeTransport:
    calls = []

    def __init__(self, *args, effort='high', receipts_dir=None, **kwargs):
        self.model, self.effort = 'claude-opus-5-5', effort
        self.execution_identity = {'fake': True}

    def __call__(self, api_key, payload, role='translator'):
        data = json.loads(payload['messages'][1]['content'])
        group = data['translationGroupId']
        if payload.get('reasoning_effort') == 'medium':
            FakeTransport.calls.append((group, 'review', data['astraDraft']['targetUtterances'][0]))
            status = 'fail' if data['astraDraft']['targetUtterances'][0] == 'opus' and group == 'group-0002' else 'pass'
            return {'schemaVersion': 'codex-cli-layer2-response-v2', 'requestedModel': 'gpt-6.1-sol',
                    'content': json.dumps(review(group, data['astraDraft'], status)),
                    'usage': {'input_tokens': 50, 'output_tokens': 5}, 'elapsedSeconds': 3.0}
        arm = 'sol' if payload.get('model') == 'gpt-6.1-sol' else 'opus'
        FakeTransport.calls.append((group, arm))
        usage = ({'input_tokens': 100, 'output_tokens': 10} if arm == 'sol'
                 else {'inputTokens': 100, 'outputTokens': 20})
        return {'schemaVersion': ('codex-cli-layer2-response-v2' if arm == 'sol' else 'claude-cli-layer2-response-v1'),
                'requestedModel': 'gpt-6.1-sol' if arm == 'sol' else 'claude-opus-5-5',
                'content': json.dumps(content(group, arm)), 'usage': usage,
                'elapsedSeconds': 2.0 if arm == 'sol' else 1.0, 'listPriceUsd': 0.1 if arm == 'opus' else None}


class ClaudeTranslationABTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.baseline = self.root / 'baseline'
        self.baseline.mkdir()
        for group in ('group-0001', 'group-0002'):
            source = {'translationGroupId': group, 'sourceUnitIds': [group + '-u1']}
            payload = {'model': 'gpt-6.1-sol', 'messages': [{'role': 'system', 'content': 'Translate.'},
                                                           {'role': 'user', 'content': json.dumps(source)}]}
            (self.baseline / f'{group}-astra.policy-preview.json').write_text(json.dumps(
                {'role': 'translator', 'payload': payload, 'policy': {'targetLocale': 'ko'}}))
            reviewer = {'model': 'gpt-6.1-sol', 'messages': [
                {'role': 'system', 'content': 'Review.'},
                {'role': 'user', 'content': json.dumps({**source, 'astraDraft': {'old': True}})}]}
            (self.baseline / f'{group}-sol.policy-preview.json').write_text(json.dumps(
                {'role': 'reviewer', 'payload': reviewer, 'policy': {'targetLocale': 'ko'}}))
        repair = {'translationGroupId': 'group-0003', 'sourceUnitIds': ['group-0003-u1'], 'partialRepair': {}}
        (self.baseline / 'group-0003-astra.policy-preview.json').write_text(json.dumps(
            {'payload': {'messages': [{'role': 'system', 'content': 'x'},
                                      {'role': 'user', 'content': json.dumps(repair)}]}}))
        FakeTransport.calls = []
        for name in ('CodexLayer2Transport', 'ClaudeLayer2Transport'):
            patcher = patch.object(ab, name, FakeTransport)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_ab(self, *extra):
        ab.main(['--baseline', str(self.baseline), '--out', str(self.root / 'out'), *extra])

    def test_arms_interleave_and_resume_without_new_calls(self):
        self.run_ab()
        self.assertEqual(FakeTransport.calls, [('group-0001', 'sol'), ('group-0001', 'opus'),
                                               ('group-0002', 'opus'), ('group-0002', 'sol')])
        summary = json.loads((self.root / 'out' / 'summary.json').read_text())
        self.assertEqual(summary['opusFasterPairs'], 2)
        self.assertEqual(summary['targetLocale'], 'ko')
        self.assertEqual(summary['skippedRepairGroups'], ['group-0003'])
        self.assertEqual(summary['sol']['usage']['inputTokens'], 200)
        self.assertEqual(summary['opus']['usage']['outputTokens'], 40)
        key = json.loads((self.root / 'out' / 'blind-key.json').read_text())
        self.assertEqual([row['X'] for row in key], ['sol', 'opus'])
        self.run_ab()
        self.assertEqual(len(FakeTransport.calls), 4)

    def test_started_without_response_blocks_rerun(self):
        self.run_ab()
        (self.root / 'out' / 'group-0002' / 'opus' / 'response.json').unlink()
        with self.assertRaisesRegex(AssertionError, 'Unknown outcome'):
            self.run_ab()


    def test_review_swaps_only_the_draft_and_counts_passes(self):
        self.run_ab('--review')
        reviews = [call for call in FakeTransport.calls if call[1] == 'review']
        self.assertEqual(reviews, [('group-0001', 'review', 'sol'), ('group-0001', 'review', 'opus'),
                                   ('group-0002', 'review', 'opus'), ('group-0002', 'review', 'sol')])
        summary = json.loads((self.root / 'out' / 'summary.json').read_text())
        self.assertEqual(summary['sol']['review']['passed'], 2)
        self.assertEqual(summary['opus']['review']['passed'], 1)
        self.assertEqual(summary['opus']['review']['failed'], ['group-0002'])
        self.run_ab('--review')
        self.assertEqual(len(FakeTransport.calls), 8)

    def test_group_window_selects_groups(self):
        self.run_ab('--first-group', '2', '--group-count', '1')
        self.assertEqual({call[0] for call in FakeTransport.calls}, {'group-0002'})


if __name__ == '__main__':
    unittest.main()
