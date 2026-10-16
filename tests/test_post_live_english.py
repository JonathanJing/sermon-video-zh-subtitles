"""W3b: the Layer 1 English group lives in source/post_live_english.

The dual_pdf pipeline imports these names back, post-live's run identity hashes the
new file, and closures that list the legacy monolith also list it.
"""
import unittest

from scripts import run_post_live_subtitle_generation as post_live
from scripts import sermon_pipeline
from tongxing_production import path_aliases
from tongxing_production.source import post_live_english


class PostLiveEnglishTests(unittest.TestCase):
    def test_pipeline_names_are_the_moved_objects(self):
        for name in ('transcribe_openai_audio', 'transcribe_reference', 'transcribe_reference_chunks',
                     'transcription_cache_identity', 'read_transcription_cache', 'write_transcription_cache',
                     'correct_english', 'mfa_options', 'precompute_source_fingerprint', 'clean_text',
                     'read_json', 'write_json', 'ffprobe_duration', 'source_file_identity', 'DEFAULT_ZH_TERM_MAP'):
            with self.subTest(name=name):
                self.assertIs(getattr(sermon_pipeline, name), getattr(post_live_english, name))

    def test_layer_1_module_imports_nothing_from_the_dual_pdf_workflow(self):
        text = open(post_live_english.__file__, encoding='utf-8').read()
        self.assertNotIn('workflows', text.split('"""', 2)[2])
        self.assertNotIn('from scripts', text)

    def test_post_live_identity_and_split_members_cover_the_new_file(self):
        member = 'packages/production/src/tongxing_production/source/post_live_english.py'
        self.assertIn(member, path_aliases.SPLIT_MEMBERS['scripts/sermon_pipeline.py'])
        self.assertEqual(post_live.POST_LIVE_ENGLISH_SCRIPT, post_live.REPO_ROOT / member)
        self.assertTrue(post_live.POST_LIVE_ENGLISH_SCRIPT.is_file())


if __name__ == '__main__':
    unittest.main()
