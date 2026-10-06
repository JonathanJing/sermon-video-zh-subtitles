import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import sermon_unified_study as study
from scripts.sermon_unified import contracts as c


class StudyOwnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.manifest={'source':{},'content':{'pageId':'test'},'bindings':{}}
        for name,value in {'source':{'source':{}},'anchor':{'sourceUnits':[{'sourceUnitId':'u1'}]},
            'candidate':{'locale':'zh-Hans'},'translationReview':{},
            'sections':[{'title':'Outline','body':'Text','sourceUnitIds':['u1']}]}.items():
            path=self.root/(name+'.json');path.write_text(json.dumps(value))
            self.manifest['bindings'][name]={'path':str(path),'sha256':c.file_sha(path)}
        self.config=self.root/'config.json'
        self.config.write_text(json.dumps({'schemaVersion':'sermon-unified-study-inputs-v1','kind':'outline',
            'producerIdentity':'supplied-text-v1','inputs':{key:key for key in self.manifest['bindings']}}))
        self.step={'id':'outline','locale':'zh-Hans'}
    def test_immutable_candidate_and_independent_human_pending(self):
        with patch.object(study,'validate_review'):
            first=study.execute(self.manifest,'/',self.config,self.step,self.root/'result.json')
            again=study.execute(self.manifest,'/',self.config,self.step,self.root/'result.json')
            self.assertEqual(first,again);self.assertFalse(first['productionEligible'])
            self.assertEqual(first['review'],'human_pending');self.assertEqual(first['freshApiAttempts'],0)
            Path(first['path']).write_text('{}')
            with self.assertRaises(c.ContractError):study.execute(self.manifest,'/',self.config,self.step,self.root/'result.json')
    def test_unknown_source_unit_rejected(self):
        path=self.root/'sections.json'
        path.write_text(json.dumps([{'title':'Outline','body':'Text','sourceUnitIds':['wrong']}]))
        self.manifest['bindings']['sections']['sha256']=c.file_sha(path)
        with patch.object(study,'validate_review'),self.assertRaises(c.ContractError):
            study.inspect(self.manifest,'/',self.config,self.step)
    def test_changed_supplied_text_rejected_before_review(self):
        (self.root/'sections.json').write_text('[]')
        with patch.object(study,'validate_review') as review,self.assertRaises(c.ContractError):
            study.inspect(self.manifest,'/',self.config,self.step)
        review.assert_not_called()
