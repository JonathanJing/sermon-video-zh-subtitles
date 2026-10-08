"""Data-only continuation materialization; dispatch and owner CAS stay in runtime.

No producer, approval writer, model, subprocess or budget-reservation operation is
called here. A ready result is preparation, never permission to skip admission.
"""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import re
import tempfile

from scripts.sermon_unified import contracts as c
from scripts.sermon_unified import runtime
from scripts.sermon_unified import adapters
from scripts import sermon_unified_reviews as reviews

SCHEMA = 'sermon-unified-continuation-recipe-v1'
RECIPE_BINDING = 'continuationRecipe'
ADAPTERS = {'source.prepare', 'canonical.layer2', 'canonical.audio', 'canonical.inspect',
            'review.gate', 'study.produce', 'app.delivery'}
ROLES = {'source_candidate': 'source.prepare', 'source_anchor': 'source.prepare',
         'source_transcript': 'source.prepare', 'target_candidate': 'canonical.layer2',
         'audio_package': 'canonical.audio', 'render_manifest': 'canonical.audio',
         'study_artifact': 'study.produce', 'original_review_receipt': 'review.gate'}
NAME = re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,79}$')
FIELDS = {'path', 'sha256', 'jsonSha256'}
FORBIDDEN = {'command', 'shell', 'exec', 'eval', 'import', 'module', 'script', 'python', 'argv'}


def require(condition, message):
    if not condition:
        raise c.ContractError('continuation_' + message)


def _template(value, stage):
    if isinstance(value, dict):
        special = [k for k in value if k.startswith('$')]
        if special:
            tag = special[0]
            require(len(special) == 1 and tag in {'$port', '$binding', '$config', '$output'}, 'template_token_invalid')
            require(set(value) == ({tag} if tag == '$output' else {tag, 'field'}), 'template_token_invalid')
            require(isinstance(value[tag], str) and NAME.fullmatch(value[tag]), 'template_name_invalid')
            if tag != '$output': require(value['field'] in FIELDS, 'template_field_invalid')
            if tag == '$port': require(value[tag] in stage['ports'], 'port_missing')
            if tag == '$config': require(value[tag] in stage['configs'], 'config_missing')
            return
        for key, child in value.items():
            require(key.lower() not in FORBIDDEN, 'executable_template_forbidden')
            if 'executable' in key.lower():
                require(key == 'mfa_executable' and child in (None, 'mfa'), 'executable_template_forbidden')
            _template(child, stage)
    elif isinstance(value, list):
        for child in value: _template(child, stage)
    elif isinstance(value, str):
        # Paths and URLs must come from a verified typed port/binding. No string
        # interpolation or path concatenation exists in this grammar.
        require(not any(x in value for x in ('/', '\\', '://', '${', '$(', '`'))
                and value not in {'.', '..'} and not value.startswith('~'), 'literal_locator_forbidden')


def inspect_recipe(recipe_path):
    path = Path(recipe_path).absolute()
    recipe = c.read(path)
    c.validate(recipe, SCHEMA)
    seen, revisions = set(), set()
    for stage in recipe['stages']:
        require(stage['id'] not in seen and stage['afterRunRevision'] not in revisions, 'duplicate_stage')
        seen.add(stage['id']); revisions.add(stage['afterRunRevision'])
        require(all(port['role'] in ROLES for port in stage['ports'].values()), 'unsupported_port')
        require(not ({'manifest','continuation-receipt'} & set(stage['configs'])), 'reserved_config_name')
        for config in stage['configs'].values():
            require(config['adapter'] in ADAPTERS, 'unsupported_adapter')
            _template(config['template'], stage)
        _template(stage['manifestTemplate'], stage)
        require(set(stage['manifestTemplate']) <= {'activeScope', 'steps', 'bindings'}, 'manifest_identity_override')
        for step in stage['manifestTemplate']['steps']:
            require(step.get('adapter') in ADAPTERS, 'unsupported_adapter')
        for slot in stage['requiredEvidence']:
            _template(slot.get('inputs', {}), stage)
        require(len({s['binding'] for s in stage['requiredEvidence']}) == len(stage['requiredEvidence']), 'duplicate_evidence_slot')
    return {'schemaVersion': SCHEMA, 'recipe': recipe, 'path': str(path), 'sha256': c.file_sha(path),
            'jsonSha256': c.digest(recipe), 'supportedPorts': sorted(ROLES)}


