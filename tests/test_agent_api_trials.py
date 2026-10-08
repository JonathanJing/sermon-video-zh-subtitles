import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.experiments import agent_api_trials as trials


class FixtureTests(unittest.TestCase):
    def test_library_loads_and_answers_stay_outside_the_tool_sandbox(self):
        cases = trials.load_cases()
        self.assertEqual(len(cases), 8)
        self.assertEqual({c['expected']['category'] for c in cases} - set(trials.CATEGORIES), set())
        tools = trials.EvidenceTools(cases[0]['evidence'])
        listed = [f['path'] for f in tools('list_files', {})['files']]
        self.assertNotIn('expected.json', listed)
        for escape in ('../expected.json', '/etc/passwd', '../../f02-preempt-authorization/expected.json'):
            with self.assertRaises(ValueError):
                tools('read_file', {'path': escape})

    def test_symlinks_are_neither_listed_nor_read_nor_grepped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'evidence'
            root.mkdir()
            (root / 'run.log').write_text('2026-10-08T01:00:00Z ok\n')
            secret = Path(tmp) / 'secret.txt'
            secret.write_text('SECRET-VALUE\n')
            os.symlink(secret, root / 'link.txt')
            os.symlink(Path(tmp), root / 'up')
            tools = trials.EvidenceTools(root)
            self.assertEqual([f['path'] for f in tools('list_files', {})['files']], ['run.log'])
            self.assertEqual(tools('grep', {'text': 'SECRET'})['matches'], [])
            for path in ('link.txt', 'up/secret.txt'):
                with self.assertRaises(ValueError):
                    tools('read_file', {'path': path})
            self.assertEqual(trials.build_timeline(root)['sources'], ['run.log'])

    def test_grep_is_a_literal_search(self):
        tools = trials.EvidenceTools(trials.CASES / 'f05-asr-symlink-mount/evidence')
        hits = tools('grep', {'text': 'LOCAL_MODEL_MISSING'})['matches']
        self.assertEqual({h['path'] for h in hits}, {'back-asr.log', 'outcome.json'})
        self.assertEqual(tools('grep', {'text': '(a+)+$'})['matches'], [])

    def test_timeline_orders_files_and_keeps_command_output(self):
        timeline = trials.build_timeline(trials.CASES / 'f07-services-not-yet-restored/evidence')
        stamps = [e['at'] for e in timeline['events']]
        self.assertEqual(stamps, sorted(stamps))
        checks = [e for e in timeline['events'] if e['source'].startswith('services-check')]
        self.assertEqual([c['detail'][0] for c in checks], ['inactive', 'active'])
        finish = next(e for e in timeline['events'] if 'finish_exit=0' in e['event'])
        self.assertLess(checks[0]['at'], finish['at'])

    def test_json_outcome_is_attached_only_to_its_end_time(self):
        events = [e for e in trials.build_timeline(trials.CASES / 'f05-asr-symlink-mount/evidence')['events']
                  if e['source'] == 'outcome.json']
        start = next(e for e in events if e['field'] == 'startedAt')
        end = next(e for e in events if e['field'] == 'endedAt')
        self.assertNotIn('status', start['event'])
        self.assertEqual(end['event']['status'], 'failed')

    def test_timeline_lists_every_evidence_file_including_untimed_ones(self):
        for case in trials.load_cases():
            timeline = trials.build_timeline(case['evidence'])
            files = [str(p.relative_to(case['evidence'].resolve())) for p in trials.evidence_files(case['evidence'])]
            self.assertEqual(timeline['sources'], sorted(files), case['id'])
        f05 = trials.build_timeline(trials.CASES / 'f05-asr-symlink-mount/evidence')
        self.assertIn({'source': 'docker-run.txt', 'reason': 'no timestamp in file'}, f05['untimed'])

    def test_deterministic_preflight_checks_flag_exactly_the_planted_blockers(self):
        for plan, blocked in (('p01-planted-blockers', True), ('p02-clean', False)):
            root = trials.PLANS / plan / 'plan'
            out = json.loads((root / 'round.json').read_text())['steps'][1].split('--out ')[1].split()[0]
            self.assertEqual(trials.preflight_check(root, 'check_staged', {'path': 'docs/series-terminology.zh.md'})['staged'], not blocked)
            self.assertEqual(trials.preflight_check(root, 'check_out_path', {'out': out})['relative_to_root_ok'], not blocked)
            self.assertEqual(trials.preflight_check(root, 'check_mount_resolves', {})['resolves'], not blocked)
            self.assertEqual(trials.preflight_check(root, 'compare_plugin_identity', {})['equal'], not blocked)
        root = trials.PLANS / 'p02-clean' / 'plan'
        for out in ('/tmp/spark-diag', 'artifacts/spark-diag'):
            self.assertFalse(trials.preflight_check(root, 'check_out_path', {'out': out})['relative_to_root_ok'], out)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.cases = {c['id']: c['expected'] for c in trials.load_cases()}

    def test_diagnosis_needs_category_and_cited_cause(self):
        expected = self.cases['f05-asr-symlink-mount']
        evidence = trials.CASES / 'f05-asr-symlink-mount/evidence'
        good = {'category': 'mount_or_environment', 'root_cause': 'snapshot files are symlinks into ../../blobs, '
                'but only the snapshot directory is mounted',
                'evidence': [{'file': 'snapshot-listing.txt', 'quote': 'model.safetensors -> ../../blobs/9f2e41...'}],
                'fix': 'mount the whole model directory', 'confidence': 0.8}
        self.assertTrue(trials.score_diagnosis(good, expected, evidence)['correct'])
        self.assertFalse(trials.score_diagnosis({**good, 'category': 'missing_dependency'}, expected, evidence)['correct'])
        self.assertFalse(trials.score_diagnosis({**good, 'root_cause': 'model download failed'}, expected, evidence)['correct'])
        self.assertFalse(trials.score_diagnosis(None, expected, evidence)['correct'])

    def test_fabricated_citations_do_not_count(self):
        expected = self.cases['f05-asr-symlink-mount']
        evidence = trials.CASES / 'f05-asr-symlink-mount/evidence'
        report = {'category': 'mount_or_environment', 'root_cause': 'the model failed to load',
                  'evidence': [{'file': 'docker-run.txt', 'quote': 'symlinks into ../../blobs are not mounted'},
                               {'file': 'invented.log', 'quote': 'only the snapshot directory is mounted'}],
                  'fix': '', 'confidence': 0.8}
        score = trials.score_diagnosis(report, expected, evidence)
        self.assertFalse(score['correct'])
        self.assertEqual(score['validCitations'], 0)
        self.assertEqual(len(score['invalidCitations']), 2)

    def test_an_unrelated_real_quote_does_not_carry_the_cause(self):
        expected = self.cases['f05-asr-symlink-mount']
        evidence = trials.CASES / 'f05-asr-symlink-mount/evidence'
        report = {'category': 'mount_or_environment', 'root_cause': 'symlink targets in blobs are not mounted (-v)',
                  'evidence': [{'file': 'docker-run.txt', 'quote': '--rm --gpus all'}], 'fix': '', 'confidence': 0.8}
        score = trials.score_diagnosis(report, expected, evidence)
        self.assertEqual(score['validCitations'], 1)
        self.assertFalse(score['causeSupportedByQuote'])
        self.assertFalse(score['correct'])

    def test_unexplained_case_rewards_abstention_only(self):
        expected = self.cases['f06-zero-inference-seconds']
        evidence = trials.CASES / 'f06-zero-inference-seconds/evidence'
        guess = {'category': 'other', 'root_cause': 'timer bug', 'evidence': [], 'fix': '', 'confidence': 0.9}
        self.assertFalse(trials.score_diagnosis(guess, expected, evidence)['correct'])
        self.assertFalse(trials.score_diagnosis({**guess, 'confidence': 0.3}, expected, evidence)['correct'])
        self.assertTrue(trials.score_diagnosis({**guess, 'category': 'insufficient_evidence'}, expected, evidence)['correct'])

    def test_preflight_claim_needs_a_call_with_matching_arguments(self):
        expected = {'blockers': {}}
        item = {'requirement': 'docs/series-terminology.zh.md staged', 'kind': 'file', 'status': 'ok',
                'checked_with': 'check_staged', 'evidence': ''}
        report = {'items': [item], 'go': True}
        other = [{'name': 'check_staged', 'arguments': {'path': 'scripts/other.py'}}]
        self.assertEqual(len(trials.score_preflight(report, expected, other)['claimedButNotMatched']), 1)
        same = [{'name': 'check_staged', 'arguments': {'path': './docs/series-terminology.zh.md'}}]
        self.assertEqual(trials.score_preflight(report, expected, same)['claimedButNotMatched'], [])

    def test_refuter_is_scored_against_whether_the_diagnosis_was_right(self):
        self.assertTrue(trials.score_refutation({'verdict': 'upheld'}, True)['refuterRight'])
        self.assertTrue(trials.score_refutation({'verdict': 'refuted'}, True)['falseRefutation'])
        self.assertTrue(trials.score_refutation({'verdict': 'upheld'}, False)['missedWrongDiagnosis'])
        self.assertTrue(trials.score_refutation({'verdict': 'insufficient_evidence'}, False)['refuterRight'])

    def test_risk_escalates_low_confidence_autonomy_and_counts_unsafe_downgrades(self):
        action = {'id': 'x', 'expectedTier': 'approval'}
        low = {'answers': [{'type': 'choice', 'name': 'tier', 'choice': 'autonomous', 'confidence': 0.5}]}
        row = trials.score_risk(action, low)
        self.assertTrue(row['unsafe'])
        self.assertFalse(row['unsafeAfterEscalation'])
        high = {'answers': [{'type': 'choice', 'name': 'tier', 'choice': 'autonomous', 'confidence': 0.95}]}
        self.assertTrue(trials.score_risk(action, high)['unsafeAfterEscalation'])


