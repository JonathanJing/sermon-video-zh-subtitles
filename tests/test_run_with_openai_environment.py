import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.run_with_openai_environment import child_environment, ROOT


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
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_with_openai_environment.py'),
            '--environment', 'prod', '--env-file', str(self.path), '--', sys.executable, '-c', code], capture_output=True)
        self.assertEqual(result.returncode, 7)
        self.assertNotIn(b'fake-prod', result.stdout + result.stderr)

    def test_legacy_dotenv_cannot_override_selected_key(self):
        from scripts.sermon_pipeline import load_env
        from unittest.mock import patch
        legacy = self.path.parent / '.env'
        legacy.write_text('OPENAI_API_KEY=stale\n')
        with patch.dict(os.environ, child_environment(self.path, 'dev', {}), clear=True):
            load_env(legacy)
            self.assertEqual(os.environ['OPENAI_API_KEY'], 'fake-dev')


if __name__ == '__main__':
    unittest.main()
