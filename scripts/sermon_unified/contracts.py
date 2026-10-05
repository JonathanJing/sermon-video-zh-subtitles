"""Side-effect-free executable manifest admission and identity."""
from __future__ import annotations
import copy
from datetime import datetime, timezone
import hashlib
import json
import subprocess
from pathlib import Path
from jsonschema import Draft202012Validator
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_release_workflow import _safe_path

ROOT = Path(__file__).resolve().parents[2]
STAGES = ('media_verify', 'window_review', 'asr', 'english_source', 'layer2_admit',
          'layer2_group', 'translation_review', 'layer3_prepare', 'layer3_unit',
          'layer3_screen', 'listen_review', 'study_product', 'publish_endpoint')
SCOPES = ('media_verified', 'english_ready_for_translation', 'layer2_machine_candidate',
          'translation_approved', 'audio_screened', 'listen_approved', 'study_approved',
          'dev_reader_verified', 'dual_test_end_approved', 'dual_production_verified')
MAX_JSON = 32 * 1024 * 1024

class ContractError(ValueError):
    def __init__(self, code, exit_code=4):
        super().__init__(code)
        self.code, self.exit_code = code, exit_code


def digest(value):
    return jobs._digest(value)


def file_sha(path):
    h = hashlib.sha256()
    with _safe_path(Path(path).absolute()).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def read(path):
    p = _safe_path(Path(path).absolute())
    if p.stat().st_size > MAX_JSON:
        raise ContractError('input_read_limit', 2)
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ContractError('duplicate_json_key', 2)
            result[k] = v
        return result
    return json.loads(p.read_text(), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ContractError('nonfinite_json', 2)))


def validate(value, schema):
    obj = read(ROOT / 'schemas' / (schema + '.schema.json'))
    errors = list(Draft202012Validator(obj, format_checker=Draft202012Validator.FORMAT_CHECKER).iter_errors(value))
    if errors:
        raise ContractError('schema_invalid', 2)


def plan_hash(manifest):
    value = {k: copy.deepcopy(v) for k, v in manifest.items()
             if k not in {'planHash', 'manifestSha256', 'provenance'}}
    # The digest of a bound file matters; its local locator is provenance.
    if 'bindings' in value:
        value['bindings'] = {k: {'sha256': v['sha256']} for k, v in value['bindings'].items()}
    return digest(value)


def binding(manifest, base, name):
    if name not in manifest.get('bindings', {}):
        raise ContractError('binding_required')
    ref = manifest['bindings'][name]
    p = _safe_path(Path(base) / ref['path'])
    if not p.is_file() or file_sha(p) != ref['sha256']:
        raise ContractError('binding_changed', 7)
    return p


def closure(modules):
    names = sorted(set(modules))
    values = {}
    for name in names:
        p = _safe_path(ROOT / name)
        if not p.is_relative_to(ROOT) or not p.is_file():
            raise ContractError('execution_module_invalid')
        values[name] = file_sha(p)
    return digest(values)


def required_modules():
    # Includes existing validators and late imports. Docs unrelated to model
    # consumption are deliberately excluded. Term rules are an input dependency.
    modules={str(p.relative_to(ROOT)) for folder, glob in [('scripts', '*.py'), ('schemas', '*.json')]
             for p in (ROOT / folder).rglob(glob)}
    # Producers late-load the legacy renderer/publisher and copy its web assets.
    # Enumerate tracked source files, never node_modules or ignored output trees.
    tracked=subprocess.run(['git','ls-files','--','experiments/sermon-dubbing-poc'],cwd=ROOT,
                           capture_output=True,text=True,timeout=10)
    if tracked.returncode:
        raise ContractError('legacy_execution_closure_unavailable')
    modules.update(name for name in tracked.stdout.splitlines() if Path(name).suffix in {'.py','.mjs','.js','.html','.css','.json'})
    return sorted(modules | {'docs/series-terminology.zh.md'})


