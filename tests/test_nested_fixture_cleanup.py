"""A failed nested fixture must not poison tempfile state for later tests."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_sermon_business_prefect_flow as business
from tests import test_sermon_local_business_callbacks as local


class NestedFixtureCleanupTests(unittest.TestCase):
    def test_business_nested_setup_failure_restores_tempdir_and_runs_child_cleanup(self):
        tempfile.gettempdir()
        original = tempfile.tempdir
        child_cleaned = []
        scope_roots = []
        def fail_setup(child):
            scope_roots.append(Path(tempfile.tempdir))
            child.addCleanup(child_cleaned.append, True)
            raise RuntimeError('synthetic preparation setup failure')
        owner = business.BusinessFlowTests()
        try:
            with patch.object(local.speech_fixtures.PreparationTests, 'setUp', fail_setup):
                with self.assertRaisesRegex(RuntimeError, 'synthetic preparation setup failure'):
                    owner.test_different_store_or_run_admission_is_rejected()
        finally:
            owner.doCleanups()
        self.assertEqual(tempfile.tempdir, original)
        self.assertEqual(child_cleaned, [True])
        self.assertTrue(scope_roots)
        self.assertFalse(scope_roots[0].exists())
        with tempfile.TemporaryDirectory() as subsequent:
            self.assertTrue(Path(subsequent).is_dir())

    def test_bounded_setup_registers_cleanup_before_initialization(self):
        cleaned = []
        def fail_setup(child):
            child.addCleanup(cleaned.append, True)
            raise RuntimeError('synthetic bounded setup failure')
        owner = unittest.TestCase()
        try:
            with patch.object(business.fixtures.BoundedRunTests, 'setUp', fail_setup):
                with self.assertRaisesRegex(RuntimeError, 'synthetic bounded setup failure'):
                    business.setup_business(owner)
        finally:
            owner.doCleanups()
        self.assertEqual(cleaned, [True])
