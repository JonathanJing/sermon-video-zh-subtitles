#!/usr/bin/env python3
"""Approved partial-group Astra/Sol experiment; never creates a candidate.

Freeze captures the current production prompt constructors without API calls.
Run requires the caller's existing key and explicit --execute. Returned model
responses are private immutable caches; unknown outcomes never gain replay rights.
"""
from __future__ import annotations
import argparse
import copy
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import urllib.request
from unittest.mock import patch

from scripts import produce_target_language_candidate as producer
from scripts import run_target_language_models as production
from scripts import sermon_accounting as accounting
from scripts import sermon_pipeline as pipeline
from scripts import sermon_provider_http as transport
from scripts import sermon_provider_limits as provider_limits
from scripts import target_language_policy as policy_tools
from scripts.experiments import layer2_ab
from scripts.sermon_execution_harness import atomic_json, work_lock

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 'sermon-bounded-layer2-experiment-v1'
LIMITS = {**provider_limits.DEFAULT_REQUEST_LIMITS, 'maxCompletionTokens': 2048}
PRICES = {'gpt-6-astra': {'input': '10', 'cached': '1', 'cacheWrite': '12.5', 'output': '50'},
          'gpt-6-sol': {'input': '2', 'cached': '.2', 'cacheWrite': '2.5', 'output': '10'}}
PRICE_URLS = {model: 'https://developers.openai.com/api/docs/models/' + model for model in PRICES}
CAPS = {'calls': 48, 'callsPerArm': 16, 'inputTokens': 48 * 8192,
        'outputTokens': 48 * 2048, 'costMicrousd': 6_000_000, 'costPerArmMicrousd': 2_000_000}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    production.save_new(Path(path), value, private=True)


def ceiling(value):
    return (value.numerator + value.denominator - 1) // value.denominator


def cost(model, inputs, outputs, *, worst=True):
    rate = PRICES[model]
    return ceiling(Fraction(rate['cacheWrite' if worst else 'input']) * inputs + Fraction(rate['output']) * outputs)


class CaptureComplete(Exception):
    pass


class SemanticFailed(ValueError):
    pass


class UsageFailed(ValueError):
    pass


class BudgetWriteFailed(OSError):
    pass


def persist_budget(path, value):
    try:
        atomic_json(path, value)
        production.jobs._sync_directory_ancestry(path.parent)
    except OSError as exc:
        raise BudgetWriteFailed('Experimental budget durability failed') from exc


def capture_prompts(source, anchor, policy, plan, indices, out, plugin):
    """Use actual group closure and stop before production evidence assembly."""
    request = producer.prepare_request(source, anchor, policy)
    production.group_plan(request, anchor, plan)  # Full coverage unchanged.
    captured = {}
    def fake(role, prompt, active_policy, output, *_args, **_kwargs):
        item = copy.deepcopy(prompt)
        group = prompt['input']
        number = int(output.name.split('-')[1]) - 1
        if role == 'reviewer':
            item['input'].pop('astraDraft')
        captured.setdefault(number, {})[role] = item
        result = {'translationGroupId': group['translationGroupId'], 'sourceUnitIds': group['sourceUnitIds'],
                  'targetUtterances': ['实验占位。'],
                  'coverage': [{'sourceUnitId': unit, 'targetText': '实验占位。'} for unit in group['sourceUnitIds']]}
        if role == 'reviewer':
            result['semanticReview'] = {'status': 'pass', 'checks': {key: 'pass' for key in production.SEMANTIC_CHECKS},
                                       'evidence': 'Offline prompt capture placeholder, no model review.', 'uncertainty': [], 'issues': []}
        return {'requestId': f'offline-{role}-{number}', 'result': result}
    def select(items, worker, workers):
        for index in indices:
            worker(items[index])
        raise CaptureComplete()
    with patch.object(production, '_model_call', fake), patch.object(production, 'ordered_group_results', select):
        try:
            production._run_prepared_groups(request, anchor, policy, out, '',
                lambda *_: (_ for _ in ()).throw(AssertionError('Prompt capture must not call a provider')),
                plan, plugin)
        except CaptureComplete:
            pass
    production.require(set(captured) == set(indices) and not (out / 'evidence.json').exists(), 'Prompt capture incomplete')
    return [{'originalPlanIndex': i, 'group': copy.deepcopy(plan[i]), 'prompts': captured[i]} for i in indices]