def job_identity(m, step):
    return {'jobRoot': m['jobRoot'], 'runRevision': m['runRevision'],
            'layer': layer(step['stageId'], step.get('reviewKind')),
            'stageId': step['stageId'], 'locale': step.get('locale'),
            'subject': {'kind': 'stage', 'id': step['id']}, 'operation': step['adapter'],
            'inputDigest': digest({'planHash': plan_hash(m), 'step': step})}


def layer(stage, kind=None):
    if stage == 'study_product':
        return kind if kind in ('outline', 'reflection') else 'outline'
    return ('layer1' if stage in STAGES[:4] else 'layer2' if stage in STAGES[4:7]
            else 'layer3' if stage in STAGES[7:11] else 'layer4')


def admit(m, base):
    version = m.get('schemaVersion') if isinstance(m, dict) else None
    if version not in ('sermon-unified-run-manifest-v1', 'sermon-unified-run-manifest-v2'):
        raise ContractError('manifest_version_invalid', 2)
    validate(m, version)
    errors = []
    def fail(code):
        if code not in errors:
            errors.append(code)
    if m['activeScope'] not in (m['canaryScope'], m['finalScope']):
        fail('scope_not_authorized')
    w = m['source']['window']
    if w['endSeconds'] <= w['startSeconds'] or (m['source'].get('durationSeconds') is not None
                                               and w['endSeconds'] > m['source']['durationSeconds']):
        fail('source_window_invalid')
    if m['activeScope'] != 'media_verified' and not w.get('approvalReceiptSha256'):
        fail('window_approval_required')
    if m['budget']['limitMicroUsd'] is None:
        fail('budget_required')
    if m['activeScope']!='media_verified' and not m['locales']:
        fail('production_locales_required')
    if sorted(p['locale'] for p in m['policies']) != sorted(m['locales']):
        fail('locale_policy_coverage')
    if version.endswith('v1'):
        fail('executable_bindings_required')
        return errors
    if m['transport'] == 'fixture' and not m.get('fixtureSetId'):
        fail('fixture_set_required')
    try:
        start = datetime.fromisoformat(m['executionWindow']['startsAt'])
        end = datetime.fromisoformat(m['executionWindow']['deadlineAt'])
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            fail('execution_window_invalid')
    except ValueError:
        fail('execution_window_invalid')
    try:
        if not set(required_modules()) <= set(m['executionAdmission']['modules']):
            fail('execution_closure_incomplete')
        if closure(m['executionAdmission']['modules']) != m['executionAdmission']['closureSha256']:
            fail('execution_closure_changed')
    except (OSError, ValueError):
        fail('execution_closure_invalid')
    needs_runtime=any(step['adapter'] in ('source.prepare','canonical.layer2','canonical.audio','app.delivery') for step in m['steps'])
    if needs_runtime:
        try:
            from scripts.sermon_unified_capabilities import inspect as inspect_capabilities
            capabilities=inspect_capabilities(binding(m,base,'consumerCapabilities'))
            if any(step['adapter']=='app.delivery' for step in m['steps']) and capabilities['targetSchemaVersions']['release']!='sermon-target-language-release-package-v3':
                fail('consumer_four_product_release_schema_required')
            if (not capabilities['snapshotBound'] or capabilities['sourceIdentity']!=m['source']
                or set(capabilities['locales'])!=set(m['locales'])
                or any(capabilities['locales'][p['locale']]['policyFileSha256']!=p['policySha256'] for p in m['policies'])):
                fail('consumer_capability_binding_changed')
        except (OSError,ValueError,KeyError,TypeError):
            fail('consumer_capabilities_required_or_invalid')
    if needs_runtime or m['executionAdmission'].get('runtimeSha256'):
        try:
            from scripts.sermon_unified_runtime_identity import snapshot
            if m['executionAdmission'].get('runtimeSha256')!=digest(snapshot()):
                fail('execution_runtime_changed_or_unbound')
        except (OSError,ValueError):
            fail('execution_runtime_unavailable')
    for name in m['bindings']:
        try:
            binding(m, base, name)
        except (OSError, ValueError):
            fail('binding_changed')
    if 'media' not in m['bindings'] or m['bindings'].get('media', {}).get('sha256') != m['source']['mediaSha256']:
        fail('source_media_binding_required')
    if w.get('approvalReceiptSha256'):
        try:
            from scripts.sermon_unified_reviews import validate_window
            validate_window(m, base=base)
        except (OSError, ValueError, KeyError, TypeError):
            fail('window_approval_invalid')
    seen = set()
    for step in m['steps']:
        if step['id'] in seen or not set(step['dependsOn']) <= seen:
            fail('step_dependency_invalid')
        seen.add(step['id'])
        if step.get('locale') and step['locale'] not in m['locales']:
            fail('step_locale_invalid')
        if step['adapter'] == 'fixture.replay' and m['transport'] != 'fixture':
            fail('fixture_transport_required')
        if step['adapter'] != 'fixture.replay' and m['transport'] == 'fixture' and step['adapter'] not in ('media.verify','review.gate'):
            fail('fixture_provider_forbidden')
        for field in ('configuration','artifact','budgetAuthorization'):
            if field in step and step[field] not in m['bindings']:
                fail('step_binding_missing')
    stage_scopes = {
        'media_verify': {'media_verified'}, 'window_review': {'media_verified'},
        'asr': {'english_ready_for_translation'}, 'english_source': {'english_ready_for_translation'},
        'layer2_admit': {'layer2_machine_candidate'}, 'layer2_group': {'layer2_machine_candidate'},
        'translation_review': {'translation_approved'}, 'layer3_prepare': {'audio_screened'},
        'layer3_unit': {'audio_screened'}, 'layer3_screen': {'audio_screened'},
        'listen_review': {'listen_approved'}, 'study_product': {'study_approved'},
        'publish_endpoint': {'dev_reader_verified','dual_test_end_approved','dual_production_verified'}}
    if not any(step['stageId']=='media_verify' and step['adapter']=='media.verify' for step in m['steps']):
        fail('media_verification_step_required')
    ancestors = {}
    by_id = {s['id']: s for s in m['steps']}
    for step in m['steps']:
        if step['scope'] not in stage_scopes[step['stageId']]:
            fail('stage_scope_mismatch')
        upstream=set(step['dependsOn'])
        for dep in step['dependsOn']:
            upstream.update(ancestors.get(dep,set()))
        ancestors[step['id']]=upstream
        if any(SCOPES.index(by_id[x]['scope'])>SCOPES.index(step['scope']) for x in upstream if x in by_id):
            fail('dependency_scope_inversion')
        stages={by_id[x]['stageId'] for x in upstream if x in by_id}
        needed={'asr':{'window_review'}, 'english_source':{'window_review'},
                'layer2_admit':{'english_source'}, 'layer2_group':{'english_source'},
                'translation_review':{'layer2_group'}, 'layer3_prepare':{'translation_review'},
                'layer3_unit':{'translation_review'}, 'layer3_screen':{'layer3_unit'},
                'listen_review':{'layer3_screen'}, 'study_product':{'translation_review'},
                'publish_endpoint':{'listen_review','study_product'}}.get(step['stageId'],set())
        if not needed <= stages:
            fail('required_stage_dependency_missing')
        if step['adapter'] in ('canonical.layer2','canonical.inspect') and step['stageId']!='english_source' and not step.get('locale'):
            fail('step_locale_required')
        # A locale dependency cannot borrow another language's approval.
        for required in needed:
            candidates=[by_id[x] for x in upstream if x in by_id and by_id[x]['stageId']==required]
            if candidates and step.get('locale') and all(x.get('locale') not in (None,step['locale']) for x in candidates):
                fail('cross_locale_dependency')
    if m.get('planHash') and m['planHash'] != plan_hash(m):
        fail('plan_hash_changed')
    return errors
