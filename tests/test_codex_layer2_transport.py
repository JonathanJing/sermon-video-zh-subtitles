"""CLI transport receipts and cache recovery must stay distinct from API calls."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from jsonschema import ValidationError

from scripts import run_target_language_models as runner
from scripts.codex_layer2_transport import CodexLayer2Transport, output_schema
from scripts import run_codex_layer2_test as command


class CodexPreDispatchBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.out = self.root / "unfinished-run"
        self.context = {"runnerImplementationSha256": "a" * 64,
                        "commandImplementationSha256": "b" * 64, "simulationOnly": True}
        self.marker = self.root / "unfinished-run-pre-dispatch-context.json"

    def test_hard_kill_before_output_creation_keeps_binding_and_rejects_changed_code(self):
        command.bind_context(self.out, self.context)
        self.assertFalse(self.out.exists())
        self.assertEqual(json.loads(self.marker.read_text()), self.context)
        self.assertEqual(self.marker.stat().st_mode & 0o777, 0o600)
        command.bind_context(self.out, self.context)
        changed = {**self.context, "runnerImplementationSha256": "c" * 64}
        with self.assertRaisesRegex(ValueError, "pre-dispatch context changed"):
            command.bind_context(self.out, changed)
        self.assertEqual(json.loads(self.marker.read_text()), self.context)

    def test_legacy_manifest_without_any_context_cannot_gain_resume_binding(self):
        self.out.mkdir()
        (self.out / "run-identity.json").write_text('{"sha256":"legacy"}')
        with self.assertRaisesRegex(ValueError, "reconcile before resume"):
            command.bind_context(self.out, self.context)
        self.assertFalse(self.marker.exists())

    def test_existing_final_context_must_match_before_legacy_binding(self):
        self.out.mkdir()
        (self.out / "run-identity.json").write_text('{"sha256":"legacy"}')
        (self.out / "test-context.json").write_text(json.dumps(self.context))
        command.bind_context(self.out, self.context)
        self.assertTrue(self.marker.exists())
        with self.assertRaisesRegex(ValueError, "implementation or context changed"):
            command.bind_context(self.out, {**self.context, "simulationOnly": False})


class CodexTestCommandGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Path(temporary.name)
        self.scope = {"simulationOnly": True, "productionEligible": False, "actualHumanApproval": False}
        self.source = {"source": {"media": {"sha256":
            "79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b"}}}
        self.anchor = {"sourceUnits": [{"sourceUnitId": f"u{index}", "english": "Source."}
                                       for index in range(39)]}
        self.policy = {"targetLocale": "zh-Hans", "batching": {"batchSize": 1, "workers": 1}}
        self.out = Path(command.__file__).resolve().parents[1] / "artifacts" / "never-dispatched-gate-fixture"

    def invoke_rejected(self, reason, out=None):
        for name, value in (("simulation-scope-report.json", self.scope), ("source.json", self.source),
                            ("anchor.json", self.anchor), ("policy.json", self.policy)):
            (self.fixture / name).write_text(json.dumps(value))
        with patch("scripts.run_codex_layer2_test.CodexLayer2Transport") as transport:
            with self.assertRaisesRegex(ValueError, reason):
                command.run_test(self.fixture, self.fixture / "policy.json", out or self.out,
                                 cli_path=Path("unused-codex"))
            transport.assert_not_called()

    def test_formal_or_approved_scope_is_rejected_before_transport(self):
        for field, value in (("simulationOnly", False), ("productionEligible", True),
                             ("actualHumanApproval", True)):
            with self.subTest(field=field):
                self.scope = {"simulationOnly": True, "productionEligible": False, "actualHumanApproval": False}
                self.scope[field] = value
                self.invoke_rejected("explicitly simulated")

    def test_output_must_be_dedicated_ignored_directory(self):
        self.invoke_rejected("dedicated ignored", out=self.fixture / "not-artifacts")
        self.invoke_rejected("dedicated ignored", out=self.out.parent)

    def test_other_locale_or_multiple_workers_are_rejected_before_transport(self):
        self.policy["targetLocale"] = "es"
        self.invoke_rejected("zh-Hans only")
        self.policy["targetLocale"] = "zh-Hans"
        self.policy["batching"]["workers"] = 2
        self.invoke_rejected("one group and locale")

    def test_changed_media_or_missing_units_are_rejected_before_transport(self):
        self.source["source"]["media"]["sha256"] = "f" * 64
        self.invoke_rejected("frozen fixed three-minute")
        self.source["source"]["media"]["sha256"] = "79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b"
        self.anchor["sourceUnits"].pop()
        self.invoke_rejected("frozen fixed three-minute")


class CodexRuntimeBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.transport = CodexLayer2Transport.__new__(CodexLayer2Transport)
        self.transport.cli_path = self.root / "fake-codex"
        self.transport.timeout_seconds = 10
        self.transport.receipts_dir = self.root / "receipts"
        self.transport.env = {"PATH": "/fixture/bin"}
        self.transport.tiers = {"translator": "default", "reviewer": "fast"}
        self.transport.execution_identity = {"backend": "codex_cli", "version": "fixture-runtime"}
        self.payload = {"model": "gpt-6-astra", "reasoning_effort": "medium", "messages": [
            {"role": "system", "content": "Translate only the frozen units."},
            {"role": "user", "content": '{"english":"Hello."}'}]}
        self.result = {"translationGroupId": "g1", "sourceUnitIds": ["u1"],
                       "targetUtterances": ["你好。"],
                       "coverage": [{"sourceUnitId": "u1", "targetText": "你好。"}]}

    def process(self, *, completed=True, tool=False, exit_code=0, mismatch=False):
        def fake_run(command, **kwargs):
            content = json.dumps(self.result, ensure_ascii=False)
            (Path(kwargs["cwd"]) / "result.json").write_text(content + "\n")
            rows = [{"type": "thread.started", "thread_id": "runtime-thread"},
                    {"type": "turn.started"},
                    {"type": "item.completed", "item": {"type": "agent_message",
                     "text": "{}" if mismatch else content}}]
            if tool:
                rows.append({"type": "item.completed", "item": {"type": "command_execution"}})
            if completed:
                rows.append({"type": "turn.completed", "usage": {
                    "input_tokens": 100, "cached_input_tokens": 50, "output_tokens": 20}})
            return subprocess.CompletedProcess(command, exit_code,
                stdout="\n".join(json.dumps(row) for row in rows), stderr="fixture stderr")
        return fake_run

    def test_runtime_success_has_own_envelope_and_matching_output(self):
        with patch("scripts.codex_layer2_transport.subprocess.run", side_effect=self.process()) as run:
            response = self.transport("", self.payload)
        self.assertEqual(response["id"], "codex:runtime-thread")
        self.assertEqual(response["requestedModel"], "gpt-6-astra")
        self.assertIsNone(response["serverModel"])
        self.assertEqual(json.loads(CodexLayer2Transport.completed_content(
            response, "gpt-6-astra", "translator")), self.result)
        self.assertEqual(response["usage"]["output_tokens"], 20)
        self.assertEqual(run.call_args.kwargs["env"], self.transport.env)
        self.assertEqual(len(list(self.transport.receipts_dir.glob("*/response.json"))), 1)

    def test_sol61_high_fast_configuration_requests_and_records_exact_model(self):
        from scripts.codex_layer2_transport import TEST_CONFIGURATION
        self.transport.models = {role: TEST_CONFIGURATION[role]['model'] for role in ('translator', 'reviewer')}
        self.transport.tiers = {'translator': 'fast', 'reviewer': 'fast'}
        self.transport.simulation_model_configuration = TEST_CONFIGURATION
        self.payload.update(model='gpt-6.1-sol', reasoning_effort='high', service_tier='fast')
        with patch('scripts.codex_layer2_transport.subprocess.run', side_effect=self.process()) as run:
            response = self.transport('', self.payload)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index('-m') + 1], 'gpt-6.1-sol')
        self.assertIn('model_reasoning_effort="high"', command)
        self.assertIn('service_tier="fast"', command)
        self.assertIn('fast_mode', command)
        self.assertEqual(response['requestedModel'], 'gpt-6.1-sol')
        self.assertEqual(response['requestedReasoningEffort'], 'high')
        self.assertEqual(response['requestedServiceTier'], 'fast')
        self.assertIsNone(response['serverModel'])
        self.assertEqual(CodexLayer2Transport.completed_content(response, 'gpt-6.1-sol', 'translator'), response['content'])
        with self.assertRaises(ValueError):
            CodexLayer2Transport.completed_content(response, 'gpt-6.1-sol', 'reviewer')
        self.payload['reasoning_effort'] = 'medium'
        with patch('scripts.codex_layer2_transport.subprocess.run') as blocked:
            with self.assertRaisesRegex(ValueError, 'configuration_changed'):
                self.transport('', self.payload)
            blocked.assert_not_called()

    def test_default_transport_cannot_dispatch_new_translator_model(self):
        self.payload['model'] = 'gpt-6.1-sol'
        with patch('scripts.codex_layer2_transport.subprocess.run') as blocked:
            with self.assertRaisesRegex(ValueError, 'unsupported_codex_language_model'):
                self.transport('', self.payload)
            blocked.assert_not_called()

    def test_runtime_rejects_incomplete_tool_or_failed_process(self):
        cases = {"missing-completion": {"completed": False}, "tool": {"tool": True},
                 "nonzero-exit": {"exit_code": 2}}
        for name, options in cases.items():
            with self.subTest(name=name), patch("scripts.codex_layer2_transport.subprocess.run",
                                                side_effect=self.process(**options)):
                with self.assertRaisesRegex(RuntimeError, "terminal_or_tool_failure"):
                    self.transport("", self.payload)
        self.assertEqual(len(list(self.transport.receipts_dir.glob("*/events.jsonl"))), 3)
        self.assertEqual(list(self.transport.receipts_dir.glob("*/response.json")), [])

    def test_runtime_rejects_stdout_file_disagreement(self):
        with patch("scripts.codex_layer2_transport.subprocess.run", side_effect=self.process(mismatch=True)):
            with self.assertRaisesRegex(RuntimeError, "final_message_file_mismatch"):
                self.transport("", self.payload)

    def test_fast_reviewer_runtime_requests_fast_without_api_key(self):
        self.payload["model"] = "gpt-6-sol"
        self.result["semanticReview"] = {"status": "pass", "checks": {
            key: "pass" for key in runner.SEMANTIC_CHECKS}, "evidence": "Meaning preserved.",
            "uncertainty": [], "issues": []}
        with patch("scripts.codex_layer2_transport.subprocess.run", side_effect=self.process()) as run:
            response = self.transport("", self.payload)
        command = run.call_args.args[0]
        self.assertIn('service_tier="fast"', command)
        self.assertIn("fast_mode", command)
        self.assertEqual(response["requestedServiceTier"], "fast")
        with patch("scripts.codex_layer2_transport.subprocess.run") as blocked:
            with self.assertRaisesRegex(ValueError, "must_not_receive_api_key"):
                self.transport("fixture-secret", self.payload)
            blocked.assert_not_called()

    def test_runtime_timeout_preserves_receipt_and_runner_unknown_marker(self):
        output = self.root / "group-astra.json"
        policy = {"translator": {"model": "gpt-6-astra", "reasoningEffort": "medium"}}
        prompt = {"instruction": "Translate.", "input": {"english": "Hello."}}
        error = subprocess.TimeoutExpired("fake-codex", 10, output=b"partial events", stderr=b"partial error")
        with patch("scripts.codex_layer2_transport.subprocess.run", side_effect=error) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                runner._model_call("translator", prompt, policy, output, "", self.transport)
            with self.assertRaises(ValueError):
                runner._model_call("translator", prompt, policy, output, "", self.transport)
            self.assertEqual(run.call_count, 1)
        self.assertTrue(output.with_suffix(".started.json").exists())
        failure_paths = list(self.transport.receipts_dir.glob("*/failure.json"))
        self.assertEqual(len(failure_paths), 1)
        self.assertEqual(json.loads(failure_paths[0].read_text())["status"], "unknown_outcome")
        self.assertFalse(output.exists())

    def test_constructor_strips_api_environment_and_requires_chatgpt(self):
        cli = self.root / "codex-wrapper"
        cli.write_text("fixture wrapper")
        auth_root = self.root / "auth-home"
        auth_root.mkdir()
        auth_path = auth_root / "auth.json"
        auth_path.write_text(json.dumps({"auth_mode": "chatgpt"}))
        environment = {"CODEX_HOME": str(auth_root), "OPENAI_API_KEY": "fixture-key",
                       "OPENAI_DEV_API_KEY": "fixture-dev-key", "CODEX_API_KEY": "fixture-codex-key"}
        with patch.dict(os.environ, environment), patch(
                "scripts.codex_layer2_transport.subprocess.check_output", return_value="codex fixture-v1"):
            transport = CodexLayer2Transport(cli_path=cli)
            self.assertFalse(any(key.startswith("OPENAI_") for key in transport.env))
            self.assertNotIn("CODEX_API_KEY", transport.env)
            auth_path.write_text(json.dumps({"auth_mode": "apikey"}))
            with self.assertRaisesRegex(ValueError, "requires_chatgpt_auth"):
                CodexLayer2Transport(cli_path=cli)


class CodexCompletedReceiptTests(unittest.TestCase):
    def receipt(self, reviewer=False):
        result = {"translationGroupId": "g1", "sourceUnitIds": ["u1"],
                  "targetUtterances": ["中文。"],
                  "coverage": [{"sourceUnitId": "u1", "targetText": "中文。"}]}
        if reviewer:
            result["semanticReview"] = {"status": "pass", "checks": {
                key: "pass" for key in runner.SEMANTIC_CHECKS},
                "evidence": "All source meanings retained.", "uncertainty": [], "issues": []}
        return {"schemaVersion": "codex-cli-layer2-response-v1", "id": "codex:thread-1",
                "threadId": "thread-1", "requestedModel": "gpt-6-sol" if reviewer else "gpt-6-astra",
                "serverModel": None, "completed": True, "content": json.dumps(result),
                "usage": {"input_tokens": 10, "output_tokens": 5}, "exitCode": 0}

    def test_completed_receipt_preserves_requested_model_without_server_claim(self):
        row = self.receipt()
        self.assertEqual(CodexLayer2Transport.completed_content(row, "gpt-6-astra", "translator"),
                         row["content"])
        self.assertIsNone(row["serverModel"])

    def test_incomplete_or_conflicting_receipts_are_rejected(self):
        changes = {"wrong-schema": {"schemaVersion": "chat-completion"},
                   "not-completed": {"completed": False},
                   "nonzero-exit": {"exitCode": 1},
                   "wrong-requested-model": {"requestedModel": "gpt-6-sol"},
                   "different-thread-id": {"id": "codex:thread-other"}}
        for name, patch in changes.items():
            with self.subTest(name=name):
                row = self.receipt()
                row.update(patch)
                with self.assertRaises(ValueError):
                    CodexLayer2Transport.completed_content(row, "gpt-6-astra", "translator")

    def test_review_schema_accepts_canonical_string_evidence(self):
        schema = output_schema("reviewer")
        semantic = schema["properties"]["semanticReview"]
        self.assertEqual(semantic["properties"]["evidence"]["type"], "string")
        row = self.receipt(reviewer=True)
        self.assertEqual(CodexLayer2Transport.completed_content(row, "gpt-6-sol", "reviewer"),
                         row["content"])

    def test_invalid_result_is_rejected_even_with_successful_cli_exit(self):
        for content in ("not json", "{}"):
            with self.subTest(content=content):
                row = self.receipt()
                row["content"] = content
                with self.assertRaises((ValueError, ValidationError)):
                    CodexLayer2Transport.completed_content(row, "gpt-6-astra", "translator")


class FakeCLITransport:
    def __init__(self, tier="fast", result=None, error=None):
        self.execution_identity = {"backend": "codex_cli", "reviewerTier": tier,
                                   "version": "fixture-v1"}
        self.result = result or {"targetUtterances": ["中文。"]}
        self.error = error
        self.calls = 0

    def __call__(self, key, payload):
        if key:
            raise ValueError("CLI must not receive an API key")
        self.calls += 1
        if self.error:
            raise self.error
        return {"id": "codex:fixture-thread", "requestedModel": payload["model"],
                "serverModel": None, "content": json.dumps(self.result),
                "completed": True, "backend": "codex_cli"}

    @staticmethod
    def completed_content(response, model, role):
        if response.get("requestedModel") != model or response.get("completed") is not True:
            raise ValueError("CLI receipt is incomplete or has a different requested model")
        return response["content"]


class CodexCacheIsolationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.policy = {"translator": {"model": "gpt-6-astra", "reasoningEffort": "medium"}}
        self.prompt = {"instruction": "Translate the frozen group.", "input": {"english": "Hello."}}

    def call(self, path, transport, reuse_from=None):
        return runner._model_call("translator", self.prompt, self.policy, path,
                                  "", transport, reuse_from)

    @staticmethod
    def api_call(key, payload):
        return {"id": "api-fixture", "model": payload["model"], "choices": [{
            "finish_reason": "stop", "message": {"content": '{"targetUtterances":["中文。"]}'}}]}

    def test_cli_cache_cannot_be_reused_as_api_or_api_as_cli(self):
        cli_path = self.root / "cli" / "result.json"
        api_path = self.root / "api" / "result.json"
        self.call(cli_path, FakeCLITransport())
        self.call(api_path, self.api_call)
        with self.assertRaises(ValueError):
            self.call(self.root / "api-reuse" / "result.json", self.api_call, cli_path)
        with self.assertRaises(ValueError):
            self.call(self.root / "cli-reuse" / "result.json", FakeCLITransport(), api_path)

    def test_changed_cli_execution_identity_cannot_reuse_cache(self):
        old = self.root / "old" / "result.json"
        self.call(old, FakeCLITransport(tier="fast"))
        other = FakeCLITransport(tier="default")
        with self.assertRaises(ValueError):
            self.call(self.root / "new" / "result.json", other, old)
        self.assertEqual(other.calls, 0)

    def test_raw_cli_receipt_recovers_without_another_online_call(self):
        path = self.root / "result.json"
        transport = FakeCLITransport()
        saved = self.call(path, transport)
        path.unlink()
        self.assertEqual(self.call(path, transport), saved)
        self.assertEqual(transport.calls, 1)

    def test_cli_raw_and_validated_cache_are_private(self):
        path = self.root / "private" / "result.json"
        self.call(path, FakeCLITransport())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.with_suffix(".raw.json").stat().st_mode & 0o777, 0o600)

    def test_unknown_cli_outcome_blocks_automatic_retry(self):
        path = self.root / "result.json"
        uncertain = FakeCLITransport(error=TimeoutError("Unknown CLI outcome"))
        with self.assertRaises(TimeoutError):
            self.call(path, uncertain)
        self.assertTrue(path.with_suffix(".started.json").exists())
        retry = FakeCLITransport()
        with self.assertRaises(ValueError):
            self.call(path, retry)
        self.assertEqual(retry.calls, 0)


if __name__ == "__main__":
    unittest.main()


class CodexResourceBoundaryTests(unittest.TestCase):
    process = CodexRuntimeBoundaryTests.process

    def setUp(self):
        CodexRuntimeBoundaryTests.setUp(self)
        self.policy = {'schemaVersion': 'sermon-unified-resource-policy-v1',
            'brokerRoot': str(self.root / 'broker'),
            'capacities': {'cpu': 1, 'online_api': 1, 'codex_cli': 1, 'spark_tts': 1, 'publisher': 1}}
        self.transport.resource_policy = self.policy

    def ledger(self):
        from scripts.sermon_unified import resources
        path = self.root / 'broker' / resources.BROKER_LOCK_ID / 'resources.json'
        return list(json.loads(path.read_text())['reservations'].values())

    def test_busy_pre_dispatch_and_direct_calls_spawn_zero_cli(self):
        from scripts.sermon_unified import resources, contracts
        resources.reserve(self.policy, operation_id='occupied', owner='fixture-owner', resource='codex_cli')
        with patch('scripts.codex_layer2_transport.subprocess.run') as run:
            with self.assertRaisesRegex(contracts.ContractError, 'resource_broker_busy'):
                self.transport.admit_resource(self.payload)
            with self.assertRaisesRegex(contracts.ContractError, 'resource_broker_busy'):
                self.transport('', self.payload)
            run.assert_not_called()
        self.assertEqual([row['status'] for row in self.ledger()], ['held'])

    def test_hook_permit_consumed_once_terminal_durable_before_release(self):
        from scripts.sermon_unified import resources, contracts
        permit = self.transport.admit_resource(self.payload)
        self.assertIs(permit, self.transport.admit_resource(self.payload))
        self.assertEqual([row['status'] for row in self.ledger()], ['held'])
        real_release = resources.release
        def checked_release(*args, **kwargs):
            evidence = json.loads((permit.directory / 'resource-outcome.json').read_text())
            self.assertEqual(evidence['status'], 'terminal')
            self.assertIsNotNone(evidence['responseSha256'])
            self.assertTrue((permit.directory / 'response.json').is_file())
            return real_release(*args, **kwargs)
        with patch('scripts.codex_layer2_transport.subprocess.run', side_effect=self.process()) as run, \
             patch.object(resources, 'release', side_effect=checked_release):
            self.transport('', self.payload)
            self.assertEqual(run.call_count, 1)
        self.assertEqual([row['status'] for row in self.ledger()], ['released'])
        with patch('scripts.codex_layer2_transport.subprocess.run') as run:
            with self.assertRaisesRegex(contracts.ContractError, 'resource_operation_already_reserved'):
                self.transport('', self.payload)
            run.assert_not_called()

    def test_timeout_and_incomplete_hold_capacity_no_reconstruction_retry(self):
        from scripts.sermon_unified import contracts
        for name, behavior in [('timeout', subprocess.TimeoutExpired('fixture', 10)),
                               ('incomplete', self.process(completed=False))]:
            with self.subTest(name=name):
                self.transport.resource_policy = {**self.policy, 'brokerRoot': str(self.root / name)}
                self.transport.receipts_dir = self.root / (name + '-receipts')
                with patch('scripts.codex_layer2_transport.subprocess.run', side_effect=behavior) as run:
                    with self.assertRaises((subprocess.TimeoutExpired, RuntimeError)):
                        self.transport('', self.payload)
                    self.assertEqual(run.call_count, 1)
                outcome = json.loads(next(self.transport.receipts_dir.glob('*/resource-outcome.json')).read_text())
                self.assertEqual(outcome['status'], 'unknown_outcome')
                # Reconstruct transport state, retaining bound run receipt root.
                if hasattr(self.transport, '_resource_local'): del self.transport._resource_local
                with patch('scripts.codex_layer2_transport.subprocess.run') as run:
                    with self.assertRaisesRegex(contracts.ContractError, 'resource_operation_already_reserved'):
                        self.transport('', self.payload)
                    run.assert_not_called()

    def test_terminal_tool_rejection_releases_and_durable_write_failure_holds(self):
        with patch('scripts.codex_layer2_transport.subprocess.run', side_effect=self.process(tool=True)):
            with self.assertRaisesRegex(RuntimeError, 'terminal_or_tool_failure'):
                self.transport('', self.payload)
        self.assertEqual([r['status'] for r in self.ledger()], ['released'])
        self.payload['messages'][1]['content'] = 'different fixture'
        with patch('scripts.codex_layer2_transport.subprocess.run', side_effect=self.process()), \
             patch('scripts.codex_layer2_resources.atomic_json', side_effect=OSError('fixture private detail')):
            with self.assertRaises(OSError): self.transport('', self.payload)
        self.assertEqual(sorted(r['status'] for r in self.ledger()), ['held', 'released'])

    def test_payload_identity_policy_change_rejected_and_secret_not_bound(self):
        from scripts.sermon_unified import contracts
        permit = self.transport.admit_resource(self.payload)
        binding = (permit.directory / 'resource-binding.json').read_text()
        self.assertNotIn('Hello', binding)
        self.assertNotIn('messages', binding)
        self.assertNotIn('PATH', binding)
        del self.transport._resource_local
        self.transport.execution_identity = {'backend': 'codex_cli', 'version': 'changed'}
        with patch('scripts.codex_layer2_transport.subprocess.run') as run:
            with self.assertRaisesRegex(contracts.ContractError, 'resource_call_identity_changed'):
                self.transport('', self.payload)
            run.assert_not_called()

    def test_confirmed_spawn_failure_records_terminal_before_release(self):
        with patch('scripts.codex_layer2_transport.subprocess.run', side_effect=FileNotFoundError('private')):
            with self.assertRaises(FileNotFoundError): self.transport('', self.payload)
        self.assertEqual([r['status'] for r in self.ledger()], ['released'])
        outcome = json.loads(next(self.transport.receipts_dir.glob('*/resource-outcome.json')).read_text())
        self.assertEqual(outcome['status'], 'terminal')
        self.assertEqual(outcome['errorType'], 'FileNotFoundError')

    def test_constructor_requires_receipts_and_binds_policy_without_environment_secrets(self):
        cli = self.root / 'codex-wrapper'
        cli.write_text('fixture wrapper')
        auth_root = self.root / 'auth-home'
        auth_root.mkdir()
        (auth_root / 'auth.json').write_text(json.dumps({'auth_mode': 'chatgpt'}))
        with patch.dict(os.environ, {'CODEX_HOME': str(auth_root), 'OPENAI_API_KEY': 'fixture-secret'}), \
             patch('scripts.codex_layer2_transport.subprocess.check_output', return_value='codex fixture-v1'):
            with self.assertRaisesRegex(ValueError, 'resource_policy_requires_receipts_directory'):
                CodexLayer2Transport(cli, resource_policy=self.policy)
            transport = CodexLayer2Transport(cli, resource_policy=self.policy, receipts_dir=self.root / 'durable')
        self.assertEqual(len(transport.execution_identity['resourcePolicySha256']), 64)
        self.assertEqual(len(transport.execution_identity['resourceAdapterSha256']), 64)
        self.assertNotIn('fixture-secret', json.dumps(transport.execution_identity))
