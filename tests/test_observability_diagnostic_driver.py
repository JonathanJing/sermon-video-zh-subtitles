"""Driver timing boundaries use the actual call order, without paid transports."""
import hashlib
import json
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import patch
from scripts import run_observability_diagnostic as driver
from scripts import sermon_accounting as accounting
from scripts import weekly_pipeline_report as weekly


class DiagnosticDriverTests(unittest.TestCase):
    def test_asr_setup_model_and_output_are_separate_serial_spans(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.mp4';source.write_bytes(b'fixture media')
            model=root/'model';model.mkdir();(model/'weights.npz').write_bytes(b'fixture weights')
            out=root/'out';out.mkdir()
            real_run=driver.subprocess.run
            def decode(argv, **kwargs):
                if argv[0]=='ffmpeg': Path(argv[-1]).write_bytes(b'fixture wav'); return None
                return real_run(argv,**kwargs)
            def infer(*_args, **kwargs):
                self.assertEqual(kwargs['language'],'en');time.sleep(.01)
                return {'text':'fixture words','segments':[{}]}
            with patch.object(driver,'ASR_CHECKPOINT_SHA256',driver.sha(model/'weights.npz')), patch.object(driver.subprocess,'run',side_effect=decode), patch.dict('sys.modules',{'mlx_whisper':types.SimpleNamespace(transcribe=infer)}):
                report=driver.local_asr(source,model,2,out)
            projected=weekly.project(out/'accounting')['runs'][0]
            nodes={n['stage']:n for n in projected['workUnits']}
            names=['diagnostic.source_decode','diagnostic.local_asr_setup','diagnostic.local_asr','diagnostic.local_asr_output']
            for before,after in zip(names,names[1:]):
                self.assertEqual(nodes[after]['dependsOnSha256'],[nodes[before]['spanSha256']])
            self.assertEqual(nodes[names[1]]['executorType'],'deterministic_program')
            self.assertEqual(nodes[names[3]]['executorType'],'deterministic_program')
            self.assertEqual(nodes[names[2]]['executorType'],'production_model')
            observations=projected['localModelObservations'];self.assertEqual(len(observations),2)
            self.assertEqual({o['spanSha256'] for o in observations},{nodes[names[2]]['spanSha256']})
            self.assertEqual(next(o for o in observations if o['status']=='completed')['outputSha256'],report['transcriptSha256'])
            self.assertEqual(report['transcriptSha256'],hashlib.sha256((out/'fresh-local-asr.json').read_bytes()).hexdigest())

    def test_audio_locale_wrappers_follow_actual_serial_invocations(self):
        from scripts import inspect_canonical_audio as audio
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);assets=root/'assets';assets.mkdir();package=assets/'package.json';package.write_text(json.dumps({'units':[{'audio':{'sha256':'a'*64}}]}))
            inputs=[{'locale':locale,'artifactRoot':str(assets),'package':str(package),'trackedFiles':[str(package)],
                'root':str(root),'config':{},'upstream':{}} for locale in ('zh-Hans','ko','es')]
            out=root/'output';out.mkdir()
            order=[]
            def inspect(*args):
                order.append(args[-1]);time.sleep(.01)
                return {'outputSha256':'b'*64,'listeningReviewSha256':'c'*64}
            with patch.object(audio,'inspect',side_effect=inspect):
                result=driver.audio_validation(inputs,out)
            run=weekly.project(out/'accounting')['runs'][0]
            nodes=sorted(run['workUnits'],key=lambda n:n['startedAt'])
            self.assertEqual(order,['zh-Hans','ko','es']);self.assertEqual(len(result['locales']),3)
            self.assertEqual(nodes[0]['dependsOnSha256'],[])
            for before,after in zip(nodes,nodes[1:]):self.assertEqual(after['dependsOnSha256'],[before['spanSha256']])
            self.assertAlmostEqual(run['criticalPath']['activeSeconds'],sum(n['elapsedSeconds'] for n in nodes),places=6)

    def test_real_producer_source_identity_includes_media_hash(self):
        from tests import test_run_target_language_models as fixtures
        from scripts import run_target_language_models as models
        t=fixtures.RunTargetLanguageModelsTests();t.setUp();self.addCleanup(t.doCleanups);f=t.fixture
        models.run_accounted(f.source,f.anchor,f.policy,t.out,'fixture-key',t.fake_call,None,f.plugin_path,None,None)
        events,_=accounting.read_events(t.out/'accounting')
        identity=next(e['metrics'] for e in events if e.get('stage')=='layer2.source_identity')
        self.assertEqual(identity['sourceMediaSha256'],f.source['source']['media']['sha256'])