def _artifact(path, *, sha=None, json_sha=None):
    path = Path(path).absolute()
    actual = c.file_sha(path)
    require(sha is None or actual == sha, 'artifact_hash_changed')
    value = c.read(path)
    digest = c.digest(value)
    require(json_sha is None or digest == json_sha, 'artifact_json_changed')
    return {'path': str(path), 'sha256': actual, 'jsonSha256': digest}


def _source(package, manifest):
    from scripts.sermon_unified_audio import source_identity
    reviews.schema(package, 'sermon-english-source-package-v1.schema.json')
    actual, expected = source_identity(package), manifest['source']
    require(all(actual.get(k) == expected.get(k) for k in ('sourceId', 'sourceUrlHash', 'mediaSha256', 'durationSeconds'))
            and all(actual['window'].get(k) == expected['window'].get(k) for k in
                    ('startSeconds', 'endSeconds', 'timeBase', 'approvalReceiptSha256')), 'source_identity_changed')


def _port(state, port, root):
    manifest = state['manifest']; sid = port['stepId']; role = port['role']
    step = next((s for s in manifest['steps'] if s['id'] == sid), None)
    row = state['steps'].get(sid, {})
    require(step is not None and step['adapter'] == ROLES[role], 'port_adapter_changed')
    if row.get('process') != 'succeeded': return None
    require(runtime.reusable_evidence(root, state['runKey'], state, step), 'upstream_evidence_changed')
    folder = runtime.folder(root, state['runKey'])
    if role == 'original_review_receipt':
        recorded = state['reviews'][sid]
        path = folder / ('review-' + recorded['originalSha256'] + '.json')
        # Historical review storage normalizes JSON. It must not be labelled as
        # the original bytes. Root trusted-ingest may retain the original path.
        original = recorded.get('originalPath')
        if original:
            return _artifact(original, sha=recorded['originalSha256'])
        if c.file_sha(path) == recorded['originalSha256']:
            return _artifact(path, sha=recorded['originalSha256'])
        raise c.ContractError('continuation_original_review_bytes_unavailable')
    origin = manifest
    if row.get('reusedFromRevision'):
        origin = c.read(folder / ('revision-' + str(row['reusedFromRevision']) + '.json'))['manifest']
    original_step = next(s for s in origin['steps'] if s['id'] == sid)
    response_path = folder / ('response-' + c.digest(c.job_identity(origin, original_step)) + '.json')
    require(c.file_sha(response_path) == row['responseSha256'], 'response_changed')
    response = c.read(response_path)
    require(response['identity'] == c.job_identity(origin, original_step), 'response_identity_changed')
    result = response['result']
    if role.startswith('source_'):
        source_path = Path(result['candidatePath'])
        package = c.read(source_path)
        _source(package, manifest)
        require(c.digest(package) == result['candidateSha256'], 'source_candidate_changed')
        if role == 'source_candidate': return _artifact(source_path, json_sha=result['candidateSha256'])
        ref = package['anchors' if role == 'source_anchor' else 'transcript']['artifact']
        return _artifact(source_path.parent / ref['path'], sha=ref['sha256'], json_sha=ref['jsonSha256'])
    if role == 'target_candidate':
        from scripts import canonical_layer2_controller as ctl
        config = ctl.load_configuration(adapters.config_path(manifest, '/', step))
        path = config.lanes[step['locale']]['candidate']
        value = c.read(path)
        reviews.schema(value, 'sermon-target-language-candidate-v2.schema.json')
        require(value['targetLocale'] == step['locale'], 'candidate_locale_changed')
        return _artifact(path, json_sha=result['candidateJsonSha256'])
    if role in {'audio_package', 'render_manifest'}:
        ref = result['audioPackage' if role == 'audio_package' else 'renderManifest']
        return _artifact(ref['path'], sha=ref['sha256'], json_sha=ref.get('jsonSha256'))
    return _artifact(result['path'], sha=result['sha256'], json_sha=result['jsonSha256'])


def _reference(state, name):
    manifest = state['manifest']
    row = manifest.get('bindings', {}).get(name) or state.get('continuationEvidence', {}).get(name)
    if row is None: return None
    require(isinstance(row, dict) and {'path', 'sha256'} <= set(row), 'evidence_reference_invalid')
    path = Path(row['path']).absolute()
    require(c.file_sha(path) == row['sha256'], 'binding_changed')
    # Media bindings may be binary; only ask for canonical JSON when requested.
    return {'path': str(path), 'sha256': row['sha256']}


