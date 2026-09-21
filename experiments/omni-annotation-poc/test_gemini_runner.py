import tempfile
import unittest
from pathlib import Path

from run_gemini_live import resolve_key, scrub_audio_data


class GeminiRunnerTest(unittest.TestCase):
    def test_reads_quoted_key_from_explicit_env_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text('GEMINI_API_KEY="test-key"\n', encoding="utf-8")
            self.assertEqual(resolve_key(path), "test-key")

    def test_reads_google_key_alias_from_explicit_env_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("GOOGLE_API_KEY=test-google-key\n", encoding="utf-8")
            self.assertEqual(resolve_key(path), "test-google-key")

    def test_audio_payload_is_omitted_from_saved_messages(self):
        value = {"inline_data": {"mime_type": "audio/pcm", "data": "abcd"}}
        self.assertEqual(
            scrub_audio_data(value)["inline_data"]["data"],
            "<audio omitted; serialized_length=4>",
        )


if __name__ == "__main__":
    unittest.main()
