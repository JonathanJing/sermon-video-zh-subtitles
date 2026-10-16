"""Infrastructure I1: shared contracts in the package, review half in review/, scripts/ facades."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import canonical_pipeline_definition as legacy_pipeline
from scripts import sermon_accounting as accounting
from scripts import sermon_mock_tts_contract as mock_tts
from scripts import sermon_pipeline
from scripts import sermon_prefect_dag as prefect
from scripts import sermon_review_contracts as legacy
from scripts import sermon_workflow_jobs as jobs
from tongxing_production import path_aliases, ports
from tongxing_production.contracts import canonical, pipeline_definition, reasons, schemas
from tongxing_production.review import contracts as review_contracts

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / path_aliases.PRODUCTION
OLD_NAMES = ('MAX_BYTES', 'HARD_CHECKS', 'VERSIONS', 'ContractError', 'require', 'canonical_bytes',
             'canonical_sha256', 'bytes_sha256', '_pairs', 'decode_json', 'read_snapshot', '_strict_json',
             'validator', 'receipt_sha256', '_review_semantics', 'validate_gate_admission', 'validate_contract',
             'validate_candidate_artifact', 'validate_review_binding', 'validate_repair_binding',
             'validate_revision_lineage')


def child(code, cwd):
    """Run code in a fresh interpreter with the repository and package importable, from another directory."""
    environment = {**os.environ, 'PYTHONPATH': os.pathsep.join((str(ROOT / 'packages/production/src'), str(ROOT)))}
    return subprocess.run([sys.executable, '-c', code], cwd=cwd, env=environment, capture_output=True, text=True,
                          check=False)


class ContractsSplitTests(unittest.TestCase):
    def test_facades_are_the_package_modules_and_keep_every_old_name(self):
        self.assertIs(legacy, review_contracts)
        self.assertIs(legacy_pipeline, pipeline_definition)
        self.assertIs(legacy.ContractError, canonical.ContractError)
        for name in OLD_NAMES:
            with self.subTest(name=name):
                self.assertTrue(hasattr(legacy, name))
        for name in ('ContractError', 'require', 'canonical_bytes', 'canonical_sha256', 'bytes_sha256', '_pairs',
                     'decode_json', 'read_snapshot', '_strict_json', 'MAX_BYTES'):
            self.assertIs(getattr(legacy, name), getattr(canonical, name), name)

    def test_canonical_hashes_match_the_job_store_digest(self):
        corpus = [{'b': 1, 'a': [1.5, None, True, 'é', ' ']}, [], {}, 'text', 0, -1, 2**70,
                  {'nested': {'z': {'y': [{'x': 'ü'}]}}}]
        for path in sorted((ROOT / 'schemas').glob('*.json'))[:40]:
            corpus.append(json.loads(path.read_text()))
        for value in corpus:
            with self.subTest(value=str(value)[:40]):
                self.assertEqual(canonical.canonical_sha256(value), jobs._digest(value))
                self.assertEqual(pipeline_definition._digest(value), jobs._digest(value))

    def test_pipeline_digest_rejects_non_json_with_the_contract_error(self):
        # Allowed difference (design §2.1): the job store raised TypeError here.
        with self.assertRaises(canonical.ContractError):
            pipeline_definition._digest({'value': object()})
        with self.assertRaises(ValueError):
            pipeline_definition._digest({'value': float('nan')})

    def test_pre_dispatch_reasons_are_one_shared_constant(self):
        self.assertIs(sermon_pipeline.PRE_DISPATCH_REASONS, reasons.PRE_DISPATCH_REASONS)
        accounting_source = Path(accounting.__file__).read_text()
        self.assertNotIn('from scripts.sermon_pipeline import PRE_DISPATCH_REASONS', accounting_source)

    def test_schemas_load_from_the_configured_root_outside_the_repository(self):
        self.assertEqual(schemas.root(), ROOT / 'schemas')
        with tempfile.TemporaryDirectory() as directory:
            result = child('from scripts import sermon_review_contracts as c\n'
                           'c.validator("sermon-review-receipt-v1"); c.validator("sermon-target-language-policy-v3")\n'
                           'from scripts import tongxing_host\n'
                           'from tongxing_production.text import backend\n'
                           'print(backend.current().schemas.path("sermon-review-rubric-v1.schema.json").is_file())',
                           cwd=directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'True')

    def test_unconfigured_schema_root_is_unbound_and_contracts_import_nothing_else(self):
        with tempfile.TemporaryDirectory() as directory:
            result = child('import sys\n'
                           'from tongxing_production.contracts import canonical, pipeline_definition, reasons, schemas\n'
                           'from tongxing_production.review import contracts\n'
                           'loaded = sorted(n for n in sys.modules if n.startswith(("tongxing_production", "scripts")))\n'
                           'print(",".join(loaded))\n'
                           'try:\n    contracts.validator("sermon-review-receipt-v1")\n'
                           'except Exception as exc:\n    print(type(exc).__name__)\n', cwd=directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded, error = result.stdout.split()
        self.assertEqual(loaded.split(','), ['tongxing_production', 'tongxing_production.contracts',
                                             'tongxing_production.contracts.canonical',
                                             'tongxing_production.contracts.pipeline_definition',
                                             'tongxing_production.contracts.reasons',
                                             'tongxing_production.contracts.schemas',
                                             'tongxing_production.review', 'tongxing_production.review.contracts'])
        self.assertEqual(error, ports.Unbound.__name__)

    def test_review_validator_keeps_its_allowlist(self):
        with self.assertRaisesRegex(canonical.ContractError, '^unsupported_review_contract$'):
            legacy.validator('sermon-accounting-log-contract-v1')
        self.assertIs(legacy.validator('sermon-review-rubric-v1'), schemas.validator('sermon-review-rubric-v1'))

    def test_schema_root_must_be_absolute(self):
        with self.assertRaises(ValueError):
            schemas.configure('schemas')


class SplitClosureTests(unittest.TestCase):
    def test_alias_names_the_review_half_and_split_members_name_the_generic_half(self):
        self.assertEqual(path_aliases.resolve('scripts/sermon_review_contracts.py'),
                         path_aliases.PRODUCTION + 'review/contracts.py')
        self.assertEqual(path_aliases.resolve('scripts/canonical_pipeline_definition.py'),
                         path_aliases.PRODUCTION + 'contracts/pipeline_definition.py')
        for member in path_aliases.SPLIT_MEMBERS['scripts/sermon_review_contracts.py']:
            self.assertTrue((ROOT / member).is_file(), member)

    def test_closures_hash_the_split_members(self):
        before = prefect.code_identity(), mock_tts.implementation_sha256()
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory).resolve() / 'canonical.py'
            changed.write_bytes(b'# changed generic half\n')
            members = (str(changed), path_aliases.PRODUCTION + 'contracts/schemas.py')
            with patch.dict(path_aliases.SPLIT_MEMBERS, {'scripts/sermon_review_contracts.py': members}):
                after = prefect.code_identity(), mock_tts.implementation_sha256()
        self.assertNotEqual(after[0], before[0])
        self.assertNotEqual(after[1], before[1])

    def test_closure_inputs_differ_from_a_scripts_only_reading_by_the_split_files_alone(self):
        def sha(path):
            return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        legacy_inputs = {name: sha(path_aliases.resolve('scripts/' + name)) for name in prefect.CLOSURE}
        members = path_aliases.SPLIT_MEMBERS['scripts/sermon_review_contracts.py']
        self.assertEqual(prefect.code_identity(),
                         canonical.canonical_sha256({**legacy_inputs, **{path: sha(path) for path in members}}))


if __name__ == '__main__':
    unittest.main()