class Missing(Exception):
    pass


def _resolve(value, *, ports, bindings, configs, directory, draft=False):
    if isinstance(value, dict):
        for tag, table in (('$port', ports), ('$binding', bindings), ('$config', configs)):
            if tag in value:
                ref = table.get(value[tag])
                if ref is None:
                    if draft: return value
                    raise Missing(value[tag])
                if value['field'] == 'jsonSha256' and 'jsonSha256' not in ref:
                    ref = dict(ref, jsonSha256=c.digest(c.read(ref['path'])))
                return ref[value['field']]
        if '$output' in value: return str(directory / ('output-' + value['$output']))
        return {k: _resolve(v, ports=ports, bindings=bindings, configs=configs, directory=directory, draft=draft) for k,v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, ports=ports, bindings=bindings, configs=configs, directory=directory, draft=draft) for v in value]
    return value


def _unchanged_content(before, after, kind):
    a,b = copy.deepcopy(before), copy.deepcopy(after)
    if kind == 'approved_source':
        for value in (a,b):
            for key in ('packageId','status','translationEligible','review','issues','downstreamInvalidationKey'):
                value.pop(key, None)
            value['transcript'].pop('completenessReview', None)
    else:
        for value in (a,b):
            value.pop('status', None); value.pop('humanReview', None)
    require(a == b, 'approved_content_changed')