def frozen_code():
    names = ('run_target_language_models.py', 'produce_target_language_candidate.py', 'target_language_policy.py',
             'sermon_pipeline.py', 'sermon_accounting.py', 'sermon_provider_http.py', 'sermon_provider_limits.py',
             'sermon_execution_harness.py', 'experiments/layer2_ab.py', 'experiments/benchmark_layer2_bounded.py')
    return {name: digest(ROOT / 'scripts' / name) for name in names}


def freeze(prepared, proposal, out):
    production.require(not out.exists(), 'Use a new experiment directory')
    source, anchor, policy, plan = [read(prepared / name) for name in
        ('source.json', 'anchor.json', 'baseline-policy.json', 'group-plan.json')]
    proposal = read(proposal)
    production.require(policy_tools.canonical_sha256(source) == proposal['englishSourcePackageJsonSha256']
        and policy_tools.canonical_sha256(anchor) == proposal['anchorManifestSha256']
        and policy_tools.canonical_sha256(policy) == proposal['baselinePolicySha256']
        and policy_tools.canonical_sha256(plan) == proposal['fullOriginalGroupPlanSha256'], 'Proposal source/policy/plan changed')
    indices = [row['originalPlanIndex'] for row in proposal['selectedGroups']]
    production.require(len(indices) == 8 and indices == sorted(set(indices)), 'Eight original groups required')
    plugin = Path(read(prepared / 'experiment.json')['plugin']['path'])
    production.require_plugin_identity(plugin, policy['languageReview']['pluginImplementationSha256'])
    for role, model in production.MODEL_ROLES.items():
        production.require(policy[role]['model'] == model and policy[role]['reasoningEffort'] == 'medium', 'Formal medium roles required')
    out.mkdir(parents=True, mode=0o700)
    frozen = out / 'frozen'
    captured = capture_prompts(source, anchor, policy, plan, indices, frozen / 'offline-capture', plugin)
    for name, value in (('source', source), ('anchor', anchor), ('baseline-policy', policy), ('group-plan', plan)):
        save(frozen / (name + '.json'), value)
    # Full source context and policy are preserved; only workers differ.
    policies = {}
    for workers in (1, 2, 3):
        arm_policy = copy.deepcopy(policy)
        arm_policy['batching']['workers'] = workers
        arm_policy['componentSha256']['batching'] = policy_tools.canonical_sha256(arm_policy['batching'])
        producer.prepare_request(source, anchor, arm_policy)
        policies[str(workers)] = arm_policy
    for row in captured:
        production.model_payload('translator', row['prompts']['translator'], policy, LIMITS)
        production.model_payload('reviewer', {**row['prompts']['reviewer'],
            'input': {**row['prompts']['reviewer']['input'], 'astraDraft': {'placeholder': 'actual returned draft checked at dispatch'}}}, policy, LIMITS)
    manifest = {'schemaVersion': SCHEMA, 'experimentOnly': True, 'formalCoverageComplete': False,
        'humanApproval': False, 'releaseEligible': False, 'fullOriginalGroups': len(plan), 'selected': captured,
        'policies': policies, 'requestLimits': LIMITS, 'caps': CAPS, 'code': frozen_code(),
        'inputHashes': {name: digest(frozen / (name + '.json')) for name in ('source', 'anchor', 'baseline-policy', 'group-plan')},
        'plugin': {'path': str(plugin.resolve()), 'implementationSha256': policy['languageReview']['pluginImplementationSha256']},
        'pricing': {'verifiedAt': '2026-10-01', 'ratesUsdPerMillion': PRICES, 'sources': PRICE_URLS,
                    'tier': 'standard/default', 'invoiced': False, 'nativeAccountingSolPrice': 'unknown'},
        'authorization': 'User authorized official Astra/Sol bounded sample using existing config, independent budget and ledger; no repair/retry.',
        'experimentalParameterDifference': 'max_completion_tokens2048 including reasoning; production strict default4096; native non-strict runner may omit explicit cap. Prompts/models/medium preserved.',
        'promptCapture': 'Current production full-plan group closure, exact instructions and original context; reviewer actual astraDraft inserted at runtime.'}
    save(frozen / 'manifest.json', manifest)
    return manifest


