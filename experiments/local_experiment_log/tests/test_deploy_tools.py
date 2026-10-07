import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from experiments.local_experiment_log import deploy_tools as deploy


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.source = self.base/'source'
        for name, data in {
            'experiments/local_experiment_log/deploy_tools.py': Path(deploy.__file__).read_bytes(),
            'experiments/local_experiment_log/tool.py': b'print("one")\n',
            'scripts/sermon_log_contract.py': b'# validator\n',
            'schemas/sermon-accounting-log-contract-v1.schema.json': b'{}\n',
        }.items():
            path = self.source/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.bundle = self.base/'bundle.tgz'
        deploy.build(self.source, self.bundle, 'a'*40)
        self.root = self.base/'isolated-tools'

    def rewrite_bundle(self, change):
        with tarfile.open(self.bundle, 'r:gz') as archive:
            entries = [(member.name, archive.extractfile(member).read()) for member in archive]
        entries = change(entries)
        with tarfile.open(self.bundle, 'w:gz') as archive:
            for name, data in entries:
                member = tarfile.TarInfo(name); member.size = len(data)
                archive.addfile(member, io.BytesIO(data))

    def test_install_verify_and_first_install_rollback(self):
        receipt = deploy.install(self.bundle, self.root)
        identity = deploy.verify_release(self.root/receipt['current_target'])
        self.assertEqual(identity['release_id'], receipt['release_id'])
        self.assertEqual(receipt['service_restarts'], 0)
        self.assertIsNone(receipt['previous_target'])
        deploy.rollback(receipt)
        self.assertFalse((self.root/'current').exists())
        self.assertTrue((self.root/receipt['current_target']).is_dir())

    def test_upgrade_rollback_restores_previous_release(self):
        first = deploy.install(self.bundle, self.root)
        (self.source/'experiments/local_experiment_log/tool.py').write_bytes(b'print("two")\n')
        deploy.build(self.source, self.bundle, 'a'*40)
        second = deploy.install(self.bundle, self.root)
        self.assertNotEqual(first['release_id'], second['release_id'])
        self.assertEqual(second['previous_target'], first['current_target'])
        deploy.rollback(second)
        self.assertEqual((self.root/'current').readlink().as_posix(), first['current_target'])

    def test_corrupt_bundle_rejected_before_install(self):
        self.rewrite_bundle(lambda entries: [(name, b'corrupt' if name.endswith('tool.py') else data) for name, data in entries])
        with self.assertRaisesRegex(ValueError, 'bundle_hash_mismatch'):
            deploy.install(self.bundle, self.root)
        self.assertFalse(self.root.exists())

    def test_path_escape_rejected_before_install(self):
        self.rewrite_bundle(lambda entries: entries+[('../escape.py', b'bad')])
        with self.assertRaisesRegex(ValueError, 'unsafe_bundle_member'):
            deploy.install(self.bundle, self.root)
        self.assertFalse((self.base/'escape.py').exists())

    def test_symlink_install_root_rejected(self):
        self.root.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'unsafe_install_directory'):
            deploy.install(self.bundle, self.root)

    def test_foreign_pointer_rejected(self):
        self.root.mkdir()
        (self.root/'current').symlink_to('/outside/production')
        with self.assertRaisesRegex(ValueError, 'foreign_current_pointer'):
            deploy.install(self.bundle, self.root)
        self.assertEqual((self.root/'current').readlink().as_posix(), '/outside/production')

    def test_modified_release_blocks_reuse_and_rollback(self):
        receipt = deploy.install(self.bundle, self.root)
        (self.root/receipt['current_target']/'experiments/local_experiment_log/tool.py').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'installed_release_hash_mismatch'):
            deploy.install(self.bundle, self.root)

    def test_rollback_cannot_overwrite_changed_pointer(self):
        receipt = deploy.install(self.bundle, self.root)
        current = self.root/'current'
        current.unlink(); current.symlink_to('releases/0000000000000000')
        with self.assertRaisesRegex(ValueError, 'rollback_pointer_changed'):
            deploy.rollback(receipt)


if __name__ == '__main__':
    unittest.main()
