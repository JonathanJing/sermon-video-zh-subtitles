"""Documented confirmed entrypoint with fake ASR; no network or secret lookup."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests.legacy_pipeline_patches import patch_both  # W3b: Layer 1 names live in two modules
from tests import experiment_modules

subject = experiment_modules.load("experiments/local-asr/run_local_asr_gpt_reaudit.py")


class AsrReauditOutcomeTests(unittest.TestCase):
    def setUp(self):
        (subject.REPO_ROOT/'artifacts').mkdir(parents=True,exist_ok=True)

    def fixture(self, root):
        audio=root/'audio.bin';audio.write_bytes(b'synthetic audio fixture')
        item={'id':'unit1','audioPath':str(audio.relative_to(subject.REPO_ROOT)),
              'audioSha256':subject.sha256_file(audio),'durationSeconds':1.0,
              'selectionReasons':['synthetic'],'modelReviewedReferenceText':'Hello.',
              'modelTranscripts':{},'referenceProvenance':{}}
        base=root/'base.json';base.write_text(json.dumps({'items':[item]}))
        queue=root/'queue.json';queue.write_text(json.dumps({'manifestSha256':subject.sha256_file(base),
               'durationMinutes':1/60,'items':[item]}))
        return ['reaudit','--queue',str(queue),'--base-manifest',str(base),
                '--output-dir',str(root/'output'),'--calibrated-manifest',str(root/'calibrated.json'),
                '--workers','2','--confirm-billable-asr']

    def test_confirmed_standalone_workers_bind_output_and_replay_without_spark(self):
        with tempfile.TemporaryDirectory(dir=subject.REPO_ROOT/'artifacts') as tmp:
            root=Path(tmp);argv=self.fixture(root)
            with patch.dict(os.environ,{},clear=True),patch('sys.argv',argv), \
                 patch.object(subject,'read_secret',return_value='synthetic-key'), \
                 patch_both("multipart_request", return_value={'text':'Hello.'}) as asr, \
                 patch('tongxing_production.compute.spark_exclusive_session.Client.from_environment',side_effect=AssertionError('Spark consulted')), \
                 patch('builtins.print'):
                self.assertEqual(subject.main(),0)
                self.assertEqual(subject.main(),0)
            self.assertEqual(asr.call_count,1)
            rows=list((root/'output'/'accounting'/'api-cli-outcomes').glob('*/outcome.json'))
            self.assertEqual(len(rows),1)
            self.assertEqual(json.loads(rows[0].read_text())['status'],'returned')
            report=json.loads((root/'output'/'run-report.json').read_text())
            self.assertEqual(report['cacheHitCount'],1)

    def test_unknown_standalone_asr_blocks_next_entrypoint_dispatch(self):
        with tempfile.TemporaryDirectory(dir=subject.REPO_ROOT/'artifacts') as tmp:
            root=Path(tmp);argv=self.fixture(root)
            with patch.dict(os.environ,{},clear=True),patch('sys.argv',argv), \
                 patch.object(subject,'read_secret',return_value='synthetic-key'), \
                 patch_both("multipart_request", side_effect=TimeoutError('unknown')) as asr, \
                 patch('builtins.print'):
                self.assertEqual(subject.main(),1)
                self.assertEqual(subject.main(),1)
            self.assertEqual(asr.call_count,1)
            self.assertFalse((root/'calibrated.json').exists())
            report=json.loads((root/'output'/'run-report.json').read_text())
            self.assertEqual(report['status'],'failed_closed')
            self.assertIn('reconciliation_required',report['errors'][0]['error'])
