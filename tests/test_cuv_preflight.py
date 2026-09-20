import unittest
from unittest.mock import Mock
from scripts.cuv_preflight import POLICY, EvidenceBlocked, preflight, require_ready


class PreflightTests(unittest.TestCase):
    def make(self):
        blocks = [{'id': 'a', 'en': 'Word plus'}, {'id': 'b', 'en': 'Word'}]
        quote = {'quoteId': 'q', 'reference': 'REV 3:21', 'start': 0, 'end': 4, 'uncertainty': []}
        rows = [{'id': b['id'], 'quotes': [{**quote, 'quoteId': str(i)}],
                 'speakerReferences': [], 'uncertainty': []} for i, b in enumerate(blocks)]
        return blocks, {'issues': [], 'blocks': rows}

    def call(self, blocks, mapping, **overrides):
        manifest = {'preflightPolicy': POLICY, **overrides}
        return preflight(manifest, mapping, blocks, self.library,
                         validate_context=self.context, audit_content=self.content)

    def setUp(self):
        self.library, self.context, self.content = Mock(), Mock(), Mock()

    def test_collects_all_references_before_selection(self):
        blocks, mapping = self.make()
        self.library.lookup.side_effect = ValueError('missing verse')
        report = self.call(blocks, mapping)
        self.assertEqual(len(report['findings']), 2)
        self.assertEqual(self.library.lookup.call_count, 2)
        with self.assertRaises(EvidenceBlocked) as caught:
            require_ready(report)
        self.assertEqual(caught.exception.as_dict()['status'], 'blocked')

    def test_classification_is_provisional_and_preserves_uncertainty(self):
        blocks, mapping = self.make()
        report = self.call(blocks, mapping)
        self.assertEqual([r['classification'] for r in report['inventory']], ['mixed', 'direct'])
        self.assertFalse(report['humanApproval'])
        self.assertTrue(all(r['requiresIndependentReview'] for r in report['inventory']))
        mapping['blocks'][0]['uncertainty'] = ['possibly quotation']
        report = self.call(blocks, mapping)
        self.assertEqual(report['inventory'][0]['classification'], 'unresolved')
        self.assertEqual(report['status'], 'ready_for_independent_review')
        self.assertTrue(report['hasPendingInterpretation'])

    def test_source_context_requires_real_images(self):
        blocks, mapping = self.make()
        mapping['blocks'][0]['sourceContext'] = {'evidenceBinding': {'path': 'frame.json', 'sha256': 'hash'}}
        report = self.call(blocks, mapping)
        self.assertEqual(report['findings'][0]['code'], 'source_images_not_enabled')
        self.content.side_effect = FileNotFoundError('missing actual frame')
        report = self.call(blocks, mapping, auditSourceMediaPolicy='images')
        self.assertEqual(report['findings'][0]['code'], 'audit_payload')
        self.content.assert_called_once()

    def test_every_shared_verse_is_looked_up(self):
        blocks, mapping = self.make()
        mapping['blocks'][0]['quotes'][0]['sharedReferences'] = ['REV 2:7', 'REV 3:5']
        report = self.call(blocks, mapping)
        self.assertIn('shared_verse_evidence_not_enabled', [f['code'] for f in report['findings']])
        refs = [call.args[0] for call in self.library.lookup.call_args_list]
        self.assertIn('REV 2:7', refs)
        self.assertIn('REV 3:5', refs)

    def test_unexpected_programming_error_is_not_evidence_block(self):
        blocks, mapping = self.make()
        self.library.lookup.side_effect = RuntimeError('bug')
        with self.assertRaises(RuntimeError):
            self.call(blocks, mapping)


class RunPreflightTests(unittest.TestCase):
    def test_missing_actual_frame_blocks_run_before_any_model_call(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from scripts import sermon_cuv_translation as mod
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / 'source.mp4'
            video.write_bytes(b'synthetic-source')
            contract = root / 'contract.json'
            mod.save_frozen(contract, {'durationSeconds': 100, 'sha256': mod.file_hash(video)})
            parent = root / 'parent' / 'job.json'
            block = {'id': 0, 'en': 'The promise is eternal life.', 'zh': '旧稿'}
            mod.save_frozen(parent, {'blocks': [block], 'inputs': {
                'sourceVideo': mod.bind(video), 'sourceContract': mod.bind(contract)}})
            frame = root / 'frame.jpg'
            frame.write_bytes(b'\xff\xd8\xfffixture')
            frame_binding = mod.bind(frame)
            evidence = root / 'visual.json'
            mod.save_frozen(evidence, {
                'schemaVersion': 'sermon-source-visual-context-v1',
                'parentJob': mod.bind(parent), 'sourceVideo': mod.bind(video),
                'sourceContract': mod.bind(contract),
                'frames': [{**frame_binding, 'fullVideoSeconds': 20, 'observedText': 'The Promise'}],
                'observer': {'type': 'model_visual_inspection', 'humanApproval': False},
                'finding': 'Source slide contains a summary.'})
            mapping = root / 'map.json'
            mod.save_frozen(mapping, {'schemaVersion': mod.MAP_SCHEMA,
                'parentJobSha256': mod.file_hash(parent), 'issues': [], 'blocks': [{
                    'id': 0, 'quotes': [], 'speakerReferences': [], 'uncertainty': [],
                    'sourceContext': {'evidenceBinding': mod.bind(evidence),
                        'frameBinding': frame_binding, 'summaryText': 'Promise',
                        'classificationRationale': 'Summary requires actual visual verification.'}}]})
            frame.unlink()
            out = root / 'out'
            with mock.patch.object(mod, 'chat_json', side_effect=AssertionError('no paid work')) as api:
                with self.assertRaises(EvidenceBlocked):
                    mod.run(parent, out, reference_map_path=mapping)
                api.assert_not_called()
            self.assertEqual('blocked', mod.read(out / 'run-status.json')['status'])
            self.assertTrue(mod.read(out / 'preflight.json')['findings'])
            self.assertFalse((out / 'spoken-review.json').exists())

    def test_global_audit_findings_are_evidence_blocked(self):
        from scripts import sermon_cuv_translation as mod
        audit = {'issues': ['Missing direct quote'], 'blocks': [{'id': 0}]}
        with self.assertRaises(EvidenceBlocked) as caught:
            mod.narration_caveats(audit, {'path': 'fixture', 'sha256': 'fixture'},
                                 [{'id': 0}], [], None, 'identity',
                                 manifest={'preflightPolicy': POLICY})
        self.assertEqual('quotation_audit', caught.exception.stage)
