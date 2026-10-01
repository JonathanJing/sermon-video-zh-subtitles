"""Versioned complete local checkpoint inventory; no model, network or approval."""
from pathlib import Path
import hashlib
import os
import re
import stat

from scripts import sermon_review_contracts as c
from scripts import sermon_public_snapshot as public
from scripts import sermon_execution_extensions as extensions
from scripts.sermon_release_workflow import _safe_path

SCHEMA='sermon-preview-checkpoint-manifest-v1'
INVENTORY_SCHEMA='sermon-preview-checkpoint-inventory-v1'
REQUIRED_FILES={'model.safetensors','config.json','generation_config.json','tokenizer_config.json',
    'vocab.json','merges.txt','preprocessor_config.json','speech_tokenizer/model.safetensors',
    'speech_tokenizer/config.json','speech_tokenizer/configuration.json','speech_tokenizer/preprocessor_config.json'}

def file_snapshot(path):
    path=_safe_path(Path(path));digest=hashlib.sha256()
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd);c.require(stat.S_ISREG(before.st_mode),'checkpoint_regular_file_required')
        with os.fdopen(os.dup(fd),'rb') as stream:
            for chunk in iter(lambda:stream.read(4*1024*1024),b''):digest.update(chunk)
        after=os.fstat(fd);named=path.lstat()
    finally:os.close(fd)
    identity=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns)
    c.require(stat.S_ISREG(named.st_mode) and identity(before)==identity(after)==identity(named),
        'checkpoint_changed_during_hash')
    _safe_path(path)
    return {'sha256':digest.hexdigest(),'bytes':before.st_size}

def sha(path):return file_snapshot(path)['sha256']

def ref(path):return {'path':str(_safe_path(Path(path))),'fileBytesSha256':sha(path)}

def inventory(root):
    root=_safe_path(Path(root));c.require(root.is_absolute() and root.is_dir(),'checkpoint_absolute_directory_required')
    rows=[]
    for path in sorted(root.rglob('*')):
        c.require(not path.is_symlink(),'checkpoint_symlink_forbidden')
        if path.is_dir():continue
        relative=path.relative_to(root).as_posix()
        c.require(path.is_file() and len(relative)<=512 and not {'..','.'}&set(Path(relative).parts),
            'checkpoint_unsafe_inventory_file')
        c.require('__pycache__' not in path.parts and path.suffix not in {'.pyc','.pyo'},'checkpoint_derived_bytecode_forbidden')
        rows.append({'relativePath':relative,**file_snapshot(path)})
        c.require(len(rows)<=1024,'checkpoint_inventory_size_limit')
    c.require(REQUIRED_FILES<={r['relativePath'] for r in rows},'checkpoint_required_file_missing')
    return rows

def build(root,output,*,checkpoint_ref,conditioning_sha256):
    root=_safe_path(Path(root));output=_safe_path(Path(output))
    c.require(output.is_absolute() and not output.exists() and not output.is_relative_to(root)
        and not root.is_relative_to(output),'checkpoint_manifest_new_external_output_required')
    c.require(type(checkpoint_ref) is str and 0<len(checkpoint_ref)<=512 and checkpoint_ref.strip()==checkpoint_ref,
        'checkpoint_ref_required')
    c.require(type(conditioning_sha256) is str and re.fullmatch('[a-f0-9]{64}',conditioning_sha256),
        'checkpoint_conditioning_hash_required')
    rows=inventory(root);by_name={r['relativePath']:r for r in rows}
    c.require(by_name['model.safetensors']['sha256']==conditioning_sha256,'checkpoint_primary_model_changed')
    output.mkdir(parents=True,mode=0o700)
    inv={'schemaVersion':INVENTORY_SCHEMA,'files':rows,'treeSha256':c.canonical_sha256(rows)}
    inv_path=output/'checkpoint-inventory.json';public.save_once(inv_path,inv)
    manifest={'schemaVersion':SCHEMA,'checkpointRoot':str(root),'checkpointRef':checkpoint_ref,
        'conditioningSha256':conditioning_sha256,'configSha256':by_name['config.json']['sha256'],
        'inventory':ref(inv_path),'treeSha256':inv['treeSha256'],'fileCount':len(rows),
        'validatorCode':ref(Path(__file__)),'productionEligible':False,'humanAcceptance':'pending',
        'scope':'complete_local_checkpoint_tree_not_model_quality_or_human_acceptance'}
    manifest_path=output/'checkpoint-manifest.json';public.save_once(manifest_path,manifest)
    return validate(manifest_path,root=root,checkpoint_ref=checkpoint_ref,conditioning_sha256=conditioning_sha256)

