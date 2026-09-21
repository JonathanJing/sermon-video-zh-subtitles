import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "render_vietnamese_voice_demos", ROOT / "scripts/render_vietnamese_voice_demos.py"
)
subject = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(subject)


class VietnameseVoiceDemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads((ROOT / "config/speaker-voice-registry.json").read_text())
        cls.script = json.loads(
            (ROOT / "experiments/sermon-dubbing-poc/multilingual-voice-demo-script-v1.json").read_text()
        )
        cls.references = json.loads(
            (ROOT / "experiments/sermon-dubbing-poc/multilingual-voice-demo-references-v1.json").read_text()
        )

    def test_vietnamese_adapter_has_one_task_per_speaker(self):
        tasks = subject.prepare_tasks(self.registry, self.script, self.references)
        self.assertEqual(len(tasks), 6)
        self.assertEqual({task["adapter"] for task in tasks}, {"gwen_tts_zero_shot_reference"})
        self.assertEqual({task["revision"] for task in tasks}, {"a83e1f08656d48217a83f0ad422d1610d5b5c963"})

    def test_reference_hash_is_part_of_conditioning_identity(self):
        changed = json.loads(json.dumps(self.references))
        changed["references"][0]["sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "conditioning ref mismatch"):
            subject.prepare_tasks(self.registry, self.script, changed)

    def test_vietnamese_demo_is_split_only_at_sentence_boundaries(self):
        text = next(item["text"] for item in self.script["locales"] if item["targetLocale"] == "vi")
        chunks = subject.split_sentences(text)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(chunk.endswith(".") for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
