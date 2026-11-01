"""Offline tests for the headless poster artwork entry; no model call is dispatched."""
import binascii
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.delivery.posters import artwork

FAKE_CODEX = '''#!/usr/bin/env python3
import json, os, sys, time, uuid
from pathlib import Path

if '--version' in sys.argv:
    print('fake-codex 1.0.0'); sys.exit(0)
if os.environ.get('FAKE_COUNT_FILE'):
    with open(os.environ['FAKE_COUNT_FILE'], 'a') as handle: handle.write('1\\n')
mode = os.environ.get('FAKE_MODE', 'ok')
thread = os.environ.get('FAKE_THREAD', '01a197d9-0000-7000-8000-000000000001')
if mode == 'sleep':
    time.sleep(30)
result = Path(sys.argv[sys.argv.index('-o') + 1])
home = Path(os.environ['CODEX_HOME'])
folder = home / 'generated_images' / thread
def make(name):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ('exec-' + uuid.uuid4().hex + '.png')
    path.write_bytes(Path(os.environ['FAKE_' + name]).read_bytes())
    return path
def emit(rows):
    for row in rows: print(json.dumps(row))
rows = [{'type': 'thread.started', 'thread_id': thread}, {'type': 'turn.started'}]
if mode == 'fail':
    rows.append({'type': 'turn.failed', 'error': 'boom'})
    emit(rows); sys.exit(1)
paths = []
if mode == 'ok': paths = [make('OK')]
elif mode == 'nopath': paths = [make('OK')]
elif mode == 'wrongpath': paths = [make('OK')]
elif mode == 'two': paths = [make('OK'), make('OK')]
elif mode == 'bad_ratio': paths = [make('SQUARE')]
if mode == 'nopath': text = 'IMAGE READY'
elif mode == 'wrongpath': text = 'SAVED=/tmp/some-other-image.png'
else: text = 'SAVED=' + str(paths[0]) if paths else 'NO IMAGE'
rows.append({'type': 'item.completed', 'item': {'id': 'item_1', 'type': 'agent_message', 'text': text}})
rows.append({'type': 'turn.completed', 'usage': {'input_tokens': 1000, 'output_tokens': 10}})
emit(rows)
result.write_text(text + '\\n')
sys.exit(0)
'''

PROVENANCE = (b'jumdc2pa urn:c2pa:74e2d223-b93d-48a8-888b-5f3324c53a51 '
              b'xmp:iid:28d29d78-90e2-4e21-b203-076b8ff3b652 dnamegChatGPTgversionigpt-image '
              b'2026-11-01T16:02:36.003037747Z')


def png_bytes(width, height, provenance=None):
    def chunk(kind, payload):
        return (struct.pack('>I', len(payload)) + kind + payload +
                struct.pack('>I', binascii.crc32(kind + payload) & 0xFFFFFFFF))
    rows = (b'\x00' + b'\x80' * width) * height
    body = chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0))
    if provenance:
        body += chunk(b'caBX', provenance)
    return b'\x89PNG\r\n\x1a\n' + body + chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b'')


class PosterArtworkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / 'codex-home'
        (self.home / 'generated_images').mkdir(parents=True)
        (self.home / 'auth.json').write_text(json.dumps({'auth_mode': 'chatgpt'}))
        self.cli = self.root / 'fake-codex'
        self.cli.write_text(FAKE_CODEX)
        self.cli.chmod(0o755)
        self.png_ok = self.root / 'fake-ok.png'
        self.png_ok.write_bytes(png_bytes(1024, 1536, PROVENANCE))
        self.png_square = self.root / 'fake-square.png'
        self.png_square.write_bytes(png_bytes(1024, 1024))
        self.prompt = self.root / 'prompt.txt'
        self.prompt.write_text('Text-free portrait 2:3 background: a warm ivory paper surface.\n')
        self.environment = mock.patch.dict(os.environ, {
            'CODEX_HOME': str(self.home), 'SERMON_CODEX_CLI': str(self.cli),
            'FAKE_OK': str(self.png_ok), 'FAKE_SQUARE': str(self.png_square),
            'FAKE_COUNT_FILE': str(self.root / 'count.txt'),
        }, clear=False)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.saved_key = os.environ.pop('OPENAI_API_KEY', None)
        self.addCleanup(self._restore_key)

    def _restore_key(self):
        if self.saved_key is not None:
            os.environ['OPENAI_API_KEY'] = self.saved_key

    def dispatches(self):
        path = self.root / 'count.txt'
        return len(path.read_text().splitlines()) if path.exists() else 0

    def test_complete_dispatch_binds_artifact_prompt_and_provenance(self):
        out = self.root / 'art'
        receipt = artwork.run(self.prompt, out, 'gpt-6.1-sol', 60)
        self.assertEqual(receipt['status'], 'complete')
        self.assertEqual(self.dispatches(), 1)
        self.assertTrue((out / 'art.png').is_file())
        self.assertEqual((out / 'art-prompt.txt').read_text(), self.prompt.read_text())
        self.assertEqual(receipt['artSha256'], artwork.digest(out / 'art.png'))
        self.assertEqual((receipt['width'], receipt['height']), (1024, 1536))
        self.assertEqual(receipt['promptDelivery'], 'model_mediated_unverified')
        self.assertEqual(receipt['threadId'], '01a197d9-0000-7000-8000-000000000001')
        self.assertTrue(receipt['savedPath'].startswith('generated_images/01a197d9'))
        self.assertEqual(receipt['c2pa']['manifestUrn'], 'urn:c2pa:74e2d223-b93d-48a8-888b-5f3324c53a51')
        self.assertEqual(receipt['c2pa']['softwareAgent'], 'ChatGPT')
        self.assertEqual(receipt['c2pa']['softwareAgentVersion'], 'gpt-image')
        self.assertEqual(receipt['c2pa']['instanceId'], '28d29d78-90e2-4e21-b203-076b8ff3b652')
        self.assertEqual(receipt['agentReply'], {'present': True, 'namesSavedImage': True})
        self.assertIn(receipt['composition']['placement'], {'ok', 'edge', 'low', 'high', 'unknown'})
        self.assertIsInstance(receipt['warnings'], list)
        self.assertFalse(receipt['humanApproval'])
        self.assertFalse((out / 'started.json').exists())

    def test_turn_without_path_evidence_still_binds_the_single_artifact(self):
        os.environ['FAKE_MODE'] = 'nopath'
        out = self.root / 'art'
        receipt = artwork.run(self.prompt, out, 'gpt-6.1-sol', 60)
        self.assertEqual(receipt['status'], 'complete')
        self.assertEqual(receipt['agentReply'], {'present': True, 'namesSavedImage': False})
        self.assertTrue((out / 'art.png').is_file())

    def test_reply_naming_a_different_image_is_rejected(self):
        os.environ['FAKE_MODE'] = 'wrongpath'
        out = self.root / 'art'
        with self.assertRaisesRegex(artwork.ArtworkError, 'different image'):
            artwork.run(self.prompt, out, 'gpt-6.1-sol', 60)
        self.assertEqual(json.loads((out / 'outcome.json').read_text())['status'],
                         'failed_agent_reply_mismatch')

    def test_resume_reuses_the_verified_artifact_without_another_dispatch(self):
        out = self.root / 'art'
        first = artwork.run(self.prompt, out, 'gpt-6.1-sol', 60)
        second = artwork.run(self.prompt, out, 'gpt-6.1-sol', 60)
        self.assertEqual(first['artSha256'], second['artSha256'])
        self.assertEqual(self.dispatches(), 1)

    def test_changed_prompt_requires_a_fresh_output_directory(self):
        out = self.root / 'art'
        artwork.run(self.prompt, out, 'gpt-6.1-sol', 60)
        self.prompt.write_text('A different scene.\n')
        with self.assertRaisesRegex(artwork.ArtworkError, 'prompt changed'):
            artwork.run(self.prompt, out, 'gpt-6.1-sol', 60)

    def test_tampered_artwork_is_rejected(self):
        out = self.root / 'art'
        artwork.run(self.prompt, out, 'gpt-6.1-sol', 60)
        (out / 'art.png').write_bytes(b'not a png')
        with self.assertRaisesRegex(artwork.ArtworkError, 'modified'):
            artwork.run(self.prompt, out, 'gpt-6.1-sol', 60)

    def test_turn_without_an_image_is_a_recorded_known_failure(self):
        os.environ['FAKE_MODE'] = 'none'
        out = self.root / 'art'
        with self.assertRaisesRegex(artwork.ArtworkError, 'exactly one new generated image'):
            artwork.run(self.prompt, out, 'gpt-6.1-sol', 60)
        self.assertEqual(json.loads((out / 'outcome.json').read_text())['status'],
                         'failed_expected_one_image')
        with self.assertRaisesRegex(artwork.ArtworkError, 'not empty'):
            artwork.run(self.prompt, out, 'gpt-6.1-sol', 60)

    def test_more_than_one_image_is_rejected(self):
        os.environ['FAKE_MODE'] = 'two'
        with self.assertRaisesRegex(artwork.ArtworkError, 'exactly one new generated image'):
            artwork.run(self.prompt, self.root / 'art', 'gpt-6.1-sol', 60)

    def test_non_portrait_artwork_is_rejected_before_composition(self):
        os.environ['FAKE_MODE'] = 'bad_ratio'
        out = self.root / 'art'
        with self.assertRaisesRegex(artwork.ArtworkError, '2:3 portrait'):
            artwork.run(self.prompt, out, 'gpt-6.1-sol', 60)
        self.assertEqual(json.loads((out / 'outcome.json').read_text())['status'], 'failed_png_identity')

    def test_failed_turn_is_reported_not_bound(self):
        os.environ['FAKE_MODE'] = 'fail'
        with self.assertRaisesRegex(artwork.ArtworkError, 'did not complete cleanly'):
            artwork.run(self.prompt, self.root / 'art', 'gpt-6.1-sol', 60)

    def test_timeout_is_an_unknown_outcome_that_blocks_redisptach(self):
        os.environ['FAKE_MODE'] = 'sleep'
        out = self.root / 'art'
        with self.assertRaisesRegex(artwork.ArtworkError, 'timed out'):
            artwork.run(self.prompt, out, 'gpt-6.1-sol', 1)
        self.assertEqual(json.loads((out / 'started.json').read_text())['outcome'], 'unknown_outcome')
        with self.assertRaisesRegex(artwork.ArtworkError, 'unknown outcome'):
            artwork.run(self.prompt, out, 'gpt-6.1-sol', 1)

    def test_api_keys_are_stripped_from_the_child_because_the_tool_is_login_backed(self):
        os.environ['OPENAI_API_KEY'] = 'sk-test-not-forwarded'
        os.environ['CODEX_API_KEY'] = 'sk-test-not-forwarded'
        child = artwork.child_environment()
        self.assertNotIn('OPENAI_API_KEY', child)
        self.assertNotIn('CODEX_API_KEY', child)
        self.assertEqual(child['CODEX_HOME'], str(self.home))

    def test_non_chatgpt_auth_is_refused(self):
        (self.home / 'auth.json').write_text(json.dumps({'auth_mode': 'api_key', 'OPENAI_API_KEY': 'x'}))
        with self.assertRaisesRegex(artwork.ArtworkError, 'ChatGPT-authenticated'):
            artwork.run(self.prompt, self.root / 'art', 'gpt-6.1-sol', 60)

    def test_placeholders_are_never_sent_to_the_model(self):
        self.prompt.write_text('Title: {{title}}\n')
        with self.assertRaisesRegex(artwork.ArtworkError, 'placeholders'):
            artwork.run(self.prompt, self.root / 'art', 'gpt-6.1-sol', 60)
        self.assertEqual(self.dispatches(), 0)

    def test_dry_run_shows_the_command_without_spending_a_dispatch(self):
        result = artwork.run(self.prompt, self.root / 'art', 'gpt-6.1-sol', 60, dry_run=True)
        self.assertEqual(result['status'], 'dry_run')
        self.assertIn('image_generation', result['command'])
        self.assertIn('--disable', result['command'])
        self.assertEqual(self.dispatches(), 0)


if __name__ == '__main__':
    unittest.main()