def validate_evidence_slot(state, slot, ref, *, inputs, references):
    """Read-only trusted-ingest validator. Never records or creates approval.

    inputs are resolved file paths from the recipe; references is the current
    bound slot map. Approved packages require an independently supplied receipt.
    Full budget/configuration admission is repeated after materialization.
    """
    actual = _artifact(ref['path'], sha=ref['sha256'])
    value = c.read(actual['path']); kind = slot['kind']; manifest = state['manifest']
    if kind == 'human_review':
        reviews.validate_review(slot['reviewKind'], actual['path'], inputs=inputs,
            expected_source=manifest['source'], expected_locale=slot.get('locale'))
    elif kind in {'approved_source','approved_candidate'}:
        require('machine' in inputs and slot.get('receiptBinding') in references, 'independent_review_required')
        before = c.read(inputs['machine'])
        receipt = references[slot['receiptBinding']]
        require(receipt is not None, 'independent_review_required')
        _unchanged_content(before, value, kind)
        if kind == 'approved_source':
            from scripts import build_english_source_package as source
            _source(value, manifest)
            source.validate_ready_package(value)
            require(value['review']['evidence']['sha256'] == receipt['sha256'], 'source_review_receipt_changed')
            checked_inputs = dict(inputs, source=actual['path'])
            reviews.validate_review('english', receipt['path'], inputs=checked_inputs, expected_source=manifest['source'])
        else:
            reviews.schema(value, 'sermon-target-language-candidate-v2.schema.json')
            checked_inputs = dict(inputs, candidate=actual['path'])
            reviews.validate_review('translation', receipt['path'], inputs=checked_inputs,
                expected_source=manifest['source'], expected_locale=slot.get('locale'))
    elif kind == 'budget_authorization':
        version = value.get('schemaVersion')
        require(version in {'sermon-source-budget-authorization-v1', 'sermon-canonical-layer2-budget-authorization-v1',
                            'sermon-canonical-layer2-budget-authorization-v2',
                            'sermon-study-budget-authorization-v1'}, 'budget_schema_invalid')
        binding = value.get('binding', value)
        require(binding.get('productionRunId') == manifest['productionRunId'], 'budget_run_changed')
        approval = _artifact(Path(actual['path']).parent / value['approvalReceipt'], sha=value['authority']['approvalSha256'])
        approved = c.read(approval['path'])
        if version == 'sermon-source-budget-authorization-v1':
            from scripts import sermon_source_budget as source_budget
            from scripts import sermon_unified_source as source_producer
            require(set(value) == {'schemaVersion','binding','authority','approvalReceipt'}
                    and set(binding) == {'productionRunId','configurationSha256','codeIdentitySha256','budgetRoot'}, 'budget_schema_invalid')
            source_budget.SourceBudget(Path(binding['budgetRoot']), value['authority'], verify=lambda: None)
            expected_binding = {**binding, 'globalBounds':value['authority']['globalBounds'],
                                'requestLimits':value['authority']['requestLimits']}
            expected_code = source_producer.code.code_identity()
        elif version == 'sermon-study-budget-authorization-v1':
            from scripts import sermon_study_generation as generation
            c.validate(value, 'sermon-study-budget-authorization-v1')
            generation.budget.SourceBudget(Path(binding['budgetRoot']), value['authority'], verify=lambda: None)
            require(value['approvalReceiptSha256'] == value['authority']['approvalSha256']
                    and binding['globalBounds'] == value['authority']['globalBounds']
                    and binding['requestLimits'] == value['authority']['requestLimits']
                    and Path(binding['budgetRoot']).is_absolute(), 'study_budget_binding_changed')
            expected_binding = binding
            expected_code = generation.code_identity()
        else:
            from scripts import canonical_layer2_budget as layer2_budget
            from scripts import canonical_layer2_controller as controller
            scoped = version == 'sermon-canonical-layer2-budget-authorization-v2'
            optional = {'ledgerScope'} if scoped else set()
            require(set(value) == {'schemaVersion','productionRunId','configurationSha256','codeIdentitySha256',
                                   'requestLimits','authority','approvalReceipt'} | optional
                    and (not scoped or value['ledgerScope'] == 'locale'), 'budget_schema_invalid')
            limits = layer2_budget.limits.validate_request_limits(value['requestLimits'])
            authority = layer2_budget.budget._authority(value['authority'])
            expected_binding = dict(approved.get('binding', {}))
            require(set(expected_binding) == {'productionRunId','configurationSha256','codeIdentitySha256','budgetRoot',
                                              'requestLimits','globalBounds','unitBounds','limits'} | optional
                    and (not scoped or expected_binding['ledgerScope'] == 'locale')
                    and all(expected_binding[k] == value[k] for k in ('productionRunId','configurationSha256','codeIdentitySha256'))
                    and expected_binding['requestLimits'] == limits
                    and all(expected_binding[k] == authority[k] for k in ('globalBounds','unitBounds','limits')), 'budget_approval_binding_changed')
            expected_code = controller.code_identity()
        # Locale-scoped v2 ledgers can spend the cap once per registered locale, as the adapter preflight counts it.
        locale_count = max(1, len(manifest.get('locales') or [])) \
            if version == 'sermon-canonical-layer2-budget-authorization-v2' else 1
        require(re.fullmatch('[a-f0-9]{64}', str(binding.get(
                    'executionSha256' if version == 'sermon-study-budget-authorization-v1' else 'configurationSha256','')))
                and binding.get('codeIdentitySha256') == expected_code
                and value['authority']['globalBounds']['costMicrousd'] * locale_count <= manifest['budget']['limitMicroUsd'], 'budget_execution_binding_changed')
        # Layer 2 v1 and v2 share one approval schema; the scope lives in the binding.
        approval_schema = ('sermon-canonical-layer2-budget-approval-v1' if version.startswith('sermon-canonical-layer2-')
                           else version.replace('authorization','approval'))
        require(approved.get('schemaVersion') == approval_schema
                and approved.get('binding') == expected_binding
                and approved.get('humanApproval') is True and approved.get('decision') == 'approved'
                and approved.get('reviewedBy') and approved.get('reviewedAt') and approved.get('operatorEvidence'), 'budget_approval_invalid')
    else:
        raise c.ContractError('continuation_evidence_kind_invalid')
    return actual


