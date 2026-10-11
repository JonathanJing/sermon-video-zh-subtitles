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
    return {"translationPolicySha256": "p" * 64, "productionPolicyReady": False}


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
        self.assertEqual(request["translationPolicySha256"], "p" * 64)

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

    def test_v3_shadow_loads_as_shadow(self):
        config = controller.load_configuration(self.write(self.v3(candidateMode="shadow"), "shadow.json"))
        self.assertEqual(config.candidate_mode, "shadow")

    def test_v3_rejects_unknown_candidate_mode(self):
        with self.assertRaises(Exception):
            controller.load_configuration(self.write(self.v3(candidateMode="draft"), "bad-mode.json"))

    def test_v1_rejects_candidate_mode_field(self):
        with self.assertRaises(Exception):
            controller.load_configuration(self.write(dict(self.base, candidateMode="shadow"), "v1-with-field.json"))
