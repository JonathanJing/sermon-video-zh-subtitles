#!/usr/bin/env python3
"""Explicit Spark diagnostic dispatch; preflight is read-only and never loads models.

execute verifies current local L2 admission before staging immutable inputs,
runs one GPU locale at a time, and copies full evidence back. Unknown dispatches
must be reconciled, not automatically repeated. No publication or approval.
"""
from __future__ import annotations
import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import socket
import stat
import socketserver
import struct
import threading
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))
from scripts.experiments import diagnostic_audio_inputs as inputs
from scripts import codex_layer2_diagnostic as diagnostic

HOST = 'achillesjing@192.168.1.152'
CHECKPOINT = '/home/achillesjing/dgx-spark-benchmark/results/sermon-voice-poc-20260905/checkpoints/checkpoint-epoch-0'
# HF snapshot files are symlinks into ../../blobs, so mount the whole model repo
# directory and address the pinned snapshot inside it.
ASR_HUB = '/home/achillesjing/sermon-speech-runtime/model-cache/hub/models--Qwen--Qwen3-ASR-0.6B'
ASR_SNAPSHOT = '/asr-hub/snapshots/5eb144179a02acc5e5ba31e748d22b0cf3e303b0'
MEDIA_TOOLS = '/home/achillesjing/sermon-mfa-runtime/env'
BROKER = '/home/achillesjing/dgx-spark-benchmark/results/next-concurrency-605s-shared-gpu-20261005-r3'
IMAGES = {'tts': 'sha256:e615da846c45d026d221bda0f168ae35022af18ac7ec4e5245d04fb62c314f14',
          'asr': 'sha256:a0a74493c2b670fc76ba04f30c849da4486e3ca3f9dbb8e9e588eb5abc9d0873'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def relative(path):
    path = Path(path).resolve()
    require(path.is_relative_to(ROOT / 'artifacts'), 'diagnostic_path_must_be_in_ignored_artifacts')
    return str(path.relative_to(ROOT))


def _session_job_purpose(out_dir):
    return 'diagnostic-audio.' + inputs.digest(str(Path(out_dir).resolve()))[:32]


def inventory(directory):
    return {str(path.relative_to(directory)): inputs.sha(path)
            for path in sorted(directory.rglob('*')) if path.is_file()}


def preflight(args):
    fixture = diagnostic.load_fixture(args.fixture)
    manifest = fixture[-1]
    require(inputs.sha(args.media) == manifest['sourceMediaSha256'], 'spark_source_media_hash_changed')
    locale = fixture[2]['targetLocale']
    registry = inputs.read(args.registry)
    speaker = next(row for row in registry['speakers'] if row['speakerId'] == 'eric_geiger')
    cap = next(row for row in speaker['localeCapabilities'] if row['targetLocale'] == locale)
    require(locale in ('zh-Hans', 'ko', 'es') and not cap.get('adapterOverride')
            and cap['status'] in ('human_reviewed', 'unverified_poc')
            and speaker['authorization']['status'] == 'authorized', 'spark_diagnostic_voice_not_ready')
    args.diagnostic_fixture = args.fixture
    args.diagnostic_candidate = args.layer2_out / 'diagnostic-candidate.json'
    args.evidence = args.layer2_out / 'evidence.json'
    binding = None
    if args.diagnostic_candidate.exists():
        _, binding = inputs.checked_inputs(args)
    return {'schemaVersion': 'spark-diagnostic-audio-preflight-v1',
            'status': 'ready_for_explicit_dispatch' if binding else 'awaiting_layer2',
            'targetLocale': locale, 'sourceUnits': manifest['sourceUnits'], 'groups': manifest['groups'],
            'sourceMediaSha256': manifest['sourceMediaSha256'], 'sourceWindow': manifest['sourceWindow'],
            'fixtureSha256': inputs.digest(manifest), 'diagnosticBinding': binding,
            'checkpointSha256': speaker['checkpoint']['checkpointSha256'],
            'speakerCapabilityStatus': cap['status'], 'modelLanguage': cap['modelLanguage'],
            'ttsReplicas': 8, 'ttsBatchSize': 8, 'cpuWorkers': 4, 'backAsrReplicas': 1, 'backAsrBatchSize': 8,
            'sparkSessionRequiredForExecution': True,
            'realModelCalls': 0, 'productionEligible': False, 'humanApproval': False, 'releaseEligible': False}


def remote_command(argv):
    return ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', HOST,
            ' '.join(shlex.quote(str(item)) for item in argv)]


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, **kwargs)


