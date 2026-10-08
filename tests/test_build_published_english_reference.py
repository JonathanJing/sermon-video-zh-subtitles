import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_published_english_reference import build_reference, canonical_sha
from delivery_contract import project_human_catalog

CHECKS = ('sourceIdentity', 'transcriptCompleteness', 'wordAlignment', 'sentenceAndPauseBoundaries')


class EnglishReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.public = root / 'public'
        self.private = root / 'private'
        self.public.mkdir()
        self.private.mkdir()
        transcript = self.evidence('segments.json', {'segments': []})
        anchors = self.evidence('anchors.json', {'input': {'mfaSegmentsSha256': transcript['sha256']}, 'sourceUnits': [
            {'sourceUnitId': 'u1', 'english': 'Grace to you.'},
            {'sourceUnitId': 'u2', 'english': 'And peace.'}]})
        unit_ids = ['u1', 'u2']
        receipt = self.evidence('receipt.json', dict(humanApproval=True, checks={k: 'approved' for k in CHECKS},
            anchorManifestJsonSha256=anchors['jsonSha256'], alignedSegmentsSha256=transcript['sha256'],
            reviewedSourceUnitIds=unit_ids))
        window = self.evidence('window.json', {'approved': True})
        source = {'schemaVersion': 'sermon-english-source-package-v1', 'status': 'ready_for_translation',
                  'translationEligible': True,
                  'source': {'media': {'sha256': 'b' * 64}, 'approvedWindow': {
                      'humanApproval': True, 'status': 'approved', 'evidence': window}},
                  'transcript': {'artifact': transcript},
                  'anchors': {'artifact': anchors, 'sourceUnitCount': 2},
                  'review': {'humanApproval': True, 'checks': {k: 'approved' for k in CHECKS},
                             'evidence': receipt, 'reviewedSourceUnitIds': unit_ids}}
        self.source_path = self.private / 'source.json'
        self.source_path.write_text(json.dumps(source))
        self.source_sha = canonical_sha(source)
        self.targets = {'ko': self.publish('ko', 'human_reviewed', 'human_reviewed')}
        self.page = dict(id='week', date='2026-10-04', sourceLocale='en', sourceIdentitySha256=self.source_sha,
                         defaultTargetLocale='ko', title='Week', targets=dict(self.targets))
        self.v3 = dict(schemaVersion='sermon-multilingual-catalog-v3', generatedAt='2026-10-04T00:00:00Z',
                       defaultPageId='week', pages=[self.page])
        self.save('/multilingual-v3.json', self.v3)

    def evidence(self, name, value):
        path = self.private / name
        data = json.dumps(value).encode()
        path.write_bytes(data)
        return dict(path=str(path), sha256=hashlib.sha256(data).hexdigest(), jsonSha256=canonical_sha(value))

    def save(self, url, value):
        data = json.dumps(value).encode()
        path = self.public / url.lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def publish(self, locale, content_status, audio_status, *, content_overrides=None):
        machine = 'machine_checked' in (content_status, audio_status)
        groups = [dict(textGroupId='g1', sourceUnitIds=['u1']), dict(textGroupId='g2', sourceUnitIds=['u2'])]
        content = dict(pageId='week', targetLocale=locale, status=content_status,
                       englishSourcePackageJsonSha256=self.source_sha, sourceMediaSha256='b' * 64,
                       targetLanguageCandidateJsonSha256='c' * 64, cues=groups)
        content.update(content_overrides or {})
        content_sha = self.save(f'/content/week/{locale}.json', content)
        captions_sha = self.save(f'/captions/week/{locale}.json', dict(cues=[dict(textGroupId='g1'), dict(textGroupId='g2')]))
        release = dict(status='published_http_verified', contentStatus=content_status, audioStatus=audio_status,
                       pageId='week', targetLocale=locale, contentLocale=locale, targetLanguageCandidateJsonSha256='c' * 64,
                       englishSourcePackageJsonSha256=self.source_sha,
                       schemaVersion='sermon-target-language-release-package-v4' if machine
                       else 'sermon-target-language-release-package-v3',
                       assets=[dict(role='content', path=f'/content/week/{locale}.json', sha256=content_sha),
                               dict(role='captions', path=f'/captions/week/{locale}.json', sha256=captions_sha)])
        url = f"/releases-{'v4' if machine else 'v2'}/week/{locale}.json"
        return dict(releasePackageUrl=url, releasePackageJsonSha256=self.save(url, release),
                    contentStatus=content_status, audioStatus=audio_status, capabilities=['text', 'captions', 'audio'])

    def seal_v4(self):
        self.page['targets']['es'] = self.publish('es', 'machine_checked', 'machine_checked')
        v4 = dict(self.v3, schemaVersion='sermon-multilingual-catalog-v4')
        self.save('/multilingual-v4.json', v4)
        self.save('/multilingual-v3.json', project_human_catalog(v4))
        return v4

    def test_v3_snapshot_lists_human_locales(self):
        reference = build_reference(self.public, 'week', self.source_path)
        self.assertEqual(reference['reviewState'], 'human_approved')
        self.assertEqual(list(reference['targets']), ['ko'])
        self.assertEqual([b['english'] for b in reference['targets']['ko']['blocks']], ['Grace to you.', 'And peace.'])

    def test_v3_snapshot_rejects_machine_checked_release(self):
        target = self.publish('ko', 'machine_checked', 'machine_checked')
        self.page['targets']['ko'] = dict(self.targets['ko'], releasePackageJsonSha256=target['releasePackageJsonSha256'],
                                          releasePackageUrl=target['releasePackageUrl'])
        self.save('/multilingual-v3.json', self.v3)
        with self.assertRaisesRegex(ValueError, 'Unpublished or unreviewed release: ko'):
            build_reference(self.public, 'week', self.source_path)

    def test_v4_snapshot_adds_machine_checked_locale(self):
        self.seal_v4()
        reference = build_reference(self.public, 'week', self.source_path)
        self.assertEqual(sorted(reference['targets']), ['es', 'ko'])
        es = reference['targets']['es']
        self.assertEqual(es['releasePackageJsonSha256'], self.page['targets']['es']['releasePackageJsonSha256'])
        self.assertEqual([b['textGroupId'] for b in es['blocks']], ['g1', 'g2'])
        # reviewState covers the English source only; it never restates a locale's translation status.
        self.assertEqual(reference['reviewState'], 'human_approved')
        self.assertNotIn('human', json.dumps(es))

    def test_v4_snapshot_rejects_diverged_v3(self):
        self.seal_v4()
        self.save('/multilingual-v3.json', self.v3)  # still lists es, so not the human-only projection
        with self.assertRaisesRegex(ValueError, 'human-only projection'):
            build_reference(self.public, 'week', self.source_path)

    def test_v4_snapshot_rejects_content_status_promotion(self):
        self.seal_v4()
        es = self.publish('es', 'machine_checked', 'machine_checked', content_overrides={'status': 'human_reviewed'})
        self.page['targets']['es'] = es
        v4 = dict(self.v3, schemaVersion='sermon-multilingual-catalog-v4')
        self.save('/multilingual-v4.json', v4)
        with self.assertRaisesRegex(ValueError, 'Content identity/status mismatch: es'):
            build_reference(self.public, 'week', self.source_path)

    def test_v4_snapshot_rejects_catalog_status_differing_from_release(self):
        self.seal_v4()
        es = self.publish('es', 'machine_checked', 'machine_checked')
        self.page['targets']['es'] = dict(es, audioStatus='human_reviewed')
        v4 = dict(self.v3, schemaVersion='sermon-multilingual-catalog-v4')
        self.save('/multilingual-v4.json', v4)
        with self.assertRaisesRegex(ValueError, 'v4 catalog target: es'):
            build_reference(self.public, 'week', self.source_path)


if __name__ == '__main__':
    unittest.main()
