"""Current-producer recovery snapshots with real admission, synthetic inputs, no models."""
import fcntl
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import export_layer3_recovery_intents as subject
from scripts import render_formal_target_language_speech as producer
from tests import test_render_formal_target_language_speech as render_fixtures


def settings(**changes):
    value = {"schemaVersion": producer.RECOVERY_SETTINGS_VERSION, "seed": 42,
        "batchSize": 1, "replicas": 1, "device": "cuda:0", "dtype": "bfloat16",
        "attention": "sdpa", "instruct": None, "reactionLagSeconds": .05,
        "interUtteranceGapSeconds": .05, "maxEndLagSeconds": 8., "trackFormat": "wav",
        "unitInstructions": None}
    return dict(value, **changes)


class ExportTests(unittest.TestCase):
    def setUp(self):
        fixture = render_fixtures.FormalRenderTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.root = fixture.root.resolve().parent / "export-job"
        self.paths = {key: path.resolve() for key, path in fixture.paths.items()}
        self.map_path = self.root / "checkpoint-map.json"
        self.policies_path = self.root / "operation-policies.json"
        policies = {"normalization": {"policy": "exact_human_approved_target_text_no_rewrite"},
                    "asrScreening": {"policy": "synthetic_test"}, "subtitle": {"policy": "synthetic_test"}}
        adapter = producer.package.read_object(self.paths["adapter"])
        for name, field in (("normalization", "normalizationPolicySha256"),
                            ("asrScreening", "asrScreeningPolicySha256"),
                            ("subtitle", "subtitlePolicySha256")):
            adapter[field] = producer.identity.json_sha256(policies[name])
        self.paths["adapter"].write_text(json.dumps(adapter))
        producer.package.speech.prepare_job(self.paths["source"], self.paths["anchor"],
            self.paths["candidate"], self.paths["policy"], self.paths["human_receipt"],
            self.paths["adapter"], self.paths["registry"], self.root,
            clip_voice_authorization_path=self.paths["clip_voice_authorization"],
            clip_voice_capability_path=self.paths["clip_voice_capability"],
            clip_timeline_map_path=self.paths["clip_timeline_map"])
        self.paths["job"] = self.root / "job.json"
        self.map_path.write_text(json.dumps({"schemaVersion": "sermon-speaker-checkpoint-map-v1",
            "checkpoints": [{"speakerId": adapter["speakerId"],
                "checkpointRef": adapter["conditioningRef"], "path": "/nonexistent/model-not-loaded"}]}))
        self.policies_path.write_text(json.dumps(policies))
        self.settings_path = self.root / "recovery-settings.json"
        self.settings_path.write_text(json.dumps(settings()))
        self.lock_path = self.root / ".formal-render.lock"
        self.lock_path.touch()

    def export(self):
        return subject.export_snapshot(self.paths, self.map_path, self.policies_path, self.settings_path)

    def inventory(self):
        return {str(p): (producer.identity.sha256(p), p.stat().st_mtime_ns)
                for p in self.fixture.fixture.root.rglob("*") if p.is_file()}

    def test_full_formal_validation_complete_coverage_without_models_cache_reads_or_writes(self):
        before = self.inventory()
        with patch.object(producer, "QwenSynthesizer", side_effect=AssertionError("model loaded")), \
             patch.object(producer.demos, "validate_checkpoint", side_effect=AssertionError("weights opened")), \
             patch.object(producer, "write_json_atomic", side_effect=AssertionError("cache written")):
            result = self.export()
        self.assertEqual(before, self.inventory())
        self.assertEqual([i["unitIndex"] for i in result["intents"]], [0, 1])
        self.assertEqual(result["validation"]["unitCount"], 2)
        self.assertFalse(result["validation"]["checkpointWeightsVerified"])
        for flag in ("storedIntentsConsumed", "dispatchAuthorized", "ownerReconciled",
                     "resourceReleaseAuthorized", "crossVersionMigrationImplemented"):
            self.assertFalse(result["validation"][flag])
        self.assertEqual(result["producerFileSha256"], producer.identity.sha256(Path(producer.__file__)))
        import jsonschema
        schema_root = Path(__file__).resolve().parents[1] / "schemas"
        jsonschema.validate(result, json.loads((schema_root / f"{subject.VERSION}.schema.json").read_text()))
        jsonschema.validate(result["settings"], json.loads((schema_root / f"{producer.RECOVERY_SETTINGS_VERSION}.schema.json").read_text()))

    def test_current_scalar_export_matches_actual_renderer_intents(self):
        exported = self.export()
        context = producer.checked_context(self.paths, self.map_path, self.policies_path, assembly_only=True)
        producer.render_units(context, self.paths, self.root, self.map_path, synth_factory=render_fixtures.FakeSynth)
        for index, intent in enumerate(exported["intents"]):
            self.assertEqual(intent, producer.package.read_object(self.root / f"receipts/unit-{index:04d}.intent.json"))
        with patch.object(producer.package, "read_object", wraps=producer.package.read_object) as read:
            self.export()
            self.assertFalse(any(".intent.json" in str(call.args[0]) for call in read.call_args_list))

    def test_batch_export_matches_full_window_and_actual_renderer(self):
        from tests.test_formal_audio_batching import BatchEngine
        self.settings_path.write_text(json.dumps(settings(batchSize=2)))
        exported = self.export()
        context = producer.checked_context(self.paths, self.map_path, self.policies_path, assembly_only=True)
        producer.render_units(context, self.paths, self.root, self.map_path,
                              batch_size=2, synth_factory=BatchEngine)
        for index, intent in enumerate(exported["intents"]):
            self.assertEqual(intent, producer.package.read_object(self.root / f"receipts/unit-{index:04d}.intent.json"))
            self.assertEqual(intent["batchWindowUnitIndices"], [0, 1])
        group = context["job"]["units"][0]
        override = self.root / "instructions.json"
        import hashlib
        override.write_text(json.dumps({"schemaVersion": "sermon-unit-delivery-instructions-v1",
            "targetLocale": context["job"]["targetLocale"],
            "speechJobJsonSha256": producer.identity.json_sha256(context["job"]), "units": [{
                "translationGroupId": group["translationGroupId"], "instruction": "speak clearly",
                "approvedTextSha256": hashlib.sha256(group["text"].encode()).hexdigest(),
                "operatorEvidence": "synthetic test instruction"}]}))
        self.settings_path.write_text(json.dumps(settings(batchSize=2, unitInstructions=str(override))))
        updated = self.export()
        for old, new in zip(exported["intents"], updated["intents"]):
            self.assertNotEqual(old["batchWindowInputsSha256"], new["batchWindowInputsSha256"])
        self.assertIsNone(updated["intents"][1]["deliveryInstruction"])

    def test_no_inferred_defaults_and_invalid_settings_fail_closed(self):
        for changes in ({"seed": True}, {"batchSize": 3}, {"replicas": 8}, {"maxEndLagSeconds": float("nan")},
                        {"unitInstructions": "relative.json"}):
            self.settings_path.write_text(json.dumps(settings(**changes)))
            with self.assertRaises(ValueError):
                self.export()
        incomplete = settings(); incomplete.pop("instruct")
        with self.assertRaisesRegex(ValueError, "Complete explicit"):
            producer.recovery_render_settings(incomplete)

    def test_precise_direct_parent_batch_cache_survives_pure_builder_extraction(self):
        from tests.test_formal_audio_batching import BatchEngine
        context = producer.checked_context(self.paths, self.map_path, self.policies_path, assembly_only=True)
        producer.render_units(context, self.paths, self.root, self.map_path,
                              batch_size=2, synth_factory=BatchEngine)
        parent_sha = "12d6f6af892fd16f721e973de5347b2e5f444b6ce3702e296eb414da2a5ebdcc"
        for index in range(2):
            intent_path = self.root / f"receipts/unit-{index:04d}.intent.json"
            commit_path = self.root / f"receipts/unit-{index:04d}.render.json"
            intent = producer.package.read_object(intent_path)
            intent["batchImplementationSha256"] = parent_sha
            intent_path.write_text(json.dumps(intent))
            commit = producer.package.read_object(commit_path)
            commit["identity"] = intent
            commit_path.write_text(json.dumps(commit))
        before = self.inventory()
        with patch.object(BatchEngine, "batch", side_effect=AssertionError("cached model called")):
            producer.render_units(context, self.paths, self.root, self.map_path,
                                  batch_size=2, synth_factory=BatchEngine)
        self.assertEqual({key: value[0] for key, value in before.items()},
                         {key: value[0] for key, value in self.inventory().items()})
        self.settings_path.write_text(json.dumps(settings(batchSize=2)))
        snapshot = self.export()
        self.assertNotEqual(snapshot["intents"][0]["batchImplementationSha256"], parent_sha)

    def test_invalid_source_gate_blocks_export_without_replacing_evidence(self):
        source = producer.package.read_object(self.paths["source"])
        source["review"]["humanApproval"] = False
        self.paths["source"].write_text(json.dumps(source))
        before = self.inventory()
        with self.assertRaises(ValueError):
            self.export()
        self.assertEqual(before, self.inventory())

    def test_missing_or_busy_lock_does_not_create_or_export(self):
        self.lock_path.unlink()
        with self.assertRaisesRegex(ValueError, "Existing formal render lock"):
            self.export()
        self.assertFalse(self.lock_path.exists())
        self.lock_path.touch()
        with self.lock_path.open("rb") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, "renderer active"):
                self.export()

    def test_root_symlink_and_replaced_lock_refused(self):
        alias = self.root.parent / "root-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Symlinked"):
            subject.export_snapshot(dict(self.paths, job=alias / "job.json"),
                                    self.map_path, self.policies_path, self.settings_path)
        original = producer.build_expected_intents
        def replaced(*args, **kwargs):
            result = original(*args, **kwargs)
            self.lock_path.unlink(); self.lock_path.touch()
            return result
        with patch.object(producer, "build_expected_intents", side_effect=replaced):
            with self.assertRaisesRegex(ValueError, "root/lock replaced"):
                self.export()

    def test_dependency_changed_during_build_refused(self):
        original = producer.build_expected_intents
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            self.settings_path.write_text(json.dumps(settings(seed=43)))
            return result
        with patch.object(producer, "build_expected_intents", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "Frozen dependency changed"):
                self.export()

    def test_incomplete_or_reordered_context_cannot_claim_coverage(self):
        context = producer.checked_context(self.paths, self.map_path, self.policies_path, assembly_only=True)
        context["candidate"]["groups"].reverse()
        with self.assertRaisesRegex(ValueError, "mapping differs"):
            producer.build_expected_intents(context, self.paths, settings())
        context["candidate"]["groups"].pop()
        with self.assertRaisesRegex(ValueError, "coverage differs"):
            producer.build_expected_intents(context, self.paths, settings())

    def test_cli_stdout_snapshot_without_output_option(self):
        args = ["--settings", str(self.settings_path), "--checkpoint-map", str(self.map_path),
                "--audio-operation-policies", str(self.policies_path)]
        names = {"human_receipt": "human-review-receipt", "registry": "speaker-registry"}
        for key, path in self.paths.items():
            args.extend(["--" + names.get(key, key.replace("_", "-")), str(path)])
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            subject.main(args)
        self.assertEqual(json.loads(output.getvalue())["validation"]["modelCalls"], 0)

    def test_current_snapshot_is_accepted_by_readonly_planner(self):
        from scripts import production_recovery_plan as planner
        context = producer.checked_context(self.paths, self.map_path, self.policies_path, assembly_only=True)
        producer.render_units(context, self.paths, self.root, self.map_path,
                              synth_factory=render_fixtures.FakeSynth)
        snapshot_path = self.root.parent / "expected-current.json"
        snapshot_path.write_text(json.dumps(self.export()))
        before = self.inventory()
        plan = planner.plan_layer3(self.paths["job"], expected_intents_path=snapshot_path)
        self.assertEqual(plan["counts"], {"reuse": 2, "revalidate": 0, "recompute": 0, "unknown": 0})
        self.assertEqual(before, self.inventory())


if __name__ == "__main__":
    unittest.main()