def _spark_session(session_id=None, owner=None):
    from scripts.spark_exclusive_session import Client
    return Client.from_environment(session_id=session_id, owner=owner)


class AdmissionGateway:
    """Private, read-only host admission socket for offline GPU containers."""
    @staticmethod
    def peer_uid(connection):
        if hasattr(socket, 'SO_PEERCRED'):
            _, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            return uid
        if hasattr(connection, 'getpeereid'):
            return connection.getpeereid()[0]
        raise ValueError('gateway_peer_identity_unavailable')

    def __init__(self, directory, session, hold, *, runner_pid=None):
        self.directory, self.session = Path(directory), session
        require(type(hold) is dict and isinstance(hold.get('jobId'), str) and hold['jobId'], 'gateway_job_required')
        self.job_id, self.runner_pid = hold['jobId'], runner_pid or os.getpid()
        parent = self.directory.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        identity = parent.lstat()
        require(not parent.is_symlink() and identity.st_uid == os.getuid()
                and stat.S_IMODE(identity.st_mode) == 0o700, 'gateway_parent_identity_rejected')
        self.directory.mkdir(mode=0o700, exist_ok=False)
        self.path = self.directory / 'admission.sock'
        gateway = self
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    self.connection.settimeout(30)
                    uid = gateway.peer_uid(self.connection)
                    require(uid == os.getuid(), 'gateway_peer_uid_rejected')
                    line = self.rfile.readline(16385)
                    require(len(line) <= 16384 and line.endswith(b'\n'), 'gateway_request_too_large')
                    request = json.loads(line)
                    require(type(request) is dict and set(request) == {'action', 'session_id', 'owner'}
                            and request['action'] == 'require'
                            and request['session_id'] == gateway.session.environment['SPARK_EXCLUSIVE_SESSION_ID']
                            and request['owner'] == gateway.session.environment['SPARK_EXCLUSIVE_SESSION_OWNER'],
                            'gateway_readonly_identity_required')
                    snapshot = gateway.session.request('status')
                    job = snapshot['session']['jobs'].get(gateway.job_id)
                    process = next((row for row in snapshot['inventory']['processes']
                                    if row.get('pid') == gateway.runner_pid), None)
                    require(job is not None and job['status'] == 'active'
                            and job['sessionId'] == request['session_id'] and job['owner'] == request['owner']
                            and process is not None and not process.get('unreadable')
                            and {'pid': gateway.runner_pid, 'startTicks': process['startTicks']} in job['processes'],
                            'gateway_bound_runner_not_active')
                    response = {'result': {**gateway.session.require_ready(), 'jobId': gateway.job_id}}
                except Exception as exc:
                    # No command arguments, credentials or arbitrary exception
                    # messages are returned across the container boundary.
                    response = {'error': 'gateway_admission_rejected:' + type(exc).__name__}
                wire = json.dumps(response).encode() + b'\n'
                if len(wire) > 65536:
                    wire = b'{"error":"gateway_response_too_large"}\n'
                self.wfile.write(wire)
        class Server(socketserver.ThreadingUnixStreamServer):
            daemon_threads = True
            allow_reuse_address = False
        self.server = Server(str(self.path), Handler)
        os.chmod(self.path, 0o600)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5)
        self.path.unlink(missing_ok=True)
        self.directory.rmdir()


