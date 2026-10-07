"""Durable delivery of validated accounting events. Replay never executes work."""
from contextlib import contextmanager
import fcntl
import json
import hashlib
import os
from pathlib import Path
import re
import stat
import threading
import uuid

from scripts import sermon_log_contract as contract
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_release_workflow import _safe_path

_lock = threading.Lock()
_producers = {}
_ledger_held = threading.local()
DURABLE_BINDING_NAME = '.durable-controller-stream.json'
DURABLE_DELIVERY_DIRECTORY = '.durable-controller-events'


def _fork_reset():
    global _lock, _producers, _ledger_held
    _lock, _producers, _ledger_held = threading.Lock(), {}, threading.local()


if hasattr(os,'register_at_fork'): os.register_at_fork(after_in_child=_fork_reset)


def prepare(directory, build):
    """Allocate once, validate before reserving a sequence, then freeze the fact."""
    if getattr(_ledger_held, 'active', False):
        raise ValueError('recursive_accounting_ledger_lock')
    key = str(Path(directory).absolute())
    with _lock:
        producer, sequence = _producers.get(key, (uuid.uuid4().hex, 0))
        event = build(uuid.uuid4().hex, producer, sequence + 1)
        contract.validate_event(event)
        root = Path(directory)
        if _durable_enabled(root):
            # Bound streams validate a ledger+pending union, so even ordinary
            # process-local producers must freeze N before N+1 can be reserved.
            # No process-local producer identity is persisted or propagated.
            with _ledger(directory) as (root,pending,fd):
                _check_durable(root,pending,fd,event)
                _run_profile(root,fd,event)
                path=pending/(event['eventId']+'.json')
                jobs._reject_link(path,directory=False)
                if path.exists():raise ValueError('pending_event_identity_conflict')
                jobs._persist(path,event)
        _producers[key] = producer, sequence + 1
        return json.loads(contract.canonical_bytes(event))


@contextmanager
def _ledger(directory):
    if getattr(_ledger_held, 'active', False):
        raise ValueError('recursive_accounting_ledger_lock')
    _ledger_held.active = True
    try:
        with _ledger_file(directory) as state:
            yield state
    finally:
        _ledger_held.active = False


@contextmanager
def _ledger_file(directory):
    root = _safe_path(directory)
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    jobs._reject_link(root,directory=True)
    pending = root/'.pending-events'
    jobs._reject_link(pending,directory=True)
    pending.mkdir(mode=0o700,exist_ok=True)
    root_fd = jobs._directory_fd(root)
    try:
        # Reuse the jobs helper's bounded Darwin creation-race handling,
        # including directory-inode and symlink rechecks; never retry work.
        fd = jobs._open_lock_file(root/'events.jsonl',root_fd)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode): raise ValueError('invalid_ledger_file')
            fcntl.flock(fd,fcntl.LOCK_EX)
            os.fsync(fd)
            jobs._sync_directory_ancestry(root)
            yield root,pending,fd
        finally: os.close(fd)
    finally: os.close(root_fd)


def _append(fd,event):
    data = contract.canonical_bytes(event)+b'\n'
    if len(data)>contract.MAX_EVENT_BYTES: raise ValueError('event_size_limit')
    end = os.lseek(fd,0,os.SEEK_END)
    if end:
        os.lseek(fd,-1,os.SEEK_END); last=os.read(fd,1);os.lseek(fd,0,os.SEEK_END)
        if last != b'\n': os.write(fd,b'\n')
    while data:
        written=os.write(fd,data)
        if written<=0: raise OSError('ledger_short_write')
        data=data[written:]
    os.fsync(fd)


def _run_profile(root,fd,event):
    """Legacy and profile events cannot silently share one run identity."""
    bindings=root/'.run-profiles'
    jobs._reject_link(bindings,directory=True)
    bindings.mkdir(mode=0o700,exist_ok=True)
    marker=bindings/(hashlib.sha256(event['runId'].encode()).hexdigest()+'.json')
    binding={'runId':event['runId'],'contractVersion':contract.VERSION}
    jobs._reject_link(marker,directory=False)
    if marker.exists():
        if jobs._read(marker)!=binding:raise ValueError('run_contract_version_mismatch')
        return
    os.lseek(fd,0,os.SEEK_SET)
    with os.fdopen(os.dup(fd),'rb') as stream:
        for line in stream:
            try: previous=json.loads(line)
            except (ValueError,UnicodeError):continue
            if isinstance(previous,dict) and previous.get('runId')==event['runId'] and previous.get('contractVersion')!=contract.VERSION:
                raise ValueError('run_contract_version_mismatch')
    jobs._sync_directory(root)
    jobs._persist(marker,binding)


def deliver(directory,event):
    contract.validate_event(event)
    event=json.loads(contract.canonical_bytes(event))
    # All durable intent and folder metadata precede the append and return.
    with _ledger(directory) as (root,pending,fd):
        _check_durable(root,pending,fd,event)
        _run_profile(root,fd,event)
        path=pending/(event['eventId']+'.json')
        jobs._reject_link(path,directory=False)
        if path.exists():
            if jobs._read(path)!=event:raise ValueError('pending_event_identity_conflict')
        else: jobs._persist(path,event)
        _append(fd,event)
        path.unlink();jobs._sync_directory(pending)
    return event['eventId']


def _durable_enabled(root):
    return any((root/name).exists() or (root/name).is_symlink()
        for name in (DURABLE_BINDING_NAME, DURABLE_DELIVERY_DIRECTORY))


def _check_durable(root,pending,fd,event=None):
    # Opt-in only: even importing extra project code here would change an
    # ordinary caller's already-frozen execution identity.
    if not _durable_enabled(root):
        return None
    from scripts import sermon_durable_accounting as durable
    return durable.validate_locked(root,pending,fd,additional_events=[event] if event is not None else ())


def replay_pending(directory):
    count=0
    with _ledger(directory) as (root,pending,fd):
        _check_durable(root,pending,fd)
        # Names, sizes and types are bounded before parsing; no referenced path
        # or provider is contacted. A duplicate append is intentionally safe.
        entries=list(pending.iterdir())
        if len(entries)>4096:raise ValueError('pending_event_count_limit')
        for path in sorted(entries):
            if not re.fullmatch(r'[a-f0-9]{32}\.json',path.name):raise ValueError('invalid_pending_event_name')
            jobs._reject_link(path,directory=False)
            if path.stat().st_size>4*contract.MAX_EVENT_BYTES:raise ValueError('pending_event_size_limit')
            event=jobs._read(path);contract.validate_event(event)
            if event['eventId']!=path.stem:raise ValueError('pending_event_identity_mismatch')
            _run_profile(root,fd,event);_append(fd,event)
            path.unlink();jobs._sync_directory(pending);count+=1
    return {'replayedEvents':count,'externalActions':0}
