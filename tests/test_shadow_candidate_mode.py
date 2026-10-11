import json
import unittest
from unittest.mock import patch

from scripts import canonical_layer2_controller as controller
from scripts import produce_target_language_candidate as produce
from scripts import target_language_policy as policy_tools
from tests import test_canonical_layer2_controller as fixtures


SOURCE = {"source": {"id": "fixture"}}
ANCHOR = {"sourceUnits": [{"sourceUnitId": "u1", "english": "Hello"}]}


def not_ready_identity(*_args):
    return {"translationPolicySha256": "p" * 64, "productionPolicyReady": False, "unresolved": ["terminology_review_pending"]}


class ShadowCandidatePreparationTests(unittest.TestCase):
    def setUp(self):
        patches = [
            patch.object(produce, "validate_source_for_translation", return_value="a" * 64),
            patch.object(policy_tools, "validate_policy", side_effect=not_ready_identity),
            patch.object(policy_tools, "validate_source_scope", return_value=None),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_production_mode_still_rejects_unresolved_policy(self):
        with self.assertRaisesRegex(ValueError, "Production policy has unresolved"):
            produce.prepare_request(SOURCE, ANCHOR, {"targetLocale": "zh-Hans"})

    def test_shadow_mode_admits_unresolved_policy_and_marks_request(self):
        request = produce.prepare_request(SOURCE, ANCHOR, {"targetLocale": "zh-Hans"}, candidate_mode="shadow")
        self.assertEqual(request["candidateMode"], "shadow")
        self.assertEqual(request["schemaVersion"], "sermon-target-language-evidence-request-v2")
        self.assertEqual(request["translationPolicySha256"], "p" * 64)

    def test_shadow_rejects_nonterminology_and_missing_reasons(self):
        for reasons in (None, ["scripture_policy_pending"], ["language_review_plugin_pending"],
                        ["plugin_implementation_hash_unbound_migrate_to_v2"], ["new_unknown_reason"],
                        ["terminology_review_pending", "scripture_policy_pending"]):
            identity = {"translationPolicySha256": "p" * 64, "productionPolicyReady": False}
            if reasons is not None:
                identity["unresolved"] = reasons
            with self.subTest(reasons=reasons), patch.object(policy_tools, "validate_policy", return_value=identity):
                with self.assertRaisesRegex(ValueError, "only unresolved terminology"):
                    produce.prepare_request(SOURCE, ANCHOR, {"targetLocale": "zh-Hans"}, candidate_mode="shadow")

    def test_shadow_model_runner_refuses_before_transport(self):
        from scripts import run_target_language_models as models
        from unittest.mock import Mock
        call = Mock()
        with self.assertRaisesRegex(ValueError, "Shadow execution is not implemented"):
            models.run_accounted(SOURCE, ANCHOR, {}, None, "", call, None, None, None, None,
                                 candidate_mode="shadow")
        call.assert_not_called()

    def test_shadow_admission_cannot_emit_production_candidate(self):
        with self.assertRaisesRegex(ValueError, "Shadow candidate admission is not implemented"):
            produce.admit_evidence(SOURCE, ANCHOR, {}, {"candidateMode": "shadow"}, {}, {}, None, "")

    def test_production_request_is_unchanged_and_unmarked(self):
        with patch.object(policy_tools, "validate_policy", return_value={"translationPolicySha256": "p" * 64, "productionPolicyReady": True}):
            request = produce.prepare_request(SOURCE, ANCHOR, {"targetLocale": "zh-Hans"})
        self.assertNotIn("candidateMode", request)

    def test_unknown_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown candidate mode"):
            produce.prepare_request(SOURCE, ANCHOR, {"targetLocale": "zh-Hans"}, candidate_mode="draft")


class ShadowConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CanonicalLayer2ControllerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.base = json.loads(self.fixture.path.read_text())
        self.auto_repair = {"routingVersion": controller.auto_repair.ROUTING_VERSION, "groupWorkers": 16, "maxActiveLocales": 1}

    def write(self, data, name):
        path = self.fixture.root / name
        path.write_text(json.dumps(data))
        return path

    def v3(self, **extra):
        return dict(self.base, schemaVersion=controller.AUTO_REPAIR_SCHEMA, layer2AutoRepair=self.auto_repair, **extra)

    def test_v1_configuration_is_production(self):
        config = controller.load_configuration(self.fixture.path)
        self.assertEqual(config.candidate_mode, "production")

    def test_v3_without_candidate_mode_is_production(self):
        config = controller.load_configuration(self.write(self.v3(), "v3.json"))
        self.assertEqual(config.candidate_mode, "production")
        self.assertEqual(config.auto_repair["groupWorkers"], 16)

    def test_v4_shadow_loads_as_shadow(self):
        config = controller.load_configuration(self.write(dict(self.v3(), schemaVersion=controller.SHADOW_SCHEMA, candidateMode="shadow"), "shadow.json"))
        self.assertEqual(config.candidate_mode, "shadow")

    def test_v3_rejects_unknown_candidate_mode(self):
        with self.assertRaises(Exception):
            controller.load_configuration(self.write(self.v3(candidateMode="draft"), "bad-mode.json"))

    def test_v1_rejects_candidate_mode_field(self):
        with self.assertRaises(Exception):
            controller.load_configuration(self.write(dict(self.base, candidateMode="shadow"), "v1-with-field.json"))

    def test_v3_rejects_shadow_field(self):
        with self.assertRaises(Exception):
            controller.load_configuration(self.write(self.v3(candidateMode="shadow"), "bad-v3.json"))
