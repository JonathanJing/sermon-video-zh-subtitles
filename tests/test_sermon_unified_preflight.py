import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_canonical_layer2_controller as fixtures
from tools.ops import sermon_unified_preflight as subject
from tongxing_production.text import stat_memo


class UnifiedPreflightTests(unittest.TestCase):
    def test_moved_implementation_bytes_are_in_loaded_code_identity(self):
        original_read_bytes = Path.read_bytes
        target = Path(subject.__file__).resolve()
        touched = []

        def changed_bytes(path):
            data = original_read_bytes(path)
            if path.resolve() == target:
                touched.append(True)
                return data + b'\n# synthetic identity change\n'
            return data

        baseline = subject.layer2.code_identity()
        # A patched read leaves the stat identity unchanged; a fresh binding memo forces the full hash.
        with patch.object(Path, 'read_bytes', changed_bytes), \
                patch.object(subject.layer2, '_BINDING_MEMO', stat_memo.StatMemo()):
            changed = subject.layer2.code_identity()
        self.assertTrue(touched)
        self.assertNotEqual(baseline, changed)

    def setUp(self):
        self.fixture = fixtures.CanonicalLayer2ControllerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_real_validators_read_only_and_report_actual_capacity_and_missing_downstream(self):
        before = self.fixture.files()
        with patch.object(subject.layer2.os.environ, 'get', side_effect=AssertionError('secret lookup')), \
                patch.object(subject.jobs, 'start_job', side_effect=AssertionError('dispatch')):
            result = subject.inspect_config(self.fixture.path)
        self.assertEqual(self.fixture.files(), before)
        self.assertTrue(result['layer2Ready'], result)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['maxConcurrentLocaleJobs'], 1)
        self.assertEqual(result['maxInFlightApiCalls'], 24)
        self.assertEqual(result['apiSlotRoot'], str(self.fixture.root.resolve() / '.jobs.layer2-api-slots'))
        self.assertTrue(result['locales']['zh-Hans']['pluginIdentityVerified'])
        self.assertEqual({b['stage'] for b in result['blockers']}, {'audio', 'release'})
        self.assertFalse((self.fixture.root / 'jobs').exists())

    def test_code_identity_mismatch_prevents_layer2_ready(self):
        result = subject.inspect_config(self.fixture.path, expected_code_identity='f' * 64)
        self.assertFalse(result['layer2Ready'])
        self.assertIn('code_closure_changed', [b['reasonCode'] for b in result['blockers']])

    def test_uncertain_owner_keeps_slot_occupied(self):
        with self.fixture.active(status='uncertain'):
            result = subject.inspect_config(self.fixture.path)
        self.assertEqual(result['occupiedLocaleSlots'], 1)
        self.assertFalse(result['layer2Ready'])
        self.assertIn('locale_slot_occupied_until_completion_or_reconciliation',
                      [b['reasonCode'] for b in result['blockers']])

    def test_invalid_config_is_structured_failure(self):
        self.fixture.path.write_text('{}')
        result = subject.inspect_config(self.fixture.path)
        self.assertEqual(result['blockers'][0]['reasonCode'], 'invalid_layer2_execution_configuration')
