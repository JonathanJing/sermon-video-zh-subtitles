import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import weekly_poster_template as template
import test_build_multilingual_sermon_posters as fixtures


class TemplateTests(unittest.TestCase):
    setUp = fixtures.MultilingualPosterTests.setUp
    save = fixtures.MultilingualPosterTests.save
    save_catalog = fixtures.MultilingualPosterTests.save_catalog
    load = fixtures.MultilingualPosterTests.load
    machine_week = fixtures.MultilingualPosterTests.machine_week
    def reference(self, bundles):
        source = bundles['zh-Hans']['source']
        return dict(**{k:source[k] for k in ('pageId','sourceIdentitySha256','contentSha256')},
                    title='Jesus Judges and Keeps', series='Revelation', scripture='Revelation 6–8:1')

    def test_fourth_artwork_never_becomes_english_content_release(self):
        bundles, _ = self.load()
        template.add_english_reference(bundles, self.reference(bundles))
        en = bundles['en']
        self.assertEqual(en['brief']['locale'], 'en')
        self.assertEqual(en['source']['targetLocale'], 'zh-Hans')
        self.assertFalse(en['source']['announcementEligible'])
        self.assertIn('contentLang=zh-Hans&lang=en',en['brief']['qrURL'])
        self.assertEqual(en['source']['releasePackageSha256'],bundles['zh-Hans']['source']['releasePackageSha256'])

    def test_english_copy_is_bound_to_exact_week_and_frozen_text(self):
        bundles, _ = self.load()
        for key in ('pageId','sourceIdentitySha256','contentSha256','title'):
            ref = self.reference(bundles);ref[key]='' if key=='title' else 'wrong'
            with self.subTest(key=key), self.assertRaises(ValueError):
                template.add_english_reference(copy.deepcopy(bundles),ref)

    def test_mixed_review_remains_visible_in_new_template_and_english(self):
        self.machine_week(('human_reviewed','machine_checked'))
        bundles,_ = self.load()
        template.add_english_reference(bundles,self.reference(bundles))
        for bundle in bundles.values():self.assertEqual(bundle['brief']['labels']['showReview'],'true')
        self.assertIn('not fully human reviewed',bundles['en']['brief']['reviewLabel'])
        self.assertIn('Mariners Church',bundles['es']['brief']['labels']['disclaimer'])

    def test_two_payloads_required_in_both_final_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);brief={'qrURL':'https://example.web.app/?week=x'}
            checks=[]
            for name,dims in [('poster.png',(1200,1800)),('poster-preview.png',(600,900))]:
                (out/name).write_bytes(b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',*dims))
                checks.append(dict(file=name,passed=True,decodedPayloads=[template.STORE_URL,brief['qrURL']]))
            report=dict(schemaVersion='tongxing-dual-qr-validation-v1',checks=checks)
            (out/'qr-validation.json').write_text(json.dumps(report))
            self.assertEqual(len(template.verify_outputs(out,brief)),3)
            checks[1]['decodedPayloads']=[brief['qrURL']]
            (out/'qr-validation.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'two exact'):template.verify_outputs(out,brief)