def docker_commands(args, session=None, hold=None):
    local_out = ROOT / relative(args.out)
    remote_stage = str(args.remote_stage)
    require(remote_stage.startswith('/home/achillesjing/dgx-spark-benchmark/results/next-concurrency-')
            and '..' not in Path(remote_stage).parts, 'invalid_new_remote_stage')
    media = ROOT / relative(args.out) / 'inputs' / 'source.mp4'
    map_path, policy = local_out / 'inputs' / 'checkpoint-map.json', local_out / 'inputs' / 'gpu-policy.json'
    output = local_out / 'outputs'
    common = ['docker', 'run', '--rm', '--gpus', 'all', '--network', 'none', '--ipc', 'host',
              '--user', '1000:1000',
              '-e', 'HF_HUB_OFFLINE=1', '-e', 'TRANSFORMERS_OFFLINE=1',
              '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'PATH=/media-tools/bin:/usr/local/bin:/usr/bin:/bin',
              '-e', 'XDG_CACHE_HOME=/tmp/audio-cache', '-e', 'TRITON_CACHE_DIR=/tmp/audio-triton',
              '-e', 'TORCHINDUCTOR_CACHE_DIR=/tmp/audio-inductor',
              '-v', remote_stage + ':' + str(ROOT), '-v', CHECKPOINT + ':/checkpoint:ro',
              '-v', ASR_HUB + ':/asr-hub:ro', '-v', MEDIA_TOOLS + ':/media-tools:ro',
              '-v', BROKER + ':/shared-gpu', '-w', str(ROOT), '--entrypoint', '/usr/bin/python']
    if session is not None:
        common[2:2] = ['--label', 'tongxing.spark.session=' + session.environment['SPARK_EXCLUSIVE_SESSION_ID'],
            '--label', 'tongxing.spark.owner=' + session.environment['SPARK_EXCLUSIVE_SESSION_OWNER'],
            '--label', 'tongxing.spark.job=' + hold['jobId'],
            '-e', 'SPARK_EXCLUSIVE_SESSION_ID=' + session.environment['SPARK_EXCLUSIVE_SESSION_ID'],
            '-e', 'SPARK_EXCLUSIVE_SESSION_OWNER=' + session.environment['SPARK_EXCLUSIVE_SESSION_OWNER'],
            '-e', 'SPARK_EXCLUSIVE_SOCKET=/spark-session-gateway/admission.sock',
            '-v', str(Path('/tmp/tongxing-spark-gateway') / hold['jobId']) + ':/spark-session-gateway:ro']
    worker = 'scripts/experiments/replay_fixed_clip_local_models.py'
    tts = common + [IMAGES['tts'], worker, 'tts', '--diagnostic-fixture', str(args.fixture.resolve()),
        '--diagnostic-candidate', str((args.layer2_out / 'diagnostic-candidate.json').resolve()),
        '--evidence', str((args.layer2_out / 'evidence.json').resolve()), '--media', str(media),
        '--registry', str(args.registry.resolve()), '--checkpoint-map', str(map_path),
        '--out', str(output / 'tts'), '--batch-size', '8', '--replicas', '8', '--cpu-workers', '4',
        '--cpu-queue-units', '16', '--resource-policy', str(policy)]
    asr = common + [IMAGES['asr'], worker, 'asr', '--tts-manifest', str(output / 'tts' / 'manifest.json'),
        '--model-path', ASR_SNAPSHOT, '--out', str(output / 'asr'), '--batch-size', '8',
        '--resource-policy', str(policy)]
    return [tts, asr]


def verify_outputs(root, proof):
    from scripts.experiments import replay_fixed_clip_local_models as worker
    tts = inputs.read(root / 'tts' / 'manifest.json')
    asr = inputs.read(root / 'asr' / 'manifest.json')
    require(tts['mediaSha256'] == proof['sourceMediaSha256']
            and tts['sourceUnitCount'] == proof['sourceUnits']
            and tts['voice']['checkpointSha256'] == proof['checkpointSha256'], 'spark_output_media_or_voice_changed')
    require(tts['diagnosticBinding']['sourceWindow'] == proof['sourceWindow']
            and len(tts['groups']) == len(asr['groups']) == proof['groups']
            and tts['replicas'] == tts['batchSize'] == asr['batchSize'] == 8
            and tts['cpuWorkers'] == 4 and asr['modelReplicas'] == 1
            and asr['ttsManifestSha256'] == inputs.sha(root / 'tts' / 'manifest.json'),
            'spark_output_coverage_or_profile_changed')
    for name, final in (('tts', tts), ('asr', asr)):
        stage = root / name
        run_identity = inputs.read(stage / 'run.json')
        require(final.get('status') == 'completed_diagnostic' and final.get('targetLocale') == proof['targetLocale']
                and all(final.get(k) is False for k in ('humanApproval', 'productionEligible', 'releaseEligible'))
                and all(final.get(k) == value for k, value in run_identity.items()),
                'spark_audio_completion_not_verified')
        selected = ([{k: row[k] for k in ('groupId', 'sourceUnitIds', 'text', 'textSha256')}
                     for row in tts['groups']] if name == 'tts' else tts['groups'])
        rows = []
        for index, start in enumerate(range(0, len(selected), 8)):
            receipt = worker.completed_batch(stage, index, run_identity, selected[start:start + 8])
            require(receipt is not None, 'spark_batch_not_completed')
            rows.extend(receipt['outputs'])
        require(rows == final['groups'], 'spark_manifest_batch_join_changed')
        cleanup, outcome = inputs.read(stage / 'gpu-cleanup.json'), inputs.read(stage / 'resource-outcome.json')
        require(cleanup['identitySha256'] == outcome['identitySha256'] == inputs.digest(run_identity)
                and outcome['manifestSha256'] == inputs.sha(stage / 'manifest.json'),
                'spark_terminal_resource_evidence_changed')
    for row in tts['groups']:
        worker.safe_audio(root / 'tts', row)


