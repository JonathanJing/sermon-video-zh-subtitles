"""Offline checks for the Beta upload admission boundary; no Apple requests."""
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import tempfile
import subprocess
import sys
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'apps/tongxing-ios/scripts/testflight.py'
spec = importlib.util.spec_from_file_location('tongxing_testflight', SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class TestFlightReleaseAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.archive = self.root / 'Tongxing.xcarchive'
        self.archive.mkdir()
        (self.archive / 'Info.plist').write_bytes(plistlib.dumps({'fixture': True}))
        self.record = {'schemaVersion': 1, 'channel': 'beta', 'status': 'archive_succeeded',
                       'bundleID': release.BUNDLE, 'version': '1.26.11', 'build': '52', 'sourceCommit': 'a' * 40,
                       'contentOrigin': 'https://ai-for-god-sermon-audio-dev.web.app',
                       'archivePath': str(self.archive),
                       'archiveManifestSHA256': release.archive_digest(self.archive)}
        self.record_path = self.root / 'release-record.json'
        self.write_record()

    def write_record(self):
        self.record_path.write_text(json.dumps(self.record))

    def ipa(self, extension_version='1.26.11', extension_id=None):
        path = self.root / 'fixture.ipa'
        with zipfile.ZipFile(path, 'w') as archive:
            for name, identifier, version in [
                ('Payload/Tongxing.app/Info.plist', release.BUNDLE, '1.26.11'),
                ('Payload/Tongxing.app/PlugIns/Activity.appex/Info.plist',
                 extension_id or release.BUNDLE + '.listening-activity', extension_version)
            ]:
                archive.writestr(name, plistlib.dumps({'CFBundleIdentifier': identifier,
                    'CFBundleShortVersionString': version, 'CFBundleVersion': '52',
                    'TongxingContentOrigin': self.record['contentOrigin']}))
        return path

    def test_matching_archive_and_ipa_admitted(self):
        self.assertEqual(release.validate_candidate(self.record_path, self.ipa())['build'], '52')

    def test_modified_archive_rejected(self):
        (self.archive / 'Info.plist').write_bytes(b'changed after freeze')
        with self.assertRaisesRegex(ValueError, 'hash'):
            release.validate_candidate(self.record_path)

    def test_production_record_rejected(self):
        self.record['channel'] = 'production'
        self.write_record()
        with self.assertRaisesRegex(ValueError, 'Beta'):
            release.validate_candidate(self.record_path)

    def test_mismatching_extension_version_rejected(self):
        with self.assertRaisesRegex(ValueError, 'identity/version/build'):
            release.validate_candidate(self.record_path, self.ipa(extension_version='1.26.10'))

    def test_wrong_extension_identity_rejected(self):
        with self.assertRaisesRegex(ValueError, 'identity/version/build'):
            release.validate_candidate(self.record_path, self.ipa(extension_id='another.app.extension'))

    def test_private_file_permissions(self):
        key = self.root / 'fixture.p8'
        key.write_text('fixture only, not a private key')
        key.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'mode 600'):
            release.private_file(key)
        key.chmod(0o600)
        self.assertEqual(release.private_file(key), key.resolve())

    def test_configure_private_metadata_and_refuse_overwrite(self):
        key = self.root / 'fixture.p8'
        key.write_text('not a real private key')
        key.chmod(0o600)
        config = self.root / 'private/config.json'
        command = [sys.executable, str(SCRIPT), 'configure', '--config', str(config),
                   '--key-file', str(key), '--key-id', 'FIXTURE', '--issuer-id', 'fixture-only']
        dry = subprocess.run(command + ['--dry-run'], capture_output=True, text=True)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertFalse(config.exists())
        created = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(config.parent.stat().st_mode & 0o777, 0o700)
        self.assertNotIn('not a real private key', config.read_text())
        refused = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('already exists', refused.stderr)

    def test_unknown_upload_blocks_retry_and_binds_receipt(self):
        # Fake fastlane exits before any network. The wrapper must still preserve intent.
        key = self.root / 'fixture.p8'
        key.write_text('not a real private key')
        key.chmod(0o600)
        config = self.root / 'config.json'
        config.write_text(json.dumps({'key_filepath': str(key), 'key_id': 'FIXTURE', 'issuer_id': 'fixture'}))
        config.chmod(0o600)
        tool_dir = self.root / 'bin'
        tool_dir.mkdir()
        counter = self.root / 'calls'
        tool = tool_dir / 'fastlane'
        tool.write_text('#!' + sys.executable + '\nfrom pathlib import Path\np = Path(' + repr(str(counter)) +
                        ')\np.write_text(p.read_text() + "x" if p.exists() else "x")\nraise SystemExit(83)\n')
        tool.chmod(0o700)
        command = [sys.executable, str(SCRIPT), 'upload', '--config', str(config),
                   '--record', str(self.record_path), '--ipa', str(self.ipa())]
        env = dict(os.environ, PATH=str(tool_dir) + os.pathsep + os.environ['PATH'])
        first = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(first.returncode, 83, first.stderr)
        intent = json.loads(next((self.root / 'upload-intents').glob('*.json')).read_text())
        evidence = Path(intent['evidenceDir'])
        self.addCleanup(__import__('shutil').rmtree, evidence)
        receipt = json.loads((evidence / 'command-result.json').read_text())
        self.assertEqual(receipt['candidate']['sourceCommit'], self.record['sourceCommit'])
        self.assertEqual(receipt['candidate']['archiveManifestSHA256'], self.record['archiveManifestSHA256'])
        self.assertEqual(receipt['ipaSHA256'], intent['ipaSHA256'])
        second = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertNotEqual(second.returncode, 0)
        self.assertIn('Prior upload attempt', second.stderr)
        self.assertEqual(counter.read_text(), 'x')
        with zipfile.ZipFile(self.root / 'fixture.ipa', 'a') as ipa:
            ipa.writestr('Payload/Tongxing.app/changed.txt', 'different binary package')
        different = subprocess.run(command + ['--retry-upload'], env=env, capture_output=True, text=True)
        self.assertNotEqual(different.returncode, 0)
        self.assertIn('different IPA', different.stderr)
        self.assertEqual(counter.read_text(), 'x')

    def test_repository_credential_path_rejected(self):
        with self.assertRaisesRegex(ValueError, 'outside this repository'):
            release.private_file(SCRIPT)


if __name__ == '__main__':
    unittest.main()
