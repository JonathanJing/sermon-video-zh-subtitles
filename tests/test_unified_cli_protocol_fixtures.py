"""Unified CLI protocol fixtures match the pre-development schemas.

These schemas are not loaded by a production command.
"""
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "unified-cli"


def _validator(name):
    schema = json.loads((ROOT / "schemas" / name).read_text())
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def _load(name):
    return json.loads((FIXTURES / name).read_text())


class UnifiedCliProtocolFixtureTests(unittest.TestCase):
    def test_examples_match_their_schemas(self):
        cases = [
            ("sermon-unified-run-manifest-v1.schema.json", "run-manifest.json"),
            ("sermon-unified-run-manifest-v1.schema.json", "mockup-180s-manifest.json"),
            ("sermon-unified-job-v1.schema.json", "job.json"),
            ("sermon-cli-result-v1.schema.json", "result-job-status.json"),
            ("sermon-cli-result-v1.schema.json", "result-plan.json"),
            ("sermon-unified-production-event-v1.schema.json", "event.json"),
        ]
        for schema_name, fixture_name in cases:
            with self.subTest(fixture=fixture_name):
                _validator(schema_name).validate(_load(fixture_name))

    def test_job_and_event_stage_enums_match(self):
        job = json.loads((ROOT / "schemas" / "sermon-unified-job-v1.schema.json").read_text())
        event = json.loads((ROOT / "schemas" / "sermon-unified-production-event-v1.schema.json").read_text())
        result = json.loads((ROOT / "schemas" / "sermon-cli-result-v1.schema.json").read_text())
        self.assertEqual(job["$defs"]["stageId"]["enum"], event["$defs"]["stageId"]["enum"])
        self.assertEqual(job["$defs"]["stageId"]["enum"], result["$defs"]["stageId"]["enum"])
        self.assertEqual(job["$defs"]["artifactKind"]["enum"], result["$defs"]["artifactKind"]["enum"])

    def test_plan_without_plan_object_is_rejected(self):
        document = _load("result-plan.json")
        del document["plan"]
        errors = list(_validator("sermon-cli-result-v1.schema.json").iter_errors(document))
        self.assertTrue(errors)

    def test_status_without_job_state_is_rejected(self):
        document = _load("result-job-status.json")
        del document["jobState"]
        errors = list(_validator("sermon-cli-result-v1.schema.json").iter_errors(document))
        self.assertTrue(errors)

    def test_layer_must_match_stage(self):
        document = _load("job.json")
        document["layer"] = "layer1"
        errors = list(_validator("sermon-unified-job-v1.schema.json").iter_errors(document))
        self.assertTrue(errors)

    def test_mockup_keeps_the_known_180s_clip_and_fixture_transport(self):
        document = _load("mockup-180s-manifest.json")
        self.assertEqual(
            document["source"]["mediaSha256"],
            "79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b",
        )
        self.assertEqual(document["source"]["window"]["startSeconds"], 60)
        self.assertEqual(document["source"]["window"]["endSeconds"], 240)
        self.assertIsNone(document["source"]["window"]["approvalReceiptSha256"])
        self.assertEqual(document["locales"], ["zh-Hans", "ko", "es"])
        self.assertEqual(document["transport"], "fixture")
        self.assertEqual(document["activeScope"], "layer2_machine_candidate")
        self.assertEqual(document["finalScope"], "dual_production_verified")
        self.assertEqual(document["budget"]["limitMicroUsd"], 0)

    def test_final_scope_cannot_shrink(self):
        document = _load("run-manifest.json")
        document["finalScope"] = "dev_reader_verified"
        errors = list(_validator("sermon-unified-run-manifest-v1.schema.json").iter_errors(document))
        self.assertTrue(errors)

    def test_shared_production_run_id_does_not_make_two_traces_one_event(self):
        first = _load("event.json")
        second = json.loads(json.dumps(first))
        second["eventId"] = "evt-example-002"
        second["traceId"] = "trace-example-002"
        second["attemptId"] = "attempt-example-002"
        validator = _validator("sermon-unified-production-event-v1.schema.json")
        validator.validate(first)
        validator.validate(second)
        self.assertEqual(first["productionRunId"], second["productionRunId"])
        self.assertNotEqual(first["traceId"], second["traceId"])
