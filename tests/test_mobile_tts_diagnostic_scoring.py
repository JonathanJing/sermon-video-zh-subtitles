"""Synthetic metadata only: never invoke the worker, model, audio or controller."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'experiments/mobile-live-translation/runtime_tts_mac.py'
SPEC = importlib.util.spec_from_file_location('mobile_tts_diagnostic_scoring', SCRIPT)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def fake_call(*, stream=True, samples=(24000, 24000), elapsed_ms=1000, warmup=False):
    chunks = [
        {'index': index, 'sampleCount': count, 'reportedSampleCount': count, 'sampleRate': 24000,
         'is_streaming': stream, 'is_final': index == len(samples) - 1}
        for index, count in enumerate(samples)
    ]
    return {
        'callKey': ('warmup-' if warmup else '') + ('stream-' if stream else 'batch-') + 'synthetic',
        'fixture': {'id': 'synthetic', 'textSha256': 'synthetic-text-identity'},
        'warmup': warmup, 'streamRequested': stream, 'generatorExhausted': True,
        'error': None, 'finitePcm': True, 'sampleRate': 24000,
        'returnedSampleCount': sum(samples), 'fullCompletionMs': elapsed_ms,
        'observedCodecTokens': 24, 'effectiveMaxCodecTokens': 75,
        'nonStreamingFallbackAfterStreaming': False, 'chunks': chunks,
    }


class MobileTtsDiagnosticScoringTest(unittest.TestCase):
    def setUp(self):
        self.batch = fake_call(stream=False, samples=(48000,))

    def score(self, record, batch=None):
        return MOD.score_call(record, self.batch if batch is None else batch)

    def test_sample_deficit_and_surplus_do_not_qualify_even_when_fast(self):
        for count in (23000, 25000):
            with self.subTest(second_chunk=count):
                score = self.score(fake_call(samples=(24000, count), elapsed_ms=400))
                self.assertTrue(score['transportIntegrityPassed'])
                self.assertEqual(score['sampleCoverageStatus'], 'mismatch')
                self.assertEqual(score['sampleCountDeltaFromBatch'], count - 24000)
                self.assertLess(score['rtfRawReturnedConcatenation'], 1)
                self.assertIsNone(score['qualifiedRtf'])
                self.assertEqual(score['sustainedRealtimeStatus'], 'ineligible')
                self.assertFalse(score['qualifiedIncrementalAudio'])

    def test_complete_slow_stream_keeps_valid_rtf_but_is_not_eligible(self):
        score = self.score(fake_call(elapsed_ms=3000))
        self.assertTrue(score['transportIntegrityPassed'])
        self.assertEqual(score['sampleCoverageStatus'], 'matched')
        self.assertEqual(score['qualifiedRtf'], 1.5)
        self.assertEqual(score['sustainedRealtimeStatus'], 'ineligible')
        self.assertFalse(score['qualifiedIncrementalAudio'])

    def test_rtf_boundary_is_inclusive_and_does_not_approve_quality(self):
        for elapsed, eligible in ((1000, True), (2000, True), (2000.001, False)):
            with self.subTest(elapsed=elapsed):
                score = self.score(fake_call(elapsed_ms=elapsed))
                self.assertEqual(score['qualifiedIncrementalAudio'], eligible)
                for field in ('codecEosStatus', 'semanticCompletenessStatus',
                              'listeningQualityStatus', 'longRunRealtimeStatus'):
                    self.assertEqual(score[field], 'unknown')

    def test_batch_retains_numeric_rtf_without_claiming_incremental_audio(self):
        score = MOD.score_call(self.batch)
        self.assertTrue(score['transportIntegrityPassed'])
        self.assertEqual(score['sampleCoverageStatus'], 'not_applicable')
        self.assertEqual(score['qualifiedRtf'], 0.5)
        self.assertEqual(score['sustainedRealtimeStatus'], 'not_applicable')
        self.assertFalse(score['qualifiedIncrementalAudio'])

    def test_missing_batch_is_unknown(self):
        score = MOD.score_call(fake_call())
        self.assertEqual(score['sampleCoverageStatus'], 'unknown')
        self.assertIsNone(score['sampleCoverageBatchCallKey'])
        self.assertIsNone(score['sampleCountDeltaFromBatch'])
        self.assertIsNone(score['qualifiedRtf'])
        self.assertEqual(score['sustainedRealtimeStatus'], 'unknown')
        self.assertFalse(score['qualifiedIncrementalAudio'])

    def test_unusable_batch_cannot_establish_coverage(self):
        for change in (
            {'fixture': {'id': 'different', 'textSha256': 'synthetic-text-identity'}},
            {'fixture': {'id': 'synthetic', 'textSha256': 'different'}},
            {'warmup': True}, {'streamRequested': True}, {'sampleRate': 16000},
            {'error': {'type': 'SyntheticFailure'}}, {'generatorExhausted': False},
            {'finitePcm': False}, {'returnedSampleCount': 0},
            {'observedCodecTokens': 75},
        ):
            with self.subTest(change=change):
                batch = {**copy.deepcopy(self.batch), **change}
                score = self.score(fake_call(), batch)
                self.assertEqual(score['sampleCoverageStatus'], 'unknown')
                self.assertEqual(score['sustainedRealtimeStatus'], 'unknown')
                self.assertFalse(score['qualifiedIncrementalAudio'])

    def test_missing_or_invalid_timing_stays_unknown(self):
        for elapsed in (None, 0, -1, float('nan'), float('inf'), True, '1000'):
            with self.subTest(elapsed=elapsed):
                score = self.score(fake_call(elapsed_ms=elapsed))
                self.assertEqual(score['sampleCoverageStatus'], 'matched')
                self.assertIsNone(score['rtfRawReturnedConcatenation'])
                self.assertIsNone(score['qualifiedRtf'])
                self.assertEqual(score['sustainedRealtimeStatus'], 'unknown')
                self.assertFalse(score['qualifiedIncrementalAudio'])
        record = fake_call()
        del record['fullCompletionMs']
        self.assertEqual(self.score(record)['sustainedRealtimeStatus'], 'unknown')

    def test_failed_transport_never_qualifies_even_with_matching_count(self):
        for change in (
            {'error': {'type': 'SyntheticFailure'}}, {'generatorExhausted': False},
            {'finitePcm': False}, {'nonStreamingFallbackAfterStreaming': True},
            {'observedCodecTokens': 75}, {'observedCodecTokens': 76},
            {'returnedSampleCount': 0}, {'sampleRate': 0}, {'chunks': []},
        ):
            with self.subTest(change=change):
                score = self.score({**fake_call(), **change})
                self.assertFalse(score['transportIntegrityPassed'])
                self.assertIsNone(score['qualifiedRtf'])
                self.assertEqual(score['sustainedRealtimeStatus'], 'ineligible')
                self.assertFalse(score['qualifiedIncrementalAudio'])

    def test_chunk_transport_failure_cases(self):
        for failure in ('missing_final', 'multiple_finals', 'early_final', 'batch_fallback',
                        'mixed_rate', 'count_disagreement', 'negative_count'):
            with self.subTest(failure=failure):
                record = fake_call()
                first, last = record['chunks']
                if failure == 'missing_final':
                    last['is_final'] = False
                elif failure == 'multiple_finals':
                    first['is_final'] = True
                elif failure == 'early_final':
                    first['is_final'], last['is_final'] = True, False
                elif failure == 'batch_fallback':
                    last['is_streaming'] = False
                elif failure == 'mixed_rate':
                    last['sampleRate'] = 16000
                elif failure == 'count_disagreement':
                    last['reportedSampleCount'] = 23000
                else:
                    first['sampleCount'], last['sampleCount'] = -1, 48001
                score = self.score(record)
                self.assertFalse(score['transportIntegrityPassed'])
                self.assertIsNone(score['qualifiedRtf'])
                self.assertFalse(score['qualifiedIncrementalAudio'])

    def test_missing_or_invalid_reported_chunk_count_fails_closed(self):
        for change in ('missing', True, '24000'):
            with self.subTest(change=change):
                record = fake_call()
                if change == 'missing':
                    del record['chunks'][0]['reportedSampleCount']
                else:
                    record['chunks'][0]['reportedSampleCount'] = change
                score = self.score(record)
                self.assertFalse(score['transportIntegrityPassed'])
                self.assertIsNone(score['qualifiedRtf'])
                self.assertFalse(score['qualifiedIncrementalAudio'])

    def test_v2_default_output_is_separate_from_legacy_v1_directory(self):
        self.assertEqual(MOD.DEFAULT_OUTPUT.name, 'mac-v2')
        self.assertEqual(MOD.DEFAULT_OUTPUT.parent.name, 'tts-20260906')
        legacy_output = MOD.DEFAULT_OUTPUT.parent / 'mac'
        with patch.object(sys, 'argv', ['runtime_tts_mac.py', '--output', str(legacy_output)]):
            with self.assertRaises(SystemExit) as error:
                MOD.main()
        self.assertEqual(error.exception.code, 2)

    def test_summary_distinguishes_stages_and_excludes_warmups(self):
        eligible = fake_call()
        slow = fake_call(elapsed_ms=3000)
        mismatch = fake_call(samples=(24000, 23000))
        unknown = fake_call(elapsed_ms=None)
        missing_batch = fake_call()
        warmup = fake_call(warmup=True)
        records = []
        for index, record in enumerate((self.batch, eligible, slow, mismatch, unknown, missing_batch, warmup)):
            record['callKey'] = f'synthetic-{index}'
            batch = None if record is missing_batch else self.batch
            records.append({**record, **MOD.score_call(record, batch)})
        score = MOD.summarize_scores(records)
        self.assertEqual(score['qualifiedFormalCalls'], 1)
        self.assertEqual(score['transportIntegrityPassedFormalCalls'], 6)
        self.assertEqual(score['sampleCoverageMatchedFormalCalls'], 3)
        self.assertEqual(score['sampleCoverageMismatchCalls'], ['synthetic-3'])
        self.assertEqual(score['sampleCoverageUnknownCalls'], ['synthetic-5'])
        self.assertEqual(score['sustainedRealtimeUnknownCalls'], ['synthetic-4', 'synthetic-5'])
        self.assertEqual(MOD.summarize_scores([])['qualifiedFormalCalls'], 0)

    def test_scoring_is_pure_and_does_not_repair_retained_metadata(self):
        record = fake_call(samples=(24000, 23000))
        before_record, before_batch = copy.deepcopy(record), copy.deepcopy(self.batch)
        MOD.score_call(record, self.batch)
        self.assertEqual(record, before_record)
        self.assertEqual(self.batch, before_batch)


if __name__ == '__main__':
    unittest.main()