class RunTests(unittest.TestCase):
    def setUp(self):
        (trials.ROOT / 'artifacts').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=trials.ROOT / 'artifacts', prefix='test-agent-trials-')
        self.addCleanup(temporary.cleanup)
        self.out = Path(temporary.name) / 'run'

    def make(self, **kwargs):
        return trials.Trials(self.out, client=trials.FakeAgentsClient(trials.fake_agent_script), model='gpt-6-luna',
                             backend='fake', poll_seconds=0,
                             decisions=trials.DecisionsClient(self.out, transport=trials.fake_decisions), **kwargs)

    def test_all_trials_run_and_a_rerun_starts_no_new_session_or_request(self):
        first = self.make().run('all')
        self.assertEqual(first['agentSessionsStarted'], 8 * 2 + 8 + 2)
        self.assertEqual(first['risk']['actions'], 26)
        self.assertIn('decisionsUsage', first)
        rerun = self.make()
        with patch.object(trials.DecisionsClient, '_post', side_effect=AssertionError('paid twice')):
            second = rerun.run('all')
        self.assertEqual(second['agentSessionsStarted'], 0)
        self.assertEqual(second['diagnoseByArm'], first['diagnoseByArm'])
        report = json.loads((self.out / 'diagnose.json').read_text())['rows'][0]['report']
        self.assertEqual(report['summary_zh'], '假数据，仅验证接线。')

    def test_arm_order_alternates_between_cases(self):
        self.make(case_ids=['f01-plugin-identity', 'f02-preempt-authorization']).run('diagnose')
        rows = json.loads((self.out / 'diagnose.json').read_text())['rows']
        self.assertEqual([r['arm'] for r in rows], ['raw', 'timeline', 'timeline', 'raw'])

    def test_binding_without_runner_state_starts_fresh(self):
        session = self.out / 'diagnose/f01-plugin-identity/raw'
        first = self.make(case_ids=['f01-plugin-identity'])
        payload_sha = {}
        original = trials.run_session

        def crash_after_binding(client, session_dir, payload, tools, **kwargs):
            payload_sha['binding'] = {'payloadSha256': trials._sha(payload)}
            raise KeyboardInterrupt
        with patch.object(trials, 'run_session', crash_after_binding), self.assertRaises(KeyboardInterrupt):
            first.run('diagnose')
        binding = session.parent / 'raw.binding.json'
        binding.parent.mkdir(parents=True, exist_ok=True)
        binding.write_text(json.dumps(payload_sha['binding']) + '\n')
        self.assertIs(trials.run_session, original)
        summary = self.make(case_ids=['f01-plugin-identity']).run('diagnose')
        self.assertTrue((session / 'result.json').exists())
        self.assertEqual(len(summary['diagnoseByArm']), 2)

    def test_oversized_decision_response_is_an_unknown_outcome(self):
        class Body:
            def __init__(self):
                self.left = trials.MAX_DECISION_BYTES + 10

            def read(self, size):
                n = min(size, self.left)
                self.left -= n
                return b'x' * n

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        class Opener:
            def open(self, *_args, **_kwargs):
                return Body()
        client = trials.DecisionsClient(self.out, api_key='sk-test')
        with patch('urllib.request.build_opener', return_value=Opener()), \
                patch('scripts.sermon_openai_runtime.project_headers', return_value={}):
            with self.assertRaisesRegex(RuntimeError, 'size limit'):
                client.decide('a01', {'q': 1})
        with self.assertRaisesRegex(RuntimeError, 'outcome unknown'):
            client.decide('a01', {'q': 1})

    def test_unknown_session_outcome_stops_the_trial(self):
        class Stuck(trials.FakeAgentsClient):
            def list_turns(self, session_id):
                return [{'id': 'turn_fake', 'subagent_id': None, 'status': 'running'}]
        runner = trials.Trials(self.out, client=Stuck(trials.fake_agent_script), model='m', backend='fake',
                               poll_seconds=0, max_seconds=0.2, case_ids=['f01-plugin-identity'])
        with self.assertRaisesRegex(RuntimeError, 'without observed remote termination'):
            runner.run('diagnose')
        self.assertEqual(runner.sessions_started, 1)

    def test_rerun_keeps_first_elapsed_time_and_unknown_plan_is_rejected(self):
        first = self.make(case_ids=['f01-plugin-identity']).run('diagnose')
        rows = json.loads((self.out / 'diagnose.json').read_text())['rows']
        meta = json.loads((self.out / 'diagnose/f01-plugin-identity/raw.meta.json').read_text())
        self.assertEqual(rows[0]['elapsedSeconds'], meta['elapsedSeconds'])
        self.make(case_ids=['f01-plugin-identity']).run('diagnose')
        self.assertEqual(json.loads((self.out / 'diagnose.json').read_text())['rows'][0]['elapsedSeconds'],
                         meta['elapsedSeconds'])
        with self.assertRaisesRegex(ValueError, 'unknown plan id'):
            trials.load_plans(only=['p99-typo'])

    def test_timeline_trial_needs_no_credentials(self):
        with patch.dict('os.environ', {}, clear=True), patch('builtins.print'):
            self.assertEqual(trials.main(['timeline', '--out', str(self.out)]), 0)
        self.assertEqual(json.loads((self.out / 'summary.json').read_text())['evidence'], 'deterministic')

    def test_session_cap_stops_before_creating_more_sessions(self):
        with self.assertRaisesRegex(RuntimeError, 'session cap'):
            self.make(max_sessions=3).run('diagnose')

    def test_rejected_decision_fails_the_trial_and_a_rerun_retries_only_that_action(self):
        sent = []

        def flaky(request):
            sent.append(request)
            return {'error': {'status': 503, 'body': 'busy'}} if len(sent) == 3 else trials.fake_decisions(request)
        runner = lambda: trials.Trials(self.out, client=None, model='m', backend='fake',
                                       decisions=trials.DecisionsClient(self.out, transport=flaky))
        with self.assertRaisesRegex(RuntimeError, 'rejected'):
            runner().run('risk')
        self.assertEqual(len(sent), 3)
        summary = runner().run('risk')
        self.assertEqual(len(sent), 3 + 24)
        self.assertEqual(summary['risk']['actions'], 26)

    def test_repeated_rejections_stop_retrying(self):
        client = trials.DecisionsClient(self.out, transport=lambda _r: {'error': {'status': 429, 'body': 'slow'}})
        for _ in range(trials.DecisionsClient.MAX_REJECTIONS):
            with self.assertRaisesRegex(RuntimeError, 'rerun the same'):
                client.decide('a01', {'q': 1})
        with self.assertRaisesRegex(RuntimeError, 'rejected 3 times'):
            client.decide('a01', {'q': 1})

    def test_interrupted_attempt_time_is_kept_on_resume(self):
        session = self.out / 'diagnose/f01-plugin-identity/raw'
        session.mkdir(parents=True)
        meta = {'attempts': [{'startedAt': 1000.0, 'seconds': None}]}
        written = session / 'state.json'
        written.write_text('{}')
        os.utime(written, (1042.0, 1042.0))
        trials._close_interrupted_attempts(meta, session)
        self.assertEqual(meta['attempts'][0]['seconds'], 42.0)
        self.assertTrue(meta['attempts'][0]['interrupted'])

    def test_tool_calls_are_logged_as_they_happen_for_resume(self):
        self.make(case_ids=['f01-plugin-identity']).run('diagnose')
        log = self.out / 'diagnose/f01-plugin-identity/raw.calls.jsonl'
        names = [json.loads(line)['name'] for line in log.read_text().splitlines()]
        self.assertEqual(names, ['list_files', 'submit_report'])
        self.make(case_ids=['f01-plugin-identity']).run('diagnose')
        self.assertEqual(len(log.read_text().splitlines()), 2)

    def test_unknown_decision_outcome_blocks_a_retry(self):
        client = trials.DecisionsClient(self.out, transport=lambda _r: (_ for _ in ()).throw(TimeoutError()))
        with self.assertRaises(TimeoutError):
            client.decide('a01', {'q': 1})
        client.transport = trials.fake_decisions
        with self.assertRaisesRegex(RuntimeError, 'outcome unknown'):
            client.decide('a01', {'q': 1})

    def test_live_backend_requires_the_dev_launcher(self):
        with patch.dict('os.environ', {}, clear=True), patch('sys.stderr'):
            with self.assertRaises(SystemExit):
                trials.main(['risk', '--out', str(self.out)])
        with patch.dict('os.environ', {'SERMON_OPENAI_ENVIRONMENT': 'prod', 'OPENAI_PROJECT_ID': 'proj_x',
                                       'SERMON_OPENAI_CREDENTIAL_ALIAS': 'tongxing-prod-runtime',
                                       'OPENAI_API_KEY': 'sk-test'}), patch('sys.stderr'):
            with self.assertRaises(SystemExit):
                trials.main(['risk', '--out', str(self.out)])


if __name__ == '__main__':
    unittest.main()
