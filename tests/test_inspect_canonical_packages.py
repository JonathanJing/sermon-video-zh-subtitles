import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import inspect_canonical_packages as inspect
from scripts import review_target_language_candidate as review
from tests import test_produce_target_language_candidate as fixtures
from tests import test_build_english_source_package as source_fixtures
from scripts import build_english_source_package as english
from scripts import sermon_sentence_interpretation as anchors
from scripts import target_language_policy as policies


class PackageInspectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProduceTargetLanguageCandidateTests(methodName='test_compiles_valid_candidate_without_human_approval')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        source = source_fixtures.EnglishSourcePackageTests(methodName='test_bound_human_review_promotes_layer_one_only')
        source.setUp(); self.addCleanup(source.doCleanups)
        segments = copy.deepcopy(source.segments) + copy.deepcopy(source.segments)
        segments[1]['id'] = 1
        for i, segment in enumerate(segments):
            segment['referenceChunkId'] = 'block-1'
            segment['start'] += i * 3; segment['end'] += i * 3
            for word in segment['wordTimes']:
                word['start'] += i * 3; word['end'] += i * 3
        source_fixtures.write_json(source.segments_path, segments)
        source.manifest = anchors.build_anchor_manifest(segments, source_path=source.segments_path,
                                                       unit_policy=anchors.UNIT_POLICY_V2)
        source_fixtures.write_json(source.manifest_path, source.manifest)
        unit_ids = [u['sourceUnitId'] for u in source.manifest['sourceUnits']]
        review_path = source.root / 'source-review.json'
        source_fixtures.write_json(review_path, dict(schemaVersion=english.REVIEW_SCHEMA_VERSION,
            alignedSegmentsSha256=english.file_sha256(source.segments_path),
            anchorManifestJsonSha256=english.json_sha256(source.manifest), humanApproval=True,
            reviewedBy='Synthetic source reviewer', reviewedAt='2026-09-30T00:00:00Z',
            reviewedSourceUnitIds=unit_ids, checks={k: 'approved' for k in english.APPROVED_CHECKS}))
        self.fixture.source = source.build(review_path=review_path)
        self.fixture.anchor = source.manifest
        policy = copy.deepcopy(self.fixture.policy); policy.pop('componentSha256')
        policy['sourceScope']['englishSourcePackageJsonSha256'] = english.json_sha256(self.fixture.source)
        policy['sourceScope']['anchorManifestSha256'] = english.json_sha256(source.manifest)
        self.fixture.policy = policies.freeze_policy(policy)
        self.fixture.request = fixtures.subject.prepare_request(self.fixture.source, self.fixture.anchor, self.fixture.policy)
        self.fixture.evidence.update({k: v for k, v in self.fixture.request.items() if k not in {'groups', 'generation'}})
        for group, unit_id in zip(self.fixture.evidence['groups'], unit_ids):
            group['sourceUnitIds'] = [unit_id]; group['coverage'][0]['sourceUnitId'] = unit_id
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.root = Path(tmp.name)
        self.path = self.root / 'inspection.json'
        self.candidate = self.fixture.admit()
        for name, value in (('source', self.fixture.source), ('anchor', self.fixture.anchor),
                            ('policy', self.fixture.policy), ('candidate', self.candidate)):
            self.write(name + '.json', value)
        self.config = {'schemaVersion': inspect.SCHEMA, 'source': 'source.json', 'anchor': 'anchor.json',
                       'locales': {'zh-Hans': {'policy': 'policy.json', 'candidate': 'candidate.json'}}}
        self.write('inspection.json', self.config)

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value, ensure_ascii=False))

    def files(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def test_real_source_candidate_validators_inspect_without_approval_or_writes(self):
        before = self.files()
        result = inspect.inspect(self.path)
        self.assertEqual(result['nodes']['source']['status'], 'validated')
        self.assertEqual(result['nodes']['text.zh-Hans']['status'], 'validated')
        self.assertEqual(result['nodes']['audio.zh-Hans']['status'], 'human_gate')
        self.assertIn('translation_review', result['nodes']['audio.zh-Hans']['missingGates'])
        self.assertEqual(self.files(), before)
        self.assertFalse(result['dispatchEnabled'])
        self.assertEqual(result['inspectionCoverage']['release'], 'not_integrated')
        self.assertNotIn('要记得', json.dumps(result, ensure_ascii=False))
        self.assertNotIn(str(self.root), json.dumps(result))

    def approve_fixture(self):
        worksheet = review.build_worksheet(self.fixture.source, self.fixture.anchor, self.candidate, self.fixture.policy)
        worksheet = review.apply_batch_approval(worksheet, reviewer='Synthetic test reviewer',
                    reviewed_at='2026-09-30T00:00:00Z', evidence='Synthetic fixture only, not production approval')
        approved, receipt = review.approve_worksheet(self.fixture.source, self.fixture.anchor,
                                                     self.candidate, self.fixture.policy, worksheet)
        self.write('candidate.json', approved); self.write('review.json', receipt)
        self.config['locales']['zh-Hans']['humanReview'] = 'review.json'
        self.write('inspection.json', self.config)
        return approved, receipt

    def test_independent_bound_review_is_required_and_never_grants_voice(self):
        approved, receipt = self.approve_fixture()
        before = self.files(); result = inspect.inspect(self.path)
        self.assertEqual(result['nodes']['audio.zh-Hans']['missingGates'], ['voice_authorization'])
        self.assertEqual(result['nodes']['audio.zh-Hans']['status'], 'human_gate')
        self.assertEqual(self.files(), before)
        receipt['candidateJsonSha256'] = '0' * 64; self.write('review.json', receipt)
        stale = inspect.inspect(self.path)
        self.assertEqual(stale['nodes']['audio.zh-Hans']['status'], 'blocked')
        self.assertEqual(stale['inspectionDiagnostics']['audio.zh-Hans'], 'translation_review_not_validated')
        self.assertNotEqual(result['stateRevision'], stale['stateRevision'])
        self.assertEqual(json.loads((self.root / 'candidate.json').read_text()), approved)

    def test_bad_lane_policy_and_missing_candidate_do_not_block_other_lanes(self):
        self.config['locales']['ko'] = {'policy': 'missing-policy.json'}
        self.write('inspection.json', self.config)
        result = inspect.inspect(self.path)
        self.assertEqual(result['nodes']['text.zh-Hans']['status'], 'validated')
        self.assertEqual(result['nodes']['text.ko']['status'], 'blocked')
        # A valid policy with no candidate can propose translation but cannot dispatch.
        self.config['locales']['zh-Hans'].pop('candidate'); self.write('inspection.json', self.config)
        result = inspect.inspect(self.path)
        self.assertEqual(result['nodes']['text.zh-Hans']['status'], 'ready')
        self.assertFalse(result['dispatchEnabled'])

    def test_source_review_or_anchor_change_invalidates_all_locales(self):
        original = inspect.inspect(self.path)
        source = copy.deepcopy(self.fixture.source); source['review']['humanApproval'] = False
        self.write('source.json', source)
        result = inspect.inspect(self.path)
        self.assertEqual(result['nodes']['source']['status'], 'blocked')
        self.assertEqual(result['nodes']['text.zh-Hans']['status'], 'waiting_dependency')
        self.assertNotEqual(original['stateRevision'], result['stateRevision'])
        self.write('source.json', self.fixture.source)
        changed = copy.deepcopy(self.fixture.anchor); changed['sourceUnits'][0]['english'] = 'Changed source'
        self.write('anchor.json', changed)
        self.assertEqual(inspect.inspect(self.path)['nodes']['source']['status'], 'blocked')

    def test_schema_locale_and_policy_drift_cannot_admit_candidate(self):
        original = inspect.inspect(self.path)
        for key, value in (('targetLocale', 'ko'), ('translationPolicySha256', '0' * 64), ('status', 'translation_draft')):
            changed = {**self.candidate, key: value}; self.write('candidate.json', changed)
            result = inspect.inspect(self.path)
            self.assertEqual(result['nodes']['text.zh-Hans']['status'], 'blocked')
            self.assertNotEqual(original['stateRevision'], result['stateRevision'])
        self.write('candidate.json', self.candidate)
        (self.root / 'candidate.json').unlink()
        (self.root / 'candidate.json').symlink_to(self.root / 'policy.json')
        self.assertEqual(inspect.inspect(self.path)['nodes']['text.zh-Hans']['status'], 'blocked')

    def test_source_approval_flag_cannot_replace_independent_receipt_or_transcript(self):
        source = copy.deepcopy(self.fixture.source)
        source['review']['reviewedBy'] = 'Changed identity without new receipt'
        self.write('source.json', source)
        self.assertEqual(inspect.inspect(self.path)['nodes']['source']['status'], 'blocked')
        self.write('source.json', self.fixture.source)
        aligned = Path(self.fixture.source['transcript']['artifact']['path'])
        aligned.write_text('[]')
        self.assertEqual(inspect.inspect(self.path)['nodes']['source']['status'], 'blocked')

    def test_no_tracker_or_command_configuration(self):
        for field in ('tracker', 'command', 'humanApproval'):
            self.write('inspection.json', {**self.config, field: 'not admissible'})
            with self.assertRaises(ValueError): inspect.inspect(self.path)
