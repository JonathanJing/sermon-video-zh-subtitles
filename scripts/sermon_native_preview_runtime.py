"""Rebuild and verify an isolated native-preview runtime without loading a model.

The one pinned Qwen patch defers its optional 25Hz SoX import to the actual
XVectorExtractor. No worker guard or existing environment is changed. Full
runtime file hashes, interpreter/prefix and the exact patch bind real workers.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-native-preview-runtime-v1'
INVENTORY_SCHEMA = 'sermon-native-preview-runtime-inventory-v1'
PATCH_ID = 'qwen-tts-0.1.1-lazy-optional-sox-v1'
PACKAGE_FILE = 'lib/python3.13/site-packages/qwen_tts/core/tokenizer_25hz/vq/speech_vq.py'
UPSTREAM_SHA256 = '7c68fcba8c508d8a18e2241b563302d1bf46f8ecb1515c59222263d8524bb298'
PATCHED_SHA256 = '0fad1bfb5e5719bb01ee5647184216140c74ccd5e72992be75e433c93304f2f8'
CONTEXT = 'class XVectorExtractor(nn.Module):\n    def __init__(self, audio_codec_with_xvector):\n'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def patch_source(data, *, expected_before=UPSTREAM_SHA256, expected_after=PATCHED_SHA256):
    """Exact pinned transformation; test-only fixtures can supply their own hashes."""
    c.require(type(data) is bytes and c.bytes_sha256(data) == expected_before, 'native_runtime_upstream_patch_source_changed')
    text = data.decode('utf-8')
    c.require(text.count('import sox\n') == 1 and text.count(CONTEXT) == 1, 'native_runtime_patch_context_changed')
    patched = text.replace('import sox\n', '', 1).replace(CONTEXT, CONTEXT + '        import sox\n', 1).encode('utf-8')
    c.require(c.bytes_sha256(patched) == expected_after, 'native_runtime_patch_result_changed')
    return patched


def inventory(root, *, allow_bytecode=False):
    root = _safe_path(root)
    rows = []
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        # Some importers create an empty cache directory even with -B. Directory
        # shells contain no executable bytes; every descendant file stays bound.
        if path.is_dir() and not path.is_symlink() and '__pycache__' in path.parts:
            continue
        if '__pycache__' in path.parts or path.suffix in {'.pyc', '.pyo'}:
            c.require(allow_bytecode, 'native_runtime_unbound_bytecode_cache')
            continue
        if path.is_symlink():
            c.require(relative in {'bin/python', 'bin/python3', 'bin/python3.13'} and path.resolve().is_file(),
                      'native_runtime_unexpected_symlink')
            rows.append({'relativePath': relative, 'kind': 'interpreter_alias',
                         'target': os.readlink(path), 'resolvedTarget': str(path.resolve()), 'sha256': sha(path)})
        elif path.is_file():
            rows.append({'relativePath': relative, 'kind': 'file', 'bytes': path.stat().st_size, 'sha256': sha(path)})
    c.require(rows, 'native_runtime_empty_inventory')
    return rows


def clean_environment():
    return {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
            'PYTHONDONTWRITEBYTECODE': '1', 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
            'HF_DATASETS_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1', 'TOKENIZERS_PARALLELISM': 'false'}


def interpreter_info(executable):
    code = 'import json,sys,platform;print(json.dumps(dict(prefix=sys.prefix,basePrefix=sys.base_prefix,version=platform.python_version(),platform=sys.platform,architecture=platform.machine())))'
    result = subprocess.run([str(executable), '-I', '-B', '-c', code], env=clean_environment(),
                            capture_output=True, text=True, check=True, timeout=30)
    return json.loads(result.stdout)


def artifact(path):
    return {'path': str(_safe_path(path)), 'fileBytesSha256': sha(path)}


def build(source_runtime, output):
    source = _safe_path(source_runtime);out = _safe_path(output)
    c.require(source.is_dir() and not out.exists() and not source.is_relative_to(out) and not out.is_relative_to(source),
              'native_runtime_requires_new_independent_output')
    original = (source / PACKAGE_FILE).read_bytes()
    patched = patch_source(original)
    before = inventory(source, allow_bytecode=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.native-runtime-', dir=out.parent))
    try:
        runtime = temporary / 'runtime'
        # Physical copies isolate all existing dependency/source/bytecode files.
        shutil.copytree(source, runtime, symlinks=True,
                        ignore=lambda folder,names: [n for n in names if n == '__pycache__' or n.endswith(('.pyc','.pyo'))])
        (runtime / PACKAGE_FILE).write_bytes(patched)
        c.require(inventory(source, allow_bytecode=True) == before, 'native_runtime_source_changed_during_copy')
        # The upstream wheel metadata stays upstream: this is an explicit local
        # source patch, identified separately rather than a fabricated release.
        record = runtime / 'lib/python3.13/site-packages/qwen_tts-0.1.1.dist-info/RECORD'
        if record.exists():
            import base64
            rows = list(csv.reader(io.StringIO(record.read_text())))
            relative = PACKAGE_FILE.split('site-packages/', 1)[1]
            matches = [r for r in rows if r[0] == relative]
            c.require(len(matches) == 1, 'native_runtime_qwen_wheel_record_changed')
            matches[0][1:] = ['sha256=' + base64.urlsafe_b64encode(hashlib.sha256(patched).digest()).decode().rstrip('='), str(len(patched))]
            text = io.StringIO();csv.writer(text,lineterminator='\n').writerows(rows);record.write_text(text.getvalue())
        original_by_path = {r['relativePath']:r for r in before}
        copied_by_path = {r['relativePath']:r for r in inventory(runtime)}
        c.require(set(original_by_path) == set(copied_by_path), 'native_runtime_copy_inventory_changed')
        changes = {p for p in original_by_path if original_by_path[p] != copied_by_path[p]}
        expected_changes = {PACKAGE_FILE}
        if record.exists():expected_changes.add(record.relative_to(runtime).as_posix())
        c.require(changes == expected_changes, 'native_runtime_unexpected_copy_change')
        temporary.rename(out)
    except BaseException:
        if temporary.exists():shutil.rmtree(temporary)
        raise
    runtime = out / 'runtime'
    info = interpreter_info(runtime / 'bin/python')
    c.require(Path(info['prefix']).resolve() == runtime and info['version'].startswith('3.13.'),
              'native_runtime_isolation_probe_failed')
    files = inventory(runtime)
    inv = {'schemaVersion': INVENTORY_SCHEMA, 'files': files, 'treeSha256': c.canonical_sha256(files)}
    inventory_path = out / 'runtime-inventory.json';public.save_once(inventory_path, inv)
    manifest = {'schemaVersion': SCHEMA, 'patchId': PATCH_ID, 'runtimeRoot': str(runtime),
                'upstreamRuntimeRoot': str(source), 'upstreamRuntimeTreeSha256': c.canonical_sha256(before),
                'python': {'executable': str(runtime / 'bin/python'), 'resolvedExecutable': str((runtime / 'bin/python').resolve()),
                           'fileBytesSha256': sha(runtime / 'bin/python'), **info},
                'patch': {'relativePath': PACKAGE_FILE, 'upstreamSha256': UPSTREAM_SHA256,
                          'patchedSha256': PATCHED_SHA256, 'upstreamDistribution': 'qwen-tts', 'upstreamVersion': '0.1.1'},
                'inventory': {'artifactPath': str(inventory_path), 'fileBytesSha256': sha(inventory_path),
                              'treeSha256': inv['treeSha256'], 'fileCount': len(files)},
                'builderCodeSha256': sha(Path(__file__)), 'productionEligible': False,
                'scope': 'isolated_runtime_tree_and_interpreter_not_model_quality_or_human_acceptance'}
    manifest['runtimeId'] = c.canonical_sha256(manifest)
    path = out / 'runtime-manifest.json';public.save_once(path, manifest)
    validate(path)
    return {'runtimeManifest': str(path), 'runtimePython': manifest['python']['executable'],
            'runtimeId': manifest['runtimeId'], 'fileCount': len(files), 'modelLoaded': False, 'providerCalls': 0}


def validate(manifest_path, *, require_process=False):
    manifest_path = _safe_path(manifest_path);manifest,raw = public.read_snapshot(manifest_path)
    keys = {'schemaVersion','patchId','runtimeRoot','upstreamRuntimeRoot','upstreamRuntimeTreeSha256','python',
            'patch','inventory','builderCodeSha256','productionEligible','scope','runtimeId'}
    c.require(set(manifest) == keys and manifest['schemaVersion'] == SCHEMA and manifest['patchId'] == PATCH_ID
              and manifest['productionEligible'] is False and manifest['builderCodeSha256'] == sha(Path(__file__))
              and manifest['runtimeId'] == c.canonical_sha256({k:v for k,v in manifest.items() if k != 'runtimeId'}),
              'native_runtime_manifest_changed')
    root = _safe_path(manifest['runtimeRoot']);upstream = _safe_path(manifest['upstreamRuntimeRoot'])
    c.require(root.is_dir() and root != upstream and not root.is_relative_to(upstream) and not upstream.is_relative_to(root),
              'native_runtime_not_isolated')
    patch = manifest['patch']
    c.require(patch == {'relativePath': PACKAGE_FILE, 'upstreamSha256': UPSTREAM_SHA256, 'patchedSha256': PATCHED_SHA256,
                        'upstreamDistribution': 'qwen-tts', 'upstreamVersion': '0.1.1'}
              and sha(root / PACKAGE_FILE) == PATCHED_SHA256, 'native_runtime_patch_changed')
    inv_path = _safe_path(manifest['inventory']['artifactPath']);inv,inv_raw = public.read_snapshot(inv_path)
    c.require(not inv_path.is_relative_to(root) and inv_path != manifest_path
              and c.bytes_sha256(inv_raw) == manifest['inventory']['fileBytesSha256']
              and set(inv) == {'schemaVersion','files','treeSha256'} and inv['schemaVersion'] == INVENTORY_SCHEMA,
              'native_runtime_inventory_changed')
    files = inventory(root)
    c.require(files == inv['files'] and c.canonical_sha256(files) == inv['treeSha256'] == manifest['inventory']['treeSha256']
              and len(files) == manifest['inventory']['fileCount'], 'native_runtime_dependency_tree_changed')
    python = manifest['python'];executable = Path(python['executable'])
    c.require(executable == root / 'bin/python' and executable.resolve().is_file()
              and str(executable.resolve()) == python['resolvedExecutable']
              and sha(executable) == python['fileBytesSha256'] and Path(python['prefix']).resolve() == root,
              'native_runtime_interpreter_changed')
    if require_process:
        c.require(Path(sys.prefix).resolve() == root and Path(sys.executable).resolve() == executable.resolve()
                  and platform.python_version() == python['version'] and sys.platform == python['platform']
                  and platform.machine() == python['architecture'] and Path(sys.base_prefix).resolve() == Path(python['basePrefix']).resolve(),
                  'native_runtime_process_mismatch')
        c.require(sys.dont_write_bytecode, 'native_runtime_bytecode_must_be_disabled')
    return {'schemaVersion': SCHEMA, 'runtimeId': manifest['runtimeId'],
            'runtimeManifest': artifact(manifest_path), 'runtimeInventory': artifact(inv_path),
            'runtimeCode': artifact(Path(__file__)), 'dependencyTreeSha256': inv['treeSha256'],
            'interpreterFileSha256': python['fileBytesSha256'], 'runtimeRoot': str(root), 'patchId': PATCH_ID}


def smoke(manifest_path, output):
    binding = validate(manifest_path);manifest,_ = public.read_snapshot(manifest_path)
    output = _safe_path(output)
    stdout_path = output.with_suffix('.stdout.log'); stderr_path = output.with_suffix('.stderr.log')
    c.require(not any(p.exists() for p in (output, stdout_path, stderr_path)), 'native_runtime_smoke_receipt_exists')
    environment = clean_environment();environment['SERMON_NATIVE_IMPORT_MANIFEST'] = str(_safe_path(manifest_path))
    result = subprocess.run([manifest['python']['executable'], '-I', '-B', str(Path(__file__)), '--import-probe'],
                            env=environment,capture_output=True,text=True,check=False,timeout=180)
    output.parent.mkdir(parents=True, exist_ok=True)
    for path, text in ((stdout_path,result.stdout),(stderr_path,result.stderr)):
        with path.open('x') as stream:stream.write(text)
    observed = None; failure = None
    try:
        c.require(result.returncode == 0, 'native_runtime_guarded_import_failed')
        observed = json.loads(result.stdout.strip().splitlines()[-1])
        c.require(observed == {'status':'guarded_import_pass','modelLoaded':False,'modelConstructed':False,
                               'soxImported':False,'providerCalls':0,'runtimeId':binding['runtimeId']},
                  'native_runtime_import_probe_result_changed')
        c.require(validate(manifest_path) == binding, 'native_runtime_changed_during_import')
    except (ValueError, IndexError) as exc:failure = str(exc)
    receipt = {'schemaVersion':'sermon-native-preview-runtime-import-v1','runtimeBinding':binding,
               'observed':observed,'processReturncode':result.returncode,'nativeWorkerGuardUnchanged':True,
               'inference':'not_run','productionEligible':False,'stdoutSha256':c.bytes_sha256(result.stdout.encode()),
               'stderrSha256':c.bytes_sha256(result.stderr.encode()), 'stdout':artifact(stdout_path),'stderr':artifact(stderr_path),
               'workerCodeSha256':sha(ROOT/'scripts/sermon_diagnostic_preview_worker.py'),
               'status':'guarded_import_failed' if failure else 'guarded_import_pass','failureReasonCode':failure}
    public.save_once(output,receipt)
    c.require(failure is None, 'native_runtime_guarded_import_failed_receipt:' + str(output))
    return {'status':'guarded_import_pass','receipt':str(output),'runtimeId':binding['runtimeId'],'modelLoaded':False,'providerCalls':0}


def import_probe():
    manifest = _safe_path(os.environ['SERMON_NATIVE_IMPORT_MANIFEST'])
    binding = validate(manifest,require_process=True)
    from scripts import sermon_diagnostic_preview_worker as worker
    from unittest.mock import patch
    with worker._local_only(False), patch.object(worker.preview.formal.QwenSynthesizer,'__init__',side_effect=AssertionError('no model construction')):
        from qwen_tts import Qwen3TTSModel
        c.require(callable(Qwen3TTSModel.from_pretrained) and 'sox' not in sys.modules, 'native_runtime_sox_still_imported')
    c.require(validate(manifest,require_process=True) == binding, 'native_runtime_import_changed_dependency_tree')
    print(json.dumps({'status':'guarded_import_pass','modelLoaded':False,'modelConstructed':False,
                      'soxImported':False,'providerCalls':0,'runtimeId':binding['runtimeId']}))


def main():
    p = argparse.ArgumentParser(description=__doc__);p.add_argument('--import-probe',action='store_true')
    p.add_argument('--source-runtime',type=Path);p.add_argument('--build-out',type=Path)
    p.add_argument('--manifest',type=Path);p.add_argument('--smoke-out',type=Path)
    args = p.parse_args()
    if args.import_probe:import_probe()
    elif args.source_runtime and args.build_out:print(json.dumps(build(args.source_runtime,args.build_out)))
    elif args.manifest and args.smoke_out:print(json.dumps(smoke(args.manifest,args.smoke_out)))
    elif args.manifest:print(json.dumps(validate(args.manifest)))
    else:p.error('use --source-runtime/--build-out or --manifest[/--smoke-out]')


if __name__ == '__main__':main()