def validate_evidence(state, recipe_path, root, binding_name, evidence_path):
    """Validate one externally supplied evidence slot, without writing state.

    Root trusted-ingest performs CAS and persists the returned original-byte
    reference in state.continuationEvidence. This function never copies,
    normalizes, approves or mutates the supplied evidence.
    """
    info = inspect_recipe(recipe_path)
    manifest = state['manifest']
    frozen = _reference(state, RECIPE_BINDING)
    require(frozen is not None and frozen['sha256'] == info['sha256']
            and Path(frozen['path']).resolve() == Path(recipe_path).resolve(), 'recipe_not_bound')
    require(info['recipe']['productionRunId'] == manifest['productionRunId']
            and info['recipe']['jobRoot'] == manifest['jobRoot'], 'recipe_run_changed')
    stages = [s for s in info['recipe']['stages'] if s['afterRunRevision'] == manifest['runRevision']]
    require(len(stages) == 1, 'evidence_stage_missing')
    stage = stages[0]
    slots = [s for s in stage['requiredEvidence'] if s['binding'] == binding_name]
    require(len(slots) == 1, 'evidence_slot_missing')
    ports = {name: _port(state,port,root) for name,port in stage['ports'].items()}
    bindings = {name:_reference(state,name) for name in set(manifest['bindings']) | set(state.get('continuationEvidence',{}))}
    directory = runtime.folder(root,state['runKey']) / 'continuation' / info['sha256'] / stage['id']
    try:
        inputs = _resolve(slots[0].get('inputs',{}), ports=ports,bindings=bindings,configs={},directory=directory)
    except Missing as exc:
        raise c.ContractError('continuation_evidence_inputs_missing:' + str(exc)) from exc
    ref = _artifact(evidence_path)
    existing = bindings.get(binding_name)
    require(existing is None or existing['sha256'] == ref['sha256'], 'evidence_overwrite_forbidden')
    validated = validate_evidence_slot(state,slots[0],ref,inputs=inputs,references=bindings)
    # The values read for validation must still be the ones being admitted.
    for reference in [frozen,*[p for p in ports.values() if p],*[p for p in bindings.values() if p],validated]:
        require(c.file_sha(reference['path']) == reference['sha256'], 'evidence_changed_during_validation')
    return {**validated,'recipeSha256':info['sha256'],'stageId':stage['id'],
            'slotSha256':c.digest(slots[0]),'kind':slots[0]['kind']}


def _write_once(path, value):
    path = c._safe_path(Path(path).absolute())
    encoded = (json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',', ':'))+'\n').encode()
    if path.exists():
        require(path.read_bytes() == encoded, 'immutable_output_changed')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Link a fully flushed temporary inode without replacing any committed file.
    fd, temporary = tempfile.mkstemp(prefix='.continuation-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(encoded); handle.flush(); os.fsync(handle.fileno())
        try: os.link(temporary, path)
        except FileExistsError: require(path.read_bytes() == encoded, 'immutable_output_changed')
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory_fd)
        finally: os.close(directory_fd)
    finally:
        os.unlink(temporary)


