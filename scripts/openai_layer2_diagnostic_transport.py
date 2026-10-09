"""Single-attempt OpenAI API transport for isolated Layer 2 diagnostic fixtures."""
from __future__ import annotations

import hashlib
import fcntl
import json
import os
from pathlib import Path
import threading
import time
import urllib.request

from scripts import run_target_language_models as models
from scripts import sermon_provider_limits as provider_limits
from scripts.codex_layer2_transport import API_LUNA_TEST_CONFIGURATION
from scripts.sermon_unified import resources
from scripts.production_concurrency_profile import validate_profile
from scripts.sermon_execution_harness import atomic_json


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


class OpenAILayer2DiagnosticTransport:
    billing = 'api'

    def __init__(self, *, receipts_dir, resource_policy, concurrency_profile,
                 budget_config_path, simulation_model_configuration=API_LUNA_TEST_CONFIGURATION,
                 fixture_manifest_sha256,
                 timeout_seconds=180, reuse_receipts_dir=None):
        if os.environ.get('SERMON_OPENAI_ENVIRONMENT') != 'dev' or not os.environ.get('OPENAI_API_KEY'):
            raise ValueError('diagnostic_openai_dev_launcher_required')
        self.project = os.environ.get('OPENAI_PROJECT_ID', '')
        if not self.project.startswith('proj_'):
            raise ValueError('diagnostic_openai_project_required')
        self.key = os.environ['OPENAI_API_KEY']
        if simulation_model_configuration != API_LUNA_TEST_CONFIGURATION:
            raise ValueError('diagnostic_openai_model_configuration_not_authorized')
        self.model_configuration = simulation_model_configuration
        self.budget_config_path = Path(budget_config_path).resolve()
        self.budget_config = json.loads(self.budget_config_path.read_text())
        if (type(self.budget_config) is not dict
                or set(self.budget_config) != {'schemaVersion', 'maxRequests', 'hardLimitMicrousd', 'requestLimits',
                                               'fixtureManifestSha256', 'authorizationRef'}
                or self.budget_config['schemaVersion'] != 'openai-layer2-diagnostic-budget-v1'
                or type(self.budget_config['maxRequests']) is not int
                or self.budget_config['maxRequests'] != 26
                or type(self.budget_config['hardLimitMicrousd']) is not int
                or self.budget_config['hardLimitMicrousd'] != 40_000_000
                or self.budget_config['requestLimits'] != {
                    'schemaVersion': provider_limits.SCHEMA, 'maxInputTokens': 16384,
                    'maxCompletionTokens': 4096, 'wallTimeMs': 300000, 'serviceTier': 'default'}
                or not isinstance(self.budget_config['fixtureManifestSha256'], str)
                or len(self.budget_config['fixtureManifestSha256']) != 64
                or self.budget_config['fixtureManifestSha256'] != fixture_manifest_sha256
                or self.budget_config['authorizationRef'] != 'user-approved-2026-10-08-usd-40'):
            raise ValueError('diagnostic_openai_budget_binding_invalid')
        provider_limits.validate_request_limits(self.budget_config['requestLimits'])
        self.budget_ledger_path = self.budget_config_path.with_name('budget-ledger.json')
        self.budget_lock_path = self.budget_config_path.with_name('.budget-ledger.lock')
        self._budget_identity = _digest(self.budget_config)
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
        self._active_calls = 0
        self._peak_active_calls = 0
        self._request_count = 0
        self._elapsed_seconds = []
        self.execution_identity = {'schemaVersion':'openai-layer2-diagnostic-transport-v1',
            'backend':'openai_api','provider':'openai','authMode':'project_api_key',
            'credentialAlias':'tongxing-dev-runtime','projectId':self.project,
            'simulationModelConfiguration':self.model_configuration,
            'concurrencyProfile':self.profile,
            'resourcePolicySha256':resources._identity(self.resource_policy),
            'budgetConfigSha256':self._budget_identity,
            'budgetHardLimitMicrousd':self.budget_config['hardLimitMicrousd'],
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
        if payload.get('model') not in {row['model'] for row in self.model_configuration.values() if type(row) is dict}:
            raise ValueError('diagnostic_openai_model_not_in_frozen_configuration')
        bounded_payload = provider_limits.bounded_payload(payload, self.budget_config['requestLimits'])
        bound = provider_limits.request_bounds(bounded_payload, self.budget_config['requestLimits'])
        fingerprint,operation,owner,directory = self._binding(bounded_payload)
        with self._lock:
            if fingerprint in self._reserved or (directory/'started.json').exists():
                raise RuntimeError('diagnostic_openai_call_already_started')
        reused = self._reused_response(fingerprint, bounded_payload)
        if reused is not None:
            with self._lock:
                self._reserved[fingerprint]=(operation,owner,directory,'reused',bounded_payload,bound)
            return
        deadline=time.monotonic()+self.profile['busyWaitSeconds']
        while not resources.reserve(self.resource_policy,operation_id=operation,
                                    owner=owner,resource='online_api'):
            if time.monotonic()>=deadline:
                raise RuntimeError('diagnostic_openai_api_capacity_busy')
            time.sleep(.05)
        try:
            self._reserve_budget(fingerprint, bounded_payload, bound)
            with self._lock:
                self._reserved[fingerprint]=(operation,owner,directory,'new',bounded_payload,bound)
        except Exception:
            resources.release(self.resource_policy,operation_id=operation,owner=owner)
            raise

    def _reserve_budget(self, fingerprint, payload, bound):
        self.budget_lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.budget_lock_path.open('a+') as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            if self.budget_ledger_path.exists():
                ledger=json.loads(self.budget_ledger_path.read_text())
                if ledger.get('budgetConfigSha256') != self._budget_identity or type(ledger.get('reservations')) is not dict:
                    raise ValueError('diagnostic_openai_budget_ledger_identity_changed')
            else:
                ledger={'schemaVersion':'openai-layer2-diagnostic-budget-ledger-v1',
                        'budgetConfigSha256':self._budget_identity,'reservations':{}}
            rows=ledger['reservations']
            if fingerprint in rows:
                raise RuntimeError('diagnostic_openai_budget_request_already_reserved')
            if len(rows) >= self.budget_config['maxRequests']:
                raise RuntimeError('diagnostic_openai_budget_request_cap')
            spent=sum(row['reservedMicrousd'] for row in rows.values())
            if spent + bound['costMicrousd'] > self.budget_config['hardLimitMicrousd']:
                raise RuntimeError('diagnostic_openai_budget_hard_cap')
            rows[fingerprint]={'status':'reserved','model':payload['model'],
                'payloadSha256':_digest(payload),'reservedMicrousd':bound['costMicrousd'],
                'inputUpperBound':bound['inputTokens'],'outputTokenCap':bound['outputTokens']}
            atomic_json(self.budget_ledger_path,ledger)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _settle_budget(self, fingerprint, *, status, usage=None):
        with self.budget_lock_path.open('a+') as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            ledger=json.loads(self.budget_ledger_path.read_text())
            row=ledger['reservations'].get(fingerprint)
            if not isinstance(row,dict) or row.get('status') != 'reserved':
                raise ValueError('diagnostic_openai_budget_reservation_missing')
            row['status']=status
            if usage is not None:
                row['providerUsage']=usage
            atomic_json(self.budget_ledger_path,ledger)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def __call__(self, api_key, payload, response_observer=None):
        if api_key or response_observer is not None:
            raise ValueError('diagnostic_openai_transport_owns_credential_and_receipt')
        bounded_payload = provider_limits.bounded_payload(payload, self.budget_config['requestLimits'])
        fingerprint,operation,owner,directory=self._binding(bounded_payload)
        with self._lock:
            binding=self._reserved.pop(fingerprint,None)
        if binding is None or binding[:4] not in ((operation,owner,directory,'new'),(operation,owner,directory,'reused')):
            raise RuntimeError('diagnostic_openai_call_not_admitted')
        _,_,_,kind,_,bound=binding
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        atomic_json(directory/'started.json',{'schemaVersion':'openai-layer2-diagnostic-start-v1',
            'payloadSha256':_digest(bounded_payload),'executionIdentity':self.execution_identity,
            'budgetReservationMicrousd':bound['costMicrousd'],'requestStartedAtUnix':time.time()})
        if kind=='reused':
            result=self._reused_response(fingerprint,bounded_payload)
            if result is None:
                raise RuntimeError('diagnostic_openai_prior_response_missing')
            atomic_json(directory/'response.json',{'schemaVersion':'openai-layer2-diagnostic-response-v1',
                'payloadSha256':_digest(bounded_payload),'response':result,'elapsedSeconds':0,
                'timingScope':'reused_prior_response','usageSource':'prior_provider_reported',
                'reusedFrom':str((self.reuse_receipts_dir/fingerprint/'response.json').resolve())})
            return result
        request=urllib.request.Request('https://api.openai.com/v1/chat/completions',
            data=json.dumps(bounded_payload,ensure_ascii=False).encode(),method='POST',
            headers={'Authorization':'Bearer '+self.key,'OpenAI-Project':self.project,
                     'Content-Type':'application/json'})
        start=time.monotonic()
        with self._lock:
            self._active_calls += 1
            self._peak_active_calls=max(self._peak_active_calls,self._active_calls)
            self._request_count += 1
        response_received=False
        try:
            with urllib.request.urlopen(request,timeout=self.timeout_seconds) as response:
                result=json.load(response)
            elapsed=time.monotonic()-start
            self._settle_budget(fingerprint,status='response_received',usage=result.get('usage'))
            response_received=True
            atomic_json(directory/'response.json',{'schemaVersion':'openai-layer2-diagnostic-response-v1',
                'payloadSha256':_digest(bounded_payload),'response':result,'elapsedSeconds':elapsed,
                'timingScope':'complete_request','usageSource':'provider_reported',
                'budgetReservationMicrousd':bound['costMicrousd'],'responseReceivedAtUnix':time.time()})
            models.completed_response_content(result,bounded_payload['model'],'diagnostic')
            with self._lock:
                self._elapsed_seconds.append(elapsed)
            return result
        except Exception:
            if not response_received:
                self._settle_budget(fingerprint,status='outcome_unknown')
            raise
        finally:
            with self._lock:
                self._active_calls -= 1
            resources.release(self.resource_policy,operation_id=operation,owner=owner)

    def concurrency_report(self):
        with self._lock:
            ledger=json.loads(self.budget_ledger_path.read_text()) if self.budget_ledger_path.exists() else None
            reservations=ledger['reservations'] if ledger else {}
            return {'requestCount':self._request_count,'maxConcurrentRequests':self._peak_active_calls,
                    'elapsedSeconds':list(self._elapsed_seconds), 'reservedMicrousd':sum(
                        row['reservedMicrousd'] for row in reservations.values()),
                    'budgetRows':len(reservations),
                    'unknownRequests':sum(row.get('status')=='outcome_unknown' for row in reservations.values()),
                    'timingScope':'complete_request_wall_time'}

    @staticmethod
    def completed_content(response, model, role):
        return models.completed_response_content(response, model, role)
