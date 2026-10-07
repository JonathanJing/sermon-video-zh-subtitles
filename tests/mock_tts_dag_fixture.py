"""Existing diagnostic fixtures plus exact group-level synthetic TTS policy."""
from copy import deepcopy

# Load this closure before the original continuation records its code identity.
from scripts import sermon_mock_tts_dag as dag
from scripts import sermon_mock_tts_control as control
from tests.diagnostic_dag_fixture import DiagnosticDAGFixture


class MockTTSDAGFixture(DiagnosticDAGFixture):
    def dag_config(self, *, faults=None, observation_timeout=45):
        units = {locale+'.'+group['translationGroupId']: locale
            for locale, spec in self.locale_specs.items() for group in spec['groupPlan']}
        return {'schemaVersion': dag.SCHEMA,
            'diagnostic': {'schemaVersion': dag.diagnostic.SCHEMA, 'locales': {locale: {
                'localeSpec': deepcopy(spec), 'previewSpec': deepcopy(self.preview_specs[locale])}
                for locale, spec in self.locale_specs.items()}},
            'mockPolicy': {'schemaVersion': control.POLICY, 'units': units,
                'maxJobs': 2*len(units), 'maxAttemptsPerUnit': 2, 'maxConcurrentJobs': 2,
                'workerTimeoutSeconds': 60, 'observationTimeoutSeconds': observation_timeout},
            'faults': deepcopy(faults or {})}


def resume_in_clean_process(payload_path):
    """Restore the exact original fixture module inventory; never change identity."""
    import importlib
    import json
    from pathlib import Path
    from scripts import sermon_accounting as accounting
    from scripts import sermon_bounded_business_callbacks as offline
    from scripts import sermon_review_contracts as c
    from scripts.sermon_diagnostic_dag_session import DiagnosticSession
    value = json.loads(Path(payload_path).read_text())
    expected = value['continuation']['executionIdentity']
    for name, digest in expected['loadedProjectCodeSha256'].items():
        assert name.startswith('scripts/') and name.endswith('.py')
        path = dag.diagnostic.pilot.REPO/name
        assert c.bytes_sha256(path.read_bytes()) == digest
        importlib.import_module(name[:-3].replace('/', '.'))
    assert accounting.execution_identity() == expected, 'clean resume code identity must match exactly'
    replies = []
    def fixture_reply(request, timeout, *, deadline):
        assert value.get('allowNewFixtureResponses') is True, 'normal repeat must not call the synthetic provider'
        payload = json.loads(request.data)
        inputs = json.loads(payload['messages'][1]['content'])
        assert 'translationGroupId' in inputs, 'existing Source must never be redispatched'
        if payload['model'] == 'gpt-6-astra':
            group = next(row for row in value['fixtureGroups'] if row['translationGroupId'] == inputs['translationGroupId'])
            body = {key: group[key] for key in ('translationGroupId', 'sourceUnitIds', 'targetUtterances', 'coverage')}
        else:
            assert payload['model'] == 'gpt-6-sol'
            body = {'reviewedArtifactSha256': inputs['reviewedArtifactSha256'], 'reviewVerdict': 'pass',
                'checks': [{'checkId': key, 'result': 'pass', 'evidence': 'synthetic'} for key in sorted(c.HARD_CHECKS)],
                'issues': [], 'assessedUnitIds': inputs['sourceUnitIds'], 'unassessedUnitIds': []}
        replies.append(body)
        return {'id': 'capture-'+str(len(replies)), 'model': payload['model'],
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(body)}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}
    transport = offline.OfflineHTTPTransport(fixture_reply, fixture_id='diagnostic-dag-fixture')
    session = DiagnosticSession(value['plan'], value['continuation'], offline_transport=transport, request_limits=DiagnosticDAGFixture.request_limits)
    result = dag.run(session, value['config'], recovery=value.get('recovery'))
    Path(value['resumeResultPath']).write_text(json.dumps(result))
    assert len(transport.observations) == (4 if value.get('allowNewFixtureResponses') else 0), transport.observations
    return result
