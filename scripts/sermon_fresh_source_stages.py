"""Fixed synthetic Fresh Source operations with original typed provider leaves.

This is a stage adapter, not an engine. The caller owns scheduling and an actual
canonical accounting context. Every completed stage has an immutable sidecar;
consumers validate every predecessor before dispatch. No custom model callback,
MFA execution, human approval or production eligibility is exposed.
"""
from copy import deepcopy
from pathlib import Path

from scripts import sermon_accounting as accounting
from scripts import sermon_completion as completion
from scripts import sermon_fresh_diagnostic as fresh
from scripts import sermon_fresh_diagnostic_source as source
from scripts import sermon_fresh_source_causality as causality
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as immutable
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-fresh-source-stage-result-v1'
ORDER = causality.ORDER


class FreshSourceStages:
    def __init__(self, session, recipe, authorization):
        c.require(type(session) is fresh.FreshDiagnosticSession and session.offline_fixture
            and session.evidence_mode == 'synthetic', 'fresh_stages_synthetic_session_required')
        c.require(type(recipe) is dict and set(recipe) <= {'prior_plan_path', 'prior_source_path',
            'prior_aligned_path', 'prior_summary_path', 'audio_path', 'run_mfa', 'local_runtime_path'}
            and {'prior_plan_path', 'prior_source_path', 'prior_aligned_path', 'prior_summary_path', 'audio_path'} <= set(recipe)
            and recipe.get('run_mfa', False) is False and recipe.get('local_runtime_path') is None,
            'fresh_stages_fixed_alignment_fixture_required')
        self.session = session
        self.recipe = {key: str(value) if key.endswith('_path') and value is not None else value
            for key, value in recipe.items()}
        self.authorization = deepcopy(authorization)
        self.root = _safe_path(session.root/'fresh-source-stages', recursive=True)
        self.frozen_recipe = {'schemaVersion': 'sermon-fresh-source-recipe-v2',
            'files': {key: {'path': str(_safe_path(Path(value))), 'sha256': source._sha(value)}
                for key, value in self.recipe.items() if key.endswith('_path') and value is not None},
            'runMFA': False, 'authorizationSha256': c.canonical_sha256(authorization)}
        self.binding = {'schemaVersion': 'sermon-fresh-source-stages-v1',
            'planSha256': c.canonical_sha256(session.plan), 'recipeSha256': c.canonical_sha256(self.frozen_recipe),
            'requestLimitsSha256': c.canonical_sha256(session.subject.limits),
            'stageOrder': list(ORDER), 'evidenceMode': 'synthetic', 'productionEligible': False}

    def freeze(self):
        self.session._check()
        immutable.save_once(self.session.root/'fresh-source-recipe.json', self.frozen_recipe)
        immutable.save_once(self.root/'binding.json', self.binding)
        return deepcopy(self.binding)

    def _check(self):
        self.session._check()
        c.require(public.read_snapshot(self.root/'binding.json')[0] == self.binding
            and self.binding['planSha256'] == c.canonical_sha256(self.session.plan)
            and self.binding['requestLimitsSha256'] == c.canonical_sha256(self.session.subject.limits)
            and public.read_snapshot(self.session.root/'fresh-source-recipe.json')[0] == self.frozen_recipe
            and all(source._sha(row['path']) == row['sha256'] for row in self.frozen_recipe['files'].values())
            and self.frozen_recipe['authorizationSha256'] == c.canonical_sha256(self.authorization),
            'fresh_stages_frozen_binding_changed')

    def _path(self, stage):
        c.require(stage in ORDER, 'fresh_stages_stage_invalid')
        return self.root/(stage+'.result.json')

    def _validate(self, stage, result, prior):
        count = ORDER.index(stage)+1
        identity, events = completion.current_events()
        c.require(type(result) is dict and set(result) == {'schemaVersion', 'stage', 'bindingSha256',
            'priorResultSha256', 'causality', 'productionEligible'} and result['schemaVersion'] == SCHEMA
            and result['stage'] == stage and result['bindingSha256'] == c.canonical_sha256(self.binding)
            and result['priorResultSha256'] == (c.canonical_sha256(prior) if prior is not None else None)
            and result['productionEligible'] is False
            and result['causality']['logDirectory'] == str(identity[0]), 'fresh_stages_result_changed')
        args = {}
        for index, key, operation, model in ((2, 'asr_ref', 'transcription.initial', 'gpt-transcribe'),
                (3, 'review_ref', 'source.initial', 'gpt-6-astra')):
            if count >= index:
                args[key] = source.returned_receipt(self.session.root, self.session.subject.config, operation, model)[1]
        if count >= 4:
            args['aligned_sha256'] = source._sha(self.session.root/'aligned-segments.json')
        if count >= 5:
            args['source_sha256'] = c.canonical_sha256(public.read_snapshot(self.session.root/'source.json')[0])
        causality.validate_prefix(result['causality'], events, through=stage, plan=self.session.plan,
            recipe=self.frozen_recipe, **args)
        if prior is not None:
            c.require({key: result['causality']['handles'][key] for key in ORDER[:count-1]}
                == prior['causality']['handles'], 'fresh_stages_predecessor_changed')
        return deepcopy(result)

    def execute(self, stage, upstream=None):
        self._check()
        c.require(stage in ORDER, 'fresh_stages_stage_invalid')
        index = ORDER.index(stage)
        prior = public.read_snapshot(self._path(ORDER[index-1]))[0] if index else None
        c.require(upstream == prior, 'fresh_stages_upstream_result_changed')
        if prior is not None:
            previous = public.read_snapshot(self._path(ORDER[index-2]))[0] if index > 1 else None
            self._validate(ORDER[index-1], prior, previous)
        path = self._path(stage)
        if path.exists():
            result = self._validate(stage, public.read_snapshot(path)[0], prior)
            if stage == 'sourcePackage':
                self._adopt()
            return result
        handles = {} if prior is None else deepcopy(prior['causality']['handles'])
        if stage == 'intake':
            with accounting.stage('diagnostic.source_preflight', depends_on=[], work_unit_id='source.preflight',
                    executor_type='deterministic_program') as span:
                source.preflight_recipe(self.session.plan, self.recipe, self.authorization)
                accounting.record_workload('diagnostic.source_recipe_binding', {
                    'recipeSha256': c.canonical_sha256(self.frozen_recipe),
                    'planSha256': c.canonical_sha256(self.session.plan)})
            handle = completion.capture(span, production_run_id=self.session.subject.config['runId'],
                artifact_sha256=c.canonical_sha256(self.frozen_recipe), artifact_kind='frozen_recipe',
                execution_mode='deterministic_validation')
        elif stage == 'transcription':
            result = self.session.runner.transcribe(Path(self.recipe['audio_path']).read_bytes(),
                depends_on=[handles['intake']['spanId']], completion_result=True)
            handle = result['completion']
        elif stage == 'sourceCheck':
            result = self.session.runner.source_check(operation_id='source.initial',
                depends_on=[handles['transcription']['spanId']], completion_result=True)
            handle = result['completion']
            # Provider completion is a real receipt, not semantic admission.
            # Validate the returned Source response before making this node ready.
            source._stage_inputs(self.session.plan, self.session.subject, self.recipe,
                self.authorization, dict(handles, sourceCheck=handle))
        elif stage == 'alignment':
            result = source.prepare_alignment(self.session.plan, self.session.subject, recipe=self.recipe,
                authorization=self.authorization, source_completions=handles)
            handle = result['completion']
        else:
            alignment = public.read_snapshot(self.root/'alignment.json')[0]
            prepared = source.prepare_source_package(self.session.plan, self.session.subject, recipe=self.recipe,
                authorization=self.authorization, source_completions={key: handles[key] for key in ORDER[:3]},
                alignment_result=alignment)
            self.session.adopt_prepared_source(prepared)
            handle = public.read_snapshot(self.session.root/'fresh-source-causality.json')[0]['handles'][stage]
        handles[stage] = handle
        identity, _ = completion.current_events()
        result = {'schemaVersion': SCHEMA, 'stage': stage, 'bindingSha256': c.canonical_sha256(self.binding),
            'priorResultSha256': c.canonical_sha256(prior) if prior is not None else None,
            'causality': {'schemaVersion': causality.SCHEMA, 'runId': self.session.subject.config['runId'],
                'planSha256': c.canonical_sha256(self.session.plan), 'recipeSha256': c.canonical_sha256(self.frozen_recipe),
                'logDirectory': str(identity[0]), 'handles': handles}, 'productionEligible': False}
        self._validate(stage, result, prior)
        immutable.save_once(path, result)
        return deepcopy(result)

    def _adopt(self):
        prepared = {key: public.read_snapshot(self.session.root/name)[0] for key, name in
            (('source', 'source.json'), ('anchor', 'anchor-manifest.json'),
             ('context', 'diagnostic-context.json'), ('evidence', 'fresh-source-evidence.json'))}
        causal = public.read_snapshot(self.session.root/'fresh-source-causality.json')[0]
        prepared['completionSpans'] = [causal['handles']['sourcePackage']['spanId']]
        return self.session.adopt_prepared_source(prepared)
