from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from scripts import sermon_accounting as accounting
from scripts import sermon_completion as completion
from scripts import sermon_log_profile as profile
from scripts import sermon_review_contracts as c
from scripts import sermon_source_producer_compatibility as compatibility


class CompletionTests(unittest.TestCase):
    def test_terminal_leaf_only_and_equivalent_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            with profile.session(Path(directory)/'logs','completion',work_kind='engineering',evidence_mode='synthetic',production_run_id='a'*64):
                with accounting.stage('parent',depends_on=[],work_unit_id='parent') as parent:
                    with accounting.stage('child',depends_on=[],work_unit_id='child') as child: pass
                handle=completion.capture(child,production_run_id='a'*64,artifact_sha256='b'*64,
                    artifact_kind='frozen_recipe')
                with self.assertRaisesRegex(c.ContractError,'container_forbidden'):
                    completion.capture(parent,production_run_id='a'*64,artifact_sha256='b'*64,
                        artifact_kind='frozen_recipe')
                _,events=completion.current_events()
                completion.validate(handle,events+events,production_run_id='a'*64)
                for key,value in [('attemptId','wrong'),('productionRunId','f'*64),('artifactSha256','f'*64)]:
                    bad=deepcopy(handle);bad[key]=value
                    with self.subTest(key=key),self.assertRaises(c.ContractError):
                        completion.validate(bad,events,production_run_id='a'*64,artifact_sha256='b'*64)

    def test_exact_reviewed_migration_only(self):
        binding={key:'a'*64 for key in ('parentPlanSha256','newPlanSha256','sourceCanonicalSha256',
            'anchorCanonicalSha256','alignmentBytesSha256','asrReceiptSha256','sourceCheckReceiptSha256')}
        current=compatibility.FOLLOWUP_SOURCE_SHA256
        actual=c.bytes_sha256((Path(compatibility.__file__).parent/'sermon_fresh_diagnostic_source.py').read_bytes())
        self.assertEqual(current['scripts/sermon_fresh_diagnostic_source.py'],actual)
        accepted=compatibility.verify(compatibility.CURRENT_SOURCE_SHA256,current,current,binding)
        self.assertEqual(accepted['migrationId'],compatibility.FOLLOWUP_MIGRATION)
        changed=dict(current);changed['scripts/mfa_alignment.py']='f'*64
        with self.assertRaises(c.ContractError):compatibility.verify(compatibility.CURRENT_SOURCE_SHA256,changed,changed,binding)
        with self.assertRaises(c.ContractError):compatibility.verify(compatibility.HISTORICAL_SOURCE_SHA256,current,current,binding)


if __name__=='__main__':unittest.main()
