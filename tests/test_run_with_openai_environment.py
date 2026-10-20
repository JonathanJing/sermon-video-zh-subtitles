import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.ops.run_with_openai_environment import child_environment, ROOT


class RuntimeEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / '.env.openai'
        self.path.write_text('OPENAI_DEV_PROJECT_ID=proj_dev\nOPENAI_DEV_API_KEY=fake-dev\n'
                             'OPENAI_PROD_PROJECT_ID=proj_prod\nOPENAI_PROD_API_KEY=fake-prod\n')
        self.path.chmod(0o600)

    def test_selection_replaces_inherited_credentials_and_excludes_other_environment(self):
        for selected in ('dev', 'prod'):
            env = child_environment(self.path, selected, {'OPENAI_API_KEY': 'stale',
                'OPENAI_DEV_API_KEY': 'stale-dev', 'OPENAI_PROD_API_KEY': 'stale-prod',
                'OPENAI_API_KEY_SECRET': 'stale-secret', 'PATH': '/bin'})
            self.assertEqual(env['OPENAI_API_KEY'], 'fake-' + selected)
            self.assertEqual(env['OPENAI_PROJECT_ID'], 'proj_' + selected)
            self.assertEqual(env['SERMON_OPENAI_CREDENTIAL_ALIAS'], 'tongxing-' + selected + '-runtime')
            self.assertNotIn('OPENAI_PROD_API_KEY', env)
            self.assertNotIn('OPENAI_DEV_API_KEY', env)
            self.assertNotIn('OPENAI_API_KEY_SECRET', env)

    def test_cross_environment_sharing_rejected(self):
        for original, replacement in [('fake-prod', 'fake-dev'), ('proj_prod', 'proj_dev')]:
            text = self.path.read_text()
            self.path.write_text(text.replace(original, replacement))
            with self.assertRaisesRegex(ValueError, 'cross_environment'):
                child_environment(self.path, 'dev', {})
            self.path.write_text(text)

    def test_permissions_and_shell_expansion_rejected_without_echo(self):
        self.path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'mode_600'):
            child_environment(self.path, 'dev', {})
        self.path.chmod(0o600)
        self.path.write_text(self.path.read_text().replace('fake-dev', '$(secret-command)'))
        with self.assertRaisesRegex(ValueError, '^invalid_credential_file_value$'):
            child_environment(self.path, 'dev', {})

    def test_child_process_uses_selected_environment_and_propagates_exit(self):
        code = "import os,sys; assert os.environ['OPENAI_API_KEY']=='fake-prod'; assert 'OPENAI_DEV_API_KEY' not in os.environ; sys.exit(7)"
        result = subprocess.run([sys.executable, str(ROOT / 'tools/ops/run_with_openai_environment.py'),
            '--environment', 'prod', '--env-file', str(self.path), '--', sys.executable, '-c', code], capture_output=True)
        self.assertEqual(result.returncode, 7)
        self.assertNotIn(b'fake-prod', result.stdout + result.stderr)

    def test_extra_or_repeated_keys_rejected(self):
        text = self.path.read_text()
        for extra in ('OPENAI_API_KEY=fake-extra\n', 'OPENAI_ORG_ID=org_extra\n', 'OPENAI_DEV_API_KEY=fake-again\n'):
            self.path.write_text(text + extra)
            with self.assertRaisesRegex(ValueError, '^invalid_credential_file_assignment$'):
                child_environment(self.path, 'dev', {})
        self.path.write_text(text)

    def test_selected_project_must_be_explicit(self):
        text = self.path.read_text()
        for project in ('', 'REPLACE_WITH_DEV_PROJECT', 'org-not-a-project'):
            self.path.write_text(text.replace('proj_dev', project))
            with self.assertRaisesRegex(ValueError, '^selected_environment_not_configured$'):
                child_environment(self.path, 'dev', {})
        self.path.write_text(text)

    def test_default_key_file_is_at_the_repository_root(self):
        self.assertTrue((ROOT / 'AGENTS.md').is_file())
        self.assertEqual(ROOT, Path(__file__).resolve().parents[1])

    def test_scripts_path_runs_the_same_launcher(self):
        from scripts import run_with_openai_environment as old
        from tools.ops import run_with_openai_environment as new
        self.assertIs(old, new)
        code = "import os,sys; assert os.environ['OPENAI_PROJECT_ID']=='proj_dev'; sys.exit(5)"
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_with_openai_environment.py'),
            '--environment', 'dev', '--env-file', str(self.path), '--', sys.executable, '-c', code], capture_output=True)
        self.assertEqual(result.returncode, 5)
        self.assertNotIn(b'fake-dev', result.stdout + result.stderr)

    def test_legacy_dotenv_cannot_override_selected_key(self):
        from scripts import tongxing_host  # noqa: F401  binds the production package ports
        from tongxing_production.workflows.dual_pdf.pipeline import load_env
        from unittest.mock import patch
        legacy = self.path.parent / '.env'
        legacy.write_text('OPENAI_API_KEY=stale\n')
        with patch.dict(os.environ, child_environment(self.path, 'dev', {}), clear=True):
            load_env(legacy)
            self.assertEqual(os.environ['OPENAI_API_KEY'], 'fake-dev')


if __name__ == '__main__':
    unittest.main()
