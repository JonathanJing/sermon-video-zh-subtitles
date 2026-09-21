import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "render_multilingual_voice_demos", ROOT / "scripts/render_multilingual_voice_demos.py"
)
subject = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(subject)


class MultilingualVoiceDemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads((ROOT / "config/speaker-voice-registry.json").read_text())
        cls.script = json.loads(
            (ROOT / "experiments/sermon-dubbing-poc/multilingual-voice-demo-script-v1.json").read_text()
        )
        cls.checkpoint_map = {
            "schemaVersion": "sermon-speaker-checkpoint-map-v1",
            "checkpoints": [
                {
                    "speakerId": speaker["speakerId"],
                    "checkpointRef": speaker["checkpoint"]["checkpointRef"],
                    "path": f"/deployment/{speaker['speakerId']}/checkpoint",
                }
                for speaker in cls.registry["speakers"]
            ],
        }

    def test_qwen_sft_renderer_expands_only_its_three_supported_locales(self):
        tasks = subject.prepare_tasks(self.registry, self.script, self.checkpoint_map)
        self.assertEqual(len(tasks), 18)
        self.assertEqual({task["targetLocale"] for task in tasks}, {"zh-Hans", "ko", "es"})
        self.assertEqual(len({task["speakerId"] for task in tasks}), 6)

    def test_adapter_override_must_use_its_own_renderer(self):
        with self.assertRaisesRegex(ValueError, "registered adapter override"):
            subject.prepare_tasks(self.registry, self.script, self.checkpoint_map, selected_locales=["vi"])

    def test_language_parameter_must_match_registry(self):
        changed = json.loads(json.dumps(self.script))
        changed["locales"][1]["modelLanguage"] = "Chinese"
        with self.assertRaisesRegex(ValueError, "Model language mismatch"):
            subject.prepare_tasks(self.registry, changed, self.checkpoint_map)

    def test_checkpoint_ref_cannot_be_redirected_by_deployment_map(self):
        changed = json.loads(json.dumps(self.checkpoint_map))
        changed["checkpoints"][0]["checkpointRef"] = "speaker-voice://wrong"
        with self.assertRaisesRegex(ValueError, "Checkpoint mapping ref differs"):
            subject.prepare_tasks(self.registry, self.script, changed)


if __name__ == "__main__":
    unittest.main()
