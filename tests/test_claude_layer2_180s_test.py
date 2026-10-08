import json
import tempfile
import unittest
from pathlib import Path

from scripts.experiments import claude_layer2_180s_test as runner

BASELINE = Path('artifacts/codex-cli-layer2-180s-20261005')


def review(**overrides):
    semantic = {'status': 'pass', 'checks': {name: 'pass' for name in runner.CHECKS},
                'evidence': 'ok', 'uncertainty': [], 'issues': []}
    semantic.update(overrides)
    return {'semanticReview': semantic}


class VerdictTest(unittest.TestCase):
    def test_all_pass_is_passed(self):
        self.assertTrue(runner.review_passed(review()))

    def test_any_failed_check_blocks(self):
        checks = {name: 'pass' for name in runner.CHECKS} | {'noAddedMeaning': 'fail'}
        self.assertFalse(runner.review_passed(review(status='fail', checks=checks)))

    def test_issue_or_uncertainty_blocks_even_with_pass_status(self):
        self.assertFalse(runner.review_passed(review(issues=['x'])))
        self.assertFalse(runner.review_passed(review(uncertainty=['y'])))


class ReviewerPromptTest(unittest.TestCase):
    def test_only_the_draft_is_replaced(self):
        if not (BASELINE / 'group-0001-sol.policy-preview.json').exists():
            self.skipTest('frozen baseline is not present in this checkout')
        group = runner.load_groups(BASELINE.resolve())[0]
        draft = json.loads(json.dumps(json.loads(group['reviewerMessages'][1]['content'])['astraDraft']))
        draft['targetUtterances'] = ['替换文本']
        messages = runner.reviewer_messages(group['reviewerMessages'], draft)
        self.assertEqual(messages[0], group['reviewerMessages'][0])
        user = json.loads(messages[1]['content'])
        self.assertEqual(user['astraDraft']['targetUtterances'], ['替换文本'])
        self.assertEqual(user['englishUnits'], json.loads(group['reviewerMessages'][1]['content'])['englishUnits'])

    def test_unexpected_draft_fields_are_refused(self):
        frozen = [{'role': 'system', 'content': 's'},
                  {'role': 'user', 'content': json.dumps({'astraDraft': {'a': 1}})}]
        with self.assertRaises(AssertionError):
            runner.reviewer_messages(frozen, {'b': 2})


class CallRecoveryTest(unittest.TestCase):
    def test_unknown_outcome_blocks_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            messages = [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'u'}]

            def fail(_messages):
                raise RuntimeError('terminal failure')

            with self.assertRaises(RuntimeError):
                runner.run_call(job, 'translator', fail, messages)
            with self.assertRaisesRegex(AssertionError, 'Unknown outcome'):
                runner.run_call(job, 'translator', fail, messages)

    def test_saved_response_is_reused_only_for_the_same_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            messages = [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'u'}]
            calls = []

            def ok(_messages):
                calls.append(1)
                return {'content': '{}', 'usage': {}}

            first, new, attempts = runner.run_call(job, 'reviewer', ok, messages)
            again, new_again, _ = runner.run_call(job, 'reviewer', ok, messages)
            self.assertTrue(new)
            self.assertFalse(new_again)
            self.assertEqual(attempts, 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(first, again)
            changed = [{'role': 'system', 'content': 's2'}, {'role': 'user', 'content': 'u'}]
            with self.assertRaisesRegex(AssertionError, 'Cached prompt changed'):
                runner.run_call(job, 'reviewer', ok, changed)

    def test_terminal_failure_retries_once_and_keeps_each_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            messages = [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'u'}]
            outcomes = [RuntimeError(runner.TERMINAL_FAILURE), {'content': '{}', 'usage': {}}]

            def call(_messages):
                outcome = outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome

            response, fresh, attempts = runner.run_call(job, 'reviewer', call, messages, max_attempts=2)
            self.assertEqual((response['content'], fresh, attempts), ('{}', True, 2))
            self.assertTrue((job / 'reviewer' / 'started.attempt-1.json').exists())
            # The successful attempt keeps started.json, which binds the saved response's prompt hash.
            self.assertEqual(json.loads((job / 'reviewer' / 'started.json').read_text())['attempt'], 2)
            failures = json.loads((job / 'reviewer' / 'failures.json').read_text())
            self.assertEqual([row['attempt'] for row in failures], [1])
            again, new_again, attempts_again = runner.run_call(job, 'reviewer', call, messages, max_attempts=2)
            self.assertEqual((new_again, attempts_again), (False, 2))

    def test_terminal_failure_stops_after_the_attempt_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            messages = [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'u'}]
            calls = []

            def call(_messages):
                calls.append(1)
                raise RuntimeError(runner.TERMINAL_FAILURE)

            with self.assertRaisesRegex(RuntimeError, 'after 2 attempts'):
                runner.run_call(job, 'reviewer', call, messages, max_attempts=2)
            self.assertEqual(len(calls), 2)
            failures = json.loads((job / 'reviewer' / 'failures.json').read_text())
            self.assertEqual([row['attempt'] for row in failures], [1, 2])
            self.assertFalse((job / 'reviewer' / 'started.json').exists())
            with self.assertRaisesRegex(RuntimeError, 'after 2 attempts'):
                runner.run_call(job, 'reviewer', call, messages, max_attempts=2)
            self.assertEqual(len(calls), 2)

    def test_timeout_is_never_retried_and_blocks_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            messages = [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'u'}]
            calls = []

            def timeout(_messages):
                calls.append(1)
                raise RuntimeError('claude_language_timeout')

            with self.assertRaisesRegex(RuntimeError, 'claude_language_timeout'):
                runner.run_call(job, 'reviewer', timeout, messages, max_attempts=2)
            self.assertTrue((job / 'reviewer' / 'started.json').exists())
            with self.assertRaisesRegex(AssertionError, 'Unknown outcome'):
                runner.run_call(job, 'reviewer', timeout, messages, max_attempts=2)
            self.assertEqual(len(calls), 1)


class GroupDecisionTest(unittest.TestCase):
    def test_decision_is_appended_to_system_prompt_only(self):
        frozen = [{'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'u'}]
        decided = runner.with_group_decision(frozen, 'Keep the English title Super Bloom.')
        self.assertEqual(frozen[0]['content'], 'rules')
        self.assertTrue(decided[0]['content'].startswith('rules\n\nProject decision'))
        self.assertIn('Keep the English title Super Bloom.', decided[0]['content'])
        self.assertEqual(decided[1], frozen[1])

    def test_no_decision_keeps_the_frozen_prompt(self):
        frozen = [{'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'u'}]
        self.assertEqual(runner.with_group_decision(frozen, None), frozen)


if __name__ == '__main__':
    unittest.main()
