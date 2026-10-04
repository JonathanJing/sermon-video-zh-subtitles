import tempfile
from pathlib import Path
import unittest
from scripts import review_target_language_audio as review
from tests.test_review_target_language_audio import fixture


class AdjudicationDetailTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.package,self.screening=fixture()
        for ref in (self.package['units'][0]['audio'],self.package['track']):
            p=self.root/ref['path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture audio bytes')
            ref['sha256']=review.identity.sha256(p)
        unit=self.package['units'][0]
        self.screening['trackSha256']=self.package['track']['sha256']
        self.screening['unitAudioSha256s']=[unit['audio']['sha256']]
        self.screening['results'][0]['audioSha256']=unit['audio']['sha256']
        self.details=review.prepare_details(self.package,self.screening)
        self.details['details'][0].update(reason='asr_misrecognition',evidence='Individually adjudicated fixture',
                                         correctedTranscript='fixture correction')
        self.worksheet=review.prepare(self.package,self.screening)
        self.worksheet.update(decision='approved',reviewedBy='fixture-human',reviewedAt='2026-10-04T00:00:00Z',
                              fullPlayback='approved',videoSync1x='approved',
                              checks={key:'approved' for key in review.CHECKS})
        self.worksheet['asrAdjudications'][0].update(decision='approved',evidence='fixture review')

    def test_optional_details_preserve_existing_receipt_and_bind_unit_truth(self):
        summary=review.validate_details(self.package,self.screening,self.details,artifact_root=self.root)
        self.assertEqual(summary['reviewQueueFalseAlarmFraction'],1)
        old=review.approve(self.package,self.screening,self.worksheet)
        new=review.approve(self.package,self.screening,self.worksheet,adjudication_details=self.details,artifact_root=self.root)
        self.assertEqual(old,new)
        self.details['details'][0]['targetTextSha256']='0'*64
        with self.assertRaisesRegex(ValueError,'binding changed'):
            review.validate_details(self.package,self.screening,self.details,artifact_root=self.root)

    def test_unresolved_truth_is_not_counted_or_approved(self):
        self.details['details'][0]['reason']='unresolved'
        summary=review.validate_details(self.package,self.screening,self.details,artifact_root=self.root)
        self.assertIsNone(summary['reviewQueueFalseAlarmFraction'])
        with self.assertRaisesRegex(ValueError,'requires repair or adjudication'):
            review.approve(self.package,self.screening,self.worksheet,adjudication_details=self.details,artifact_root=self.root)

    def test_changed_track_invalidates_detail_even_when_unit_unchanged(self):
        (self.root/self.package['track']['path']).write_bytes(b'changed track')
        with self.assertRaisesRegex(ValueError,'audio hash changed'):
            review.validate_details(self.package,self.screening,self.details,artifact_root=self.root)