def prepare_next_revision(state, recipe_path, root):
    inspected = inspect_recipe(recipe_path); recipe = inspected['recipe']; manifest = state['manifest']
    require(recipe['productionRunId'] == manifest['productionRunId'] and recipe['jobRoot'] == manifest['jobRoot'], 'recipe_run_changed')
    frozen = _reference(state, RECIPE_BINDING)
    require(frozen is not None and frozen['sha256'] == inspected['sha256']
            and Path(frozen['path']).resolve() == Path(recipe_path).resolve(), 'recipe_not_bound')
    require(state['runKey'] == runtime.run_key(manifest) and state['planHash'] == c.plan_hash(manifest), 'state_identity_changed')
    if state.get('cancelRequested'):
        return {'status':'waiting','reason':'cancelled','requiredEvidence':[]}
    if any(row.get('process') in {'running','waiting_reconciliation','unknown'} for row in state['steps'].values()):
        return {'status':'waiting','reason':'reconciliation_required','requiredEvidence':[]}
    matches = [s for s in recipe['stages'] if s['afterRunRevision'] == manifest['runRevision']]
    if not matches: return {'status':'waiting','reason':'no_continuation_stage','requiredEvidence':[]}
    stage = matches[0]
    directory = c._safe_path(runtime.folder(root,state['runKey']) / 'continuation' / inspected['sha256'] / stage['id'])
    ports = {name: _port(state, port, root) for name,port in stage['ports'].items()}
    bindings = {name: _reference(state,name) for name in set(manifest['bindings']) | set(state.get('continuationEvidence',{}))}
    resolver = dict(ports=ports,bindings=bindings,configs={},directory=directory)
    drafts = {name:_resolve(config['template'], **resolver, draft=True) for name,config in stage['configs'].items()}
    context = {'source':manifest['source'],'content':manifest['content'],'ports':ports,
               'configurationDrafts':{name:{'value':value,'path':str(directory / (name+'.json')),
                   'jsonSha256':c.digest(value),
                   'templateSha256':c.digest(stage['configs'][name]['template'])} for name,value in drafts.items()}}
    required = [{'kind':'upstream_artifact','port':name,'stepId':stage['ports'][name]['stepId']} for name,value in ports.items() if value is None]
    for slot in stage['requiredEvidence']:
        ref = bindings.get(slot['binding'])
        if ref is None:
            required.append(dict(slot)); continue
        try: inputs = _resolve(slot.get('inputs',{}), **resolver)
        except Missing:
            required.append(dict(slot,reason='review_inputs_missing')); continue
        if slot.get('receiptBinding') and bindings.get(slot['receiptBinding']) is None:
            required.append(dict(slot,reason='independent_review_missing')); continue
        validate_evidence_slot(state,slot,ref,inputs=inputs,references=bindings)
    if required:
        return {'status':'waiting','reason':'required_evidence','requiredEvidence':required,'inputContext':context,
                'recipeSha256':inspected['sha256'],'stageId':stage['id']}
    # Files are deterministic across retries; configuration dependencies form a
    # small explicit DAG. No generated path can be supplied by a template.
    pending = dict(stage['configs']); generated = {}; config_refs = resolver['configs']
    while pending:
        progressed = False
        for name,config in list(pending.items()):
            try: value = _resolve(config['template'], **resolver)
            except Missing: continue
            path = directory / (name + '.json')
            _write_once(path,value)
            config_refs[name] = _artifact(path)
            generated[name] = config_refs[name]
            del pending[name]; progressed = True
        require(progressed, 'unresolved_config_dependency')
    patch = _resolve(stage['manifestTemplate'], **resolver)
    next_manifest = copy.deepcopy(manifest)
    require(not ({s['id'] for s in manifest['steps']} & {s['id'] for s in patch['steps']}), 'step_overwrite_forbidden')
    next_manifest['steps'] += patch['steps']
    next_manifest['activeScope'] = patch.get('activeScope',manifest['activeScope'])
    for name,ref in patch.get('bindings',{}).items():
        require(name not in next_manifest['bindings'] or next_manifest['bindings'][name] == ref, 'binding_overwrite_forbidden')
        next_manifest['bindings'][name] = ref
    next_manifest['runRevision'] += 1
    c.validate(next_manifest,'sermon-unified-run-manifest-v2')
    for name,ref in next_manifest['bindings'].items(): c.binding(next_manifest,'/',name)
    for step in patch['steps']:
        if step.get('configuration'):
            ref = next_manifest['bindings'][step['configuration']]
            require(any(ref['path'] == r['path'] and stage['configs'][name]['adapter'] == step['adapter']
                        for name,r in generated.items()), 'configuration_adapter_changed')
        adapters.inspect_step(next_manifest,'/',step,ready=False)
    # Reread every consumed byte after validators and before committing output.
    for ref in [frozen,*[p for p in ports.values() if p],*[p for p in bindings.values() if p]]:
        require(c.file_sha(ref['path']) == ref['sha256'], 'input_changed_during_materialization')
    manifest_path = directory / 'manifest.json'
    _write_once(manifest_path,next_manifest)
    receipt = {'schemaVersion':'sermon-unified-continuation-receipt-v1','recipeSha256':inspected['sha256'],
        'stageId':stage['id'],'runKey':state['runKey'],'productionRunId':manifest['productionRunId'],
        'priorPlanHash':state['planHash'],'fromRunRevision':manifest['runRevision'],
        'toRunRevision':next_manifest['runRevision'],'ports':ports,'evidence':{s['binding']:bindings[s['binding']] for s in stage['requiredEvidence']},
        'configurations':generated,'manifest':_artifact(manifest_path),'humanApprovalCreated':False,
        'modelDispatches':0}
    c.validate(receipt, 'sermon-unified-continuation-receipt-v1')
    receipt_path = directory / 'continuation-receipt.json'
    _write_once(receipt_path,receipt)
    return {'status':'ready','manifest':next_manifest,'manifestPath':str(manifest_path),
            'manifestSha256':c.file_sha(manifest_path),'planHash':c.plan_hash(next_manifest),
            'receiptPath':str(receipt_path),'receiptSha256':c.file_sha(receipt_path),
            'expectedStateRevision':state['stateRevision'],'priorPlanHash':state['planHash'],
            'recipeSha256':inspected['sha256'],'stageId':stage['id']}
