from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from scripts import sermon_codex_supervisor as cli
from scripts import sermon_production_supervisor as production
from scripts.run_sermon_production_supervisor_agent import SupervisorDecision, supervisor_instructions, verify_decision


def setup(tmp_path, **changes):
    config = production.SupervisorConfig(sunday='2026-10-04', state_file='state.json',
                                         work_root=tmp_path / 'work', gcs_bucket=None)
    args = Namespace(sunday=config.sunday, out=tmp_path / 'report.json', mode='execute',
                     model='gpt-6-luna', reasoning_effort='medium', service_tier='fast',
                     max_turns=5, agent_timeout_seconds=60, agent_run_dir=None,
                     resume_agent_session=False)
    for key, value in changes.items():
        setattr(args, key, value)
    return args, config


def state(action, human=False):
    return {'recommendedAction': {'action': action, 'humanActionRequired': human}}


def decision(action, human=False, status='blocked'):
    return {'tool': 'submit_supervisor_decision', 'arguments': {
        'status': status, 'action': action, 'summary_zh': '依据持久证据',
        'human_action_required': human, 'evidence': []}}


def run(args, config, callback):
    return cli.session_report(args, config, supervisor_instructions('agents-api'),
                              SupervisorDecision, verify_decision, call_json=callback)


def test_cli_advances_guarded_stage_then_stops_for_human(tmp_path):
    args, config = setup(tmp_path)
    current = state('run_timeline_probe')
    calls = []
    def call(prompt, **kwargs):
        calls.append((prompt, kwargs))
        if len(calls) == 1:
            return {'tool': 'run_timeline_probe', 'arguments': {}}
        return decision('request_window_approval', True)
    def prepare(config):
        current.update(state('request_window_approval', True))
        return {'status': 'completed'}
    with patch.object(cli.workflow, 'snapshot', side_effect=lambda config: current), patch.object(production, 'run_timeline_probe', side_effect=prepare) as tool:
        result = run(args, config, call)
    assert result['status'] == 'blocked'
    assert result['decision']['human_action_required'] is True
    assert tool.call_count == 1
    assert len(calls) == 2
    assert calls[0][1]['model'] == 'gpt-6-luna'
    assert calls[0][1]['reasoning'] == 'medium'
    assert calls[0][1]['service_tier'] == 'fast'
    assert calls[0][1]['output_dir'].name == 'turn-001'


def test_unknown_cli_call_cannot_be_reissued_on_resume(tmp_path):
    args, config = setup(tmp_path)
    count = []
    def broken(prompt, **kwargs):
        count.append(1)
        raise TimeoutError('unknown provider outcome')
    with patch.object(cli.workflow, 'snapshot', return_value=state('request_window_approval', True)):
        result = run(args, config, broken)
        args.resume_agent_session = True
        args.agent_run_dir = Path(result['agentSession']['runDirectory'])
        resumed = run(args, config, broken)
    assert count == [1]
    assert resumed['status'] == 'failed'
    assert 'codex_outcome_unknown_inspect_existing_receipt' in resumed['decision']['evidence']


def test_shadow_rejects_mutation_and_has_no_shell_or_approval_tool(tmp_path):
    args, config = setup(tmp_path, mode='shadow')
    def malicious(prompt, **kwargs):
        assert 'run_approved_reading_pdf_generation' not in prompt
        return {'tool': 'run_timeline_probe', 'arguments': {}}
    with patch.object(cli.workflow, 'snapshot', return_value=state('run_timeline_probe')), patch.object(production, 'run_timeline_probe') as tool:
        result = run(args, config, malicious)
    tool.assert_not_called()
    assert result['status'] == 'failed'


def test_unresolved_prior_api_session_blocks_transport_change(tmp_path):
    args, config = setup(tmp_path)
    root = tmp_path / 'agents-api-runs'
    root.mkdir()
    (root / 'run-old').mkdir()
    (root / 'active-old.json').write_text('{"runName":"run-old"}')
    def never(*args, **kwargs):
        raise AssertionError('must not call a new model')
    with patch.object(cli.workflow, 'snapshot', return_value=state('wait_for_active_run')):
        result = run(args, config, never)
    assert result['status'] == 'failed'
    assert 'prior_configuration_session_unresolved_inspect_existing_run' in result['decision']['evidence']


def test_invalid_approval_cannot_be_overridden_by_model(tmp_path):
    args, config = setup(tmp_path, max_turns=1)
    with patch.object(cli.workflow, 'snapshot', return_value=state('request_window_approval', True)), patch.object(production, 'run_reading_pdf_generation') as tool:
        result = run(args, config, lambda *a, **kw: {'tool': 'run_approved_reading_pdf_generation', 'arguments': {}})
    tool.assert_not_called()
    assert result['status'] == 'failed'
