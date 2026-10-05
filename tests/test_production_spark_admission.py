"""Real entrypoints must fail before dispatch; offline seams are explicit."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import production_spark_admission as admission
from scripts import spark_exclusive_session as sessions
from scripts import mfa_spark, render_formal_target_language_speech as speech
from scripts import sermon_source_budget as budgets
from scripts import run_codex_layer2_test as layer2
from tests import test_codex_layer2_diagnostic as fixtures


class ProductionSessionCallTests(unittest.TestCase):
    def client(self):
        client = Mock()
        client.start_job.return_value = {'jobId': 'test-job'}
        client.require_ready.return_value = {'jobId':'test-job','status':'running'}
        return client

    def test_atomic_job_reservation_precedes_dispatch_and_terminal_releases(self):
        events = []
        client = self.client()
        client.start_job.side_effect = lambda purpose: events.append(('start', purpose)) or {'jobId': 'test-job'}
        client.end_job.side_effect = lambda *a, **kw: events.append(('end', kw))
        caller = admission.SessionBoundCaller(lambda: events.append(('call', None)) or {'ok': True})
        with patch.object(sessions.Client, 'from_environment', return_value=client):
            self.assertEqual(caller(), {'ok': True})
        self.assertEqual([event[0] for event in events], ['start', 'call', 'end'])
        self.assertEqual(events[-1][1], {'process_exited': True, 'outcome': 'known_terminal'})

    def test_denied_reservation_never_dispatches(self):
        client = self.client();client.start_job.side_effect = sessions.SessionError('session_not_ready')
        real = Mock()
        with patch.object(sessions.Client, 'from_environment', return_value=client):
            with self.assertRaisesRegex(sessions.SessionError, 'session_not_ready'):
                admission.SessionBoundCaller(real)()
        real.assert_not_called();client.end_job.assert_not_called()

    def test_invalid_callable_signature_fails_before_durable_hold(self):
        def real(prompt, *, model):
            raise AssertionError('callable body must not execute')
        client = self.client()
        with patch.object(sessions.Client, 'from_environment', return_value=client):
            with self.assertRaisesRegex(sessions.SessionError, 'arguments_invalid_before_dispatch'):
                admission.SessionBoundCaller(real)("prompt", model="gpt-6-luna", resource_class="supervisor")
        client.start_job.assert_not_called()
        client.end_job.assert_not_called()

    def test_unknown_preserves_original_exception_and_hold(self):
        client = self.client();client.end_job.side_effect = sessions.SessionError('job_requires_reconciliation')
        real = Mock(side_effect=TimeoutError('real call unknown'))
        with patch.object(sessions.Client, 'from_environment', return_value=client):
            with self.assertRaisesRegex(TimeoutError, 'real call unknown'):
                admission.SessionBoundCaller(real)()
        client.end_job.assert_called_once_with({'jobId': 'test-job'}, process_exited=False, outcome='unknown')

    def test_explicit_injected_verifier_checks_each_call_and_pre_dispatch_admission(self):
        checks = Mock(); real = Mock(); real.execution_identity = {'backend': 'fixture'}
        wrapped = admission.SessionBoundCaller(real, verifier=checks)
        self.assertEqual(wrapped.execution_identity, real.execution_identity)
        wrapped.admit_resource({'model': 'fixture'})
        wrapped('call')
        self.assertEqual(checks.call_count, 2)
        real.assert_called_once_with('call')

    def test_native_model_gate_requires_exact_live_parent_identity(self):
        client = self.client(); client.session_id='session'; client.owner='owner'
        client.require_ready.return_value={'status':'running','bootId':'boot'}
        job={'status':'active','sessionId':'session','owner':'owner',
             'processes':[{'pid':11,'startTicks':100}]}
        status={'session':{'sessionId':'session','owner':'owner','status':'running','jobs':{'held':job}},
            'inventory':{'host':'spark','bootId':'boot','processes':[
                {'pid':11,'ppid':1,'startTicks':100},{'pid':24,'ppid':11,'startTicks':200}]}}
        client.request.return_value=status
        with patch.dict('os.environ', {'SPARK_EXCLUSIVE_JOB_ID':'held'}, clear=True), \
             patch.object(sessions.Client,'from_environment',return_value=client), \
             patch.object(admission,'_native_process_identity',return_value=(24,200,'spark','boot')):
            self.assertEqual(admission.require_bound_model_session()['jobId'],'held')
            job['processes'][0]['startTicks']=999
            with self.assertRaisesRegex(sessions.SessionError,'bound_live_parent'):
                admission.require_bound_model_session()
            job['processes'][0]['startTicks']=100;job['status']='unknown'
            with self.assertRaisesRegex(sessions.SessionError,'bound_live_parent'):
                admission.require_bound_model_session()

    def test_ready_session_without_gpu_parent_job_is_insufficient(self):
        client=self.client()
        with patch.dict('os.environ',{},clear=True), \
             patch.object(sessions.Client,'from_environment',return_value=client):
            with self.assertRaisesRegex(sessions.SessionError,'bound_live_parent'):
                admission.require_bound_model_session()
        client.start_job.assert_not_called()

    def test_container_without_verified_parent_receipt_denies(self):
        client=self.client();client.require_ready.return_value={'status':'running'}
        with patch.dict('os.environ',{'SPARK_EXCLUSIVE_SOCKET':'/test/job.sock'},clear=True), \
             patch.object(sessions.Client,'from_environment',return_value=client):
            with self.assertRaisesRegex(sessions.SessionError,'parent_job_binding_required'):
                admission.require_bound_model_session()

    def test_container_gateway_is_readonly_and_parent_hold_protects_call(self):
        client = self.client(); real = Mock(return_value={"ok": True})
        with patch.dict("os.environ", {"SPARK_EXCLUSIVE_SOCKET":"/test-only/job.sock"}), \
             patch.object(sessions.Client, "from_environment", return_value=client):
            self.assertEqual(admission.SessionBoundCaller(real)(), {"ok": True})
        client.require_ready.assert_called_once_with()
        client.start_job.assert_not_called(); client.end_job.assert_not_called()

    def test_legacy_notes_and_reading_cli_deny_before_side_effects(self):
        from scripts import generate_notes_with_openai as notes
        from scripts import build_sermon_reading_edition_with_openai as reading
        client = self.client(); client.start_job.side_effect = sessions.SessionError("session_not_ready")
        with patch.object(sessions.Client, "from_environment", return_value=client), \
             patch.object(notes.requests, "post") as notes_api, patch.object(reading.subprocess, "run") as reading_cli:
            with self.assertRaisesRegex(sessions.SessionError, "session_not_ready"):
                notes.request_openai_notes({"model":"test"}, "test-only")
            with self.assertRaisesRegex(sessions.SessionError, "session_not_ready"):
                reading.codex_json({"messages":[]}, codex_cli=Path("unused"), model="test",
                    reasoning_effort="medium", schema_path=Path("unused"), output_path=Path("unused"))
        notes_api.assert_not_called(); reading_cli.assert_not_called()

    def test_legacy_page_text_and_source_audio_deny_before_side_effects(self):
        from scripts import sermon_pipeline as pipeline
        client = self.client(); client.start_job.side_effect = sessions.SessionError("session_not_ready")
        with patch.object(sessions.Client, "from_environment", return_value=client), \
             patch.object(pipeline, "json_request") as text, patch.object(pipeline, "multipart_request") as audio:
            with self.assertRaisesRegex(sessions.SessionError, "session_not_ready"):
                pipeline.chat_json("test-only", {"model":"gpt-6-astra"})
            with self.assertRaisesRegex(sessions.SessionError, "session_not_ready"):
                pipeline.transcribe_openai_audio("test-only", "gpt-transcribe", "source", Path("nonexistent"))
        text.assert_not_called(); audio.assert_not_called()

    def test_qwen_constructors_deny_before_import_or_model_load(self):
        def denied():raise sessions.SessionError('session_not_ready')
        from scripts.experiments.replay_fixed_clip_local_models import LocalASR
        for cls in (speech.QwenSynthesizer, speech.SparkQwenSynthesizer):
            with self.subTest(cls=cls.__name__):
                with self.assertRaisesRegex(sessions.SessionError, 'session_not_ready'):
                    cls(Path('nonexistent'), device='cuda:0', dtype='bfloat16', attention='sdpa', session_verifier=denied)
        with self.assertRaisesRegex(sessions.SessionError, "session_not_ready"):
            LocalASR(Path("nonexistent"), device="cuda:0", session_verifier=denied)

    def test_source_budget_denies_before_budget_started_or_network(self):
        authority = {'approvalSha256': 'a' * 64,
            'globalBounds': {'requests': 2, 'wallTimeMs': 2000, 'costMicrousd': 2000},
            'requestLimits': dict(budgets.text_limits.DEFAULT_REQUEST_LIMITS)}
        with tempfile.TemporaryDirectory() as directory:
            store = budgets.SourceBudget(Path(directory), authority, verify=lambda: None)
            with patch.object(budgets.spark_admission, 'require_session', side_effect=sessions.SessionError('session_not_ready')), \
                 patch.object(budgets.http, 'execute') as network:
                with self.assertRaisesRegex(sessions.SessionError, 'session_not_ready'):
                    store.call(operation='asr.0000', identity={'model':'gpt-transcribe'},
                        bounds={'requests':1,'wallTimeMs':1000,'costMicrousd':1000}, request=b'audio',
                        api_key='test-only-not-a-secret', content_type='audio/wav', endpoint='https://invalid.example/audio')
                network.assert_not_called()
            ledger = Path(directory) / 'source-budget.json'
            self.assertFalse(ledger.exists(), 'Admission denial must not reserve provider budget')

    def test_mfa_alignment_denies_before_ssh_and_keeps_preflight_readonly(self):
        options = dict(host='user@spark', python='/env/bin/python', root='/jobs',
            mfa_executable='/env/bin/mfa', dictionary_path='/models/dict', acoustic_model='/models/acoustic')
        with patch.object(mfa_spark.spark_admission, 'require_session', side_effect=sessions.SessionError('session_not_ready')), \
             patch.object(mfa_spark.subprocess, 'run') as ssh:
            with self.assertRaisesRegex(sessions.SessionError, 'session_not_ready'):
                mfa_spark._call('align', chunks=[{'text':'Source.'}], clip_path=Path('unread-file'), **options)
            ssh.assert_not_called()

    def test_diagnostic_layer2_denies_before_real_transport_construction(self):
        fixture = fixtures.DiagnosticChainTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.freeze()
        with patch.object(layer2.spark_admission, 'require_session', side_effect=sessions.SessionError('session_not_ready')), \
             patch.object(layer2, 'CodexLayer2Transport') as transport:
            with self.assertRaisesRegex(sessions.SessionError, 'session_not_ready'):
                layer2.run_diagnostic_test(fixture.fixture, fixture.out, cli_path=Path('unused'))
            transport.assert_not_called()


def test_normal_supervisor_default_cli_denies_before_pending_or_model(tmp_path):
    from scripts import sermon_codex_supervisor as supervisor
    from scripts import sermon_codex_transport as transport
    from tests import test_sermon_codex_supervisor as support
    from scripts.run_sermon_production_supervisor_agent import SupervisorDecision, supervisor_instructions, verify_decision
    args, config = support.setup(tmp_path)
    with patch.object(supervisor.workflow, 'snapshot', return_value=support.state('request_window_approval', True)), \
         patch.object(supervisor.spark_admission, 'require_session', side_effect=sessions.SessionError('session_not_ready')), \
         patch.object(transport, 'call_json') as real:
        result = supervisor.session_report(args, config, supervisor_instructions('agents-api'),
            SupervisorDecision, verify_decision)
        real.assert_not_called()
    assert result['status'] == 'failed'
    directory = Path(result['agentSession']['runDirectory'])
    state = supervisor.guarded.read_object(directory / 'codex-state.json')
    assert state['pending'] is False and state['turns'] == 0
