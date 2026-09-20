import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from scripts import sermon_cuv_translation as mod
from scripts.cuv_scripture import DEFAULT_LIBRARY_PATH, DEFAULT_PROVENANCE_PATH


class SourceMediaAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.image = self.root / 'frame.jpg'
        self.image.write_bytes(b'\xff\xd8\xfftest-frame')
        self.parent = self.root / 'job.json'
        self.parent.write_text(json.dumps({'blocks': [{'id': 0, 'en': 'Conquer.', 'zh': '得胜。'}]}))
        self.evidence = self.root / 'visual.json'
        self.evidence.write_text('{}')
        self.map = self.root / 'map.json'
        self.map.write_text(json.dumps({'schemaVersion': mod.MAP_SCHEMA, 'parentJobSha256': mod.file_hash(self.parent), 'issues': [], 'blocks': [{
            'id': 0, 'uncertainty': [], 'speakerReferences': [],
            'sourceContext': {'evidenceBinding': mod.bind(self.evidence), 'frameBinding': mod.bind(self.image), 'summaryText': 'Summary', 'classificationRationale': 'Inspect image'},
            'quotes': [{'quoteId': 'q0', 'sourceText': 'Conquer.', 'reference': 'REV 2:7', 'evidence': 'formula', 'uncertainty': [],
                        'sharedReferences': ['REV 2:7', 'REV 2:26', 'REV 3:5'], 'referenceRole': 'shared_phrase_representative'}]}]}))
        self.manifest = {'auditSourceMediaPolicy': mod.AUDIT_SOURCE_MEDIA_POLICY, 'parentJob': mod.bind(self.parent),
                         'referenceMap': mod.bind(self.map), 'library': mod.bind(DEFAULT_LIBRARY_PATH), 'provenance': mod.bind(DEFAULT_PROVENANCE_PATH)}
        self.frames = {'frames': [{**mod.bind(self.image), 'fullVideoSeconds': 2, 'observedText': 'Summary'}]}

    def test_both_audits_receive_actual_bytes_and_exact_shared_verses(self):
        with mock.patch.object(mod, 'validate_source_context_evidence', return_value=self.frames) as validate:
            for stage in ['audit-quotes', 'audit-narration-caveats']:
                content = mod.audit_user_content(stage, {'original': True}, self.manifest)
                data = json.loads(content[0]['text'])
                self.assertTrue(data['original'])
                lookups = data['actualSourceEvidence']['sharedReferenceLookups'][0]['lookups']
                self.assertIn('那得胜又遵守我命令到底的', lookups[1]['fullText'])
                self.assertIn('凡得胜的', lookups[2]['fullText'])
                url = next(x['image_url']['url'] for x in content if x['type'] == 'image_url')
                self.assertEqual(base64.b64decode(url.split(',', 1)[1]), self.image.read_bytes())
            self.assertEqual(validate.call_count, 2)

    def test_legacy_and_unrelated_stage_requests_remain_exact_text(self):
        data = {'en': '原文'}
        expected = json.dumps(data, ensure_ascii=False)
        self.assertEqual(mod.audit_user_content('audit-quotes', data, {}), expected)
        self.assertEqual(mod.audit_user_content('select-0', data, self.manifest), expected)

    def test_tampered_frame_fails_before_api(self):
        self.image.write_bytes(b'\xff\xd8\xffchanged')
        with mock.patch.object(mod, 'validate_source_context_evidence', return_value=self.frames), mock.patch.object(mod, 'chat_json') as api:
            with self.assertRaises(ValueError):
                mod.audit_user_content('audit-quotes', {}, self.manifest)
            api.assert_not_called()

    def test_new_cache_binds_multimodal_payload_and_replays_offline(self):
        response = {'model': mod.MODEL, 'choices': [{'finish_reason': 'stop', 'message': {'content': '{"issues":[]}'}}]}
        with mock.patch.object(mod, 'validate_source_context_evidence', return_value=self.frames), mock.patch.dict('os.environ', {'OPENAI_API_KEY': 'test-only'}), mock.patch.object(mod, 'chat_json', return_value=response) as api:
            result, binding = mod.cached_call(self.root/'out', 'audit-quotes', 'Review', {}, 'new', manifest=self.manifest)
            payload = api.call_args.args[1]
            self.assertTrue(any(x['type'] == 'image_url' for x in payload['messages'][1]['content']))
            receipt = mod.read(binding['path'])
            self.assertEqual(receipt['request']['payload'], payload)
            self.assertEqual(receipt['requestSha256'], mod.digest(receipt['request']))
            api.reset_mock()
            again, _ = mod.cached_call(self.root/'out', 'audit-quotes', 'Review', {}, 'new', manifest=self.manifest, offline=True)
            self.assertEqual(result, again)
            api.assert_not_called()

if __name__ == '__main__':
    unittest.main()
