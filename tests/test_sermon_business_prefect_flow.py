"""Real callbacks + real business receipts; all media, models and approvals synthetic."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import sermon_business_prefect_flow as flow
from scripts import sermon_bounded_business_callbacks as callbacks
from scripts import sermon_review_contracts as c
from tests import test_run_bounded_diagnostic as fixtures


def setup_business(owner, *, matched=True, unknown=False):
    f = fixtures.BoundedRunTests(); owner.addCleanup(f.doCleanups); f.setUp()
    def respond(request, timeout, *, deadline):
        if unknown:
            raise TimeoutError('synthetic unknown outcome')
        result = f.capture(request, timeout, deadline=deadline)
        if matched and request.full_url.endswith('/audio/transcriptions'):
            anchor = c.decode_json(f.f.args[1])
            result['text'] = ' '.join(unit['english'] for unit in anchor['sourceUnits'])
        return result
    transport = callbacks.OfflineHTTPTransport(respond, fixture_id='business-flow-fixture')
    f.subject.executor = transport
    subject = callbacks.BoundedBusinessCallbacks(f.subject, f.f.root, source_clip=f.clip,
        fixture_id='business-flow-fixture', offline=True)
    nodes = [flow.Node('asr', 'transcribe', {'wav_bytes': f.raw}),
        flow.Node('source', 'source_check', depends_on=('asr',)),
        flow.Node('text.zh-Hans', 'locale', dict(zip(
            ('source_bytes', 'anchor_bytes', 'policy_bytes', 'rubric_bytes'), f.f.args)) |
            {'graph': f.graph, 'plugin_path': f.f.f.plugin_path,
             'plugin_sha256': f.f.f.plugin_sha, 'group_plan': f.plan},
            ('source',), (f.f.f.plugin_path,)),
        flow.Node('text.admit', 'admit_locale', depends_on=('text.zh-Hans',)),
        flow.Node('speech.prepare', 'prepare_speech', depends_on=('text.admit',)),
        flow.Node('speech.render', 'render_speech', depends_on=('speech.prepare',)),
        flow.Node('delivery', 'delivery_preflight', depends_on=('speech.render',))]
    return f, transport, subject, nodes


def execute_all(dag):
    results = {}
    for node in dag.nodes:
        results[node.id] = dag.execute(node.id, [results[key] for key in node.depends_on])
    return results


class BusinessFlowTests(unittest.TestCase):
    def setUp(self):
        self.f, self.transport, self.callbacks, self.nodes = setup_business(self)
        self.root = self.f.f.root / 'orchestration'

    def test_actual_asr_source_strict_locale_restart_and_human_barrier(self):
        dag = flow.BusinessDAG(self.root, self.callbacks, self.nodes)
        with self.f.f.session():
            result = execute_all(dag)
            self.assertEqual(result['asr']['executionStatus'], 'completed', result)
            self.assertEqual(result['source']['machineStatus'], 'pass', result)
            text = result['text.zh-Hans']
            self.assertEqual(text['machineStatus'], 'pass', result)
            self.assertEqual(text['humanStatus'], 'pending')
            self.assertEqual(text['admissionStatus'], 'waiting_human_translation_review')
            self.assertEqual(text['alignmentBinding']['timingProvenance'], 'frozen_fixture_alignment_not_generated')
            self.assertEqual(len(self.transport.observations), 6)
            before = self.callbacks.provider_evidence()
            again = execute_all(flow.BusinessDAG(self.root, self.callbacks, self.nodes))
            self.assertEqual(again['text.zh-Hans']['artifactSha256'], text['artifactSha256'])
            self.assertEqual(before, self.callbacks.provider_evidence())
        self.assertEqual(len(self.transport.observations), 6)
        for key in ('speech.prepare', 'speech.render', 'delivery'):
            self.assertEqual(result[key]['executionStatus'], 'blocked')
            self.assertFalse(result[key]['processed'])
        from scripts import sermon_accounting as accounting
        rows, errors = accounting.read_events(self.f.f.root / 'logs')
        self.assertFalse(errors)
        starts = {r['spanId']: r for r in rows if r['event'] == 'stage_started'}
        self.assertEqual(starts[result['source']['completionSpans'][0]]['dependsOn'],
                         result['asr']['completionSpans'])
        self.assertGreaterEqual(text['elapsedSeconds'], 0)
        self.assertTrue(all(row['productionEligible'] is False for row in result.values()))

    def test_actual_same_store_human_admission_and_speech_preparation_stop_at_voice(self):
        from scripts import sermon_strict_gate_admission as admission
        from scripts import review_target_language_candidate as human
        from scripts import sermon_local_business_callbacks as local
        from tests import test_prepare_target_language_speech_job as voice_fixtures
        from unittest.mock import patch
        scope_directory = str(Path(self.enterContext(tempfile.TemporaryDirectory())).resolve())
        self.enterContext(patch.object(tempfile, 'tempdir', scope_directory))
        self.f, self.transport, self.callbacks, self.nodes = setup_business(self)
        self.root = self.f.f.root / 'orchestration'
        # Freeze the in-scope plugin path before generation and retain that
        # exact binding at admission instead of moving it after model calls.
        plugin = self.f.f.root / self.f.f.f.plugin_path.name
        plugin.write_bytes(self.f.f.f.plugin_path.read_bytes())
        node = self.nodes[2]
        self.nodes[2] = flow.Node(node.id, node.operation,
            {**node.kwargs, 'plugin_path': plugin}, node.depends_on, (plugin,))
        with self.f.f.session():
            initial = flow.BusinessDAG(self.root, self.callbacks, self.nodes[:3])
            execute_all(initial)
        result = initial._envelopes['text.zh-Hans']['result']
        pending = c.read_snapshot(Path(result['output']) / 'candidate.json')[0]
        source, anchor, policy, rubric = map(c.decode_json, self.f.f.args)
        worksheet = human.build_worksheet(source, anchor, pending, policy, strict_rubric=rubric)
        reviewed = human.apply_batch_approval(worksheet, reviewer='Synthetic fixture',
            reviewed_at='2026-10-01T00:00:00Z', evidence='Synthetic test approval, never actual human acceptance')
        approved, receipt = human.approve_worksheet(source, anchor, pending, policy, reviewed, strict_rubric=rubric)
        root = self.f.f.root
        paths = {}
        for name, raw in zip(('source', 'anchor', 'policy', 'rubric'), self.f.f.args):
            paths[name] = root / (name + '.json'); paths[name].write_bytes(raw)
        (root / 'approved.json').write_bytes(c.canonical_bytes(approved))
        (root / 'human.json').write_bytes(c.canonical_bytes(receipt))
        config = admission.Configuration(self.f.subject.config['runId'], 'zh-Hans', root / 'jobs',
            root / 'locales', tuple(Path(row['root']) for row in result['revisions']), **paths,
            public_candidate=root / 'approved.json', human_receipt=root / 'human.json',
            plugin=plugin, plugin_sha256=self.f.f.f.plugin_sha)
        boundary = admission.AdmissionBoundary(config, self.f.subject.store)
        voice = voice_fixtures.TargetLanguageSpeechJobTests(); self.addCleanup(voice.doCleanups); voice.setUp()
        registry, adapter = voice.registry, voice.adapter
        capability = next(row for row in registry['speakers'][0]['localeCapabilities'] if row['targetLocale'] == 'zh-Hans')
        capability.pop('adapterOverride', None)
        adapter.update(targetLocale='zh-Hans', languageParameter=capability['modelLanguage'],
            capabilityEvidenceSha256=c.canonical_sha256(capability['reviewEvidence']),
            registryJsonSha256=c.canonical_sha256(registry))
        adapter_path, registry_path = root / 'adapter.json', root / 'registry.json'
        adapter_path.write_bytes(c.canonical_bytes(adapter)); registry_path.write_bytes(c.canonical_bytes(registry))
        local.initialize_scope(scope_directory, 'approved-business-fixture')
        scope = dict(offline=True, fixture_id='approved-business-fixture', fixture_root=Path(scope_directory))
        nodes = [*self.nodes[:3], flow.Node('admit', 'admit_locale',
            {'boundary': boundary, 'created_at': '2026-10-01T00:00:00Z'}, ('text.zh-Hans',)),
            flow.Node('prepare', 'prepare_speech', {'boundary': boundary,
                'adapter_path': adapter_path, 'registry_path': registry_path, 'out': root / 'speech', **scope}, ('admit',)),
            flow.Node('render', 'render_speech', depends_on=('prepare',))]
        with self.f.f.session():
            dag = flow.BusinessDAG(root / 'approved-dag', self.callbacks, nodes)
            observed = execute_all(dag)
            self.assertEqual(observed['admit']['admissionStatus'], 'prepare_layer3_intent', observed)
            self.assertEqual(observed['prepare']['executionStatus'], 'completed', observed)
            self.assertEqual(observed['prepare']['admissionStatus'], 'awaiting_voice_authorization')
            self.assertEqual(observed['render']['executionStatus'], 'blocked')
            replay = execute_all(flow.BusinessDAG(root / 'approved-dag', self.callbacks, nodes))
            self.assertEqual(replay['prepare']['artifactSha256'], observed['prepare']['artifactSha256'])
        self.assertEqual(len(self.transport.observations), 6)

    def test_unrelated_ready_alignment_cannot_become_current_asr_descendant(self):
        f, transport, subject, nodes = setup_business(self, matched=False)
        with f.f.session():
            result = execute_all(flow.BusinessDAG(f.f.root / 'dag', subject, nodes))
        self.assertEqual(result['source']['executionStatus'], 'completed')
        self.assertEqual(result['text.zh-Hans']['reason'], 'awaiting_alignment_binding')
        self.assertEqual(len(transport.observations), 2)

    def test_unknown_is_owned_by_provider_and_blocks_all_dependencies_on_restart(self):
        f, transport, subject, nodes = setup_business(self, unknown=True)
        with f.f.session():
            dag = flow.BusinessDAG(f.f.root / 'dag', subject, nodes)
            first = execute_all(dag)
            before = subject.provider_evidence()
            second = execute_all(flow.BusinessDAG(f.f.root / 'dag', subject, nodes))
            self.assertEqual(before, subject.provider_evidence())
        self.assertEqual(len(transport.observations), 1)
        for result in (first, second):
            self.assertEqual(result['asr']['executionStatus'], 'outcome_unknown')
            self.assertIsNone(result['asr']['processed'])
            self.assertTrue(all(row['executionStatus'] == 'blocked' for key, row in result.items() if key != 'asr'))
            self.assertTrue(all(not row['processed'] for row in result.values()))
            self.assertEqual(result['source']['reason'], 'upstream_not_admitted')

    def test_changed_frozen_bytes_and_file_fail_before_new_call(self):
        dag = flow.BusinessDAG(self.root, self.callbacks, self.nodes)
        self.nodes[0].kwargs['wav_bytes'] = b'changed'
        with self.f.f.session():
            self.assertEqual(dag.execute('asr')['executionStatus'], 'blocked')
        self.assertEqual(self.transport.observations, [])
        with self.assertRaises(ValueError):
            flow.BusinessDAG(self.root, self.callbacks, self.nodes)

    def test_orchestration_root_cannot_write_or_lock_outside_fixture(self):
        outside = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        for action in (flow.BusinessDAG, flow.run):
            with self.assertRaisesRegex(ValueError, 'root_outside_fixture_scope'):
                action(outside / 'escaped-run', self.callbacks, self.nodes)
            self.assertEqual(list(outside.iterdir()), [])
        for root in (self.f.f.root, self.f.f.root / 'budget' / 'dag', self.f.f.root / 'jobs'):
            with self.assertRaises(ValueError):
                flow.BusinessDAG(root, self.callbacks, self.nodes)
        unrelated = self.f.f.root / 'unrelated'; unrelated.mkdir()
        (unrelated / 'keep.txt').write_text('preserve')
        with self.assertRaisesRegex(ValueError, 'dedicated_directory'):
            flow.BusinessDAG(unrelated, self.callbacks, self.nodes)
        self.assertEqual([p.name for p in unrelated.iterdir()], ['keep.txt'])

    def test_orchestration_symlink_and_later_root_redirection_are_rejected(self):
        outside = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        link = self.f.f.root / 'linked'; link.symlink_to(outside, target_is_directory=True)
        for action in (flow.BusinessDAG, flow.run):
            with self.assertRaises(ValueError): action(link / 'dag', self.callbacks, self.nodes)
        self.assertEqual(list(outside.iterdir()), [])
        dag = flow.BusinessDAG(self.root, self.callbacks, self.nodes)
        self.root.rename(self.root.with_name('original-orchestration'))
        self.root.symlink_to(outside, target_is_directory=True)
        from scripts import sermon_business_progress as progress
        with self.f.f.session(), self.assertRaises(ValueError): progress.update(dag)
        self.assertEqual(list(outside.iterdir()), [])

    def test_delivery_cannot_skip_render_or_use_unrelated_locale_evidence(self):
        bypass = [*self.nodes[:4], flow.Node('delivery', 'delivery_preflight', depends_on=('text.admit',))]
        with self.assertRaisesRegex(ValueError, 'phase_dependency_required'):
            flow.BusinessDAG(self.root, self.callbacks, bypass)
        self.assertFalse(self.root.exists())
        node = flow.Node('delivery', 'delivery_preflight', {'root': self.f.f.root,
            'configuration': {'source': 'source.json', 'anchor': 'anchor.json',
                              'locales': {'zh-Hans': {'audioPackage': 'unrelated-audio.json'}}}},
            ('speech.render',))
        dag = flow.BusinessDAG(self.root, self.callbacks, [*self.nodes[:-1], node])
        with self.assertRaisesRegex(ValueError, 'audio_chain_required'):
            dag._local_binding(node)
        # A different locale's apparent render cannot satisfy this lane, even
        # before its original manifest/artifact validator is reached.
        dag._envelopes['speech.render'] = {'result': {'targetLocale': 'ko'}}
        dag._outcomes['speech.render'] = {'executionStatus': 'completed'}
        with self.assertRaisesRegex(ValueError, 'audio_chain_required'):
            dag._local_binding(node)
        self.assertEqual(self.transport.observations, [])

    def test_no_arbitrary_operation_or_skipped_source_gate(self):
        for nodes in ([flow.Node('shell', 'subprocess')],
                      [flow.Node('text', 'locale')],
                      [flow.Node('check', 'source_check')],
                      [flow.Node('asr', 'transcribe', {'wav_bytes': lambda: b'bad'})]):
            with self.assertRaises(ValueError):
                flow.BusinessDAG(self.root, self.callbacks, nodes)

    def test_local_stages_cannot_be_independent_roots(self):
        for operation in ('admit_locale', 'prepare_speech', 'render_speech', 'delivery_preflight'):
            with self.assertRaisesRegex(ValueError, 'phase_dependency'):
                flow.BusinessDAG(self.root, self.callbacks, [flow.Node('bypass', operation)])

    def test_different_store_or_run_admission_is_rejected(self):
        from tests import test_sermon_local_business_callbacks as local_fixtures
        f = local_fixtures.SpeechTests(); self.addCleanup(f.doCleanups); f.setUp()
        nodes = [*self.nodes[:3], flow.Node('admit', 'admit_locale',
                 {'boundary': f.f.f.boundary, 'created_at': '2026-10-01T00:00:00Z'}, ('text.zh-Hans',))]
        with self.assertRaisesRegex(ValueError, 'store_or_run_changed'):
            flow.BusinessDAG(self.root, self.callbacks, nodes)

    def test_admission_direct_paths_reject_external_cwd_and_absolute_escape_before_reads(self):
        from dataclasses import replace
        from unittest.mock import patch
        from scripts import sermon_strict_gate_admission as admission
        root = self.callbacks.root
        config = admission.Configuration(self.callbacks.subject.config['runId'], 'zh-Hans',
            root / 'jobs', root / 'revisions', (root / 'revisions' / 'r1',),
            **{key: root / (key + '.json') for key in ('source', 'anchor', 'policy', 'rubric')},
            public_candidate=root / 'approved.json', human_receipt=root / 'human.json',
            plugin=root / 'plugin.py', plugin_sha256='a' * 64)
        outside = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        dag = flow.BusinessDAG(self.root, self.callbacks, self.nodes[:3])
        previous = Path.cwd()
        try:
            os.chdir(outside)
            for job_root in (Path('escaped-jobs'), outside / 'escaped-jobs'):
                boundary = admission.AdmissionBoundary(replace(config, job_root=job_root),
                                                       self.callbacks.subject.store)
                node = flow.Node('admit', 'admit_locale', {'boundary': boundary,
                    'created_at': '2026-10-01T00:00:00Z'}, ('text.zh-Hans',))
                # Neither entry may read a source or acquire a boundary lock
                # before rejecting paths resolved against the external cwd.
                with patch.object(Path, 'read_bytes', side_effect=AssertionError('unexpected input read')):
                    with self.assertRaisesRegex(ValueError, 'absolute|outside_scope'):
                        flow.BusinessDAG(root / 'unsafe-dag', self.callbacks, [*self.nodes[:3], node])
                    with self.assertRaisesRegex(ValueError, 'absolute|outside_scope'):
                        dag._admit(node)
                self.assertFalse((root / 'unsafe-dag').exists())
                self.assertEqual(list(outside.iterdir()), [])
        finally:
            os.chdir(previous)
        self.assertEqual(self.transport.observations, [])

    def test_mutated_admission_paths_are_rechecked_before_frozen_input_reads(self):
        from dataclasses import replace
        from unittest.mock import patch
        from scripts import sermon_strict_gate_admission as admission
        root = self.callbacks.root
        config = admission.Configuration(self.callbacks.subject.config['runId'], 'zh-Hans',
            root / 'jobs', root / 'revisions', (root / 'revisions' / 'r1',),
            **{key: root / (key + '.json') for key in ('source', 'anchor', 'policy', 'rubric')},
            public_candidate=root / 'approved.json', human_receipt=root / 'human.json',
            plugin=root / 'plugin.py', plugin_sha256='a' * 64)
        boundary = admission.AdmissionBoundary(config, self.callbacks.subject.store)
        node = flow.Node('admit', 'admit_locale', {'boundary': boundary,
            'created_at': '2026-10-01T00:00:00Z'}, ('text.zh-Hans',))
        dag = flow.BusinessDAG(self.root, self.callbacks, [*self.nodes[:3], node])
        boundary.config = replace(config, source=Path('relative-source.json'))
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('unexpected frozen input read')):
            with self.assertRaisesRegex(ValueError, 'must_be_absolute'): dag._check()
        self.assertEqual(self.transport.observations, [])

    def test_forged_or_mutated_upstream_observations_do_not_grant_dispatch(self):
        dag = flow.BusinessDAG(self.root, self.callbacks, self.nodes)
        with self.f.f.session():
            first = dag.execute('source', [{'nodeId': 'asr', 'readyForDownstream': True}])
            self.assertEqual(first['executionStatus'], 'blocked')
            asr = dag.execute('asr')
            asr['resultSha256'] = '0' * 64
            second = dag.execute('source', [asr])
            self.assertEqual(second['executionStatus'], 'blocked')
        self.assertEqual(len(self.transport.observations), 1)


@unittest.skipUnless(os.environ.get('SERMON_TEST_PREFECT') == '1', 'optional real local Prefect engine')
class PrefectBusinessRuntimeTests(unittest.TestCase):
    def test_fresh_sdk_real_business_callbacks_and_serialized_transport_guards(self):
        script = r'''
import json, sys, unittest
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tests.test_sermon_business_prefect_flow import setup_business
from scripts import sermon_business_prefect_flow as flow
owner=unittest.TestCase()
f, transport, subject, nodes=setup_business(owner)
try:
    result=flow.run(f.f.root/'prefect-business',subject,nodes)
    assert result['nodes']['text.zh-Hans']['machineStatus']=='pass', result
    assert len(transport.observations)==6
    assert len({row['flowRunId'] for row in result['nodes'].values()})==1
    assert all(result['nodes'][key]['executionStatus']=='blocked' for key in ('speech.prepare','speech.render','delivery'))
    assert not result['published'] and not result['freshAlignmentProduced']
    print('actual-prefect-business-ok')
finally:
    # SDK shutdown hooks still need their private cwd/files; process owns cleanup.
    pass
'''
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run([sys.executable, '-c', script, str(flow.pilot.REPO)],
                cwd=root, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-7000:])
        self.assertIn('actual-prefect-business-ok', result.stdout)


if __name__ == '__main__':
    unittest.main()
