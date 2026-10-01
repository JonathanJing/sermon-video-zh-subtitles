from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_execution_extensions as ext
from scripts import sermon_review_contracts as c
from scripts import run_bounded_diagnostic as entry, sermon_strict_layer2 as strict
from tests import test_run_bounded_diagnostic as fixtures


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.base = {'gitCommit': 'a'*40, 'trackedWorkingTreeDirty': False,
            'loadedProjectCodeSha256': {'scripts/source.py': 'b'*64},
            'pythonVersion': '3.12.2', 'platform': 'darwin', 'architecture': 'arm64', 'scope': 'loaded'}
        self.current = deepcopy(self.base)
        self.current['loadedProjectCodeSha256']['scripts/audio.py'] = 'c'*64
        self.args = dict(stage_id='audio.prepare', declared_additions={'scripts/audio.py': 'c'*64},
            external_runtime_sha256={'tts': 'd'*64}, binding={k:'e'*64 for k in ext.BINDING_KEYS})

    def test_predeclared_stage_extension_and_immutable_receipt(self):
        original = deepcopy(self.base)
        receipt = ext.make_extension(self.base, self.current, **self.args)
        self.assertEqual(ext.validate_extension(receipt, self.base, self.current, **self.args), receipt)
        with tempfile.TemporaryDirectory() as temp:
            path = ext.persist_extension(Path(temp), receipt); before = path.read_bytes()
            self.assertEqual(ext.persist_extension(Path(temp), receipt), path)
            self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.base, original)

    def test_changed_deleted_or_undeclared_loaded_module_rejected(self):
        cases = [dict(self.current['loadedProjectCodeSha256'], **{'scripts/source.py':'f'*64}),
                 {'scripts/audio.py':'c'*64},
                 dict(self.current['loadedProjectCodeSha256'], **{'scripts/unknown.py':'f'*64})]
        for modules in cases:
            with self.subTest(modules=modules), self.assertRaisesRegex(c.ContractError, 'extension_undeclared_or_changed_module'):
                ext.make_extension(self.base, dict(self.current, loadedProjectCodeSha256=modules), **self.args)

    def test_new_commit_dirty_process_or_python_change_is_not_extension(self):
        for key, value in [('gitCommit','f'*40),('trackedWorkingTreeDirty',True),('pythonVersion','3.13'),('architecture','x86_64')]:
            with self.subTest(key=key), self.assertRaises(c.ContractError):
                ext.make_extension(self.base, dict(self.current, **{key:value}), **self.args)

    def test_old_module_cannot_be_redeclared_and_paths_closed(self):
        for additions in [{'scripts/source.py':'b'*64}, {'scripts/../private.py':'f'*64}, {'/Users/private.py':'f'*64}]:
            with self.subTest(additions=additions), self.assertRaises(c.ContractError):
                ext.make_extension(self.base, self.current, **dict(self.args, declared_additions=additions))

    def test_runtime_receipt_chain_retains_original_runtime_and_binding(self):
        first = ext.make_extension(self.base, self.current, **self.args)
        second_current = deepcopy(self.current);second_current['loadedProjectCodeSha256']['scripts/release.py']='f'*64
        args = dict(self.args, stage_id='release.prepare', declared_additions={'scripts/release.py':'f'*64}, parent_receipt=first)
        second = ext.make_extension(self.current, second_current, **args)
        self.assertEqual(second['parentReceiptSha256'], c.canonical_sha256(first))
        with self.assertRaisesRegex(c.ContractError,'extension_old_runtime_changed'):
            ext.make_extension(self.current, second_current, **dict(args,external_runtime_sha256={'tts':'f'*64}))
        changed = dict(self.args['binding'], runId='f'*64)
        with self.assertRaisesRegex(c.ContractError,'extension_parent_binding_changed'):
            ext.make_extension(self.current, second_current, **dict(args,binding=changed))

    def test_tampered_receipt_or_frozen_declarations_cannot_be_used(self):
        receipt = ext.make_extension(self.base, self.current, **self.args)
        bad = deepcopy(receipt);bad['binding']['runConfigSha256']='f'*64
        with self.assertRaisesRegex(c.ContractError,'extension_receipt_changed'):
            ext.validate_extension(bad, self.base, self.current, **self.args)
        with self.assertRaises(c.ContractError):
            ext.validate_extension(receipt, self.base, self.current,
                **dict(self.args,declared_additions={'scripts/audio.py':'f'*64}))


class PlannedExtensionTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.BoundedRunTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        model=ExtensionTests();model.setUp();self.base,self.current=model.base,model.current
        config=dict(self.f.subject.config,codeSha256=c.canonical_sha256(self.base))
        self.plan={'schemaVersion':'sermon-bounded-diagnostic-plan-v1','runDirectory':str(self.f.f.root),
            'providerConfig':config,'authority':self.f.subject.store.authority,
            'executionIdentity':self.base,'sourceClipPath':str(self.f.clip)}
        strict.save_once(self.f.f.root/'run-plan.json',self.plan)
        self.declaration={'schemaVersion':'sermon-stage-code-declaration-v1',
            'originalPlanSha256':c.canonical_sha256(self.plan),'stageId':'audio.prepare',
            'moduleAdditions':{'scripts/audio.py':'c'*64},'externalRuntimeSha256':{'tts':'d'*64}}
        binding={'runId':config['runId'],'runConfigSha256':c.canonical_sha256(config),
            'storeSha256':self.f.subject.store.store_sha256,
            'sourceIdentitySha256':c.canonical_sha256({key:config[key] for key in
                ('sourceMediaSha256','sourceClipSha256','sourceAudioSha256','sourceWindowSeconds')}),
            'inputSha256':c.canonical_sha256(self.plan)}
        self.receipt=ext.make_extension(self.base,self.current,stage_id='audio.prepare',
            declared_additions=self.declaration['moduleAdditions'],
            external_runtime_sha256=self.declaration['externalRuntimeSha256'],binding=binding)
        ext.freeze_stage_declaration(self.plan,self.base,self.declaration)

    def test_declaration_must_precede_module_loading_and_cannot_be_overwritten(self):
        with self.assertRaisesRegex(c.ContractError,'declaration_requires_original_execution_identity'):
            ext.freeze_stage_declaration(self.plan,self.current,self.declaration)
        changed=dict(self.declaration,externalRuntimeSha256={'tts':'f'*64})
        with self.assertRaises(c.ContractError):
            ext.freeze_stage_declaration(self.plan,self.base,changed)
        with patch.object(entry.accounting,'execution_identity',return_value=self.current):
            with self.assertRaisesRegex(c.ContractError,'diagnostic_stage_declaration_not_frozen'):
                entry.prepare_plan(self.plan,stage_declaration=changed,extension_receipt=self.receipt)

    def test_entry_consumes_stage_receipt_and_preserves_plan_config_budget_and_clock(self):
        path=self.f.f.root/'run-plan.json';before=path.read_bytes()
        with patch.object(entry.accounting,'execution_identity',return_value=self.current):
            root,subject=entry.prepare_plan(self.plan,stage_declaration=self.declaration,
                                          extension_receipt=self.receipt)
        self.assertEqual(subject.config,self.plan['providerConfig'])
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse((root/'budget').exists())
        self.assertEqual(self.f.calls,[])
        self.assertEqual(len(list((root/'execution-extensions').glob('*.json'))),1)

    def test_extension_is_opt_in_and_rejects_stale_declarations_or_missing_receipt(self):
        with patch.object(entry.accounting,'execution_identity',return_value=self.current):
            with self.assertRaisesRegex(c.ContractError,'code_identity_changed'):entry.prepare_plan(self.plan)
            with self.assertRaisesRegex(c.ContractError,'extension_and_declaration_required'):
                entry.prepare_plan(self.plan,stage_declaration=self.declaration)
            bad=dict(self.declaration,originalPlanSha256='0'*64)
            with self.assertRaisesRegex(c.ContractError,'stage_declaration_changed'):
                entry.prepare_plan(self.plan,stage_declaration=bad,extension_receipt=self.receipt)
        self.assertEqual(self.f.calls,[])
