"""Durable spoken revision tests: real producers, synthetic transports only."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from scripts import canonical_layer2_controller as subject
from scripts import canonical_spoken_revision as spoken
from scripts import run_target_language_models as models
from scripts import produce_target_language_candidate as producer
from tests import test_canonical_layer2_controller as helpers


class SpokenRevisionTests(unittest.TestCase):
    setUp = helpers.CanonicalLayer2ControllerTests.setUp
    save_config = helpers.CanonicalLayer2ControllerTests.save_config
    files = helpers.CanonicalLayer2ControllerTests.files
    fake_call = helpers.CanonicalLayer2ControllerTests.fake_call
    active = helpers.CanonicalLayer2ControllerTests.active
    execute = helpers.CanonicalLayer2ControllerTests.execute

    def prepare(self):
        f = self.fixture.fixture
        prior = self.root / 'prior'
        models.run(f.source, f.anchor, f.policy, prior, 'fixture-key', self.fake_call,
                   plugin_path=f.plugin_path)
        self.calls.clear()
        request = producer._load(prior / 'request.json')
        evidence = producer._load(prior / 'evidence.json')
        group = evidence['groups'][0]
        brief = {'schemaVersion': models.REVISION_BRIEF_SCHEMA,
                 **{key: request[key] for key in ('targetLocale', 'englishSourcePackageJsonSha256',
                    'anchorManifestSha256', 'translationPolicySha256')},
                 'groups': [{'translationGroupId': group['translationGroupId'],
                             'sourceUnitIds': group['sourceUnitIds'],
                             'priorTargetTextSha256': hashlib.sha256(''.join(group['targetUtterances']).encode()).hexdigest(),
                             'proposedTargetText': ''.join(group['targetUtterances']) + '（合成测试提案）'}]}
        (self.root / 'brief.json').write_text(json.dumps(brief))
        (self.root / 'manifest.json').write_text(json.dumps(spoken.prepare_manifest(prior)))
        self.config_data['schemaVersion'] = subject.SCHEMA_V2
        self.config_data['locales']['zh-Hans']['spokenRevision'] = {
            'reuseFrom': 'prior', 'brief': 'brief.json', 'cacheManifest': 'manifest.json'}
        self.save_config()
        return prior

    def test_v2_shadow_checks_actual_inputs_without_writes_or_transport(self):
        self.prepare()
        before = self.files()
        with patch.object(subject.jobs, 'start_job') as start:
            result = subject.Controller(self.path).tick()
        self.assertEqual(result['status'], 'ready')
        self.assertFalse(result['dispatched'])
        self.assertEqual(before, self.files())
        self.assertFalse(self.calls)
        start.assert_not_called()

    def test_v1_rejects_new_lane_and_v2_rejects_two_repair_modes(self):
        self.prepare()
        self.config_data['schemaVersion'] = subject.SCHEMA
        self.save_config()
        with self.assertRaisesRegex(ValueError, 'invalid_execution_lane'):
            subject.load_configuration(self.path)
        self.config_data['schemaVersion'] = subject.SCHEMA_V2
        self.config_data['locales']['zh-Hans']['partialRepair'] = {'reuseFrom': 'prior', 'brief': 'brief.json'}
        self.save_config()
        with self.assertRaisesRegex(ValueError, 'invalid_execution_lane'):
            subject.load_configuration(self.path)

    def test_spoken_worker_preserves_slot_wrapper_and_unchanged_cache_bytes(self):
        prior = self.prepare()
        slot = subject.api_concurrency.request_slot
        with self.active() as (config, code, key, folder), patch.object(
                subject.api_concurrency, 'request_slot', wraps=slot) as slots:
            result = self.execute(config, code, key)
            self.assertEqual(slots.call_count, 2)
            snapshot = folder / 'spoken-reuse'
            self.assertTrue(snapshot.is_dir())
            self.assertEqual((snapshot / 'evidence.json').read_bytes(), (prior / 'evidence.json').read_bytes())
        self.assertEqual(len(self.calls), 2)
        self.assertIn('revisionBrief', json.loads(self.calls[0]['messages'][1]['content']))
        for suffix in ('astra', 'sol'):
            for ext in ('.json', '.raw.json'):
                name = 'group-0002-' + suffix + ext
                self.assertEqual((prior / name).read_bytes(), (self.output / name).read_bytes())
        candidate = producer._load(self.output / 'candidate.json')
        self.assertFalse(candidate['releaseEligible'])
        self.assertEqual(candidate['status'], 'machine_review_pass_human_review_pending')
        self.assertTrue(result['candidateJsonSha256'])

    def test_source_cache_drift_is_blocked_before_any_request(self):
        prior = self.prepare()
        path = prior / 'group-0002-sol.json'
        original = path.read_text()
        path.write_text(original + ' ')
        result = subject.Controller(self.path).tick()
        self.assertEqual(result['nodes']['text.zh-Hans']['status'], 'blocked')
        self.assertFalse(self.calls)

    def test_brief_manifest_and_policy_binding_changes_are_detected(self):
        self.prepare()
        before = subject.load_configuration(self.path).sha256
        brief = producer._load(self.root / 'brief.json')
        brief['groups'][0]['proposedTargetText'] += 'test'
        (self.root / 'brief.json').write_text(json.dumps(brief))
        self.assertNotEqual(subject.load_configuration(self.path).sha256, before)
        brief['translationPolicySha256'] = 'f' * 64
        (self.root / 'brief.json').write_text(json.dumps(brief))
        result = subject.Controller(self.path).tick()
        self.assertEqual(result['nodes']['text.zh-Hans']['status'], 'blocked')
        self.assertFalse(self.calls)

    def test_unknown_api_marker_and_nonpass_evidence_are_rejected(self):
        prior = self.prepare()
        marker = prior / 'group-9999-astra.started.json'
        marker.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Uncertain paid'):
            spoken.prepare_manifest(prior)
        marker.unlink()
        evidence = producer._load(prior / 'evidence.json')
        evidence['groups'][0]['semanticReview']['status'] = 'fail'
        (prior / 'evidence.json').write_text(json.dumps(evidence))
        with self.assertRaisesRegex(ValueError, 'spoken_prior_group_not_pass'):
            spoken.prepare_manifest(prior)

    def test_raw_parsed_mismatch_and_overlap_are_rejected(self):
        prior = self.prepare()
        raw_path = prior / 'group-0001-astra.raw.json'
        raw = producer._load(raw_path)
        raw['response']['choices'][0]['message']['content'] = '{}'
        raw_path.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError, 'spoken_prior_raw_parsed_mismatch'):
            spoken.prepare_manifest(prior)
        self.config_data['locales']['zh-Hans']['outputDirectory'] = 'prior/child'
        self.save_config()
        with self.assertRaisesRegex(ValueError, 'invalid_spoken_revision_paths'):
            subject.load_configuration(self.path)

    def test_snapshot_tampering_blocks_candidate_admission(self):
        self.prepare()
        with self.active() as (config, code, key, folder):
            def mutate(key, payload):
                reply = self.fake_call(key, payload)
                target = folder / 'spoken-reuse' / 'request.json'
                target.chmod(0o644)
                target.write_text(target.read_text() + ' ')
                return reply
            with self.assertRaisesRegex(ValueError, 'spoken_prior_cache_manifest_mismatch'):
                self.execute(config, code, key, caller=mutate)
        self.assertFalse((self.output / 'candidate.json').exists())


if __name__ == '__main__':
    unittest.main()
