"""Single-attempt OpenAI API transport for isolated Layer 2 diagnostic fixtures."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import time
import urllib.request

from scripts import run_target_language_models as models
from scripts.codex_layer2_transport import TEST_CONFIGURATION
from scripts.sermon_unified import resources
from scripts.production_concurrency_profile import validate_profile
from scripts.sermon_execution_harness import atomic_json


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


class OpenAILayer2DiagnosticTransport:
    billing = 'api'

    def __init__(self, *, receipts_dir, resource_policy, concurrency_profile,
                 timeout_seconds=180, reuse_receipts_dir=None):
        if os.environ.get('SERMON_OPENAI_ENVIRONMENT') != 'dev' or not os.environ.get('OPENAI_API_KEY'):
            raise ValueError('diagnostic_openai_dev_launcher_required')
        self.project = os.environ.get('OPENAI_PROJECT_ID', '')
        if not self.project.startswith('proj_'):
            raise ValueError('diagnostic_openai_project_required')
        self.key = os.environ['OPENAI_API_KEY']
        self.resource_policy = resources.validate_policy(resource_policy)
        self.profile = validate_profile(concurrency_profile)
        if self.resource_policy['capacities']['online_api'] != self.profile['sourceASRWorkers']:
            raise ValueError('diagnostic_openai_shared_capacity_mismatch')
        self.receipts_dir = Path(receipts_dir)
        self.reuse_receipts_dir = None
        if reuse_receipts_dir is not None:
            raw_reuse = Path(reuse_receipts_dir)
            artifact_root = Path(__file__).resolve().parents[1] / 'artifacts'
            if raw_reuse.is_symlink() or not raw_reuse.is_dir() or not raw_reuse.resolve().is_relative_to(artifact_root):
                raise ValueError('diagnostic_openai_reuse_receipts_must_be_artifacts')
            self.reuse_receipts_dir = raw_reuse.resolve()
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._reserved = {}
        self.execution_identity = {'schemaVersion':'openai-layer2-diagnostic-transport-v1',
            'backend':'openai_api','provider':'openai','authMode':'project_api_key',
            'credentialAlias':'tongxing-dev-runtime','projectId':self.project,
            'simulationModelConfiguration':TEST_CONFIGURATION,
            'concurrencyProfile':self.profile,
            'resourcePolicySha256':resources._identity(self.resource_policy),
            'timeoutSeconds':timeout_seconds}

    def _binding(self, payload):
        fingerprint = _digest({'payload':payload,'executionIdentity':self.execution_identity})
        owner = {'callId':fingerprint,'backend':'openai_api','projectId':self.project}
        return fingerprint,'openai-layer2:'+fingerprint,owner,self.receipts_dir/fingerprint

    def _reused_response(self, fingerprint, payload):
        if self.reuse_receipts_dir is None:
            return None
        source = self.reuse_receipts_dir / fingerprint
        started, completed = source / 'started.json', source / 'response.json'
        if not started.exists() and not completed.exists():
            return None
        if (not started.is_file() or not completed.is_file() or source.is_symlink()
                or started.is_symlink() or completed.is_symlink()):
            raise RuntimeError('diagnostic_openai_prior_call_not_reconciled')
        initial, terminal = json.loads(started.read_text()), json.loads(completed.read_text())
        payload_sha = _digest(payload)
        if initial.get('payloadSha256') != payload_sha or terminal.get('payloadSha256') != payload_sha \
                or initial.get('executionIdentity') != self.execution_identity:
            raise ValueError('diagnostic_openai_prior_response_identity_changed')
        response = terminal.get('response')
        if not isinstance(response, dict):
            raise ValueError('diagnostic_openai_prior_response_invalid')
        models.completed_response_content(response,payload['model'],'diagnostic')
        return response

    def admit_resource(self, payload):
        fingerprint,operation,owner,directory = self._binding(payload)
        with self._lock:
            if fingerprint in self._reserved or (directory/'started.json').exists():
                raise RuntimeError('diagnostic_openai_call_already_started')
        reused = self._reused_response(fingerprint, payload)
        if reused is not None:
            with self._lock:
                self._reserved[fingerprint]=(operation,owner,directory,'reused')
            return
        deadline=time.monotonic()+self.profile['busyWaitSeconds']
        while not resources.reserve(self.resource_policy,operation_id=operation,
                                    owner=owner,resource='online_api'):
            if time.monotonic()>=deadline:
                raise RuntimeError('diagnostic_openai_api_capacity_busy')
            time.sleep(.05)
        with self._lock:
            self._reserved[fingerprint]=(operation,owner,directory,'new')

    def __call__(self, api_key, payload, response_observer=None):
        if api_key or response_observer is not None:
            raise ValueError('diagnostic_openai_transport_owns_credential_and_receipt')
        fingerprint,operation,owner,directory=self._binding(payload)
        with self._lock:
            binding=self._reserved.pop(fingerprint,None)
        if binding not in ((operation,owner,directory,'new'),(operation,owner,directory,'reused')):
            raise RuntimeError('diagnostic_openai_call_not_admitted')
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        atomic_json(directory/'started.json',{'schemaVersion':'openai-layer2-diagnostic-start-v1',
            'payloadSha256':_digest(payload),'executionIdentity':self.execution_identity})
        if binding[-1]=='reused':
            result=self._reused_response(fingerprint,payload)
            if result is None:
                raise RuntimeError('diagnostic_openai_prior_response_missing')
            atomic_json(directory/'response.json',{'schemaVersion':'openai-layer2-diagnostic-response-v1',
                'payloadSha256':_digest(payload),'response':result,'elapsedSeconds':0,
                'timingScope':'reused_prior_response','usageSource':'prior_provider_reported',
                'reusedFrom':str((self.reuse_receipts_dir/fingerprint/'response.json').resolve())})
            return result
        request=urllib.request.Request('https://api.openai.com/v1/chat/completions',
            data=json.dumps(payload,ensure_ascii=False).encode(),method='POST',
            headers={'Authorization':'Bearer '+self.key,'OpenAI-Project':self.project,
                     'Content-Type':'application/json'})
        start=time.monotonic()
        with urllib.request.urlopen(request,timeout=self.timeout_seconds) as response:
            result=json.load(response)
        elapsed=time.monotonic()-start
        atomic_json(directory/'response.json',{'schemaVersion':'openai-layer2-diagnostic-response-v1',
            'payloadSha256':_digest(payload),'response':result,'elapsedSeconds':elapsed,
            'timingScope':'complete_request','usageSource':'provider_reported'})
        models.completed_response_content(result,payload['model'],'diagnostic')
        resources.release(self.resource_policy,operation_id=operation,owner=owner)
        return result

    @staticmethod
    def completed_content(response, model, role):
        return models.completed_response_content(response, model, role)
