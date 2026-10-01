"""Complete checkpoint evidence only: synthetic files, zero model/network."""
from pathlib import Path
import copy
import os
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_preview_checkpoint_manifest as subject
from scripts import sermon_review_contracts as c
from scripts import sermon_public_snapshot as public


class CheckpointManifestTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.checkpoint=self.root/'checkpoint';self.checkpoint.mkdir()
        for name in subject.REQUIRED_FILES:
            path=self.checkpoint/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('inert fixture '+name).encode())
        self.digest=subject.sha(self.checkpoint/'model.safetensors');self.ref='speaker-voice://fixture/eric'
        self.output=self.root/'manifest';self.binding=subject.build(self.checkpoint,self.output,
            checkpoint_ref=self.ref,conditioning_sha256=self.digest)
        self.path=self.output/'checkpoint-manifest.json'

    def validate(self,**changes):
        return subject.validate(self.path,**{'root':self.checkpoint,'checkpoint_ref':self.ref,
            'conditioning_sha256':self.digest,**changes})

    def test_complete_tree_replays_without_writes_and_contains_auxiliary_weights(self):
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(self.validate(),self.binding)
        self.assertIn(str(self.checkpoint/'speech_tokenizer/model.safetensors'),{row['path'] for row in self.binding['files']})
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_every_auxiliary_config_tokenizer_or_weight_change_is_rejected(self):
        for name in sorted(subject.REQUIRED_FILES-{'model.safetensors','config.json'}):
            with self.subTest(name=name):
                path=self.checkpoint/name;before=path.read_bytes();path.write_bytes(before+b' changed')
                with self.assertRaisesRegex(ValueError,'checkpoint_tree_changed'):self.validate()
                path.write_bytes(before)

    def test_added_file_missing_file_and_changed_primary_are_rejected(self):
        extra=self.checkpoint/'extra.json';extra.write_text('{}')
        with self.assertRaisesRegex(ValueError,'checkpoint_tree_changed'):self.validate()
        extra.unlink();missing=self.checkpoint/'vocab.json';raw=missing.read_bytes();missing.unlink()
        with self.assertRaisesRegex(ValueError,'required_file_missing'):self.validate()
        missing.write_bytes(raw);(self.checkpoint/'model.safetensors').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'checkpoint_tree_changed'):self.validate()

    def test_symlink_escape_and_derived_bytecode_rejected(self):
        link=self.checkpoint/'escape';link.symlink_to(self.root/'manifest')
        with self.assertRaises(ValueError):self.validate()
        link.unlink();cache=self.checkpoint/'__pycache__';cache.mkdir();(cache/'model.pyc').write_bytes(b'inert')
        with self.assertRaisesRegex(ValueError,'derived_bytecode'):self.validate()

    def test_manifest_inventory_and_conditioning_binding_cannot_be_substituted(self):
        with self.assertRaisesRegex(ValueError,'manifest_changed'):self.validate(checkpoint_ref='other')
        with self.assertRaisesRegex(ValueError,'manifest_changed'):self.validate(conditioning_sha256='f'*64)
        inventory=self.output/'checkpoint-inventory.json';inventory.write_bytes(inventory.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'inventory_changed'):self.validate()

    def test_output_inside_checkpoint_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'external_output_required'):
            subject.build(self.checkpoint,self.checkpoint/'manifest',checkpoint_ref=self.ref,conditioning_sha256=self.digest)

    def test_swapped_final_symlink_before_open_never_follows_external_target(self):
        target=self.checkpoint/'generation_config.json';external=self.root/'external';external.write_bytes(b'external')
        original=os.open
        def swap(path,flags,*args,**kwargs):
            if Path(path)==target:target.unlink();target.symlink_to(external)
            return original(path,flags,*args,**kwargs)
        with patch.object(subject.os,'open',side_effect=swap),self.assertRaises(OSError):subject.file_snapshot(target)

    def test_named_file_replacement_after_read_is_rejected(self):
        target=self.checkpoint/'generation_config.json';original=os.fstat;calls=[0]
        def replace(fd):
            observed=original(fd);calls[0]+=1
            if calls[0]==2:
                replacement=target.with_suffix('.replacement');replacement.write_bytes(target.read_bytes());replacement.replace(target)
            return observed
        with patch.object(subject.os,'fstat',side_effect=replace),self.assertRaisesRegex(ValueError,'changed_during_hash'):
            subject.file_snapshot(target)

    def test_size_and_hash_are_bound_to_the_same_descriptor_snapshot(self):
        target=self.checkpoint/'generation_config.json';raw=target.read_bytes();snapshot=subject.file_snapshot(target)
        self.assertEqual(snapshot,{'bytes':len(raw),'sha256':c.bytes_sha256(raw)})
        row=next(row for row in subject.inventory(self.checkpoint) if row['relativePath']=='generation_config.json')
        self.assertEqual(row,{'relativePath':'generation_config.json',**snapshot})

    def declaration(self,bindings):
        run=self.root/'run';run.mkdir(exist_ok=True)
        identity={'gitCommit':'a'*40,'loadedProjectCodeSha256':{}}
        config={'codeSha256':c.canonical_sha256(identity)}
        plan={'runDirectory':str(run),'executionIdentity':identity,'providerConfig':config}
        public.save_once(run/'run-plan.json',plan)
        declaration={'schemaVersion':'sermon-stage-code-declaration-v1','originalPlanSha256':c.canonical_sha256(plan),
            'stageId':'preview.checkpoint','moduleAdditions':{},'externalRuntimeSha256':bindings}
        path=run/'stage-declarations/preview.checkpoint.json';path.parent.mkdir(exist_ok=True);public.save_once(path,declaration)
        return run,path,{'runConfigSha256':c.canonical_sha256(config),'continuationCodeCommit':'a'*40}

    def test_frozen_010_declaration_binds_both_manifest_and_complete_tree(self):
        run,path,context=self.declaration({'previewCheckpointManifest':self.binding['checkpointManifest']['fileBytesSha256'],
            'previewCheckpointTree':self.binding['treeSha256']})
        self.assertEqual(subject.validate_declaration(run,path,self.binding,context),subject.ref(path))
        changed=copy.deepcopy(context);changed['runConfigSha256']='b'*64
        with self.assertRaisesRegex(ValueError,'declaration_plan_changed'):subject.validate_declaration(run,path,self.binding,changed)

    def test_010_undeclared_runtime_is_rejected(self):
        run,path,context=self.declaration({})
        with self.assertRaisesRegex(ValueError,'runtime_not_declared'):subject.validate_declaration(run,path,self.binding,context)


if __name__=='__main__':unittest.main()
