"""Validate late track binding without regenerating any audio landmarks."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node required for fingerprint builder')
class FingerprintPrecomputeTests(unittest.TestCase):
    def test_binding_hashes_real_track_and_rejects_stale_landmarks(self):
        here = Path(__file__).resolve().parent
        algorithm = subprocess.check_output(['node', '--input-type=module', '-e',
            "import { CONFIG } from './web/fingerprint-core.mjs'; console.log(CONFIG.algorithmVersion)"], cwd=here, text=True).strip()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache, track, output = root / 'source.json', root / 'track.mp3', root / 'index.json'
            track.write_bytes(b'synthetic actual track')
            cache.write_text(json.dumps({'schemaVersion': 'sermon-source-landmarks-v1', 'algorithmVersion': algorithm,
                'sourceSha256': 'a' * 64, 'sourceStartSeconds': 10, 'sourceEndSeconds': 20,
                'durationSeconds': 10, 'landmarkCount': 1, 'postings': {'fixture': [1]}}))
            sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            command = ['node', str(here / 'build_fingerprint_index.mjs'), '--mode', 'bind',
                '--precomputed', str(cache), '--precomputed-sha', sha(cache), '--source-sha', 'a' * 64,
                '--start', '10', '--end', '20', '--track', str(track), '--page-id', 'test-page', '--out', str(output)]
            subprocess.run(command, check=True, capture_output=True)
            bound = json.loads(output.read_text())
            self.assertEqual(bound['schemaVersion'], 'sermon-landmark-index-v1')
            self.assertEqual(bound['trackSha256'], sha(track))
            self.assertEqual(bound['postings'], {'fixture': [1]})
            output.unlink()
            changed = command + ['--track-sha', 'b' * 64]
            self.assertNotEqual(subprocess.run(changed, capture_output=True).returncode, 0)
            self.assertFalse(output.exists())
            cache.write_text(cache.read_text() + '\n')
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertFalse(output.exists())
