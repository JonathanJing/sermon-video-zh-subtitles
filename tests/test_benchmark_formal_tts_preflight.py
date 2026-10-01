"""Frozen diagnostic input failures must stop before GPU preparation/output writes."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.experiments import benchmark_formal_tts as benchmark


def manifest():
    cases = []
    for locale in ('zh-Hans', 'ko', 'es'):
        for kind in ('short', 'long'):
            text = f'{locale} {kind} approved sentence.'
            cases.append({'caseId': f'{locale}-{kind}', 'targetLocale': locale,
                          'lengthClass': kind, 'text': text,
                          'textSha256': hashlib.sha256(text.encode()).hexdigest(),
                          'sourceAdapter': {'conditioningSha256': 'a' * 64,
                                            'speakerKey': 'eric_pilot'}})
    for locale in ('zh-Hans', 'es'):
        row = copy.deepcopy(next(row for row in cases if row['targetLocale'] == locale))
        row.update(caseId=f'{locale}-batch-fill', lengthClass='batch-fill')
        cases.append(row)
    return {'schemaVersion': 'formal-tts-component-benchmark-inputs-v1',
            'releaseEligible': False, 'checkpointSha256': 'a' * 64,
            'speakerKey': 'eric_pilot', 'cases': cases}


class FormalTTSPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input_path = self.root / 'inputs.json'
        self.out = self.root / 'new-results'

    def invoke(self, value, *extra):
        self.input_path.write_text(json.dumps(value))
        argv = ['benchmark_formal_tts', '--inputs', str(self.input_path),
                '--checkpoint', str(self.root / 'absent-checkpoint'),
                '--out', str(self.out), *extra]
        with patch('sys.argv', argv), patch.object(benchmark, 'sha') as hash_file, \
                patch.object(benchmark, 'Memory') as gpu_memory, \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            try:
                benchmark.main()
            finally:
                self.assertFalse(hash_file.called, 'Model preparation must not begin')
                self.assertFalse(gpu_memory.called, 'GPU memory access must not begin')
                self.assertFalse(self.out.exists(), 'Rejected/planned inputs must not create outputs')
            return json.loads(output.getvalue())

    def rejects_before_preparation(self, value, expected, *extra):
        with self.assertRaisesRegex(ValueError, expected):
            self.invoke(value, *extra)
        self.assertFalse(self.out.exists())

    def test_plan_has_eight_cases_and_eight_conditions_without_model_files(self):
        value = self.invoke(manifest(), '--plan')
        self.assertEqual(len(value['cases']), 8)
        self.assertEqual(len(value['conditions']), 8)

    def test_single_cold_condition_can_plan_without_gpu(self):
        self.invoke(manifest(), '--plan', '--phase', 'cold', '--condition', 'mixed-b8')

    def test_missing_tail_case_is_rejected(self):
        value = manifest()
        value['cases'].pop()
        self.rejects_before_preparation(value, 'Eight unique')

    def test_duplicate_case_mapping_is_rejected(self):
        value = manifest()
        value['cases'][-1]['caseId'] = value['cases'][0]['caseId']
        self.rejects_before_preparation(value, 'Eight unique')

    def test_two_short_cases_do_not_substitute_for_short_and_long(self):
        value = manifest()
        value['cases'][1]['lengthClass'] = 'short'
        self.rejects_before_preparation(value, 'exactly the original short and long')

    def test_batch_fill_does_not_substitute_for_locale_long_case(self):
        value = manifest()
        value['cases'][3]['lengthClass'] = 'batch-fill'
        self.rejects_before_preparation(value, 'exactly the original short and long')

    def test_changed_text_with_stale_sha_is_rejected(self):
        value = manifest()
        value['cases'][4]['text'] = 'Changed sermon wording.'
        self.rejects_before_preparation(value, 'Frozen source case')

    def test_wrong_locale_is_rejected(self):
        value = manifest()
        value['cases'][4]['targetLocale'] = 'en'
        self.rejects_before_preparation(value, 'Frozen source case')

    def test_wrong_case_checkpoint_is_rejected(self):
        value = manifest()
        value['cases'][7]['sourceAdapter']['conditioningSha256'] = 'b' * 64
        self.rejects_before_preparation(value, 'Frozen source case')

    def test_wrong_case_speaker_is_rejected(self):
        value = manifest()
        value['cases'][7]['sourceAdapter']['speakerKey'] = 'different_speaker'
        self.rejects_before_preparation(value, 'Frozen source case')

    def test_empty_or_oversized_text_is_rejected_even_with_matching_sha(self):
        for text in ('', 'x' * 121):
            with self.subTest(length=len(text)):
                value = manifest()
                value['cases'][0].update(text=text,
                    textSha256=hashlib.sha256(text.encode()).hexdigest())
                self.rejects_before_preparation(value, 'Frozen source case')

    def test_release_eligible_input_is_rejected(self):
        value = manifest()
        value['releaseEligible'] = True
        self.rejects_before_preparation(value, 'Diagnostic input')

    def test_cold_all_requires_separate_processes_before_any_model_load(self):
        self.rejects_before_preparation(manifest(), 'separate fresh Python processes', '--phase', 'cold')


if __name__ == '__main__':
    unittest.main()
