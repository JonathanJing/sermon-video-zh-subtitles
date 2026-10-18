import importlib.util
import json
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location("weekly_announcements", Path(__file__).resolve().parents[1] / "scripts/build_weekly_announcement_sidecar.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class WeeklyAnnouncementProducerTests(unittest.TestCase):
    def fixture(self):
        source_hash = "a" * 64
        content_hash = "b" * 64
        release = json.dumps(dict(pageId="week-1", targetLocale="zh-Hans", assets=[dict(role="content", sha256=content_hash)])).encode()
        poster = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 1080, 1920)
        catalog = dict(pages=[dict(id="week-1", sourceIdentitySha256=source_hash,
            targets={"zh-Hans": dict(contentStatus="human_reviewed", releasePackageJsonSha256=module.digest(release))})])
        receipt = dict(status="complete", source=dict(pageId="week-1", targetLocale="zh-Hans",
            sourceIdentitySha256=source_hash, contentSha256=content_hash, releasePackageSha256=module.digest(release),
            brief=dict(title="耶稣审判并保守", origin="https://formal.example.test")), outputs={"poster-preview.png": module.digest(poster)})
        return catalog, release, receipt, poster

    def test_binds_exact_artwork_and_existing_content(self):
        catalog, release, receipt, poster = self.fixture()
        item, evidence = module.build(catalog, release, receipt, poster, "zh-Hans", "week-1")
        self.assertEqual(item["releaseSHA256"], catalog["pages"][0]["targets"]["zh-Hans"]["releasePackageJsonSha256"])
        self.assertEqual(item["poster"]["width"], 1080)
        self.assertFalse(evidence["metadataRebound"])

    def test_v5_mixed_source_announcement_uses_edition_release_and_family_route(self):
        catalog, release, receipt, poster = self.fixture()
        source = 'c' * 64
        catalog.update(schemaVersion='sermon-multilingual-catalog-v5')
        page = catalog['pages'][0]
        page['sourceMode'] = 'per_target'; del page['sourceIdentitySha256']
        page['targets']['zh-Hans'].update(editionId='broadcast-edition', sourceIdentitySha256=source,
                                        sourceMediaSha256='d' * 64,
                                        videoDelivery=dict(schemaVersion='sermon-video-delivery-v1',
                                            canonicalUrl='/pages/broadcast-edition/full-video-browser.mp4',
                                            storageUrl='https://storage.googleapis.com/bucket/broadcast.mp4',
                                            sha256='d' * 64, bytes=1234))
        value = json.loads(release)
        value.update(pageId='broadcast-edition', englishSourcePackageJsonSha256=source)
        release = json.dumps(value).encode()
        page['targets']['zh-Hans']['releasePackageJsonSha256'] = module.digest(release)
        receipt['source'].update(editionId='broadcast-edition', sourceIdentitySha256=source,
                                 releasePackageSha256=module.digest(release))
        item, evidence = module.build(catalog, release, receipt, poster, 'zh-Hans', 'week-1')
        self.assertEqual(item['pageID'], 'week-1')
        self.assertEqual(item['sourceIdentitySHA256'], source)
        self.assertEqual(evidence['pageID'], 'week-1')
        receipt['source']['sourceIdentitySha256'] = 'e' * 64
        with self.assertRaisesRegex(ValueError, 'source/page/language changed'):
            module.build(catalog, release, receipt, poster, 'zh-Hans', 'week-1')

    def test_metadata_rebind_is_explicit_and_keeps_both_receipts(self):
        catalog, release, receipt, poster = self.fixture()
        receipt["source"]["releasePackageSha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "explicitly allow rebind"):
            module.build(catalog, release, receipt, poster, "zh-Hans", "week-1")
        _, evidence = module.build(catalog, release, receipt, poster, "zh-Hans", "week-1", True)
        self.assertTrue(evidence["metadataRebound"])
        self.assertNotEqual(evidence["originalReleaseSHA256"], evidence["currentReleaseSHA256"])

    def test_rebind_never_accepts_changed_source_content_or_image(self):
        for changed in ("source", "content", "image"):
            catalog, release, receipt, poster = self.fixture()
            if changed == "source": receipt["source"]["sourceIdentitySha256"] = "d" * 64
            if changed == "content": receipt["source"]["contentSha256"] = "d" * 64
            if changed == "image": poster += b"modified"
            with self.assertRaises(ValueError):
                module.build(catalog, release, receipt, poster, "zh-Hans", "week-1", True)
