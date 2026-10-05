import copy
import unittest
from scripts.experiments.assess_fixed_clip_local_models import assess_rows


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.audio=[];self.asr=[];self.units={}
        for i in range(1,14):
            sid=f'u{i}';gid=f'fresh-g{i:03d}'
            self.units[sid]={'start':(i-1)*10,'end':i*10}
            self.audio.append({'groupId':gid,'sourceUnitIds':[sid],'text':'测试原文。',
                               'audioSha256':str(i),'audioSeconds':9})
            self.asr.append({'groupId':gid,'expectedText':'测试原文。','recognizedText':'测试原文。',
                             'audioSha256':str(i)})

    def test_model_success_never_grants_publication_or_human_approval(self):
        r=assess_rows(self.audio,self.asr,self.units,180)
        self.assertFalse(r['publicationEligible']);self.assertFalse(r['humanApproval'])
        self.assertFalse(r['formalEligible']);self.assertEqual(r['overlongGroups'],[])
        self.assertIn('canonical_audio_and_sync_not_run',r['publicationBlockers'])

    def test_overlong_total_and_individual_window_are_reported(self):
        for row in self.audio:row['audioSeconds']=15
        r=assess_rows(self.audio,self.asr,self.units,180)
        self.assertEqual(r['exceedsSourceSeconds'],15)
        self.assertEqual(len(r['overlongGroups']),13)
        self.assertIn('diagnostic_audio_exceeds_source_duration',r['publicationBlockers'])
        self.assertIn('diagnostic_formal_max_lag_exceeded',r['publicationBlockers'])

    def test_asr_difference_is_review_evidence_not_auto_approval(self):
        self.asr[0]['recognizedText']='完全不同的内容'
        r=assess_rows(self.audio,self.asr,self.units,180)
        self.assertEqual(r['asrBelowThreshold'],['fresh-g001'])
        self.assertIn('diagnostic_asr_requires_review',r['publicationBlockers'])

    def test_own_span_excess_can_borrow_slack_without_formal_violation(self):
        self.audio[0]['audioSeconds']=11
        r=assess_rows(self.audio,self.asr,self.units,180)
        self.assertEqual(r['overlongGroups'],['fresh-g001'])
        self.assertEqual(r['synchronizationPlan']['maxLagViolations'],[])
        self.assertEqual(r['synchronizationPlan']['clipTailOverflows'],[])
        self.assertNotIn('diagnostic_formal_max_lag_exceeded',r['publicationBlockers'])
        self.assertFalse(r['publicationEligible'])

    def test_missing_reordered_or_changed_readback_is_rejected(self):
        for rows in (self.asr[:-1],list(reversed(self.asr))):
            with self.assertRaisesRegex(ValueError,'group_coverage'):
                assess_rows(self.audio,rows,self.units,180)
        changed=copy.deepcopy(self.asr);changed[0]['audioSha256']='changed'
        with self.assertRaisesRegex(ValueError,'binding_changed'):
            assess_rows(self.audio,changed,self.units,180)

if __name__=='__main__':unittest.main()
