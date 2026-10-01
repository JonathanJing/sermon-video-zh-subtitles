"""Exact local identity witness: acquire outside guard, check without processes.

This grants no network/provider authority. A clean, exact execution identity and
full tracked working-tree/index/HEAD snapshots are required; incomplete evidence
or drift rejects reuse. The bounded HTTP-only subprocess guard stays unchanged.
"""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
from scripts import sermon_accounting as accounting, sermon_review_contracts as c
from scripts.sermon_release_workflow import _safe_path

SCHEMA='sermon-historical-execution-witness-v1'
MAX_FILES=16384
MAX_FILE_BYTES=512*1024*1024
MAX_TOTAL_BYTES=2*1024**3


PRE_PROVIDER_CODES=frozenset(['historical_current_code_changed', 'historical_identity_file_changed_during_read', 'historical_identity_file_missing', 'historical_identity_file_not_regular_or_too_large', 'historical_identity_fixed_repository_required', 'historical_identity_git_inspection_failed', 'historical_identity_git_or_tree_changed', 'historical_identity_git_path_invalid', 'historical_identity_head_invalid', 'historical_identity_tracked_inventory_invalid', 'historical_identity_tracked_inventory_too_large', 'historical_identity_witness_changed'])


class HistoricalIdentityPreDispatchRejected(c.ContractError):
    """Only guard-external trusted witness acquisition raises this terminal."""
    def __init__(self, reason_code):
        c.require(reason_code in PRE_PROVIDER_CODES,'historical_identity_reason_invalid')
        super().__init__(reason_code)
        self._reason_code=reason_code

    @property
    def reason_code(self):return self._reason_code

    @property
    def phase(self):return 'before_locale_provider_dispatch'

    @property
    def provider_dispatch_occurred(self):return False


def _git(root,*args):
    result=subprocess.run(['git','--no-optional-locks','-C',str(root),*args],
        capture_output=True,check=False,timeout=5)
    c.require(result.returncode==0,'historical_identity_git_inspection_failed')
    return result.stdout


def _file(path, *, absent=False):
    path=Path(path)
    try:before=path.lstat()
    except FileNotFoundError:
        c.require(absent,'historical_identity_file_missing')
        return {'kind':'absent'}
    if stat.S_ISLNK(before.st_mode):
        value=os.readlink(path);after=path.lstat()
        c.require((before.st_dev,before.st_ino,before.st_mtime_ns,before.st_ctime_ns)==
            (after.st_dev,after.st_ino,after.st_mtime_ns,after.st_ctime_ns),
            'historical_identity_file_changed_during_read')
        return {'kind':'symlink','sha256':c.bytes_sha256(value.encode()),'bytes':len(value.encode()),
            'mode':stat.S_IMODE(before.st_mode)}
    c.require(stat.S_ISREG(before.st_mode) and before.st_size<=MAX_FILE_BYTES,
        'historical_identity_file_not_regular_or_too_large')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        opened=os.fstat(fd);digest=hashlib.sha256()
        with os.fdopen(os.dup(fd),'rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
        after=os.fstat(fd);named=path.lstat()
        identity=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns,row.st_mode)
        c.require(identity(before)==identity(opened)==identity(after)==identity(named),
            'historical_identity_file_changed_during_read')
        return {'kind':'regular','sha256':digest.hexdigest(),'bytes':after.st_size,
            'mode':stat.S_IMODE(after.st_mode)}
    finally:os.close(fd)


def _loaded(root):
    modules={}
    for module in list(sys.modules.values()):
        name=getattr(module,'__file__',None)
        if not name:continue
        try:relative=Path(name).resolve().relative_to(root)
        except (ValueError,OSError):continue
        if relative.parts[0] in {'scripts','backend','experiments'} and relative.suffix=='.py':
            modules[str(relative)]=_file(root/relative)['sha256']
    return modules


def _git_environment():
    # Hash only: no Git credential/author/config values enter a receipt.
    return c.canonical_sha256({k:v for k,v in os.environ.items() if k.startswith('GIT_')})


def _git_path(root,name):
    value=_git(root,'rev-parse','--git-path',name).decode().strip()
    c.require(value and '\n' not in value,'historical_identity_git_path_invalid')
    return str(_safe_path(Path(value) if Path(value).is_absolute() else root/value))


def _current_commit(metadata):
    head=Path(metadata['HEAD']).read_text().strip()
    if re.fullmatch('[a-f0-9]{40,64}',head):return head
    c.require(head.startswith('ref: '),'historical_identity_head_invalid')
    name=head[5:]
    c.require(re.fullmatch(r'refs/[A-Za-z0-9_./-]+',name) and '..' not in Path(name).parts,
        'historical_identity_head_invalid')
    reference=Path(metadata['headRef'])
    if reference.is_file():commit=reference.read_text().strip()
    else:
        packed=Path(metadata['packed-refs'])
        rows=[] if not packed.is_file() else packed.read_text().splitlines()
        matches=[line.split()[0] for line in rows if len(line.split())==2 and line.split()[1]==name]
        c.require(len(matches)==1,'historical_identity_head_invalid');commit=matches[0]
    c.require(re.fullmatch('[a-f0-9]{40,64}',commit),'historical_identity_head_invalid')
    return commit