def manifest_path(out):
    pointer = out / 'active-experiment.json'
    if not pointer.exists(): return out / 'frozen/manifest.json'
    value = read(pointer)
    production.require(value.get('manifestPath') == 'local-admission-revision/manifest.json', 'Invalid active experiment pointer')
    path = out / value['manifestPath']
    production.require(digest(path) == value['manifestSha256'], 'Active manifest changed')
    return path


def checked(out):
    manifest = read(manifest_path(out))
    selected_limits = manifest['requestLimits']
    production.require(manifest.get('schemaVersion') == SCHEMA and manifest.get('experimentOnly') is True
        and manifest.get('formalCoverageComplete') is False and manifest['caps'] == CAPS
        and {**selected_limits, 'maxInputTokens': LIMITS['maxInputTokens']} == LIMITS
        and selected_limits['maxInputTokens'] in (8192, 16384)
        and manifest['code'] == frozen_code(), 'Frozen experiment/code/caps changed')
    for name, expected in manifest['inputHashes'].items():
        production.require(digest(out / 'frozen' / (name + '.json')) == expected, 'Frozen input bytes changed')
    production.require_plugin_identity(Path(manifest['plugin']['path']), manifest['plugin']['implementationSha256'])
    return manifest


def archive(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    production.jobs._sync_directory_ancestry(path.parent)


def revise_local_input_admission(out, expected_returned_calls=13):
    """One explicitly authorized local bound revision; never reconciles unknowns.

    All old bytes stay immutable. Pending migration is a durable stop until both
    new identity and pointer have been published. Crash recovery never guesses.
    """
    with work_lock(out / 'execution'):
        production.require(not (out / 'active-experiment.json').exists(), 'Local revision already published')
        parent_path = out / 'frozen/manifest.json'; parent = read(parent_path)
        production.require(parent['requestLimits'] == LIMITS and parent['caps'] == CAPS, 'Parent limits changed')
        current_code = frozen_code(); own = 'experiments/benchmark_layer2_bounded.py'
        production.require({k:v for k,v in parent['code'].items() if k != own}
            == {k:v for k,v in current_code.items() if k != own}, 'Production code changed beyond benchmark')
        folder = out / 'local-admission-revision'
        production.require(digest(folder / 'parent-benchmark.py') == parent['code'][own], 'Parent benchmark snapshot missing or changed')
        for name, expected in parent['inputHashes'].items():
            production.require(digest(out / 'frozen' / (name + '.json')) == expected, 'Parent source/policy/plan bytes changed')
        production.require_plugin_identity(Path(parent['plugin']['path']), parent['plugin']['implementationSha256'])
        state = read(out / 'budget-ledger.json')
        production.require(state['identitySha256'] == digest(parent_path) and state['caps'] == CAPS
            and isinstance(state.get('haltReason'), str), 'Parent ledger identity or halt changed')
        rows = state['reservations']
        production.require(len(rows) == expected_returned_calls, 'Unexpected prior call count')
        selected = {f"group-{r['originalPlanIndex']+1:04d}":r for r in parent['selected']}
        unique_ids = set()
        for workers in (1,2,3):
            production.require(not list((out / f'workers-{workers}').glob('*.started.json')), 'Unreconciled marker blocks migration')
        for rid, reservation in rows.items():
            production.require(reservation['status'] == 'response_returned' and reservation.get('usage') is not None
                and reservation.get('estimatedCostUpperBoundMicrousd') is not None, 'Unknown/invalid usage blocks migration')
            workers, stem, suffix = rid.split('.')
            production.require(workers == 'workers-1' and stem in selected and suffix in ('astra','sol'), 'Unexpected prior reservation')
            path = out / workers / (stem + '-' + suffix + '.json'); cached = read(path)
            production.require(reservation['arm']==1 and reservation['rawPath']==str(path.with_suffix('.raw.json').relative_to(out)),
                               'Prior arm/raw path identity changed')
            raw = read(path.with_suffix('.raw.json')); response = raw['response']
            role = 'translator' if suffix == 'astra' else 'reviewer'; policy = parent['policies']['1']
            prompt = copy.deepcopy(selected[stem]['prompts'][role])
            if role == 'reviewer': prompt['input']['astraDraft'] = read(out / workers / (stem + '-astra.json'))['result']
            payload = production.model_payload(role, prompt, policy, LIMITS)
            from scripts.sermon_review_contracts import decode_json
            result = decode_json(production.completed_response_content(response, policy[role]['model'], role).encode())
            production.require(raw['payloadSha256'] == cached['payloadSha256'] == reservation['payloadSha256']
                == policy_tools.canonical_sha256(payload) and cached['model'] == response['model'] == reservation['requestedModel']
                and cached['requestId'] == response['id'] == reservation['requestId'] and cached['result'] == result
                and reservation['usage'] == response['usage'], 'Prior raw/cache/payload/request identity changed')
            normalized = {**accounting.normalize_usage(response['usage']), 'totalTokens': response['usage'].get('total_tokens')}
            observed, _ = provider_limits._observation({'requestedModel': policy[role]['model'], 'providerModel': response['model'],
                'providerUsage': normalized, 'serviceTier': response.get('service_tier'), 'elapsedSeconds': 0})
            production.require(observed is not None and observed['inputTokens'] <= reservation['bounds']['inputTokens']
                and observed['outputTokens'] <= reservation['bounds']['outputTokens']
                and reservation['estimatedCostUpperBoundMicrousd'] == cost(response['model'], observed['inputTokens'], observed['outputTokens'])
                and reservation['bounds'] == {'calls':1, 'inputTokens':provider_limits._input_upper_bound(payload),
                    'outputTokens':2048, 'costMicrousd':cost(response['model'], provider_limits._input_upper_bound(payload),2048)},
                'Prior usage/reservation inconsistent')
            production.require(layer2_ab._validate_group(result, selected[stem]['group'], reviewer=role=='reviewer'), 'Prior semantic validation failed')
            production.require(response['id'] not in unique_ids, 'Prior request IDs duplicate'); unique_ids.add(response['id'])
        failures = list((out / 'workers-1').glob('group-*-failure.json'))
        production.require(len(failures)==1, 'Only one proven local admission pause can be revised')
        failed_path=failures[0]; failed=read(failed_path); stem=failed_path.name.removesuffix('-failure.json')
        production.require(failed['phase']=='reviewer' and failed['errorClass']=='ValueError'
            and state['haltReason'].startswith(stem+':reviewer:') and stem in selected, 'Halt is not the expected local reviewer pause')
        sol=out/'workers-1'/(stem+'-sol.json')
        production.require('workers-1.'+stem+'.astra' in rows, 'Paused reviewer has no prior Astra reservation')
        production.require('workers-1.'+stem+'.sol' not in rows and not sol.exists()
            and not sol.with_suffix('.started.json').exists() and not sol.with_suffix('.raw.json').exists(),
            'Paused reviewer might have been dispatched')
        prompt=copy.deepcopy(selected[stem]['prompts']['reviewer'])
        prompt['input']['astraDraft']=read(out/'workers-1'/(stem+'-astra.json'))['result']
        old_payload=production.model_payload('reviewer',prompt,parent['policies']['1'])
        try: production.model_payload('reviewer',prompt,parent['policies']['1'],LIMITS)
        except ValueError as exc: production.require(str(exc)=='provider_input_bound_exceeded','Pause is not input bound')
        else: raise ValueError('Old input bound does not reproduce pause')
        revised_limits={**LIMITS,'maxInputTokens':16384}
        revised_payload=production.model_payload('reviewer',prompt,parent['policies']['1'],revised_limits)
        original_capped={**old_payload,'max_completion_tokens':2048,'service_tier':'default'}
        production.require(revised_payload==original_capped,'API payload changed by local revision')
        events,damaged=accounting.read_events(out/'workers-1/accounting')
        production.require(not damaged,'Prior accounting damaged')
        active=sum(e['elapsedSeconds'] for e in events if e.get('event')=='stage_finished' and e.get('stage')=='layer2_bounded_experiment')
        archive(folder/'parent-ledger.json',(out/'budget-ledger.json').read_bytes())
        archive(folder/'parent-status.json',(out/'status.json').read_bytes())
        archive(folder/'parent-failure.json',failed_path.read_bytes())
        revised=copy.deepcopy(parent); revised['code']=current_code; revised['requestLimits']=revised_limits
        revised['localAdmissionRevision']={'parentManifestSha256':digest(parent_path),'parentLedgerSha256':digest(folder/'parent-ledger.json'),
            'priorReturnedCalls':len(rows),'priorAccountingActiveSeconds':active,
            'newMaximumConservativeInputTokens':16384,'globalBudgetUnchanged':True,
            'why':'Local admission revision within user-authorized bounded acceptance; preserves total budget and API payload',
            'recoveredBaseline':'workers1 uses original attempt plus resume; do not treat resume wall as uninterrupted16call baseline.'}
        save(folder/'manifest.json',revised)
        record={'schemaVersion':SCHEMA,'experimentOnly':True,'parentManifestSha256':digest(parent_path),
            'newManifestSha256':digest(folder/'manifest.json'),'parentLedgerSha256':digest(folder/'parent-ledger.json'),
            'parentHaltReason':state['haltReason'],'reservationsSha256':policy_tools.canonical_sha256(rows),
            'cachedCallsPreserved':len(rows),'pausedPayloadSha256':policy_tools.canonical_sha256(revised_payload),
            'pausedConservativeInputUpperBound':provider_limits._input_upper_bound(revised_payload),
            'codeChangeAllowedOnly':own,'capsUnchanged':CAPS,'newLocalInputCap':16384}
        save(folder/'revision.json',record)
        state['localAdmissionHistory']=[record]
        state['identitySha256']=digest(folder/'manifest.json'); state['haltReason']='local_admission_revision_pending'
        persist_budget(out/'budget-ledger.json',state)
        save(out/'active-experiment.json',{'manifestPath':'local-admission-revision/manifest.json','manifestSha256':state['identitySha256']})
        state['haltReason']=None; persist_budget(out/'budget-ledger.json',state)
        checked(out)
        return record


class Ledger:
    """Whole matrix lease held by run; thread mutex serializes durable reservations.

    Reservations never refund call/token/cost capacity, including unknowns. Dollar
    caps reserve worst cache-write rates; estimated actual costs stay separate.
    """
    def __init__(self, out, identity, caps=CAPS):
        self.path, self.out, self.lock, self.stop = out / 'budget-ledger.json', out, threading.RLock(), threading.Event()
        self.caps = caps
        if not self.path.exists():
            save(self.path, {'schemaVersion': SCHEMA, 'identitySha256': identity, 'caps': caps, 'reservations': {}, 'haltReason': None})
        state = read(self.path)
        production.require(state['identitySha256'] == identity and state['caps'] == caps, 'Budget identity/caps changed')
        production.require(state['haltReason'] is None, 'Experiment halted; no automatic paid continuation')
        production.require(all(row['status'] == 'response_returned' and row.get('usage') is not None
            and row.get('estimatedCostUpperBoundMicrousd') is not None for row in state['reservations'].values()),
                           'Budget outcome unknown; reconcile before any dispatch')

    def reserve(self, rid, arm, payload, raw_path):
        bounds = {'calls': 1, 'inputTokens': provider_limits._input_upper_bound(payload),
                  'outputTokens': payload['max_completion_tokens']}
        bounds['costMicrousd'] = cost(payload['model'], bounds['inputTokens'], bounds['outputTokens'])
        with self.lock:
            state = read(self.path)
            production.require(not self.stop.is_set() and state['haltReason'] is None, 'Dispatch stopped')
            production.require(rid not in state['reservations'], 'Reservation already exists; never replay')
            all_rows = list(state['reservations'].values())
            own = [row for row in all_rows if row['arm'] == arm]
            for key in ('calls', 'inputTokens', 'outputTokens', 'costMicrousd'):
                production.require(sum(row['bounds'][key] for row in all_rows) + bounds[key] <= self.caps[key], 'Global budget exhausted')
            production.require(len(own) + 1 <= self.caps['callsPerArm'] and
                sum(row['bounds']['costMicrousd'] for row in own) + bounds['costMicrousd'] <= self.caps['costPerArmMicrousd'], 'Arm budget exhausted')
            state['reservations'][rid] = {'arm': arm, 'payloadSha256': policy_tools.canonical_sha256(payload),
                'requestedModel': payload['model'], 'bounds': bounds, 'status': 'request_unconfirmed',
                'rawPath': str(raw_path.relative_to(self.out)), 'usage': None, 'estimatedCostUpperBoundMicrousd': None}
            persist_budget(self.path, state)

    def returned(self, rid, response):
        with self.lock:
            state = read(self.path); row = state['reservations'][rid]
            row['status'] = 'response_returned'; row['requestId'] = response.get('id')
            usage = response.get('usage')
            normalized = {**accounting.normalize_usage(usage),
                          'totalTokens': usage.get('total_tokens') if isinstance(usage, dict) else None}
            observed, _ = provider_limits._observation({'providerModel': response.get('model'),
                'requestedModel': row['requestedModel'], 'providerUsage': normalized,
                'elapsedSeconds': 0, 'serviceTier': response.get('service_tier')})
            valid = observed is not None and response.get('model') == row['requestedModel']
            if valid:
                row['usage'] = copy.deepcopy(usage)
                row['estimatedCostUpperBoundMicrousd'] = cost(row['requestedModel'], usage['prompt_tokens'], usage['completion_tokens'])
                valid = usage['prompt_tokens'] <= row['bounds']['inputTokens'] and usage['completion_tokens'] <= row['bounds']['outputTokens']
            if not valid:
                row['status'] = 'invalid_usage'
                state['haltReason'] = state['haltReason'] or 'invalid_usage'
                self.stop.set()
            persist_budget(self.path, state)
            if not valid: raise UsageFailed('Missing/invalid/excess provider usage; keep reservation and stop')

    def halt(self, reason):
        self.stop.set()
        with self.lock:
            state = read(self.path)
            state['haltReason'] = state['haltReason'] or reason
            persist_budget(self.path, state)


def official_call(key, payload, observer):
    # Same production URL/request construction and telemetry, single bounded
    # subprocess transport: no retries, redirects, proxies, or error bodies.
    request = urllib.request.Request(pipeline.CHAT_URL, data=json.dumps(payload).encode(),
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
    request.accounting_model = payload['model']
    request.accounting_settings = accounting.request_metadata(payload)
    return pipeline.request_json(request, retries=1, response_observer=observer,
        request_executor=lambda req: transport.execute(req, LIMITS['wallTimeMs'] / 1000))


def run_arm(out, manifest, workers, key, ledger, caller=official_call):
    arm = out / f'workers-{workers}'; arm.mkdir(exist_ok=True, mode=0o700)
    production.require_reconciled_requests(arm)
    policy = manifest['policies'][str(workers)]
    limits = manifest['requestLimits']
    source, anchor = [read(out / 'frozen' / (name + '.json')) for name in ('source', 'anchor')]
    request = producer.prepare_request(source, anchor, policy)
    began = time.perf_counter()
    with accounting.accounting_session(arm / 'accounting', 'layer2_bounded_experiment', evidence_directory=arm):
        with accounting.stage('experiment.source_admission', executor_type='deterministic_program') as source_span:
            accounting.record_workload('partial_groups', {'selectedGroups': 8, 'fullOriginalGroups': manifest['fullOriginalGroups'], 'workers': workers})
        def process(row):
            index, group = row['originalPlanIndex'], row['group']
            stem = f'group-{index + 1:04d}'
            phase = 'prepare'
            try:
                production.require(not ledger.stop.is_set(), 'Dispatch stopped')
                with accounting.stage(f'experiment.group.{stem}', billing='orchestrator'):
                    translated = None; previous = source_span
                    for role, suffix in (('translator', 'astra'), ('reviewer', 'sol')):
                        phase = role
                        prompt = copy.deepcopy(row['prompts'][role])
                        if role == 'reviewer':
                            prompt['input']['astraDraft'] = translated['result']
                        path = arm / f'{stem}-{suffix}.json'
                        payload = production.model_payload(role, prompt, policy, limits)
                        cached = path.exists() or path.with_suffix('.raw.json').exists()
                        rid = f'workers-{workers}.{stem}.{suffix}'
                        def measured(api_key, dispatched, *, response_observer):
                            production.require(not ledger.stop.is_set(), 'Dispatch stopped')
                            ledger.reserve(rid, workers, dispatched, path.with_suffix('.raw.json'))
                            return caller(api_key, dispatched, response_observer)
                        def observe(response, attempt_id, elapsed):
                            save(path.with_suffix('.raw.json'), {'payloadSha256': policy_tools.canonical_sha256(payload), 'response': response})
                            save(path.with_suffix('.timing.json'), {'apiAttemptId': attempt_id, 'elapsedSeconds': elapsed, 'cached': False})
                            ledger.returned(rid, response)
                        with accounting.stage(f'experiment.{role}.{stem}', cache_hit=cached,
                                billing='local' if cached else 'api', depends_on=[previous],
                                work_unit_id=f'{stem}.{role}', executor_type='deterministic_program' if cached else 'production_model') as span:
                            result = production._model_call(role, prompt, policy, path, key, measured,
                                response_observer=observe, request_limits=limits)
                        phase = role + '_validation'
                        with accounting.stage(f'experiment.{phase}.{stem}', depends_on=[span],
                                executor_type='deterministic_program') as previous:
                            raw = read(path.with_suffix('.raw.json'))
                            from scripts.sermon_review_contracts import decode_json
                            raw_result = decode_json(production.completed_response_content(raw['response'], policy[role]['model'], role).encode())
                            production.require(raw['payloadSha256'] == policy_tools.canonical_sha256(payload)
                                and result['requestId'] == raw['response']['id'] and result['result'] == raw_result,
                                'Cached response changed from returned raw envelope')
                            if not layer2_ab._validate_group(result['result'], group, reviewer=role == 'reviewer'):
                                raise SemanticFailed('Independent review flagged group')
                        if role == 'translator': translated = result
                        else: reviewed = result
                    final = {**copy.deepcopy(group), 'targetUtterances': reviewed['result']['targetUtterances'],
                        'coverage': reviewed['result']['coverage'], 'semanticReview': production.normalize_semantic_review(reviewed['result']['semanticReview']),
                        'translatorRequestId': translated['requestId'], 'reviewerRequestId': reviewed['requestId']}
                    # Run actual pinned plugin against complete unchanged request,
                    # but one selected group; wrap receipt as experiment-only.
                    phase = 'language_plugin'
                    receipt = producer.run_language_plugin(source, anchor, policy, request, {**request, 'groups': [final]},
                        Path(manifest['plugin']['path']), manifest['plugin']['implementationSha256'])
                    save_or_check(arm / f'{stem}-plugin.json', {'experimentOnly': True, 'formalCoverageComplete': False, 'receipt': receipt})
                    if not all(r['status'] == 'pass' for r in receipt['groupReviews']):
                        raise SemanticFailed('Language plugin rejected group')
                    return final, previous
            except BaseException as exc:
                if isinstance(exc, SemanticFailed): category = 'semantic_failed'
                elif isinstance(exc, (UsageFailed, BudgetWriteFailed, accounting.AccountingWriteError)): category = 'budget_or_accounting_failed'
                elif isinstance(exc, pipeline.TransportRejection): category = 'request_rejected'
                elif phase in ('translator', 'reviewer'):
                    raw = arm / f"{stem}-{'astra' if phase == 'translator' else 'sol'}.raw.json"
                    category = 'response_validation_failed' if raw.exists() else 'request_outcome_unknown_or_not_dispatched'
                else: category = 'validation_failed'
                ledger.halt(f'{stem}:{phase}:{category}:{type(exc).__name__}')
                save_or_check(arm / f'{stem}-failure.json', {'experimentOnly': True, 'phase': phase,
                    'failureCategory': category, 'errorClass': type(exc).__name__})
                raise
        results = production.ordered_group_results(manifest['selected'], process, workers)
        spans = accounting.bounded_dependencies('experiment.partial_join', [span for _, span in results], work_unit_id='experiment.partial_join')
        with accounting.stage('experiment.partial_assembly', depends_on=spans, executor_type='deterministic_program'):
            groups = [row for row, _ in results]
            ids = [row[role + 'RequestId'] for row in groups for role in ('translator', 'reviewer')]
            production.require(len(ids) == len(set(ids)), 'Request IDs reused across groups or roles')
            result = {'schemaVersion': SCHEMA, 'experimentOnly': True, 'formalCoverageComplete': False,
                'humanApproval': False, 'releaseEligible': False, 'workers': workers, 'selectedGroupCount': len(groups),
                'fullOriginalGroups': manifest['fullOriginalGroups'], 'groups': groups,
                'wallSeconds': time.perf_counter() - began, 'sourceRequestSha256': policy_tools.canonical_sha256(request),
                'policySha256': policy_tools.canonical_sha256(policy)}
            revision=manifest.get('localAdmissionRevision') if workers==1 else None
            result['recoveredBaseline']=revision is not None
            result['wallScope']=(f"resume_with_cached{revision['priorReturnedCalls']}calls_and{len(groups)*2-revision['priorReturnedCalls']}newcalls"
                                 if revision else 'fresh_selected_groups_arm')
            if revision:
                result['originalAttemptAccountingActiveSeconds']=revision['priorAccountingActiveSeconds']
                result['activeSegmentSumSeconds']=revision['priorAccountingActiveSeconds']+result['wallSeconds']
                result['activeSegmentSumIsUninterruptedWall']=False
            save_or_check(arm / 'partial-results.json', result)
    return result


def save_or_check(path, value):
    if path.exists(): production.require(read(path) == value, 'Saved experimental artifact changed')
    else: save(path, value)


def run(out, key, caller=official_call):
    production.require(not any(os.environ.get(k) for k in (*accounting.ENV_KEYS, accounting.WORKFLOW_ENV)),
                       'Independent experimental accounting requires no inherited accounting session')
    with work_lock(out / 'execution'):
        manifest = checked(out)
        for workers in (1, 2, 3): production.require_reconciled_requests(out / f'workers-{workers}')
        ledger = Ledger(out, digest(manifest_path(out)))
        rows = []
        try:
            for workers in (1, 2, 3):
                path = out / f'workers-{workers}/partial-results.json'
                rows.append(read(path) if path.exists() else run_arm(out, manifest, workers, key, ledger, caller))
        except BaseException as exc:
            atomic_json(out / 'status.json', {'schemaVersion': SCHEMA, 'experimentOnly': True,
                'status': 'stopped', 'completedArms': len(rows), 'errorClass': type(exc).__name__, 'noAutomaticRetry': True})
            raise
        state = read(ledger.path)
        result = {'schemaVersion': SCHEMA, 'experimentOnly': True, 'status': 'completed',
            'formalCoverageComplete': False, 'humanApproval': False, 'releaseEligible': False,
            'arms': [{'workers': row['workers'], 'wallSeconds': row['wallSeconds'], 'groups': len(row['groups']),
                'recoveredBaseline':row['recoveredBaseline'],'wallScope':row['wallScope'],
                **({k:row[k] for k in ('originalAttemptAccountingActiveSeconds','activeSegmentSumSeconds','activeSegmentSumIsUninterruptedWall')} if row['recoveredBaseline'] else {})} for row in rows],
            'apiCallsReserved': len(state['reservations']), 'reservedCostMicrousd': sum(r['bounds']['costMicrousd'] for r in state['reservations'].values()),
            'estimatedCostUpperBoundWorstCacheWriteMicrousd': sum(r['estimatedCostUpperBoundMicrousd'] for r in state['reservations'].values()),
            'costIsInvoice': False, 'pricing': manifest['pricing']}
        atomic_json(out / 'status.json', result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('freeze'); prepare.add_argument('--prepared', type=Path, required=True)
    prepare.add_argument('--proposal', type=Path, required=True); prepare.add_argument('--out-dir', type=Path, required=True)
    execute = sub.add_parser('run'); execute.add_argument('--out-dir', type=Path, required=True)
    execute.add_argument('--env-file', type=Path); execute.add_argument('--execute', action='store_true')
    revise=sub.add_parser('revise-local-input-admission',help='Explicitly authorized known local pause only; no API calls')
    revise.add_argument('--out-dir',type=Path,required=True)
    args = parser.parse_args()
    if args.command == 'freeze':
        result = freeze(args.prepared, args.proposal, args.out_dir)
        print(json.dumps({'status': 'frozen', 'groups': len(result['selected']), 'apiCalls': 0, 'caps': result['caps']}))
    elif args.command=='revise-local-input-admission':
        print(json.dumps(revise_local_input_admission(args.out_dir)))
    else:
        production.require(args.execute, 'Explicit --execute required')
        if args.env_file: pipeline.load_env(args.env_file)
        key = os.environ.get('OPENAI_API_KEY', '').strip()
        production.require(bool(key), 'Existing OPENAI_API_KEY is not configured')
        try:
            print(json.dumps(run(args.out_dir, key)))
        except Exception as exc:
            print(json.dumps({'status': 'stopped', 'errorClass': type(exc).__name__, 'inspectPrivateArtifacts': True}))
            raise SystemExit(1) from None


if __name__ == '__main__': main()
