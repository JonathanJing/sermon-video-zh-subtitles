import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import firebase_dev_app_shell_update as shell
from scripts import align_firebase_dev_v3 as dev


class AppShellEvidenceTests(unittest.TestCase):
    def test_plan_rejects_modified_feature_and_wrong_commit(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            public = root / 'public'
            public.mkdir()
            for name in ('app.mjs', 'index.html', 'style.css'):
                (public / name).write_text(name)
            plan = {'environment': 'production', 'status': 'prepared_not_deployed',
                    'project': 'ai-for-god-caption-dev', 'site': 'ai-for-god-sermon-audio',
                    'sourceCommit': 'a' * 40, 'changedPaths': ['/app.mjs'],
                    'sourceFiles': {name: dev.digest(public / name) for name in
                                    ('app.mjs', 'index.html', 'style.css')}}
            plan_path = root / 'ui-update-plan.json'
            plan_path.write_text(json.dumps(plan))
            def git(*args, **kwargs):
                name = args[0][-1].split('/')[-1]
                return SimpleNamespace(returncode=0, stdout=name.encode())
            with patch.object(shell.subprocess, 'run', side_effect=git):
                self.assertEqual(shell.read_plan(public, plan_path), plan)
                (public / 'app.mjs').write_text('uncommitted')
                with self.assertRaisesRegex(ValueError, 'differs from UI plan'):
                    shell.read_plan(public, plan_path)
                (public / 'app.mjs').write_text('app.mjs')
            with patch.object(shell.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=b'other')):
                with self.assertRaisesRegex(ValueError, 'recorded source commit'):
                    shell.read_plan(public, plan_path)

    def test_existing_receipt_blocks_deploy_before_side_effect(self):
        with TemporaryDirectory() as folder:
            out = Path(folder) / 'receipt.json'
            out.write_text('original')
            with patch('sys.argv', ['shell', 'deploy', '--candidate', folder,
                                    '--preflight', folder, '--out', str(out)]), patch.object(shell, 'deploy') as deploy:
                with self.assertRaises(FileExistsError):
                    shell.main()
                deploy.assert_not_called()
                self.assertEqual(out.read_text(), 'original')

    def test_missing_receipt_parent_created_before_deploy(self):
        with TemporaryDirectory() as folder:
            out = Path(folder) / 'new' / 'receipt.json'
            def deploy(*args):
                self.assertTrue(out.is_file())
                return {'status': 'deployed_http_verification_pending'}
            with patch('sys.argv', ['shell', 'deploy', '--candidate', folder,
                                    '--preflight', folder, '--out', str(out)]), patch.object(shell, 'deploy', side_effect=deploy):
                shell.main()
            self.assertEqual(json.loads(out.read_text())['status'], 'deployed_http_verification_pending')