class ExecutionIdentityWitness:
    """Only a trusted fixed resolver uses this object; no caller callbacks."""
    @classmethod
    def capture(cls,expected):
        root=Path(accounting.__file__).resolve().parents[1]
        try:
            actual=accounting.execution_identity()
            c.require(actual==expected and actual['trackedWorkingTreeDirty'] is False,
                'historical_current_code_changed')
            return cls._capture(root,expected)
        except c.ContractError as exc:
            if type(exc) is c.ContractError and str(exc) in PRE_PROVIDER_CODES:
                raise HistoricalIdentityPreDispatchRejected(str(exc)) from exc
            raise
        except subprocess.TimeoutExpired as exc:
            raise HistoricalIdentityPreDispatchRejected('historical_identity_git_inspection_failed') from exc

    @classmethod
    def _capture(cls,root,expected):
        # Private fixture seam: production capture always fixes accounting root.
        root=_safe_path(root);self=object.__new__(cls);self.root=root
        self.identity=deepcopy(expected)
        c.require(expected['trackedWorkingTreeDirty'] is False and
            _git(root,'rev-parse','HEAD').decode().strip()==expected['gitCommit'] and
            not _git(root,'status','--porcelain','--untracked-files=no').strip(),
            'historical_current_code_changed')
        names=_git(root,'ls-files','-z').split(b'\0');names=[x.decode('utf-8') for x in names if x]
        c.require(0<len(names)<=MAX_FILES and len(names)==len(set(names)),
            'historical_identity_tracked_inventory_invalid')
        for name in names:
            c.require(not Path(name).is_absolute() and '..' not in Path(name).parts and
                '\x00' not in name,'historical_identity_tracked_inventory_invalid')
        self.tree={name:_file(root/name) for name in names}
        c.require(sum(row['bytes'] for row in self.tree.values())<=MAX_TOTAL_BYTES,
            'historical_identity_tracked_inventory_too_large')
        self.metadata={name:_git_path(root,name) for name in ('HEAD','index','packed-refs','config','config.worktree')}
        head=Path(self.metadata['HEAD']).read_text().strip()
        if head.startswith('ref: '):self.metadata['headRef']=_git_path(root,head[5:])
        # Protect the worktree .git indirection; ordinary repo .git is a directory.
        if (root/'.git').is_file():self.metadata['gitMarker']=str(root/'.git')
        self.git_files={name:_file(path,absent=True) for name,path in self.metadata.items()}
        self.environment_sha256=_git_environment()
        self.helper_sha256=_file(Path(__file__))['sha256']
        self.modules=_loaded(root)
        c.require(self.modules==expected['loadedProjectCodeSha256'] and
            _current_commit(self.metadata)==expected['gitCommit'], 'historical_current_code_changed')
        self.binding_sha256=c.canonical_sha256(self._binding())
        self._validate(expected)
        return self

    def _binding(self):
        return {'schemaVersion':SCHEMA,'identity':self.identity,'trackedTree':self.tree,
            'gitPaths':self.metadata,'gitFiles':self.git_files,'gitEnvironmentSha256':self.environment_sha256,
            'helperCodeSha256':self.helper_sha256,'executionAuthority':'none'}

    def validate(self,expected):
        c.require(type(self) is ExecutionIdentityWitness and
            self.root==Path(accounting.__file__).resolve().parents[1],
            'historical_identity_fixed_repository_required')
        return self._validate(expected)

    def _validate(self,expected):
        c.require(self.identity==expected and c.canonical_sha256(self._binding())==self.binding_sha256 and
            _file(Path(__file__))['sha256']==self.helper_sha256,
            'historical_identity_witness_changed')
        c.require(_git_environment()==self.environment_sha256 and
            {name:_file(path,absent=True) for name,path in self.metadata.items()}==self.git_files and
            {name:_file(self.root/name) for name in self.tree}==self.tree and
            _current_commit(self.metadata)==expected['gitCommit'],
            'historical_identity_git_or_tree_changed')
        c.require(_loaded(self.root)==expected['loadedProjectCodeSha256'] and
            platform.python_version()==expected['pythonVersion'] and sys.platform==expected['platform'] and
            platform.machine()==expected['architecture'], 'historical_current_code_changed')
        return {'schemaVersion':SCHEMA,'witnessSha256':self.binding_sha256,
            'executionIdentitySha256':c.canonical_sha256(expected),'newProviderCalls':0,
            'currentCheck':'pure_local_files_and_loaded_modules_no_processes','executionAuthority':'none'}
