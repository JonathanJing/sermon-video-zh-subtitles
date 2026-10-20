"""Closures keyed by legacy scripts/ names read a moved member where it lives (infrastructure I0)."""
import hashlib
import importlib.util
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from experiments.local_experiment_log import deploy_tools
from scripts import sermon_mock_tts_contract as mock_tts
from scripts import sermon_prefect_dag as prefect
from tongxing_production import path_aliases

ROOT = Path(__file__).resolve().parents[1]
MEMBER = 'scripts/sermon_guarded_command.py'


class InfrastructureAliasTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.moved = Path(self.tmp.name).resolve()/'moved.py'

    def aliased(self, data, key=MEMBER):
        """Pretend the legacy key now lives at a different file with the given bytes."""
        self.moved.write_bytes(data)
        return patch.dict(path_aliases.PATH_ALIASES, {key: str(self.moved)})

    def test_infrastructure_sections_exist_and_feed_the_alias_table(self):
        for section in (path_aliases.CONTRACTS, path_aliases.STORAGE, path_aliases.OBSERVABILITY):
            self.assertTrue(set(section.items()) <= set(path_aliases.PATH_ALIASES.items()))

    def test_closures_follow_a_byte_identical_move(self):
        before = prefect.code_identity(), mock_tts.implementation_sha256()
        with self.aliased((ROOT/MEMBER).read_bytes()):
            self.assertEqual((prefect.code_identity(), mock_tts.implementation_sha256()), before)

    def test_closures_hash_the_moved_bytes_not_the_legacy_file(self):
        before = prefect.code_identity(), mock_tts.implementation_sha256()
        with self.aliased(b'# changed implementation\n'):
            after = prefect.code_identity(), mock_tts.implementation_sha256()
        self.assertNotEqual(after[0], before[0])
        self.assertNotEqual(after[1], before[1])

    def test_log_tool_bundle_keeps_the_legacy_name_and_reads_the_moved_file(self):
        source = Path(self.tmp.name).resolve()/'source'
        for name, data in {'experiments/local_experiment_log/tool.py': b'print("one")\n',
                           'scripts/sermon_log_contract.py': b'# facade\n',
                           'schemas/sermon-accounting-log-contract-v1.schema.json': b'{}\n',
                           'schemas/sermon-accounting-log-contract-v2.schema.json': b'{}\n'}.items():
            (source/name).parent.mkdir(parents=True, exist_ok=True)
            (source/name).write_bytes(data)
        bundle = Path(self.tmp.name)/'bundle.tgz'
        with self.aliased(b'# validator\n', key='scripts/sermon_log_contract.py'):
            deploy_tools.build(source, bundle, 'a'*40)
        with tarfile.open(bundle, 'r:gz') as archive:
            self.assertEqual(archive.extractfile('scripts/sermon_log_contract.py').read(), b'# validator\n')

    def test_alias_table_loads_from_its_file_alone(self):
        """The Temporal integration check loads this file by path, outside any package."""
        spec = importlib.util.spec_from_file_location('standalone_aliases', ROOT/path_aliases.PRODUCTION/'path_aliases.py')
        standalone = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(standalone)
        self.assertEqual(standalone.PATH_ALIASES, path_aliases.PATH_ALIASES)

    def test_temporal_dependency_path_resolves_without_the_installed_package(self):
        if importlib.util.find_spec('temporalio') is None:
            self.skipTest('temporalio is installed only in the isolated Temporal runtime')
        from scripts.sermon_temporal import integration_check
        key = 'scripts/sermon_execution_harness.py'
        self.assertEqual(integration_check.dependency_path(key), ROOT/path_aliases.resolve(key))
        self.assertEqual(hashlib.sha256(integration_check.dependency_path(key).read_bytes()).hexdigest(),
                         hashlib.sha256((ROOT/key).read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
