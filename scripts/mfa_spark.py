"""Optional Spark MFA transport; MacBook-first selection lives in mfa_backend.

SSH uses normal host-key verification and key authentication. No downloads or
local inference fallback occur. Model identities are queried before cache reuse.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import tempfile

from scripts.mfa_alignment import _sha, _write, _spoken_forms

DEFAULT_ROOT = '/home/achillesjing/sermon-mfa-runtime'


def add_arguments(parser):
    for name, default in [('host', 'achillesjing@192.168.1.152'), ('proxy_jump', ''), ('relay_host', ''), ('relay_host_key_alias', ''),
                          ('python', DEFAULT_ROOT + '/env/bin/python'), ('root', DEFAULT_ROOT + '/jobs')]:
        parser.add_argument('--mfa-spark-' + name.replace('_', '-'),
                            default=os.environ.get('MFA_SPARK_' + name.upper(), default))


def transport_options(args):
    return {name: getattr(args, 'mfa_spark_' + name, None) or os.environ.get('MFA_SPARK_' + name.upper(), default)
            for name, default in [('host', 'achillesjing@192.168.1.152'), ('proxy_jump', ''), ('relay_host', ''), ('relay_host_key_alias', ''),
                                  ('python', DEFAULT_ROOT + '/env/bin/python'), ('root', DEFAULT_ROOT + '/jobs')]}


# Only this self-contained worker and the versioned adapter are sent to Spark.
WORKER = r'''
import hashlib, json, os, pathlib, sys, tarfile
root = pathlib.Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
with tarfile.open(fileobj=sys.stdin.buffer, mode='r|') as bundle:
    first = bundle.next()
    if first.name != 'request.json': raise ValueError('Missing request')
    request = json.load(bundle.extractfile(first))
    key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    run = root / key
    run.mkdir(exist_ok=True)
    import fcntl
    lock = (run/'job.lock').open('a')
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    while True:
        item = bundle.next()
        if item is None: break
        if item.name not in ('mfa_alignment.py', 'audio', 'spoken.json') or not item.isfile():
            raise ValueError('Unexpected transport member')
        target = run / item.name
        temporary = target.with_suffix('.upload')
        with bundle.extractfile(item) as source, temporary.open('wb') as dest:
            import shutil
            shutil.copyfileobj(source, dest)
        temporary.replace(target)
sys.path.insert(0, str(run))
import mfa_alignment as adapter
if adapter._sha(run/'mfa_alignment.py') != request['adapterSha256']:
    raise ValueError('Adapter transfer hash mismatch')
options = request['options']
if request.get('spokenSha256'):
    options['spoken_forms_path'] = str(run/'spoken.json')
    if adapter._sha(run/'spoken.json') != request['spokenSha256']:
        raise ValueError('Spoken forms transfer hash mismatch')
# Conda ffmpeg must be discoverable even through a non-login SSH shell.
os.environ['PATH'] = str(pathlib.Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH','')
checked = adapter.preflight(**options)
import subprocess
version = subprocess.run([checked['mfa_executable'], 'version'], check=True,
                         capture_output=True, text=True, timeout=60).stdout.strip()
if not version: raise ValueError('Empty MFA version')
import importlib.metadata, importlib.util
packages = {}
for name in ('montreal-forced-aligner', 'kalpy', 'pynini', 'numpy'):
    try: packages[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError: packages[name] = None
native_spec = importlib.util.find_spec('_kalpy')
native_path = pathlib.Path(native_spec.origin) if native_spec and native_spec.origin else None
native = {'path':str(native_path), 'sha256':adapter._sha(native_path)} if native_path and native_path.is_file() else None
# Conda records bind native Kaldi/OpenFST builds as well as Python packages.
conda_records = pathlib.Path(sys.prefix) / 'conda-meta'
native_records = {p.name:adapter._sha(p) for p in sorted(conda_records.glob('*.json'))}
identity = {'executionHost': os.uname().nodename, 'executionPlatform': sys.platform,
            'machine': os.uname().machine, 'version': version,
            'packages':packages, 'nativeKalpy':native, 'condaRecords':native_records,
            'adapterSha256': request['adapterSha256'],
            'files': {k: {'path':v, 'sha256':adapter._sha(v)} if v else None
                      for k,v in checked.items() if k != 'spoken_forms_sha256'}}
if sys.platform != 'linux' or os.uname().machine not in ('aarch64', 'arm64'):
    raise ValueError('MFA production endpoint must be Linux ARM64 DGX Spark')
# Staging paths vary between preflight and align; only forms content identifies it.
if identity['files'].get('spoken_forms_path'):
    identity['files']['spoken_forms_path'].pop('path', None)
result = {'schemaVersion':1, 'backend':'dgx-spark-ssh', 'runtime':identity}
if request['action'] == 'align':
    if adapter._sha(run/'audio') != request['audioSha256']:
        raise ValueError('Audio transfer hash mismatch')
    runtime_key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    segments = adapter.align_reference_chunks(request['chunks'], run/'audio', run/'output'/runtime_key, **options)
    manifest = json.loads(pathlib.Path(segments[0]['mfaManifest']).read_text())
    result.update(segments=segments, manifest=manifest, audioSha256=request['audioSha256'],
                  requestSha256=key)
print(json.dumps(result, ensure_ascii=False))
'''


def _call(action, *, chunks=None, clip_path=None, host, proxy_jump='', relay_host='', relay_host_key_alias='', python, root,
          mfa_executable, dictionary_path, acoustic_model, g2p_model=None, spoken_forms_path=None):
    if not re.fullmatch(r'[A-Za-z0-9_.@:-]+', host) or host.startswith('-'):
        raise ValueError('Invalid Spark SSH host')
    for label, value in [('relay host', relay_host), ('relay host key alias', relay_host_key_alias)]:
        if value and (not re.fullmatch(r'[A-Za-z0-9_.@:-]+', value) or value.startswith('-')):
            raise ValueError('Invalid Spark SSH ' + label)
    if relay_host and proxy_jump:
        raise ValueError('Use either relay host or ProxyJump, not both')
    if proxy_jump and (not re.fullmatch(r'[A-Za-z0-9_.@:,\[\]-]+', proxy_jump) or proxy_jump.startswith('-')):
        raise ValueError('Invalid Spark SSH proxy jump')
    if not str(root).startswith('/') or not str(python).startswith('/'):
        raise ValueError('Spark Python and job root must be absolute paths')
    if not dictionary_path or not acoustic_model:
        raise ValueError('Configure MFA_DICTIONARY and MFA_ACOUSTIC_MODEL as Spark paths')
    if spoken_forms_path:
        _spoken_forms(spoken_forms_path)
    adapter = Path(__file__).with_name('mfa_alignment.py')
    request = {'action': action, 'adapterSha256': _sha(adapter),
               'spokenSha256': _sha(spoken_forms_path) if spoken_forms_path else None,
               'options': {'mfa_executable': str(mfa_executable), 'dictionary_path': str(dictionary_path),
                           'acoustic_model': str(acoustic_model), 'g2p_model': str(g2p_model) if g2p_model else None,
                           'spoken_forms_path': None}}
    if action == 'align':
        request.update(chunks=chunks, audioSha256=_sha(clip_path))
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15']
    if proxy_jump:
        command += ['-J', proxy_jump]
    command += [host, shlex.join([str(python), '-c', WORKER, str(root)])]
    if relay_host:
        outer = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15']
        if relay_host_key_alias:
            outer += ['-o', 'HostKeyAlias=' + relay_host_key_alias]
        command = outer + [relay_host, shlex.join(command)]
    with tempfile.TemporaryFile() as payload:
        with tarfile.open(fileobj=payload, mode='w') as bundle:
            data = json.dumps(request, ensure_ascii=False).encode()
            entry = tarfile.TarInfo('request.json'); entry.size = len(data)
            bundle.addfile(entry, io.BytesIO(data))
            bundle.add(adapter, arcname='mfa_alignment.py')
            if spoken_forms_path:
                bundle.add(Path(spoken_forms_path).resolve(strict=True), arcname='spoken.json')
            if action == 'align':
                # Cached inputs may be symlinks. The worker accepts regular files only.
                bundle.add(Path(clip_path).resolve(strict=True), arcname='audio')
        payload.seek(0)
        try:
            completed = subprocess.run(command, stdin=payload, capture_output=True, check=True,
                                       timeout=14460 if action == 'align' else 180)
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode(errors='replace')[-2000:]
            raise RuntimeError('DGX Spark MFA failed; no local fallback. ' + detail) from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError('DGX Spark MFA unavailable; no local fallback') from exc
    result = json.loads(completed.stdout)
    if result.get('schemaVersion') != 1 or result.get('backend') != 'dgx-spark-ssh':
        raise ValueError('Invalid Spark MFA response')
    return result


def preflight(**options):
    return _call('preflight', **options)


def align_reference_chunks(chunks, clip_path, outdir, **options):
    result = _call('align', chunks=chunks, clip_path=clip_path, **options)
    if result.get('audioSha256') != _sha(clip_path) or not result.get('segments'):
        raise ValueError('Spark MFA response does not match input audio')
    if not re.fullmatch(r'[0-9a-f]{64}', result.get('requestSha256', '')):
        raise ValueError('Invalid Spark request identity')
    if result['manifest']['identity']['audioSha256'] != _sha(clip_path):
        raise ValueError('Spark manifest audio mismatch')
    expected = ' '.join(' '.join(str(c.get('text', '')).split()) for c in chunks if str(c.get('text', '')).strip())
    if ' '.join(s['text'] for s in result['segments']) != expected:
        raise ValueError('Spark result changed frozen text')
    if any(s.get('requires_operator_review') is not True or s.get('timingQuality') != 'mfa_word_aligned' for s in result['segments']):
        raise ValueError('Spark result missing timing provenance')
    runtime_key = hashlib.sha256(json.dumps(result['runtime'], sort_keys=True).encode()).hexdigest()
    root = Path(outdir) / runtime_key / result['requestSha256']
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / 'manifest.json'
    _write(manifest_path, result['manifest'])
    _write(root / 'spark-runtime.json', {k:v for k,v in result.items() if k not in ('segments', 'manifest')})
    for segment in result['segments']:
        segment['remoteMfaManifest'] = segment['mfaManifest']
        segment['mfaManifest'] = str(manifest_path.resolve())
        segment['alignmentExecutionBackend'] = 'dgx-spark-ssh'
    _write(root / 'segments.json', result['segments'])
    return result['segments']