def validate(path,*,root,checkpoint_ref,conditioning_sha256):
    path=_safe_path(Path(path));root=_safe_path(Path(root));manifest,_=public.read_snapshot(path)
    c.require(set(manifest)=={'schemaVersion','checkpointRoot','checkpointRef','conditioningSha256','configSha256',
        'inventory','treeSha256','fileCount','validatorCode','productionEligible','humanAcceptance','scope'}
        and manifest['schemaVersion']==SCHEMA and manifest['checkpointRoot']==str(root)
        and manifest['checkpointRef']==checkpoint_ref and manifest['conditioningSha256']==conditioning_sha256
        and manifest['productionEligible'] is False and manifest['humanAcceptance']=='pending'
        and manifest['scope']=='complete_local_checkpoint_tree_not_model_quality_or_human_acceptance'
        and manifest['validatorCode']==ref(Path(__file__)),'checkpoint_manifest_changed')
    inv_path=_safe_path(Path(manifest['inventory']['path']))
    c.require(not path.is_relative_to(root) and not inv_path.is_relative_to(root) and inv_path!=path
        and manifest['inventory']==ref(inv_path),'checkpoint_manifest_inventory_changed')
    inv,_=public.read_snapshot(inv_path);rows=inventory(root);by_name={r['relativePath']:r for r in rows}
    c.require(set(inv)=={'schemaVersion','files','treeSha256'} and inv['schemaVersion']==INVENTORY_SCHEMA
        and rows==inv['files'] and c.canonical_sha256(rows)==inv['treeSha256']==manifest['treeSha256']
        and len(rows)==manifest['fileCount'],'checkpoint_tree_changed')
    c.require(by_name['model.safetensors']['sha256']==conditioning_sha256
        and by_name['config.json']['sha256']==manifest['configSha256'],'checkpoint_primary_model_changed')
    return {'schemaVersion':SCHEMA,'checkpointManifest':ref(path),'checkpointInventory':ref(inv_path),
        'checkpointCode':ref(Path(__file__)),'checkpointRoot':str(root),'checkpointRef':checkpoint_ref,
        'conditioningSha256':conditioning_sha256,'treeSha256':manifest['treeSha256'],
        'files':[{'path':str(root/r['relativePath']),'fileBytesSha256':r['sha256']} for r in rows]}

def validate_declaration(root,path,binding,context):
    root=_safe_path(Path(root));path=_safe_path(Path(path));plan,_=public.read_snapshot(root/'run-plan.json')
    declaration,_=public.read_snapshot(path);extensions.validate_declaration(plan,declaration)
    c.require(plan['runDirectory']==str(root) and c.canonical_sha256(plan['providerConfig'])==context['runConfigSha256']
        and plan['executionIdentity']['gitCommit']==context['continuationCodeCommit']
        and plan['providerConfig']['codeSha256']==c.canonical_sha256(plan['executionIdentity']),
        'checkpoint_declaration_plan_changed')
    c.require(path==extensions.declaration_path(plan,declaration),'checkpoint_declaration_not_frozen')
    c.require(declaration['externalRuntimeSha256'].get('previewCheckpointManifest')
        ==binding['checkpointManifest']['fileBytesSha256']
        and declaration['externalRuntimeSha256'].get('previewCheckpointTree')==binding['treeSha256'],
        'checkpoint_runtime_not_declared')
    return ref(path)
