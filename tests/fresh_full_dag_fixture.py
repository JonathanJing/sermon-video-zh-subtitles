"""Bounded, synthetic Source-to-mock fixtures with genuine strict receipts.

Import the complete graph before SourceEngineFixture freezes loaded code. The
fixture owns no production callbacks: only OfflineHTTPTransport returns canned
ASR, Source review, translation and independent-review bodies. SDK children
restore the exact loaded module inventory and require clean code identity.
"""
from copy import deepcopy
import importlib
import json
import os
import re
import shutil
from pathlib import Path
import time

from scripts import sermon_fresh_full_dag as dag
from scripts import sermon_accounting as accounting
from scripts import sermon_bounded_business_callbacks as offline
from scripts import sermon_fresh_diagnostic as fresh
from scripts import sermon_fresh_source_prefect as source_engine
from scripts import sermon_log_contract as logs
from scripts import sermon_mock_tts_control as control
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_workflow_jobs as jobs
from scripts import weekly_pipeline_report as weekly
from tests.test_sermon_fresh_source_prefect import SourceEngineFixture

LOCALE = 'zh-Hans'
UNITS = ('zh-Hans.fresh-g001', 'zh-Hans.fresh-g002')
SOURCE_NODES = ('source.preflight', 'transcription.initial', 'source.initial',
    'source.alignment', 'source.package', 'locale.freeze')


def fixture_transport(source_text, source_review, groups, *, allow_calls=True):
    replies = []

    def respond(request, timeout, *, deadline):
        assert allow_calls, 'receipt-only repeat must not call synthetic providers'
        if request.full_url.endswith('/audio/transcriptions'):
            return {'text': source_text, 'usage': {'type': 'duration', 'seconds': 180}}
        payload = json.loads(request.data)
        inputs = json.loads(payload['messages'][1]['content'])
        if 'translationGroupId' not in inputs:
            assert payload['model'] == 'gpt-6-astra'
            body = source_review
        elif payload['model'] == 'gpt-6-astra':
            group = next(row for row in groups if row['translationGroupId'] == inputs['translationGroupId'])
            assert group['sourceUnitIds'] == inputs['sourceUnitIds']
            body = {key: group[key] for key in ('translationGroupId', 'sourceUnitIds', 'targetUtterances', 'coverage')}
        else:
            assert payload['model'] == 'gpt-6-sol'
            body = {'reviewedArtifactSha256': inputs['reviewedArtifactSha256'], 'reviewVerdict': 'pass',
                'checks': [{'checkId': name, 'result': 'pass', 'evidence': 'synthetic fixture only'}
                    for name in sorted(c.HARD_CHECKS)],
                'issues': [], 'assessedUnitIds': inputs['sourceUnitIds'], 'unassessedUnitIds': []}
        replies.append(body)
        return {'id': 'fresh-full-fixture-'+str(len(replies)), 'model': payload['model'],
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(body)}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}

    return offline.OfflineHTTPTransport(respond, fixture_id='diagnostic-dag-fixture')


class FullFreshDAGFixture(SourceEngineFixture):
    def setUp(self):
        super().setUp()
        # Derive actual fresh group IDs from the same real anchor builder as the
        # Source stage. No historical g1/g2 or cached candidate IDs are reused.
        self.expected_groups = source_engine._groups(self.recipe)
        assert [row['translationGroupId'] for row in self.expected_groups] == ['fresh-g001', 'fresh-g002']
        assert [len(row['sourceUnitIds']) for row in self.expected_groups] == [3, 1]
        self.groups = [{**deepcopy(group),
            'targetUtterances': ['合成测试文本。' for _ in group['sourceUnitIds']],
            'coverage': [{'sourceUnitId': key, 'targetText': '合成测试文本。'} for key in group['sourceUnitIds']]}
            for group in self.expected_groups]
        self.transport = fixture_transport(self.seed.transcript, self.seed.content, self.groups)
        # Initialize the original active ledger before dispatch, so every run
        # must preserve its exact deadline, clock identity, limits and authority.
        self.subject = self.f.subject
        self.subject.snapshot()
        self.provider_state_path = self.subject.store.root/budget.STORE_ID/'provider-run'/'state.json'
        self.initial_provider_state = json.loads(self.provider_state_path.read_text())

    def session(self):
        return fresh.FreshDiagnosticSession(self.plan, offline_transport=self.transport)

    def dag_config(self, *, faults=None, observation_timeout=45):
        return {'schemaVersion': dag.SCHEMA,
            'mockPolicy': {'schemaVersion': control.POLICY, 'units': dict.fromkeys(UNITS, LOCALE),
                'maxJobs': 4, 'maxAttemptsPerUnit': 2, 'maxConcurrentJobs': 2,
                'workerTimeoutSeconds': 60, 'observationTimeoutSeconds': observation_timeout},
            'faults': deepcopy(faults or {})}

    def payload(self, config, result_path, *, allow_calls, recovery=None):
        return {'plan': self.plan,
            'recipe': {key: str(value) if isinstance(value, Path) else value for key, value in self.recipe.items()},
            'authorization': self.authorization, 'locales': self.locales, 'config': config,
            'fixtureSourceText': self.seed.transcript, 'fixtureSourceReview': self.seed.content,
            'fixtureGroups': self.groups, 'allowFixtureCalls': allow_calls,
            'recovery': recovery or {}, 'resultPath': str(result_path)}


