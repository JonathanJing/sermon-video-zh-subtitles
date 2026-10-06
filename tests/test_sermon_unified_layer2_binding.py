import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from scripts import sermon_unified_layer2_binding as s

class Layer2BindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.files={}
        def put(name,value):
            p=self.root/name;p.write_text(json.dumps(value));self.files[name]=p;return p
        expected={'sourceId':'s','sourceUrlHash':'a'*64,'mediaSha256':'b'*64,'window':{'startSeconds':3,'endSeconds':9}}
        put('source',{'source':{'sourceId':'s','sourceUrlHash':'a'*64,'media':{'sha256':'b'*64},'approvedWindow':expected['window']}})
        put('anchor',{});put('policy',{});put('plugin',{});put('approval',{})
        put('auth',{'approvalReceipt':'approval','authority':{'approvalSha256':s.c.file_sha(self.files['approval'])}})
        put('inspection',{'source':'source','anchor':'anchor'})
        put('execution',{'inspectionConfig':'inspection'})
        self.config=SimpleNamespace(path=self.files['execution'],inspection_root=self.root,
            inspection={'source':'source','anchor':'anchor'},sha256='x',
            lanes={'zh-CN':{'policy':self.files['policy'],'plugin':self.files['plugin']}})
        self.m={'source':expected,'policies':[{'locale':'zh-CN','policySha256':s.c.file_sha(self.files['policy'])}],
            'bindings':{k:{'path':str(v),'sha256':s.c.file_sha(v)} for k,v in self.files.items()}}
        self.step={'locale':'zh-CN','budgetAuthorization':'auth'}
        for name,result in [('load_configuration',self.config),('package_view',{}),('_inputs',({}, {}, {}))]:
            p=patch.object(s.ctl,name,return_value=result);p.start();self.addCleanup(p.stop)
    def call(self):return s.inspect_bound(self.m,self.root,self.step,self.files['execution'])
    def test_valid_closure(self):self.assertTrue(self.call()['snapshotBound'])
    def test_missing_source_binding_rejected(self):
        del self.m['bindings']['source']
        with self.assertRaisesRegex(ValueError,'binding_required'):self.call()
    def test_frozen_anchor_mutation_rejected(self):
        self.files['anchor'].write_text('{"changed":true}')
        with self.assertRaises(ValueError):self.call()
    def test_different_window_same_media_rejected(self):
        self.m['source']['window']={'startSeconds':4,'endSeconds':9}
        with self.assertRaisesRegex(ValueError,'source_mismatch'):self.call()
    def test_nested_approval_mutation_rejected(self):
        self.files['approval'].write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError,'approval_changed'):self.call()
