"""Replay committed sanitized real-run evidence independently of private assets."""
import collections
import json
from pathlib import Path
import unittest
from scripts import weekly_pipeline_report as weekly

ROOT=Path(__file__).resolve().parents[1]/'docs/reports/20260930-observability'
RERUN=ROOT/'timing-rerun'

def read(path):return json.loads(path.read_text())

class ActualTraceTests(unittest.TestCase):
    def test_safe_ledgers_reconstruct_reports_without_business_artifacts(self):
        for mode in ('cache','asr','audio'):
            with self.subTest(mode=mode):
                projected = weekly.project(RERUN/mode)
                original = read(RERUN/mode/'report.json')
                # Historical reports stay immutable. The corrected network
                # coverage fields are the only permitted projection delta.
                self.assertEqual(projected['networkCalls'], original['networkCalls'])
                self.assertEqual(projected.pop('networkCallsScope'), 'report_generation_only_deprecated')
                self.assertEqual(projected.pop('reportGenerationNetworkCalls'), 0)
                calls = projected.pop('observedProviderCalls')
                self.assertEqual(calls['status'], 'not_observed')
                self.assertIsNone(calls['directReceiptCount'])
                self.assertIsNone(calls['totalNetworkCalls'])
                self.assertEqual(projected, original)
                independent=read(RERUN/f'independent-{mode}.json')
                self.assertTrue(independent['codeClean'])
                self.assertEqual(independent['actualTransportAttempts'],0)
                self.assertFalse(independent['stage1PromotionAllowed'])

    def test_cache_identity_and_historical_usage_match_independent_oracle(self):
        run=read(RERUN/'cache/report.json')['runs'][0]
        expected=read(ROOT/'independent-cache-oracle.json')['rows']
        by_id={r['responseIdSha256']:r for r in run['cacheObservations']}
        self.assertEqual(len(expected),66);self.assertEqual(len(by_id),66)
        for row in expected:
            actual=by_id[row['responseIdSha256']]
            for key in ('role','model','cacheSha256','rawReceiptSha256','payloadSha256'):
                self.assertEqual(row[key],actual[key])
            for key,value in row['usage'].items():self.assertEqual(value,actual['usage'][key])
        independent=read(RERUN/'independent-cache.json')
        hashes=[w['metrics']['sourceMediaSha256'] for w in run['workloadEvidence'] if 'sourceMediaSha256' in w['metrics']]
        self.assertEqual(hashes,[independent['sourceMediaSha256']]*4)
        for lane in independent['locales']:
            self.assertTrue(lane['priorFilesUnchanged']);self.assertTrue(lane['evidenceEqualsPrior'])
            self.assertIn(lane['candidateJsonSha256'],[w['metrics'].get('candidateSha256') for w in run['workloadEvidence']])

    def test_asr_separate_boundaries_retain_model_span_identity(self):
        run=read(RERUN/'asr/report.json')['runs'][0]
        nodes=sorted(run['workUnits'],key=lambda n:n['startedAt'])
        self.assertEqual([n['stage'] for n in nodes],['diagnostic.source_decode','diagnostic.local_asr_setup','diagnostic.local_asr','diagnostic.local_asr_output'])
        for before,after in zip(nodes,nodes[1:]):self.assertEqual(after['dependsOnSha256'],[before['spanSha256']])
        self.assertEqual({o['spanSha256'] for o in run['localModelObservations']},{nodes[2]['spanSha256']})
        independent=read(RERUN/'independent-asr.json')
        finished=next(o for o in run['localModelObservations'] if o['status']=='completed')
        self.assertEqual(finished['outputSha256'],independent['transcriptSha256'])
        self.assertEqual(finished['outputSha256'],read(ROOT/'independent-local-asr.json')['transcriptSha256'])

    def test_audio_serial_path_and_all_unit_hashes_match_actual_packages(self):
        run=read(RERUN/'audio/report.json')['runs'][0]
        nodes=sorted(run['workUnits'],key=lambda n:n['startedAt'])
        self.assertEqual([n['stage'] for n in nodes],['diagnostic.audio.zh-Hans','diagnostic.audio.ko','diagnostic.audio.es'])
        for before,after in zip(nodes,nodes[1:]):self.assertEqual(after['dependsOnSha256'],[before['spanSha256']])
        self.assertAlmostEqual(run['criticalPath']['activeSeconds'],sum(n['elapsedSeconds'] for n in nodes),places=6)
        completed=[w['metrics'] for w in run['workloadEvidence'] if w['metrics'].get('validationCompleted')]
        started=[w for w in run['workloadEvidence'] if w['metrics'].get('validationStarted')]
        expected=[h for lane in read(RERUN/'independent-audio.json')['locales'] for h in lane['expectedAudioSha256s']]
        self.assertEqual(len(started),33);self.assertEqual(len(completed),33)
        self.assertEqual(collections.Counter(w['audioSha256'] for w in completed),collections.Counter(expected))
