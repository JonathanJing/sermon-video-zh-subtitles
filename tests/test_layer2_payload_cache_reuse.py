import copy
import itertools
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

from scripts import produce_target_language_candidate as producer
from scripts import run_target_language_models as subject
from scripts import sermon_accounting as accounting
from tests import test_produce_target_language_candidate as fixture_module


class _Caller:
    billing = "api"
    response_ids = itertools.count(1)

    def __init__(self, owner, *, runtime="runtime-a", backend="openai_api",
                 forbidden=False, translator_suffix="", semantic_fail=False,
                 plugin_forbidden_text=False, refusal_role=None):
        self.owner = owner
        self.forbidden = forbidden
        self.translator_suffix = translator_suffix
        self.semantic_fail = semantic_fail
        self.plugin_forbidden_text = plugin_forbidden_text
        self.refusal_role = refusal_role
        self.calls = []
        self.verifications = 0
        self.execution_identity = {
            "schemaVersion": "test-layer2-transport-v1",
            "backend": backend,
            "runtime": runtime,
        }

    def verify_execution(self, _api_key):
        self.verifications += 1

    def __call__(self, api_key, payload):
        if self.forbidden:
            raise AssertionError("payload cache replay must not dispatch")
        self.calls.append(copy.deepcopy(payload))
        data = json.loads(payload["messages"][1]["content"])
        group = self.owner.groups[tuple(data["sourceUnitIds"])]
        fields = ["translationGroupId", "sourceUnitIds", "targetUtterances", "coverage"]
        if payload["reasoning_effort"] == "medium":
            fields.append("semanticReview")
        result = {key: copy.deepcopy(group[key]) for key in fields}
        result["translationGroupId"] = data["translationGroupId"]
        if payload["reasoning_effort"] == "high" and self.translator_suffix:
            result["targetUtterances"][0] += self.translator_suffix
        if payload["reasoning_effort"] == "medium" and self.semantic_fail:
            result["semanticReview"]["status"] = "fail"
            result["semanticReview"]["checks"]["completeMeaning"] = "fail"
            result["semanticReview"]["issues"] = ["synthetic semantic failure"]
        if payload["reasoning_effort"] == "medium" and self.plugin_forbidden_text:
            result["targetUtterances"][0] += "禁"
        role = "translator" if payload["reasoning_effort"] == "high" else "reviewer"
        message = {"content": json.dumps(result)}
        if self.refusal_role == role:
            message["refusal"] = "synthetic provider refusal"
        return {
            "id": f"payload-cache-response-{next(self.response_ids)}",
            "model": payload["model"],
            "choices": [{"finish_reason": "stop", "message": message}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }


class Layer2PayloadCacheReuseTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.ProduceTargetLanguageCandidateTests(
            methodName="test_compiles_valid_candidate_without_human_approval")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.prior = self.root / "prior"
        self.current = self.root / "current"
        self.groups = {tuple(row["sourceUnitIds"]): row for row in self.fixture.evidence["groups"]}

    def execute(self, out, caller, *, payload_cache_from=None,
                emit_payload_cache_success=False, source=None, policy=None):
        return subject.run_accounted(
            source or self.fixture.source, self.fixture.anchor, policy or self.fixture.policy,
            out, "fixture-key", caller, None, self.fixture.plugin_path, None, None,
            payload_cache_from=payload_cache_from,
            emit_payload_cache_success=emit_payload_cache_success)

    def make_prior(self):
        caller = _Caller(self)
        evidence = self.execute(self.prior, caller, emit_payload_cache_success=True)
        self.assertEqual(len(caller.calls), 4)
        self.assertEqual(len(list(self.prior.glob("group-*-payload-cache-success.json"))), 2)
        return evidence, caller

    def test_default_run_does_not_emit_cross_round_sidecars(self):
        caller = _Caller(self)
        self.execute(self.prior, caller)
        self.assertEqual(list(self.prior.glob("group-*-payload-cache-success.json")), [])

    def test_function_and_cli_reject_non_openai_payload_cache_transport(self):
        self.make_prior()
        caller = _Caller(self, backend="codex_cli", forbidden=True)
        with self.assertRaisesRegex(ValueError, "requires openai_api transport identity"):
            self.execute(self.current, caller, payload_cache_from=self.prior)
        self.assertEqual(caller.calls, [])
        argv = ["layer2", "--english-source-package", "source.json", "--anchor", "anchor.json",
                "--policy", "policy.json", "--plugin", "plugin.py", "--out-dir", "out",
                "--model-backend", "codex-cli", "--emit-payload-cache-success"]
        with patch.object(sys, "argv", argv), self.assertRaisesRegex(
                ValueError, "requires --model-backend openai-api"):
            subject.main()

    def test_exact_payload_runtime_and_runner_identity_replay_without_calls(self):
        prior_evidence, _ = self.make_prior()
        replay = _Caller(self, forbidden=True)
        current_evidence = self.execute(self.current, replay, payload_cache_from=self.prior)
        self.assertEqual(current_evidence, prior_evidence)
        self.assertEqual(replay.calls, [])
        self.assertEqual(replay.verifications, 4)
        events, damaged = accounting.read_events(self.current / "accounting")
        self.assertFalse(damaged)
        model_starts = [row for row in events if row.get("event") == "stage_started"
                        and row.get("stage", "").startswith(("layer2.translator.", "layer2.reviewer."))]
        self.assertEqual(len(model_starts), 4)
        self.assertTrue(all(row.get("cacheHit") is True for row in model_starts))
        self.assertTrue(all(row.get("executorType") == "deterministic_program" for row in model_starts))

    def test_old_format_is_a_miss_not_a_cross_round_hit(self):
        self.make_prior()
        for path in self.prior.glob("group-*-payload-cache-success.json"):
            path.unlink()
        caller = _Caller(self)
        self.execute(self.current, caller, payload_cache_from=self.prior)
        self.assertEqual(len(caller.calls), 4)

    def test_changed_transport_identity_does_not_hit(self):
        self.make_prior()
        caller = _Caller(self, runtime="runtime-b")
        self.execute(self.current, caller, payload_cache_from=self.prior)
        self.assertEqual(len(caller.calls), 4)

    def test_role_specific_payload_and_draft_invalidation(self):
        self.make_prior()
        original = subject.model_payload

        def changed_payload(changed_role):
            def build(role, prompt, policy, request_limits=None):
                payload = original(role, prompt, policy, request_limits)
                if role == changed_role:
                    payload["messages"][0]["content"] += " Synthetic prompt revision."
                return payload
            return build

        same_output = _Caller(self)
        with patch.object(subject, "model_payload", side_effect=changed_payload("translator")):
            self.execute(self.root / "translator-payload-changed", same_output,
                         payload_cache_from=self.prior)
        self.assertEqual([row["reasoning_effort"] for row in same_output.calls],
                         ["high", "high"])

        changed_output = _Caller(self, translator_suffix=" changed")
        with patch.object(subject, "model_payload", side_effect=changed_payload("translator")):
            self.execute(self.root / "translator-output-changed", changed_output,
                         payload_cache_from=self.prior)
        self.assertEqual([row["reasoning_effort"] for row in changed_output.calls],
                         ["high", "medium", "high", "medium"])

        reviewer_only = _Caller(self)
        with patch.object(subject, "model_payload", side_effect=changed_payload("reviewer")):
            self.execute(self.root / "reviewer-payload-changed", reviewer_only,
                         payload_cache_from=self.prior)
        self.assertEqual([row["reasoning_effort"] for row in reviewer_only.calls],
                         ["medium", "medium"])

    def test_semantic_or_plugin_failure_does_not_emit_success_receipt(self):
        semantic_out = self.root / "semantic-fail"
        with self.assertRaisesRegex(ValueError, "Sol flagged group"):
            self.execute(semantic_out, _Caller(self, semantic_fail=True),
                         emit_payload_cache_success=True)
        self.assertEqual(list(semantic_out.glob("group-*-payload-cache-success.json")), [])

        plugin_out = self.root / "plugin-fail"
        with self.assertRaisesRegex(ValueError, "language_plugin_group_blocked"):
            self.execute(plugin_out, _Caller(self, plugin_forbidden_text=True),
                         emit_payload_cache_success=True)
        self.assertEqual(list(plugin_out.glob("group-*-payload-cache-success.json")), [])

    def test_nonempty_provider_refusal_never_emits_success_receipt(self):
        out = self.root / "provider-refusal"
        with self.assertRaisesRegex(ValueError, "cannot bind a refused reviewer response"):
            self.execute(out, _Caller(self, refusal_role="reviewer"),
                         emit_payload_cache_success=True)
        self.assertEqual(list(out.glob("group-*-payload-cache-success.json")), [])

    def test_payload_cache_implementation_identity_is_independent_and_required(self):
        self.make_prior()
        receipt = producer._load(self.prior / "group-0001-payload-cache-success.json")
        self.assertEqual(receipt["payloadCacheImplementationSha256"],
                         subject.PAYLOAD_CACHE_IMPLEMENTATION_SHA256)
        self.assertNotEqual(subject.PAYLOAD_CACHE_IMPLEMENTATION_SHA256,
                            subject.RUNNER_PRODUCTION_IDENTITY_SHA256)
        caller = _Caller(self, forbidden=True)
        with patch.object(subject, "PAYLOAD_CACHE_IMPLEMENTATION_SHA256", "0" * 64), \
                self.assertRaisesRegex(ValueError, "identity changed"):
            self.execute(self.current, caller, payload_cache_from=self.prior)
        self.assertEqual(caller.calls, [])

    def test_prior_root_and_bound_files_reject_symlinks(self):
        self.make_prior()
        root_link = self.root / "prior-link"
        root_link.symlink_to(self.prior, target_is_directory=True)
        caller = _Caller(self, forbidden=True)
        with self.assertRaisesRegex(ValueError, "separate existing prior root"):
            self.execute(self.root / "root-link-out", caller, payload_cache_from=root_link)

        receipt = self.prior / "group-0001-payload-cache-success.json"
        saved_receipt = self.prior / "saved-receipt.json"
        receipt.rename(saved_receipt)
        receipt.symlink_to(saved_receipt.name)
        with self.assertRaisesRegex(ValueError, "receipt must not be a symlink"):
            self.execute(self.root / "receipt-link-out", caller, payload_cache_from=self.prior)
        receipt.unlink()
        saved_receipt.rename(receipt)

        cache = self.prior / "group-0001-astra.json"
        saved_cache = self.prior / "saved-astra.json"
        cache.rename(saved_cache)
        cache.symlink_to(saved_cache.name)
        with self.assertRaisesRegex(ValueError, "files changed"):
            self.execute(self.root / "cache-link-out", caller, payload_cache_from=self.prior)
        self.assertEqual(caller.calls, [])

    def test_unknown_prior_outcome_blocks_before_dispatch(self):
        self.make_prior()
        marker = self.prior / "group-9999-astra.started.json"
        marker.write_text(json.dumps({"role": "translator", "status": "started_response_unconfirmed"}))
        caller = _Caller(self, forbidden=True)
        with self.assertRaisesRegex(ValueError, "Uncertain paid translator call"):
            self.execute(self.current, caller, payload_cache_from=self.prior)
        self.assertEqual(caller.calls, [])

    def test_changed_source_binding_or_cache_bytes_block_before_dispatch(self):
        self.make_prior()
        request = producer.prepare_request(self.fixture.source, self.fixture.anchor, self.fixture.policy)
        plan = subject.group_plan(request, self.fixture.anchor)
        caller = _Caller(self, forbidden=True)
        preview = producer._load(self.prior / "group-0001-astra.policy-preview.json")
        fingerprint = subject._model_fingerprint(preview["payload"], caller, "fixture-key")
        changed_request = {**request, "anchorManifestSha256": "0" * 64}
        with self.assertRaisesRegex(ValueError, "identity changed"):
            subject._successful_payload_cache(
                self.prior, "group-0001", "translator", fingerprint,
                changed_request, plan[0])
        self.assertEqual(caller.calls, [])

        cache = self.prior / "group-0001-astra.json"
        cache.write_text(cache.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "files changed"):
            self.execute(self.current, caller, payload_cache_from=self.prior)
        self.assertEqual(caller.calls, [])

    def test_corrupt_or_failed_success_receipt_blocks_before_dispatch(self):
        self.make_prior()
        receipt_path = self.prior / "group-0001-payload-cache-success.json"
        for index, (mutation, message) in enumerate((
                (lambda _: receipt_path.write_text("{"), "receipt is corrupt"),
                (lambda value: value["semanticReview"].update(status="fail"),
                 "did not pass semantic review"),
                (lambda value: value.update(runnerImplementationSha256="0" * 64),
                 "identity changed"))):
            with self.subTest(message=message):
                original = receipt_path.read_bytes()
                value = json.loads(original)
                result = mutation(value)
                if result is None and receipt_path.read_bytes() == original:
                    receipt_path.write_text(json.dumps(value))
                caller = _Caller(self, forbidden=True)
                with self.assertRaisesRegex(ValueError, message):
                    self.execute(self.root / f"current-{index}", caller,
                                 payload_cache_from=self.prior)
                self.assertEqual(caller.calls, [])
                receipt_path.write_bytes(original)

    def test_reviewer_key_includes_the_cached_translator_draft(self):
        self.make_prior()
        caller = _Caller(self)
        request = producer.prepare_request(self.fixture.source, self.fixture.anchor, self.fixture.policy)
        plan = subject.group_plan(request, self.fixture.anchor)
        group = plan[0]
        stem = "group-0001"
        translator_preview = producer._load(self.prior / f"{stem}-astra.policy-preview.json")
        translator_fingerprint = subject._model_fingerprint(
            translator_preview["payload"], caller, "fixture-key")
        self.assertEqual(
            subject._successful_payload_cache(
                self.prior, stem, "translator", translator_fingerprint, request, group),
            self.prior / f"{stem}-astra.json")

        reviewer_preview = producer._load(self.prior / f"{stem}-sol.policy-preview.json")
        changed = copy.deepcopy(reviewer_preview["payload"])
        reviewer_input = json.loads(changed["messages"][1]["content"])
        reviewer_input["astraDraft"]["targetUtterances"][0] += " changed"
        changed["messages"][1]["content"] = json.dumps(reviewer_input, ensure_ascii=False)
        changed_fingerprint = subject._model_fingerprint(changed, caller, "fixture-key")
        self.assertIsNone(subject._successful_payload_cache(
            self.prior, stem, "reviewer", changed_fingerprint, request, group))


if __name__ == "__main__":
    unittest.main()
