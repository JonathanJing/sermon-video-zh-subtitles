import copy
import json
from pathlib import Path
import tempfile
import unittest
from scripts import sermon_cuv_translation as mod


class VisualContextTests(unittest.TestCase):
    def fixture(self,root):
        video=root/'source.mp4';video.write_bytes(b'video fixture')
        contract=root/'contract.json';mod.save_frozen(contract,{'durationSeconds':100.0,'sha256':mod.file_hash(video)})
        parent=root/'job.json';mod.save_frozen(parent,{'inputs':{'sourceVideo':mod.bind(video),'sourceContract':mod.bind(contract)}})
        frame=root/'frame.jpg';frame.write_bytes(b'frame fixture')
        evidence={'schemaVersion':'sermon-source-visual-context-v1','parentJob':mod.bind(parent),'sourceVideo':mod.bind(video),'sourceContract':mod.bind(contract),
            'frames':[{**mod.bind(frame),'fullVideoSeconds':50,'observedText':'The Promise / The Meaning'}],
            'observer':{'type':'model_visual_inspection','humanApproval':False},'finding':'The projected material is a summary table.'}
        path=root/'evidence.json';mod.save_frozen(path,evidence)
        rows=[{'id':40,'sourceContext':{'evidenceBinding':mod.bind(path),'frameBinding':mod.bind(frame),'summaryText':'Promise summary table','classificationRationale':'The words match a summary cell, not the complete Bible verse.'}}]
        return evidence,path,{'parentJob':mod.bind(parent)},rows

    def test_valid_observation_remains_model_only(self):
        with tempfile.TemporaryDirectory() as t:
            e,p,m,rows=self.fixture(Path(t).resolve())
            self.assertEqual(mod.validate_source_context_evidence(mod.bind(p),m,rows),e)

    def test_bound_sources_frames_offsets_and_status_reject_tampering(self):
        changes=[lambda e:e['parentJob'].update(sha256='wrong'),lambda e:e['sourceVideo'].update(sha256='wrong'),
                 lambda e:e['sourceContract'].update(sha256='wrong'),lambda e:e['frames'][0].update(sha256='wrong'),
                 lambda e:e['frames'][0].update(fullVideoSeconds=100),lambda e:e['frames'][0].update(fullVideoSeconds=-1),
                 lambda e:e['frames'][0].update(fullVideoSeconds=float('nan')),lambda e:e['frames'][0].update(fullVideoSeconds=True),
                 lambda e:e['observer'].update(humanApproval=True),lambda e:e['observer'].update(type='human'),
                 lambda e:e['frames'][0].update(observedText=''),lambda e:e.update(schemaVersion='other')]
        for change in changes:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as t:
                e,p,m,rows=self.fixture(Path(t).resolve());change(e);p.write_text(json.dumps(e))
                rows[0]['sourceContext']['evidenceBinding']=mod.bind(p)
                with self.assertRaises(ValueError):mod.validate_source_context_evidence(mod.bind(p),m,rows)

    def test_inline_context_must_refer_to_an_observed_frame(self):
        for key,value in [('frameBinding',{'path':'elsewhere','sha256':'other'}),('summaryText',''),('classificationRationale','')]:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as t:
                e,p,m,rows=self.fixture(Path(t).resolve());rows[0]['sourceContext'][key]=value
                with self.assertRaises(ValueError):mod.validate_source_context_evidence(mod.bind(p),m,rows)

    def test_distinct_evidence_groups_validate_independently(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();e,p,m,rows=self.fixture(root)
            second=copy.deepcopy(e);second['finding']='A second independently bound observation.'
            other=root/'second-evidence.json';mod.save_frozen(other,second)
            row=copy.deepcopy(rows[0]);row['id']=41;row['sourceContext']['evidenceBinding']=mod.bind(other)
            rows.append(row)
            self.assertEqual(mod.validate_source_context_evidence(mod.bind(p),m,rows),e)
            self.assertEqual(mod.validate_source_context_evidence(mod.bind(other),m,rows),second)
            with self.assertRaisesRegex(ValueError,'no matching'):
                mod.validate_source_context_evidence(mod.bind(other),m,rows[:1])
