"""Real subprocess guard and immutable local identity; no provider/model/deployment."""
from pathlib import Path
import platform,sys,tempfile,subprocess,unittest,os
from types import ModuleType
from unittest.mock import patch
from scripts import sermon_accounting as accounting,sermon_review_contracts as c
from scripts import run_bounded_diagnostic as bounded,sermon_historical_identity as identity



class IdentityGuardTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (self.root/'scripts').mkdir();(self.root/'docs').mkdir()
        (self.root/'scripts/inert.py').write_text('VALUE=1\n')
        self.accounting_file=self.root/'scripts/sermon_accounting.py'
        self.accounting_file.write_bytes(Path(accounting.__file__).read_bytes())
        (self.root/'scripts/later.py').write_text('VALUE=2\n')
        (self.root/'docs/readme.md').write_text('initial\n')
        self.git('init','-q');self.git('add','.');self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture')
        module=ModuleType('historical_identity_fixture');module.__file__=str(self.root/'scripts/inert.py')
        self.enterContext(patch.dict(sys.modules,{'historical_identity_fixture':module}))
        self.expected=dict(gitCommit=self.git('rev-parse','HEAD').decode().strip(),trackedWorkingTreeDirty=False,
            loadedProjectCodeSha256={'scripts/inert.py':c.bytes_sha256((self.root/'scripts/inert.py').read_bytes())},
            pythonVersion=platform.python_version(),platform=sys.platform,architecture=platform.machine(),scope='synthetic Git repository fixture')
        self.witness=identity.ExecutionIdentityWitness._capture(self.root,self.expected)

    def git(self,*args):
        return subprocess.run(['git','--no-optional-locks','-C',str(self.root),*args],capture_output=True,check=True,timeout=5).stdout

    def guarded_check(self):
        with bounded.bounded_network_only():return self.witness._validate(self.expected)

    def test_real_http_only_guard_allows_pure_witness_and_still_denies_git_and_other_children(self):
        result=self.guarded_check();self.assertEqual(result['newProviderCalls'],0)
        with bounded.bounded_network_only():
            for command in ([sys.executable,'-c','pass'],['git','-C',str(self.root),'status']):
                with self.subTest(command=command[0]),self.assertRaisesRegex(c.ContractError,'diagnostic_unbounded_subprocess_forbidden'):
                    subprocess.run(command,capture_output=True,timeout=5)

    def test_tracked_docs_change_is_detected_inside_real_guard_without_spawn(self):
        (self.root/'docs/readme.md').write_text('changed\n')
        with self.assertRaisesRegex(c.ContractError,'historical_identity_git_or_tree_changed'):self.guarded_check()

    def test_staged_index_change_detected_even_after_worktree_bytes_restore(self):
        path=self.root/'docs/readme.md';path.write_text('staged\n');self.git('add','docs/readme.md');path.write_text('initial\n')
        with self.assertRaisesRegex(c.ContractError,'historical_identity_git_or_tree_changed'):self.guarded_check()

    def test_head_commit_change_detected_even_when_all_tree_bytes_restore(self):
        self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--allow-empty','-qm','new head')
        with self.assertRaisesRegex(c.ContractError,'historical_identity_git_or_tree_changed'):self.guarded_check()

    def test_loaded_module_addition_and_witness_tamper_rejected(self):
        module=ModuleType('historical_identity_later');module.__file__=str(self.root/'scripts/later.py')
        with patch.dict(sys.modules,{'historical_identity_later':module}),self.assertRaisesRegex(c.ContractError,'historical_current_code_changed'):
            self.guarded_check()
        self.witness.tree['docs/readme.md']['sha256']='0'*64
        with self.assertRaisesRegex(c.ContractError,'historical_identity_witness_changed'):self.guarded_check()

    def test_git_environment_and_loaded_module_bytes_drift_rejected(self):
        with patch.dict(os.environ,{'GIT_INDEX_FILE':str(self.root/'unapproved-index')}),self.assertRaisesRegex(c.ContractError,'historical_identity_git_or_tree_changed'):
            self.guarded_check()
        (self.root/'scripts/inert.py').write_text('VALUE=9\n')
        with self.assertRaisesRegex(c.ContractError,'historical_identity_git_or_tree_changed'):self.guarded_check()

    def test_exact_production_repository_required(self):
        with self.assertRaisesRegex(c.ContractError,'historical_identity_fixed_repository_required'):
            with bounded.bounded_network_only():self.witness.validate(self.expected)

    def test_production_capture_under_temporary_git_root_and_real_guard_without_clean_worktree_dependency(self):
        # Clone only this executable module's identical bytes into an isolated
        # committed Git fixture. The caller's real worktree need not be clean.
        with patch.object(accounting,'__file__',str(self.accounting_file)):
            expected=accounting.execution_identity()
            self.assertFalse(expected['trackedWorkingTreeDirty'])
            witness=identity.ExecutionIdentityWitness.capture(expected)
            with bounded.bounded_network_only():
                self.assertEqual(witness.validate(expected)['newProviderCalls'],0)
                with self.assertRaisesRegex(c.ContractError,'diagnostic_unbounded_subprocess_forbidden'):
                    accounting.execution_identity()

    def test_capture_has_precise_pre_provider_type_only_for_catalogued_failures(self):
        with patch.object(accounting,'__file__',str(self.accounting_file)):
            expected=accounting.execution_identity();expected['gitCommit']='0'*40
            with self.assertRaises(identity.HistoricalIdentityPreDispatchRejected) as caught:
                identity.ExecutionIdentityWitness.capture(expected)
        self.assertEqual(caught.exception.reason_code,'historical_current_code_changed')
        self.assertEqual(caught.exception.phase,'before_locale_provider_dispatch')
        self.assertIs(caught.exception.provider_dispatch_occurred,False)
        with self.assertRaisesRegex(c.ContractError,'historical_identity_reason_invalid'):
            identity.HistoricalIdentityPreDispatchRejected('private transcript content')


if __name__=='__main__':unittest.main()
