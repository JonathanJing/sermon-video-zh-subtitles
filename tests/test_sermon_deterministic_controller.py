from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_deterministic_controller as ctrl
from scripts.sermon_production_supervisor import SupervisorConfig


def snapshot(action, human=False, **extra):
    return {'workflowScope': 'page_release', 'workflowComplete': action == 'complete',
            'recommendedAction': {'action': action, 'humanActionRequired': human},
            'source': {'sourceId': 'fixture'}, **extra}


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config_path = self.root / 'release.json'
        self.config_path.write_text('{}')
        self.config = SupervisorConfig('2026-09-20', 'fixture-state.json', work_root=self.root,
                                       release_workflow_config=self.config_path, gcs_bucket=None)

    def controller(self, **kwargs):
        return ctrl.Controller(self.config, **kwargs)

    def test_registry_uses_only_existing_actions_with_bounded_policies(self):
        self.assertEqual(set(ctrl.ACTIONS), set(ctrl.workflow.ACTIONS))
        seen = set()
        for action in ctrl.REGISTRY:
            self.assertTrue(set(action.depends_on) <= seen)
            self.assertLessEqual(action.timeout_seconds, 21600)
            self.assertGreater(action.timeout_seconds, 0)
            seen.add(action.name)
        self.assertIn('exact_release_authorization', ctrl.ACTIONS['deploy_release'].human_gates)
        self.assertNotIn('command', json.dumps(ctrl.definition()))

    def test_shadow_has_no_files_dispatch_or_model_calls(self):
        controller = self.controller()
        with patch.object(ctrl.workflow, 'snapshot', return_value=snapshot('build_page')), \
             patch.object(ctrl.workflow, 'start_action') as dispatch:
            result = controller.run()
        self.assertEqual(result['history'][0]['status'], 'ready')
        self.assertEqual(result['runtimeCodexTurns'], 0)
        self.assertFalse(controller.root.exists())
        dispatch.assert_not_called()

    def test_checked_at_does_not_change_revision_but_approval_does(self):
        old = snapshot('build_page', checkedAt='first')
        fresh = {**old, 'checkedAt': 'second'}
        self.assertEqual(ctrl.revision(old), ctrl.revision(fresh))
        fresh['source'] = {'sourceId': 'changed'}
        self.assertNotEqual(ctrl.revision(old), ctrl.revision(fresh))

    def test_no_dispatch_for_human_unknown_wait_or_wrong_scope(self):
        for state in (snapshot('waiting_audio_review', True), snapshot('wait_for_workflow_job'),
                      snapshot('shell_from_remote'), snapshot('complete', workflowScope='dual_pdf'),
                      snapshot('complete', workflowComplete=False)):
            with self.subTest(state=state), patch.object(ctrl.workflow, 'snapshot', return_value=state), \
                 patch.object(ctrl.workflow, 'start_action') as dispatch:
                result = self.controller(mode='deterministic_execute').tick()
                self.assertIn(result['status'], ('blocked', 'waiting'))
                dispatch.assert_not_called()

    def test_existing_durable_dispatch_has_intent_before_side_effect_and_timeout(self):
        controller = self.controller(mode='deterministic_execute')
        def dispatch(config, action, **kwargs):
            state = json.loads((controller.root / 'controller-state.json').read_text())
            self.assertEqual(state['pendingIntent']['action'], action)
            self.assertEqual(kwargs['timeout_seconds'], 600)
            return {'status': 'queued', 'jobId': 'a' * 64}
        with patch.object(ctrl.workflow, 'snapshot', return_value=snapshot('build_page')), \
             patch.object(ctrl.workflow, 'start_action', side_effect=dispatch) as start:
            result = controller.run()
            self.assertEqual(result['history'][0]['status'], 'waiting')
            self.assertEqual(start.call_count, 1)
            repeated = controller.tick()
            self.assertEqual(repeated['reasonCode'], 'intent_requires_reconciliation')
            self.assertEqual(start.call_count, 1)

    def test_dispatch_failure_preserves_uncertainty_and_does_not_retry(self):
        controller = self.controller(mode='deterministic_execute')
        with patch.object(ctrl.workflow, 'snapshot', return_value=snapshot('build_page')), \
             patch.object(ctrl.workflow, 'start_action', side_effect=OSError('PRIVATE')) as start:
            result = controller.tick()
            self.assertEqual(result['reasonCode'], 'dispatch_outcome_unknown')
            self.assertNotIn('PRIVATE', json.dumps(result))
            self.assertEqual(controller.tick()['reasonCode'], 'intent_requires_reconciliation')
            self.assertEqual(start.call_count, 1)

    def test_stale_snapshot_and_changed_configuration_stop_before_dispatch(self):
        controller = self.controller(mode='deterministic_execute')
        with patch.object(ctrl.workflow, 'snapshot', side_effect=[snapshot('build_page'), snapshot('waiting_audio_review', True)]), \
             patch.object(ctrl.workflow, 'start_action') as start:
            self.assertEqual(controller.tick()['reasonCode'], 'stale_state_revision')
            start.assert_not_called()
        self.config_path.write_text('{"changed": true}')
        with patch.object(ctrl.workflow, 'start_action') as start:
            self.assertEqual(controller.tick()['reasonCode'], 'configuration_changed')
            start.assert_not_called()

    def test_version_and_terminal_scope_are_pinned_without_implicit_migration(self):
        controller = self.controller(mode='deterministic_execute')
        with patch.object(ctrl.workflow, 'snapshot', return_value=snapshot('waiting_audio_review', True)):
            controller.tick()
            other = self.controller(mode='deterministic_execute', terminal_scope='delivery_complete')
            self.assertEqual(other.tick()['reasonCode'], 'definition_or_scope_migration_required')
            with patch.object(ctrl, 'DEFINITION_VERSION', 'v-next'):
                newer = self.controller(mode='deterministic_execute')
            self.assertEqual(newer.tick()['reasonCode'], 'definition_or_scope_migration_required')

    def test_page_ready_and_delivery_complete_are_hard_stops(self):
        controller = self.controller(mode='deterministic_execute')
        with patch.object(ctrl.workflow, 'snapshot', return_value=snapshot('prepare_release')), \
             patch.object(ctrl.workflow, 'start_action') as start:
            self.assertEqual(controller.tick()['reasonCode'], 'page_ready')
            self.assertEqual(controller.tick()['status'], 'stopped')
            start.assert_not_called()
        with patch.object(ctrl.workflow, 'snapshot', return_value=snapshot('build_page')), \
             patch.object(ctrl.workflow, 'start_action') as start:
            self.assertEqual(controller.tick()['reasonCode'], 'terminal_evidence_changed')
            start.assert_not_called()
        self.assertEqual(ctrl.recommend(snapshot('complete'), 'delivery_complete')['status'], 'stopped')

    def test_fixed_happy_path_to_page_ready_zero_codex_turns(self):
        controller = self.controller(mode='deterministic_execute')
        actions = ['generate_audio_candidate', 'sync_audio', 'build_page', 'prepare_release']
        cursor = [0]
        def inspect(config):
            return snapshot(actions[cursor[0]])
        def dispatch(config, action, **kwargs):
            self.assertEqual(action, actions[cursor[0]])
            cursor[0] += 1
            return {'jobId': 'a' * 64, 'status': 'succeeded'}
        with patch.object(ctrl.workflow, 'snapshot', side_effect=inspect), \
             patch.object(ctrl.workflow, 'start_action', side_effect=dispatch) as start:
            for _ in range(3):
                self.assertEqual(controller.tick()['status'], 'waiting')
            self.assertEqual(controller.tick()['reasonCode'], 'page_ready')
            self.assertEqual(controller.tick()['runtimeCodexTurns'], 0)
            self.assertEqual(start.call_count, 3)

    def test_blocked_dispatch_is_not_reported_as_launched(self):
        with patch.object(ctrl.workflow, 'snapshot', return_value=snapshot('build_page')), \
             patch.object(ctrl.workflow, 'start_action', return_value={'status': 'blocked'}):
            result = self.controller(mode='deterministic_execute').tick()
            self.assertIs(result['dispatched'], False)
            self.assertEqual(result['reasonCode'], 'dispatch_not_admitted')

    def test_legacy_rollback_does_not_spawn_a_new_agent(self):
        with patch.object(ctrl.workflow, 'snapshot') as inspect, patch.object(ctrl.workflow, 'start_action') as start:
            self.assertEqual(self.controller(mode='legacy_agent').tick()['status'], 'legacy_handoff')
            inspect.assert_not_called(); start.assert_not_called()

    def test_concurrent_controller_cannot_dispatch_under_held_lock(self):
        controller = self.controller(mode='deterministic_execute')
        with ctrl.jobs._lock(controller.root, ctrl.jobs._digest({'purpose': 'deterministic-controller'})) as (_, _, held):
            self.assertTrue(held)
            with patch.object(ctrl.workflow, 'snapshot', return_value=snapshot('build_page')), \
                 patch.object(ctrl.workflow, 'start_action') as start:
                self.assertEqual(controller.tick()['reasonCode'], 'controller_busy')
                start.assert_not_called()

    def test_operator_terminal_scope_never_bypasses_release_authorization(self):
        controller = self.controller(mode='deterministic_execute', terminal_scope='delivery_complete')
        with patch.object(ctrl.workflow, 'snapshot', return_value=snapshot('waiting_release_authorization', True)), \
             patch.object(ctrl.workflow, 'start_action') as start:
            self.assertEqual(controller.tick()['reasonCode'], 'human_or_unknown_gate')
            start.assert_not_called()

    def test_bounds_and_invalid_mode_fail_closed(self):
        with self.assertRaises(ValueError):
            self.controller(mode='remote_flag')
        for value in (0, 33, True):
            with self.assertRaises(ValueError):
                self.controller().run(value)
        with self.assertRaises(ValueError):
            ctrl.Controller(replace(self.config, release_workflow_config=None))


if __name__ == '__main__':
    unittest.main()