def clean_child(payload_path):
    """Actual SDK only: clean committed code, genuine identities, no gate patch."""
    value = json.loads(Path(payload_path).read_text())
    expected = value['plan']['executionIdentity']
    repository = Path(dag.__file__).resolve().parents[1]
    for name, digest in expected['loadedProjectCodeSha256'].items():
        assert name.startswith('scripts/') and name.endswith('.py')
        assert c.bytes_sha256((repository/name).read_bytes()) == digest
        importlib.import_module(name[:-3].replace('/', '.'))
    identity = accounting.execution_identity()
    assert identity['trackedWorkingTreeDirty'] is False, 'actual SDK requires clean committed code'
    assert identity == expected, 'fresh clean-process code identity must match exactly'
    transport = fixture_transport(value['fixtureSourceText'], value['fixtureSourceReview'],
        value['fixtureGroups'], allow_calls=value['allowFixtureCalls'])
    session = fresh.FreshDiagnosticSession(value['plan'], offline_transport=transport)
    result = dag.run(session, value['recipe'], value['authorization'], value['locales'],
        value['config'], recovery=value.get('recovery'))
    assert result['syntheticProviderDispatches'] == len(transport.observations)
    assert len(transport.observations) == (6 if value['allowFixtureCalls'] else 0)
    Path(value['resultPath']).write_text(json.dumps(result))
    return result


def wait_for_original_jobs(root, *, timeout=90):
    """Wait for ordinary detached fixture work; never launch or retry a job."""
    control_root = Path(root)/'mock-control'
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        intents = [json.loads(path.read_text()) for path in (control_root/'intents').glob('*.json')]
        if intents and all(jobs.peek_job(control_root/'jobs', item['jobId'])['status']
                not in {'queued', 'running'} for item in intents):
            return
        time.sleep(.03)
    raise AssertionError('bounded fixture jobs did not reach an ordinary terminal state')


def immutable_files(root):
    """Source facts, provider receipts and submitted request/worker artifacts."""
    root = Path(root)
    paths = [*root.glob('fresh-source-stages/*.json'), *root.glob('fresh-source-*.json')]
    paths += [path for path in (root/'budget'/budget.STORE_ID/'provider-run').glob('*.json')
        if path.name != 'state.json']
    paths += [path for path in root.glob('fresh-full-dag/*/mock-control/requests/**/*') if path.is_file()]
    return {str(path): path.read_bytes() for path in paths}


def assert_provider_bounds_unchanged(before, after, *, expected_requests):
    for key in ('schemaVersion', 'config', 'authoritySha256', 'clockDomain', 'startedMonotonic'):
        assert after[key] == before[key], key
    assert all(after['requests'][key] == value for key, value in before['requests'].items())
    assert len(after['requests']) == expected_requests
    assert all(row['state'] == 'returned' for row in after['requests'].values())


def preserve_full_evidence(fixture_root, scenario):
    """Optional read-only synthetic SDK evidence copy before normal cleanup."""
    from tests.mock_tts_sdk_diagnostics import result_summary
    destination = os.environ.get('SERMON_FRESH_FULL_TEST_EVIDENCE_DIR')
    if not destination:
        return
    if scenario not in {'happy', 'failure', 'timeout'}:
        raise ValueError('invalid_fresh_full_sdk_scenario')
    fixture_root = Path(fixture_root)
    source = fixture_root/'fresh-full-dag'
    if not source.exists():
        return
    if any(path.is_symlink() for path in fixture_root.rglob('*')):
        raise ValueError('fresh_full_sdk_evidence_link_rejected')
    for plan in sorted(source.iterdir()):
        if not plan.is_dir() or re.fullmatch('[a-f0-9]{64}', plan.name) is None:
            continue
        target = Path(destination)/scenario/plan.name
        if target.exists() or target.resolve().is_relative_to(fixture_root.resolve()):
            raise ValueError('fresh_full_sdk_evidence_destination_invalid')
        target.parent.mkdir(parents=True, exist_ok=True)
        # This fixture is entirely synthetic. Retain Source/locale/provider and
        # mock facts together; the ephemeral Prefect database is unnecessary.
        shutil.copytree(fixture_root, target, symlinks=True,
            ignore=shutil.ignore_patterns('prefect', '.prefect*'))
        saved_plan = target/'fresh-full-dag'/plan.name
        for result_path in sorted((saved_plan/'runs').glob('*.json')):
            value = json.loads(result_path.read_text())
            summary = result_summary(value, saved_plan)
            summary['captureScope'] = 'read_only_synthetic_test_evidence_not_new_completion'
            summary['resultBytesSha256'] = c.bytes_sha256(result_path.read_bytes())
            (target/('summary-'+result_path.stem+'.json')).write_text(
                json.dumps(summary, sort_keys=True, indent=2)+'\n')