REMOTE_RUNNER = '''import fcntl,json,pathlib,subprocess,sys,time,os
c=json.loads(sys.argv[1]);sys.path.insert(0,c['codeRoot'])
os.environ.update(c['sessionEnvironment']);os.environ['SPARK_EXCLUSIVE_REMOTE_LOCAL']='1'
from scripts.spark_exclusive_session import Client
from scripts.experiments.run_spark_diagnostic_audio import AdmissionGateway
session=Client.from_environment();session.require_ready();session.bind_job(c['sparkHold'],pid=os.getpid())
broker=pathlib.Path(c['broker']);broker.mkdir(parents=True,exist_ok=True)
out=pathlib.Path(c['out']);out.mkdir(parents=True,exist_ok=True)
with (broker/'whole-audio-dispatch.lock').open('a') as lock:
 deadline=time.monotonic()+180
 while True:
  try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB);break
  except BlockingIOError:
   if time.monotonic()>=deadline:sys.exit(75)
   time.sleep(.5)
 gateway=AdmissionGateway(c['gatewayDirectory'],session,c['sparkHold'],runner_pid=os.getpid())
 try:
  for stage,argv in zip(('tts','asr'),c['commands']):
   session.require_ready()
   with (out/(stage+'.log')).open('ab') as log:
    result=subprocess.run(argv,stdout=log,stderr=subprocess.STDOUT)
   if result.returncode:sys.exit(result.returncode)
 finally:gateway.close()
'''


