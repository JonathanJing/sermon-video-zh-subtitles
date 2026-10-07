"""Optional whole-job GPU admission for isolated local audio producers.

TTS and ASR share spark_tts conservatively. Uncertain outcomes remain held;
only a verified durable completed manifest permits release, including recovery.
"""
from pathlib import Path
from scripts.sermon_unified import resources, contracts
from scripts.sermon_execution_harness import atomic_json
from scripts import sermon_workflow_jobs as jobs


def policy_from_path(path):
    return resources.validate_policy(contracts.read(Path(path))) if path is not None else None


def claim(root, identity, policy):
    root=Path(root).resolve()
    return {'schemaVersion':'local-audio-resource-claim-v1',
        'policySha256':contracts.digest(policy),
        'operationId':contracts.digest({'localAudioJob':str(root),'identity':identity}),
        'owner':{'localAudioJob':str(root),'identitySha256':contracts.digest(identity)},
        'resource':'spark_tts','units':1}


def admit(root, identity, policy):
    if policy is None:return
    value=claim(root,identity,policy);path=Path(root)/'resource-claim.json'
    if path.exists():
        if contracts.read(path)!=value:raise contracts.ContractError('local_audio_resource_identity_changed')
    else:
        atomic_json(path,value)
        jobs._sync_directory(Path(root))
    # A duplicate held/released operation is never a second dispatch permission.
    if not resources.reserve(policy,operation_id=value['operationId'],owner=value['owner'],
                             resource=value['resource']):
        raise contracts.ContractError('resource_capacity_busy')


def cleanup_receipt(identity):
    return {'schemaVersion':'local-audio-gpu-cleanup-v1',
            'identitySha256':contracts.digest(identity),'status':'cleanup_completed'}


def record_cleanup(root, identity):
    atomic_json(Path(root)/'gpu-cleanup.json', cleanup_receipt(identity))
    jobs._sync_directory(Path(root))


def require_cleanup(root, identity):
    path=Path(root)/'gpu-cleanup.json'
    if not path.is_file() or contracts.read(path)!=cleanup_receipt(identity):
        raise contracts.ContractError('local_audio_gpu_cleanup_unconfirmed')


def finish(root, identity, policy, manifest):
    if policy is None:return
    root=Path(root);value=claim(root,identity,policy)
    if contracts.read(root/'resource-claim.json')!=value:
        raise contracts.ContractError('local_audio_resource_identity_changed')
    if identity.get('gpuCleanupRequired'):
        require_cleanup(root,identity)
    path=root/'manifest.json';saved=contracts.read(path)
    if saved!=manifest or any(saved.get(k)!=v for k,v in identity.items()) or \
            saved.get('status')!='completed_diagnostic':
        raise contracts.ContractError('local_audio_resource_terminal_unconfirmed')
    outcome={'schemaVersion':'local-audio-resource-outcome-v1',
             'operationId':value['operationId'],'manifestSha256':contracts.file_sha(path),
             'identitySha256':contracts.digest(identity),'status':'completed_diagnostic'}
    result=root/'resource-outcome.json'
    if result.exists():
        if contracts.read(result)!=outcome:raise contracts.ContractError('local_audio_resource_outcome_changed')
    else:atomic_json(result,outcome)
    jobs._sync_directory(root)
    resources.release(policy,operation_id=value['operationId'],owner=value['owner'])
