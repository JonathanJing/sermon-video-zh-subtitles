"""Deploy isolated logging tools; never alters running services or job state."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
import tempfile

PACKAGE = 'experiments/local_experiment_log'

def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def sha(data):
    return hashlib.sha256(data).hexdigest()

def safe_dir(path):
    path = Path(path).absolute()
    for parent in [*reversed(path.parents), path]:
        if parent.is_symlink() or parent.exists() and not parent.is_dir():
            raise ValueError('unsafe_install_directory')
    return path

def build(source, bundle, canonical_source_pin):
    source, bundle = Path(source), Path(bundle)
    if not isinstance(canonical_source_pin, str) or not re.fullmatch(r'[a-f0-9]{40}', canonical_source_pin):
        raise ValueError('canonical_source_pin_required')
    contents = {}
    for path in sorted((source/PACKAGE).rglob('*')):
        if path.is_symlink():
            raise ValueError('source_symlink_rejected')
        if path.is_file() and '__pycache__' not in path.parts and path.suffix in ('.py', '.json', '.jsonl', '.md'):
            if path.name.startswith('audit.') or path.name == 'DELIVERY.zh.md':
                continue
            contents[path.relative_to(source).as_posix()] = path.read_bytes()
    for relative in ('scripts/sermon_log_contract.py', 'schemas/sermon-accounting-log-contract-v1.schema.json'):
        path = source/relative
        if path.is_symlink():
            raise ValueError('source_symlink_rejected')
        contents[relative] = path.read_bytes()
    identity = {'schema': 'tongxing-experiment-log-release-v1', 'canonical_source_pin': canonical_source_pin,
                'files': {name: sha(data) for name, data in contents.items()}}
    identity['release_id'] = sha(encoded(identity))[:16]
    contents['RELEASE.json'] = encoded(identity)+b'\n'
    bundle.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(bundle, 'w:gz') as archive:
        for name, data in contents.items():
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o600
            archive.addfile(info, io.BytesIO(data))
    return {'release_id': identity['release_id'], 'bundle_sha256': sha(bundle.read_bytes()), 'file_count': len(identity['files'])}

def read_bundle(bundle):
    contents = {}
    with tarfile.open(bundle, 'r:gz') as archive:
        members = archive.getmembers()
        if len(members)>100 or sum(m.size for m in members)>4*1024*1024:
            raise ValueError('bundle_size_limit')
        for member in members:
            path = PurePosixPath(member.name)
            if (not member.isfile() or path.is_absolute() or path.as_posix()!=member.name or
                '..' in path.parts or member.name in contents or not path.parts or member.size>256*1024):
                raise ValueError('unsafe_bundle_member')
            contents[member.name] = archive.extractfile(member).read()
    identity = json.loads(contents.pop('RELEASE.json'))
    release = identity.pop('release_id')
    if sha(encoded(identity))[:16]!=release or identity.get('schema')!='tongxing-experiment-log-release-v1':
        raise ValueError('release_identity_mismatch')
    if set(contents)!=set(identity['files']) or any(sha(data)!=identity['files'][name] for name,data in contents.items()):
        raise ValueError('bundle_hash_mismatch')
    identity['release_id']=release
    return identity,contents

def verify_release(root):
    root = safe_dir(root)
    identity = json.loads((root/'RELEASE.json').read_text())
    release = identity['release_id']
    if sha(encoded({k:v for k,v in identity.items() if k!='release_id'}))[:16]!=release:
        raise ValueError('installed_manifest_identity_mismatch')
    actual = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('release_symlink_rejected')
        if path.is_file() and '__pycache__' not in path.parts and path.name!='RELEASE.json':
            actual[path.relative_to(root).as_posix()] = sha(path.read_bytes())
    if actual!=identity['files']:
        raise ValueError('installed_release_hash_mismatch')
    return identity

def install(bundle, root):
    identity, contents = read_bundle(bundle)
    root = safe_dir(root); releases = safe_dir(root/'releases'); current=root/'current'
    previous=None
    if current.is_symlink():
        previous=os.readlink(current)
        if not re.fullmatch(r'releases/[a-f0-9]{16}',previous):
            raise ValueError('foreign_current_pointer')
        verify_release(root/previous)
    elif current.exists():
        raise ValueError('current_pointer_not_symlink')
    destination=releases/identity['release_id']
    releases.mkdir(parents=True,exist_ok=True,mode=0o700)
    if destination.exists():
        verify_release(destination)
    else:
        staging=Path(tempfile.mkdtemp(prefix='.incoming-',dir=releases))
        for name,data in contents.items():
            path=staging/name; path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
        (staging/'RELEASE.json').write_bytes(encoded(identity)+b'\n')
        verify_release(staging); staging.rename(destination)
    target='releases/'+identity['release_id']
    temporary=root/('.current-'+os.urandom(8).hex()); temporary.symlink_to(target)
    os.replace(temporary,current); verify_release(destination)
    return {'status':'tool_package_installed','root':str(root),'release_id':identity['release_id'],
            'current_target':target,'previous_target':previous,'files_verified':len(contents),
            'service_restarts':0,'model_executions':0,'canonical_source_pin':identity['canonical_source_pin']}

def rollback(receipt):
    root=safe_dir(receipt['root']); current=root/'current'
    if not current.is_symlink() or os.readlink(current)!=receipt['current_target']:
        raise ValueError('rollback_pointer_changed')
    previous=receipt['previous_target']
    if previous is None:
        current.unlink()
    else:
        if not re.fullmatch(r'releases/[a-f0-9]{16}',previous):
            raise ValueError('foreign_rollback_pointer')
        verify_release(root/previous)
        temporary=root/('.rollback-'+os.urandom(8).hex()); temporary.symlink_to(previous); os.replace(temporary,current)
    return {'status':'tool_pointer_restored','restored_target':previous,'service_restarts':0}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['build','install','rollback','verify'])
    for key in ('source','bundle','root','receipt'):
        parser.add_argument('--'+key,type=Path)
    parser.add_argument('--canonical-source-pin', help='40-hex source commit for the bundled canonical validator/schema')
    args=parser.parse_args()
    required = {'build': ('source','bundle','canonical_source_pin'), 'install': ('bundle','root'),
                'rollback': ('receipt',), 'verify': ('root',)}[args.action]
    if any(getattr(args, key) is None for key in required):
        parser.error('missing arguments for '+args.action)
    if args.action=='build': result=build(args.source,args.bundle,args.canonical_source_pin)
    elif args.action=='install': result=install(args.bundle,args.root)
    elif args.action=='rollback': result=rollback(json.loads(args.receipt.read_text()))
    else:
        identity=verify_release(args.root)
        result={'status':'verified','release_id':identity['release_id'],'file_count':len(identity['files'])}
    if args.receipt and args.action!='rollback':
        args.receipt.parent.mkdir(parents=True,exist_ok=True)
        args.receipt.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__': main()
