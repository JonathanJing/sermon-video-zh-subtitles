import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch, Mock

from scripts import sermon_end_to_end as flow
from scripts import sermon_agents_supervisor as agent
from scripts import run_sermon_production_supervisor_agent as entry
from scripts.sermon_production_supervisor import SupervisorConfig


def state(action='complete', **extra):
    return {'recommendedAction': {'action': action, 'humanActionRequired': False}, **extra}


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root/'release.json'
        self.path.write_text('{}')
        self.config = SupervisorConfig('2026-09-20', 'state.json', work_root=self.root,
                                       release_workflow_config=self.path)

    def test_default_keeps_existing_snapshot_and_tool_surface(self):
        config = replace(self.config, release_workflow_config=None)
        upstream = state()
        with patch.object(flow.production, 'production_snapshot', return_value=upstream):
            self.assertIs(flow.snapshot(config), upstream)
        names = {t['name'] for t in agent.tool_definitions(True, {})}
        self.assertNotIn('deploy_release', names)

    def test_pdf_complete_is_not_page_complete(self):
        with patch.object(flow.production, 'production_snapshot', return_value=state()), \
             patch('scripts.sermon_release_workflow.load_config'), \
             patch('scripts.sermon_release_workflow.snapshot', return_value=state('build_page')):
            observed = flow.snapshot(self.config)
        self.assertFalse(observed['workflowComplete'])
        self.assertEqual(observed['recommendedAction']['action'], 'build_page')
        minimal = agent.remote_snapshot({**observed, 'releaseWorkflow': {'secret': 'private'}}, self.config.sunday)
        self.assertNotIn('private', json.dumps(minimal))
        self.assertEqual(minimal['schemaVersion'], 'sermon-agent-state-minimal-v2')

    def test_upstream_gate_still_blocks_downstream(self):
        with patch.object(flow.production, 'production_snapshot', return_value=state('request_window_approval')), \
             patch('scripts.sermon_release_workflow.load_config'), \
             patch('scripts.sermon_release_workflow.snapshot') as downstream:
            observed = flow.snapshot(self.config)
        downstream.assert_not_called()
        self.assertFalse(observed['workflowComplete'])

    def test_active_and_uncertain_jobs_cannot_claim_completion(self):
        root = flow.job_root(self.config, self.path)
        root.mkdir(parents=True)
        (root/'active.json').write_text(json.dumps({'jobId': 'abc', 'action': 'deploy_release'}))
        for status, action in [('running', 'wait_for_workflow_job'), ('uncertain', 'inspect_workflow_job_failure'),
                               ('failed', 'inspect_workflow_job_failure')]:
            with self.subTest(status=status), patch.object(flow.production, 'production_snapshot', return_value=state()), \
                 patch('scripts.sermon_release_workflow.load_config'), \
                 patch('scripts.sermon_release_workflow.snapshot', return_value=state()), \
                 patch('scripts.sermon_workflow_jobs.inspect_job', return_value={'jobId': 'abc', 'status': status}):
                observed = flow.snapshot(self.config)
            self.assertEqual(observed['recommendedAction']['action'], action)
            self.assertFalse(observed['workflowComplete'])

    def test_exit_zero_without_expected_artifacts_does_not_retry(self):
        root=flow.job_root(self.config,self.path);root.mkdir(parents=True)
        (root/'active.json').write_text(json.dumps({'jobId':'abc','action':'build_page'}))
        with patch.object(flow.production,'production_snapshot',return_value=state()), \
             patch('scripts.sermon_release_workflow.load_config'), \
             patch('scripts.sermon_release_workflow.snapshot',return_value=state('build_page')), \
             patch('scripts.sermon_workflow_jobs.inspect_job',return_value={'jobId':'abc','status':'succeeded'}):
            observed=flow.snapshot(self.config)
        self.assertEqual(observed['recommendedAction']['action'],'inspect_workflow_evidence')

    def test_fixed_job_command_and_configuration_binding(self):
        with patch.object(flow,'snapshot',return_value=state('build_page',locations={'runRoot':str(self.root/'source')})), \
             patch('scripts.sermon_workflow_jobs.start_job',return_value={'jobId':'abc','status':'queued'}) as start:
            flow.job_root(self.config,self.path).mkdir(parents=True)
            observed=flow.start_action(self.config,'build_page')
        command=start.call_args.args[2]
        self.assertEqual(command[command.index('--expected-config-sha')+1],flow.config_hash(self.path))
        self.assertIn('build_page',command)
        self.assertEqual(observed['status'],'queued')
        self.assertNotIn('command',observed)

    def test_agent_cannot_deploy_in_shadow_or_when_not_recommended(self):
        for execute, expected in [(False,'shadow_mode'),(True,'current_state_does_not_allow_stage')]:
            folder=self.root/str(execute);folder.mkdir()
            tools=agent.ProductionTools(self.config,execute,folder,entry.SupervisorDecision)
            with patch.object(flow,'snapshot',return_value=state('waiting_audio_review')), \
                 patch.object(flow,'start_action') as run:
                tools('inspect_production_state',{})
                result=tools('deploy_release',{})
            self.assertEqual(result['reasonCode'],expected)
            run.assert_not_called()

    def test_remote_tools_have_no_model_supplied_paths_or_commands(self):
        definitions=agent.tool_definitions(True,{},True)
        names={t['name'] for t in definitions}
        for action in flow.ACTIONS:
            self.assertIn(action,names)
            tool=next(t for t in definitions if t['name']==action)
            self.assertEqual(tool['parameters']['properties'],{})

    def test_source_change_cannot_advance_an_unrelated_same_week_job(self):
        downstream = state('build_page', evidence={'sourceRunRoot': str(self.root/'other-source')})
        with patch.object(flow.production, 'production_snapshot', return_value=state(locations={'runRoot': str(self.root/'source')})), \
             patch('scripts.sermon_release_workflow.load_config'), \
             patch('scripts.sermon_release_workflow.snapshot', return_value=downstream):
            with self.assertRaisesRegex(ValueError, 'does not match'):
                flow.snapshot(self.config)

    def test_config_edit_invalidates_existing_agent_tool_session(self):
        from scripts.sermon_agents_api import AgentsAPIError
        folder=self.root/'session';folder.mkdir()
        tools=agent.ProductionTools(self.config,True,folder,entry.SupervisorDecision)
        self.path.write_text('{"changed":true}')
        with self.assertRaisesRegex(AgentsAPIError,'production_configuration_changed'):
            tools('inspect_production_state',{})

    def test_config_change_cannot_abandon_old_running_job(self):
        old=flow.job_root(self.config,self.path);old.mkdir(parents=True)
        (old/'active.json').write_text(json.dumps({'jobId':'old','action':'build_page'}))
        self.path.write_text('{"new":true}')
        with patch.object(flow.production,'production_snapshot',return_value=state()), \
             patch('scripts.sermon_release_workflow.load_config'), \
             patch('scripts.sermon_release_workflow.snapshot',return_value=state('build_page')), \
             patch('scripts.sermon_workflow_jobs.inspect_job',return_value={'jobId':'old','status':'running'}):
            observed=flow.snapshot(self.config)
        self.assertEqual(observed['recommendedAction']['action'],'inspect_workflow_job_failure')
        self.assertFalse(observed['workflowComplete'])

    def test_only_safe_job_identity_reaches_agent(self):
        job={'jobId':'a'*64,'status':'running','command':['secret'],'path':'private'}
        value=agent.remote_snapshot(state('wait_for_workflow_job',workflowScope='page_release',workflowJob=job),self.config.sunday)
        self.assertEqual(value['workflowJob'],{'jobId':'a'*64,'status':'running'})
        self.assertNotIn('private',json.dumps(value))
        self.assertEqual(agent.safe_workflow_job({'jobId':'/private/path','status':'running'}),{})

    def test_default_config_binding_retains_legacy_fields(self):
        from dataclasses import asdict
        config=replace(self.config,release_workflow_config=None)
        legacy=asdict(config);legacy.pop('release_workflow_config')
        self.assertEqual(agent.bound_configuration(config),legacy)