def execute(args):
    proof = preflight(args)
    require(proof['status'] == 'ready_for_explicit_dispatch', 'layer2_admission_required_before_spark_dispatch')
    relative(args.fixture); relative(args.layer2_out)
    require(args.registry.resolve() == ROOT / 'config/speaker-voice-registry.json', 'use_frozen_repository_registry')
    # Anchor a cwd-relative --out before any job hold; later paths use relative_to(ROOT).
    args.out = ROOT / relative(args.out)
    args.out.mkdir(parents=True, exist_ok=True)
    from scripts.experiments.replay_fixed_clip_local_models import save
    with (args.out / '.dispatch.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        completed = args.out / 'result.json'
        if completed.exists():
            receipt = inputs.read(completed)
            require(receipt.get('preflight') == proof and receipt.get('status') == 'completed_diagnostic'
                    and receipt['outputs'] == inventory(args.out / 'outputs'), 'spark_completed_result_changed')
            verify_outputs(args.out / 'outputs', proof)
            return receipt
        require(not (args.out / 'dispatch.started.json').exists(), 'unknown_spark_dispatch_requires_reconciliation')
        session = _spark_session(getattr(args, 'spark_session_id', None), getattr(args, 'spark_session_owner', None))
        session.require_ready()
        hold = session.start_job(_session_job_purpose(args.out), pid=os.getpid())
        stage = str(args.remote_stage)
        # Existing staged files are never overwritten. Verify complete content
        # after rsync, so changed old evidence fails before Docker/model load.
        material = args.out / 'inputs'; material.mkdir(exist_ok=True)
        speaker = next(row for row in inputs.read(args.registry)['speakers'] if row['speakerId'] == 'eric_geiger')
        save(material / 'checkpoint-map.json', {'schemaVersion': 'sermon-speaker-checkpoint-map-v1',
            'checkpoints': [{'speakerId': 'eric_geiger', 'checkpointRef': speaker['checkpoint']['checkpointRef'], 'path': '/checkpoint'}]})
        save(material / 'gpu-policy.json', {'schemaVersion': 'sermon-unified-resource-policy-v1',
            'brokerRoot': '/shared-gpu', 'capacities': {'cpu': 4, 'online_api': 0, 'codex_cli': 0, 'spark_tts': 1, 'publisher': 0}})
        paths = [args.fixture.parent / 'pinned-quotes.py', args.fixture.parent / 'pending-quote-draft.json',
                 *[p for p in args.fixture.rglob('*') if p.is_file()],
                 *[p for p in args.layer2_out.rglob('*') if p.is_file() and p.suffix in ('.json', '.py')],
                 material / 'checkpoint-map.json', material / 'gpu-policy.json']
        files = {relative(p): inputs.sha(p) for p in paths if p.exists()}
        media_relative = str((material / 'source.mp4').relative_to(ROOT))
        files[media_relative] = proof['sourceMediaSha256']
        # Code staging must have happened separately after the final freeze.
        staged = run(remote_command(['cat', stage + '/code-stage-manifest.json']), capture_output=True, text=True)
        code = json.loads(staged.stdout)['files']
        require('scripts/experiments/run_spark_diagnostic_audio.py' in code
                and all((ROOT / name).resolve().is_relative_to(ROOT)
                        and (ROOT / name).is_file() and inputs.sha(ROOT / name) == expected
                        for name, expected in code.items()), 'remote_code_differs_from_final_local_snapshot')
        check = 'import json,pathlib,hashlib,sys;m=json.loads(pathlib.Path(sys.argv[1]).read_text());assert all(hashlib.sha256((pathlib.Path(sys.argv[1]).parent/p).read_bytes()).hexdigest()==h for p,h in m["files"].items())'
        run(remote_command(['/usr/bin/python3', '-c', check, stage + '/code-stage-manifest.json']))
        file_list = material / 'input-files.txt'
        file_list.write_text(''.join(name + '\n' for name in files if name != media_relative))
        run(['rsync', '-a', '--ignore-existing', '--relative', '--files-from=' + str(file_list),
             str(ROOT) + '/', HOST + ':' + shlex.quote(stage + '/')])
        remote_media = stage + '/' + media_relative
        run(remote_command(['mkdir', '-p', str(Path(remote_media).parent)]))
        run(['rsync', '-a', '--ignore-existing', str(args.media), HOST + ':' + shlex.quote(remote_media)])
        verify = 'import json,pathlib,hashlib,sys;root=pathlib.Path(sys.argv[1]);files=json.loads(sys.argv[2]);assert all(hashlib.sha256((root/p).read_bytes()).hexdigest()==h for p,h in files.items())'
        run(remote_command(['/usr/bin/python3', '-c', verify, stage, json.dumps(files)]))
        session.require_ready()
        args.gateway_directory = Path('/tmp/tongxing-spark-gateway') / hold['jobId']
        commands = docker_commands(args, session, hold)
        save(args.out / 'dispatch.started.json', {'status': 'started_unknown_until_complete_readback',
            'callId': uuid.uuid4().hex, 'preflight': proof, 'remoteStage': stage, 'stagedInputHashes': files,
            'commandsSha256': inputs.digest(commands), 'productionEligible': False})
        # A failed SSH, lock wait, model, cleanup or copy leaves started intact.
        # The wrapper never releases or retries an uncertain remote GPU owner.
        remote_out = stage + '/' + relative(args.out) + '/outputs'
        run(remote_command(['/usr/bin/python3', '-c', REMOTE_RUNNER, json.dumps(
            {'broker': BROKER, 'out': remote_out, 'commands': commands, 'codeRoot': stage,
             'sessionEnvironment': session.environment, 'sparkHold': hold, 'gatewayDirectory': str(args.gateway_directory)})]))
        run(['rsync', '-a', HOST + ':' + shlex.quote(remote_out + '/'), str(args.out / 'outputs') + '/'])
        verify_outputs(args.out / 'outputs', proof)
        receipt = {'schemaVersion': 'spark-diagnostic-audio-result-v1', 'status': 'completed_diagnostic',
            'preflight': proof, 'remoteStage': stage, 'stagedInputHashes': files,
            'outputs': inventory(args.out / 'outputs'), 'productionEligible': False,
            'humanApproval': False, 'releaseEligible': False, 'apiCalls': 0}
        session.end_job(hold, process_exited=True, outcome='known_terminal')
        save(completed, receipt)
        return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('preflight', 'execute'))
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--layer2-out', type=Path, required=True)
    parser.add_argument('--media', type=Path, required=True)
    parser.add_argument('--registry', type=Path, default=ROOT / 'config/speaker-voice-registry.json')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--remote-stage', type=Path)
    parser.add_argument('--spark-session-id')
    parser.add_argument('--spark-session-owner')
    args = parser.parse_args(argv)
    require(args.mode != 'execute' or (args.out is not None and args.remote_stage is not None),
            'execute_requires_out_and_frozen_remote_stage')
    print(json.dumps(preflight(args) if args.mode == 'preflight' else execute(args), ensure_ascii=False))


if __name__ == '__main__':
    main()
