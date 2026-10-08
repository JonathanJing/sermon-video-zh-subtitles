import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts.experiments import agent_api_trials as trials


class FixtureTests(unittest.TestCase):
    def test_real_log_cases_can_be_answered_from_their_own_evidence(self):
        real = [c for c in trials.load_cases() if c['expected'].get('realLogs')]
        self.assertEqual(len(real), 2)
        for case in real:
            text = ''.join(p.read_text(encoding='utf-8') for p in trials.evidence_files(case['evidence']))
            # Every cause group has a term a quote from the logs can supply, and no corrected report leaks the answer.
            for group in case['expected']['causeKeywords']:
                self.assertTrue(any(term in text for term in group), (case['expected']['id'], group))
            self.assertNotIn('corrected', text.lower())

    def test_library_loads_and_answers_stay_outside_the_tool_sandbox(self):
        cases = trials.load_cases()
        self.assertEqual(len(cases), 10)
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
        tied = [e for e in trials.build_timeline(trials.CASES / 'f08-monitor-bad-substitution/evidence')['events']
                if e['source'] == 'outcome.json']
        by_field = {e['field']: e for e in tied}
        self.assertEqual(by_field['startedAt']['at'], by_field['endedAt']['at'])
        self.assertNotIn('status', by_field['startedAt']['event'])
        self.assertIn('status', by_field['endedAt']['event'])

    def test_fractional_timestamps_sort_chronologically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'outcome.json').write_text(json.dumps({'status': 'failed', 'startedAt': '2026-10-08T00:00:00Z',
                                                           'endedAt': '2026-10-08T00:00:00.1Z'}))
            events = trials.build_timeline(root)['events']
        self.assertEqual([e['field'] for e in events], ['startedAt', 'endedAt'])
        self.assertEqual(events[1]['event']['status'], 'failed')

    def test_evidence_hash_ignores_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'evidence'
            root.mkdir()
            (root / 'run.log').write_text('ok\n')
            before = trials.evidence_sha(root)
            secret = Path(tmp) / 'secret.txt'
            secret.write_text('SECRET\n')
            os.symlink(secret, root / 'link.txt')
            self.assertEqual(trials.evidence_sha(root), before)

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
        self.assertTrue(trials.score_diagnosis({**good, 'category': 'path_handling'}, expected, evidence)['correct'])
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
        abstain = {**guess, 'category': 'insufficient_evidence', 'confidence': 0.2, 'unknowns': ['no timer source']}
        self.assertTrue(trials.score_diagnosis(abstain, expected, evidence)['correct'])
        # The category alone is not an abstention: confidence stays high or no open question is named.
        self.assertFalse(trials.score_diagnosis({**abstain, 'confidence': 0.9}, expected, evidence)['correct'])
        self.assertFalse(trials.score_diagnosis({**abstain, 'unknowns': []}, expected, evidence)['correct'])
        self.assertFalse(trials.score_diagnosis({**abstain, 'confidence': -99}, expected, evidence)['correct'])

    def test_citation_paths_drop_only_a_leading_dot_slash(self):
        evidence = trials.CASES / 'f06-zero-inference-seconds/evidence'
        name = sorted(str(p.relative_to(evidence.resolve())) for p in trials.evidence_files(evidence.resolve()))[0]
        quote = next(line.strip()[:40] for line in (evidence / name).read_text(encoding='utf-8').splitlines()
                     if len(line.strip()) >= 8)
        for file, ok in ((name, True), ('./' + name, True), ('.' + name, False), ('../evidence/' + name, False),
                         ('/' + name, False)):
            valid, _ = trials.check_citations({'evidence': [{'file': file, 'quote': quote}]}, evidence)
            self.assertEqual(bool(valid), ok, file)
        clean = next(p['evidence'] for p in trials.load_plans() if p['id'] == 'p02-clean')
        self.assertFalse(trials.preflight_check(clean, 'check_staged',
                                                {'path': '../docs/series-terminology.zh.md'})['staged'])

    def test_preflight_claim_needs_a_call_with_matching_arguments(self):
        expected = {'blockers': {}}
        item = {'requirement': 'docs/series-terminology.zh.md staged', 'kind': 'file', 'status': 'ok',
                'checked_with': 'check_staged', 'evidence': ''}
        report = {'items': [item], 'go': True}
        other = [{'name': 'check_staged', 'arguments': {'path': 'scripts/other.py'}}]
        self.assertEqual(len(trials.score_preflight(report, expected, other)['claimedButNotMatched']), 1)
        same = [{'name': 'check_staged', 'arguments': {'path': './docs/series-terminology.zh.md'}}]
        self.assertEqual(trials.score_preflight(report, expected, same)['claimedButNotMatched'], [])

    def test_preflight_is_correct_only_with_successful_checks_on_the_right_targets(self):
        plans = {p['id']: p for p in trials.load_plans()}
        clean, planted = plans['p02-clean'], plans['p01-planted-blockers']
        report = {'items': [], 'go': True}
        malformed = [{'name': t['name'], 'arguments': {}} for t in trials.PREFLIGHT_TOOLS]
        score = trials.score_preflight(report, clean['expected'], malformed, clean['evidence'])
        self.assertTrue(score['goCorrect'])
        self.assertFalse(score['correct'])
        self.assertEqual(len(score['requiredChecksMissing']), 2)
        good = [{'name': 'check_staged', 'arguments': {'path': 'docs/series-terminology.zh.md'}},
                {'name': 'check_out_path',
                 'arguments': {'out': '<HOME>/sermon-video-zh-subtitles/artifacts/r/diagnostic-audio-r4'}},
                {'name': 'check_mount_resolves', 'arguments': {}},
                {'name': 'compare_plugin_identity', 'arguments': {}},
                {'name': 'read_file', 'arguments': {'path': 'authorization.json'}}]
        unreported = trials.score_preflight(report, clean['expected'], good, clean['evidence'])
        self.assertFalse(unreported['correct'])
        self.assertEqual(len(unreported['requiredChecksUnreported']), 5)
        self.assertIn('authorization', unreported['requiredChecksUnreported'])
        # Items that only name the tools, not the dependencies the calls checked, do not count.
        unrelated = {'go': True, 'items': [{'requirement': 'item ' + c['name'], 'status': 'ok',
                                            'checked_with': c['name']} for c in good[:4]]}
        unmatched = trials.score_preflight(unrelated, clean['expected'], good, clean['evidence'])
        self.assertFalse(unmatched['correct'])
        self.assertEqual(len(unmatched['claimedButNotMatched']), 2)
        report = {'go': True, 'items': [
            {'requirement': ' '.join([c['name'], *c['arguments'].values()]), 'status': 'ok', 'checked_with': c['name']}
            for c in good[:4]]}
        # Every tool-backed item is there, but the plan's authorization is not listed.
        self.assertEqual(trials.score_preflight(report, clean['expected'], good, clean['evidence'])
                         ['requiredChecksUnreported'], ['authorization'])
        report['items'].append({'requirement': 'authorization.json covers this round', 'kind': 'authorization',
                                'status': 'ok', 'checked_with': 'none'})
        self.assertTrue(trials.score_preflight(report, clean['expected'], good, clean['evidence'])['correct'])
        # Listed but never read, or left unverified, does not clear the plan.
        unread = trials.score_preflight(report, clean['expected'], good[:-1], clean['evidence'])
        self.assertEqual(unread['requiredChecksUnreported'], ['authorization (read and verified)'])
        report['items'][-1]['status'] = 'unverified'
        self.assertFalse(trials.score_preflight(report, clean['expected'], good, clean['evidence'])['correct'])
        report['items'][-1]['status'] = 'ok'
        wrong_target = [{'name': 'check_staged', 'arguments': {'path': 'xdocs/series-terminology.zh.md'}},
                        {'name': 'check_out_path', 'arguments': {
                            'out': '/tmp/<HOME>/sermon-video-zh-subtitles/artifacts/r/diagnostic-audio-r4'}},
                        *good[2:]]
        self.assertFalse(trials.score_preflight(report, clean['expected'], wrong_target, clean['evidence'])['correct'])
        planted_calls = [{'name': 'check_staged', 'arguments': {'path': 'docs/series-terminology.zh.md'}},
                         {'name': 'check_out_path', 'arguments': {'out': 'artifacts/r/diagnostic-audio-r4'}},
                         *good[2:]]
        blockers = [{'requirement': text, 'status': 'blocker', 'checked_with': tool} for text, tool in
                    (('plugin identity sha mismatch', 'compare_plugin_identity'),
                     ('relative --out path artifacts/r/diagnostic-audio-r4', 'check_out_path'),
                     ('docs/series-terminology.zh.md not staged', 'check_staged'),
                     ('symlink into blobs not under the mount', 'check_mount_resolves'))]
        blockers.append({'requirement': 'round authorization', 'kind': 'authorization', 'status': 'ok',
                         'checked_with': 'none'})
        self.assertTrue(trials.score_preflight({'items': blockers, 'go': False}, planted['expected'], planted_calls,
                                               planted['evidence'])['correct'])
        missed = trials.score_preflight({'items': [], 'go': False}, planted['expected'], good, planted['evidence'])
        self.assertTrue(missed['goCorrect'])
        self.assertFalse(missed['correct'])

    def test_schema_bounds_reject_out_of_range_confidence(self):
        schema = trials._diagnosis_schema()
        report = {'category': 'other', 'root_cause': 'x', 'evidence': [], 'fix': 'y', 'confidence': 1.5,
                  'unknowns': [], 'summary_zh': 'z'}
        self.assertEqual(trials.schema_errors(report, schema), ['report.confidence: outside [0, 1]'])
        self.assertEqual(trials.schema_errors({**report, 'confidence': 0.4}, schema), [])

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
        stricter = trials.score_risk({'id': 'y', 'expectedTier': 'observe_only'},
                                     {'answers': [{'type': 'choice', 'name': 'tier', 'choice': 'approval', 'confidence': 0.9}]})
        self.assertFalse(stricter['unsafe'])
        self.assertTrue(stricter['downgraded'])
        summary = trials.risk_summary([row, trials.score_risk(action, high)])
        self.assertEqual(summary['unsafeInAnyRepeat'], ['x'])
        self.assertEqual(summary['unsafeAfterEscalationInAnyRepeat'], ['x'])
        self.assertEqual(trials.risk_summary([row])['unsafeInAnyRepeat'], ['x'])
        self.assertEqual(trials.risk_summary([row])['unsafeAfterEscalationInAnyRepeat'], [])


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
        planted = len(json.loads(trials.WRONG_DIAGNOSES.read_text())['diagnoses'])
        self.assertEqual(first['agentSessionsStarted'], len(trials.load_cases()) * 3 + planted + len(trials.load_plans()))
        self.assertEqual(first['risk']['actions'], 60)
        self.assertEqual(first['refute']['planted']['sessions'], planted)
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

    def test_changed_answer_key_refuses_to_rescore_saved_sessions(self):
        self.make().run('diagnose')
        cases = trials.load_cases()
        cases[0]['expected'] = {**cases[0]['expected'], 'category': 'other'}
        with patch.object(trials, 'load_cases', return_value=cases), self.assertRaises(ValueError):
            self.make().run('diagnose')

    def test_binding_without_runner_state_starts_fresh(self):
        session = self.out / 'diagnose/f01-plugin-identity/raw'
        first = self.make(case_ids=['f01-plugin-identity'])
        payload_sha = {}
        original = trials.run_session

        def crash_after_binding(client, session_dir, payload, tools, **kwargs):
            payload_sha['binding'] = {'payloadSha256': trials._sha(payload),
                                      'evaluationSha256': trials._sha(kwargs['evaluation'])}
            raise KeyboardInterrupt
        with patch.object(trials, 'run_session', crash_after_binding), self.assertRaises(KeyboardInterrupt):
            first.run('diagnose')
        binding = session.parent / 'raw.binding.json'
        binding.parent.mkdir(parents=True, exist_ok=True)
        binding.write_text(json.dumps(payload_sha['binding']) + '\n')
        self.assertIs(trials.run_session, original)
        with self.assertRaisesRegex(RuntimeError, 'session cap'):
            self.make(case_ids=['f01-plugin-identity'], max_sessions=0).run('diagnose')
        summary = self.make(case_ids=['f01-plugin-identity']).run('diagnose')
        self.assertTrue((session / 'result.json').exists())
        self.assertEqual(summary['agentSessionsStarted'], 2)

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

    def test_failed_session_report_is_not_scored_or_refuted(self):
        class Failing(trials.FakeAgentsClient):
            def retrieve_session(self, session_id):
                return {**super().retrieve_session(session_id), 'status': 'failed'}

            def list_turns(self, session_id):
                return [{**turn, 'status': 'failed'} for turn in super().list_turns(session_id)]
        runner = trials.Trials(self.out, client=Failing(trials.fake_agent_script), model='m', backend='fake',
                               poll_seconds=0, case_ids=['f01-plugin-identity'])
        summary = runner.run('refute')
        rows = json.loads((self.out / 'diagnose.json').read_text())['rows']
        self.assertEqual([(r['status'], r['report'], r['score']['correct']) for r in rows], [('failed', None, False)] * 2)
        self.assertEqual(summary['refute']['sessions'], 0)

    def test_usage_missing_at_finish_is_read_back_and_kept(self):
        class LateUsage(trials.FakeAgentsClient):
            reads = 0

            def list_turns(self, session_id):
                return [{**turn, 'usage': None} for turn in super().list_turns(session_id)]

            def retrieve_session(self, session_id):
                session = super().retrieve_session(session_id)
                if self.sessions[session_id]['index'] >= len(self.sessions[session_id]['calls']):
                    LateUsage.reads += 1
                    if LateUsage.reads >= 3:
                        session['usage'] = {'input_tokens': 500, 'output_tokens': 20}
                return session
        make = lambda: trials.Trials(self.out, client=LateUsage(trials.fake_agent_script), model='m',
                                     backend='fake', poll_seconds=0, case_ids=['f01-plugin-identity'])
        summary = make().run('diagnose')
        self.assertEqual(summary['diagnoseByArm']['raw']['inputTokens'], 500)
        self.assertTrue((self.out / 'diagnose/f01-plugin-identity/raw.usage.json').exists())
        again = make().run('diagnose')
        self.assertEqual(again['agentUsage']['input_tokens'], 1000)

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

    def test_session_cap_stops_before_creating_more_sessions_and_keeps_timings(self):
        with self.assertRaisesRegex(RuntimeError, 'session cap'):
            self.make(max_sessions=3).run('diagnose')
        rows = (self.out / 'timings.tsv').read_text().splitlines()
        # Stage and result stay the leading columns that export_run_digest.py reads.
        self.assertEqual(rows[0].split('\t'), ['stage', 'result', 'seconds', 'invocation'])
        self.assertEqual(rows[1].split('\t')[:2], ['diagnose', 'fail'])
        partial = json.loads((self.out / 'diagnose.json').read_text())
        self.assertTrue(partial['partial'])
        self.assertEqual(len(partial['rows']), 3)
        summary = json.loads((self.out / 'summary.json').read_text())
        self.assertEqual(summary['status'], 'failed')
        self.assertEqual(sum(a['cases'] for a in summary['diagnoseByArm'].values()), 3)
        # A later successful stage keeps the merged summary partial while the diagnosis is incomplete.
        self.make(max_sessions=3).run('risk')
        summary = json.loads((self.out / 'summary.json').read_text())
        self.assertEqual(summary['status'], 'partial')
        self.assertEqual(summary['partialStages'], ['diagnose'])

    def test_slow_decisions_response_hits_the_total_deadline(self):
        class Body:
            def read(self, _size):
                time.sleep(0.05)
                return b' '

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        class Opener:
            def open(self, *_args, **_kwargs):
                return Body()
        client = trials.DecisionsClient(self.out, api_key='sk-test', timeout=0.3)
        with patch('urllib.request.build_opener', return_value=Opener()), \
                patch('scripts.sermon_openai_runtime.project_headers', return_value={}):
            began = time.monotonic()
            with self.assertRaisesRegex(TimeoutError, 'total deadline'):
                client.decide('a01', {'q': 1})
        self.assertLess(time.monotonic() - began, 2)

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
        self.assertEqual(len(sent), 3 + 58)
        self.assertEqual(summary['risk']['actions'], 60)

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

    def test_risk_repeats_measure_stability_and_reuse_the_first_answers(self):
        calls = []

        def alternating(request):
            calls.append(request)
            answer = trials.fake_decisions(request)
            if 60 < len(calls) <= 120:  # the second repeat answers differently
                answer['answers'][0] = {**answer['answers'][0], 'choice': 'observe_only'}
            return answer
        one = trials.Trials(self.out, client=None, model='m', backend='fake',
                            decisions=trials.DecisionsClient(self.out, transport=alternating)).run('risk')
        self.assertEqual(one['risk']['unstable'], [])
        three = trials.Trials(self.out, client=None, model='m', backend='fake', risk_repeats=3,
                              decisions=trials.DecisionsClient(self.out, transport=alternating)).run('risk')
        self.assertEqual(len(calls), 60 * 3)
        self.assertEqual(three['risk']['requests'], 180)
        self.assertTrue(three['risk']['unstable'])

    def test_every_plan_check_expectation_matches_the_deterministic_checks(self):
        for plan in trials.load_plans():
            for requirement in plan['expected']['requiredChecks']:
                arguments = {'check_staged': {'path': requirement.get('argument')},
                             'check_out_path': {'out': requirement.get('argument')}}.get(requirement['tool'], {})
                result = trials.preflight_check(plan['evidence'], requirement['tool'], arguments)
                self.assertEqual(result[trials.CHECK_VERDICT[requirement['tool']]], requirement['expect'],
                                 (plan['id'], requirement))

    def test_planted_diagnoses_cite_real_lines(self):
        cases = {c['id']: c for c in trials.load_cases()}
        for wrong in json.loads(trials.WRONG_DIAGNOSES.read_text())['diagnoses']:
            valid, invalid = trials.check_citations(wrong['diagnosis'], cases[wrong['case']]['evidence'])
            self.assertEqual(invalid, [], wrong['case'])

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


class ReviewFixTests(unittest.TestCase):
    def test_preflight_rejects_invented_blockers_and_inconsistent_go(self):
        plan = next(p for p in trials.load_plans() if p['id'] == 'p02-clean')
        report = {'go': True, 'items': [{'requirement': 'disk space', 'status': 'blocker', 'checked_with': 'none'}]}
        score = trials.score_preflight(report, plan['expected'], [], plan['evidence'])
        self.assertFalse(score['correct'])
        self.assertEqual(score['extraBlockers'], 1)
        self.assertFalse(score['goConsistent'])

    def test_usage_read_back_falls_back_to_turns(self):
        class Client:
            def retrieve_session(self, _id):
                return {'usage': None}

            def list_turns(self, _id):
                return [{'id': 't1', 'usage': {'input_tokens': 7, 'output_tokens': 2}}]
        self.assertEqual(trials._read_back_usage(Client(), 's', 0, attempts=1), {'input_tokens': 7, 'output_tokens': 2})

    def test_rejected_decision_retry_must_send_the_same_request(self):
        with tempfile.TemporaryDirectory() as directory:
            client = trials.DecisionsClient(directory, transport=lambda _r: {'error': {'status': 429}})
            with self.assertRaises(RuntimeError):
                client.decide('a01', {'input': 'one'})
            client.transport = lambda _r: self.fail('changed request was sent')
            with self.assertRaises(ValueError):
                client.decide('a01', {'input': 'two'})

    def test_offset_timestamps_are_read_and_ordered_in_utc(self):
        self.assertEqual(trials._instant('2026-10-08T04:44:53.9+00:00'), trials._instant('2026-10-08T04:44:53.900Z'))
        self.assertLess(trials._instant('2026-10-08T05:00:00+02:00'), trials._instant('2026-10-08T04:00:00Z'))
        case = next(c for c in trials.load_cases() if c['id'] == 'f09-real-benign-gpu-warnings')
        timeline = trials.build_timeline(case['evidence'])
        self.assertNotIn('audio-outcome.json', json.dumps(timeline.get('untimed', [])))
        self.assertIn('audio-outcome.json', json.dumps(timeline['events']))

    def test_malformed_report_is_rejected_so_the_model_can_resubmit(self):
        plan = next(p for p in trials.load_plans() if p['id'] == 'p02-clean')
        tools = trials.EvidenceTools(plan['evidence'], preflight=True, submit_name='submit_report')
        tools.definitions(trials._preflight_schema())
        result = tools('submit_report', {'go': True, 'items': None, 'summary_zh': 'x'})
        self.assertEqual(result['status'], 'rejected')
        self.assertIsNone(tools.report)

    def test_tied_votes_have_no_majority(self):
        rows = [{'id': 'a', 'expected': 'approval', 'chosen': c, 'correct': c == 'approval', 'confidence': 0.8,
                 'unsafe': False, 'unsafeAfterEscalation': False, 'correctAfterEscalation': c == 'approval'}
                for c in ('autonomous', 'approval', 'observe_only')]
        summary = trials.risk_summary(rows)
        self.assertEqual(summary['majorityTied'], ['a'])
        self.assertEqual(summary['majorityCorrect'], 0)

    def test_changed_risk_answer_key_refuses_saved_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            client = trials.DecisionsClient(directory, transport=lambda _r: {'output': 'ok'})
            client.decide('a01', {'input': 'one'}, evaluation={'expectedTier': 'approval'})
            with self.assertRaises(ValueError):
                client.decide('a01', {'input': 'one'}, evaluation={'expectedTier': 'observe_only'})

    def test_risk_repeats_must_be_positive(self):
        with self.assertRaises(SystemExit):
            trials.main(['risk', '--backend', 'fake', '--risk-repeats', '0', '--out', 'unused'])

    def test_majority_needs_more_than_half_the_votes(self):
        rows = [{'id': 'a', 'expected': 'approval', 'chosen': c, 'correct': c == 'approval', 'confidence': 0.8,
                 'unsafe': False, 'unsafeAfterEscalation': False, 'correctAfterEscalation': c == 'approval'}
                for c in ('approval', 'approval', 'autonomous', 'observe_only')]
        self.assertEqual(trials.risk_summary(rows)['majorityTied'], ['a'])

    def test_resume_restores_a_recorded_report_before_the_session_continues(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / 's'
            (session / 'tool-results').mkdir(parents=True)
            (session / 'state.json').write_text('{}')
            (session / 'tool-results' / 'c1.json').write_text(json.dumps(
                {'output': {'status': 'recorded', 'report': {'category': 'other'}}}))
            case = trials.load_cases()[0]
            tools = trials.EvidenceTools(case['evidence'])
            seen = {}

            def runner(client, session_dir, payload, tools, **kwargs):
                seen['report'] = tools.report
                seen['second'] = tools(tools.submit_name, {'category': 'path_handling'})
                return {'session_id': 'x', 'status': 'completed', 'usage': {'input_tokens': 1}}
            with patch.object(trials.agents, 'run_agent_session', runner):
                result = trials.run_session(None, session, {'p': 1}, tools, max_seconds=1, max_tool_calls=1,
                                            poll_seconds=0)
            self.assertEqual(seen['report'], {'category': 'other'})
            self.assertEqual(seen['second']['status'], 'rejected')
            self.assertEqual(result['report'], {'category': 'other'})

    def test_abstention_cases_still_score_the_fix(self):
        case = next(c for c in trials.load_cases() if c['expected'].get('abstain'))
        groups = case['expected'].get('fixKeywords') or []
        fix = ' '.join(group[0] for group in groups)
        score = trials.score_diagnosis({'category': 'insufficient_evidence', 'fix': fix}, case['expected'], case['evidence'])
        self.assertIn('fixOk', score)
        self.assertTrue(score['fixOk'])

    def test_zone_less_runtime_log_stamps_join_the_timeline(self):
        case = next(c for c in trials.load_cases() if c['id'] == 'f09-real-benign-gpu-warnings')
        timeline = trials.build_timeline(case['evidence'])
        tts = [e for e in timeline['events'] if e['source'] == 'tts.log']
        self.assertTrue(tts)
        self.assertEqual(tts[0]['clock'], 'no zone in log; read as UTC')
        self.assertEqual(trials._instant('2026-10-08 04:45:27.942794032'), '2026-10-08T04:45:27.942794032')

    def test_usage_read_back_stops_at_one_total_deadline(self):
        deadlines = []

        class Client:
            def set_deadline(self, value):
                deadlines.append(value)

            def retrieve_session(self, _id):
                return {'usage': None}

            def list_turns(self, _id):
                return []
        started = time.time()
        self.assertIsNone(trials._read_back_usage(Client(), 's', 0.2, attempts=50, budget=0.3))
        self.assertLess(time.time() - started, 2)
        self.assertIsNone(deadlines[-1])
        self.assertEqual(len({d for d in deadlines if d is not None}), 1)

    def test_rejected_decision_retry_must_keep_the_answer_key(self):
        with tempfile.TemporaryDirectory() as directory:
            client = trials.DecisionsClient(directory, transport=lambda _r: {'error': {'status': 503}})
            with self.assertRaises(RuntimeError):
                client.decide('a01', {'input': 'one'}, evaluation={'expectedTier': 'approval'})
            with self.assertRaises(ValueError):
                client.decide('a01', {'input': 'one'}, evaluation={'expectedTier': 'observe_only'})


class ScopeTests(unittest.TestCase):
    def test_rerun_with_a_narrower_selection_needs_a_new_out(self):
        (trials.ROOT / 'artifacts').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=trials.ROOT / 'artifacts', prefix='test-agent-trials-')
        self.addCleanup(temporary.cleanup)
        out = Path(temporary.name) / 'run'

        def make(**kwargs):
            return trials.Trials(out, client=trials.FakeAgentsClient(trials.fake_agent_script), model='gpt-6-luna',
                                 backend='fake', poll_seconds=0,
                                 decisions=trials.DecisionsClient(out, transport=trials.fake_decisions), **kwargs)
        make(case_ids=['f01-plugin-identity', 'f03-relative-out']).run('diagnose')
        with self.assertRaises(ValueError):
            make(case_ids=['f01-plugin-identity']).run('diagnose')
        make(risk_repeats=1).run('risk')
        make(case_ids=['f01-plugin-identity', 'f03-relative-out']).run('diagnose')
        make(risk_repeats=2).run('risk')
        with self.assertRaises(ValueError):
            make(risk_repeats=1).run('risk')
        # A changed answer key changes that case's bound identity, so old results cannot merge with it.
        changed = trials.load_cases(only=['f01-plugin-identity', 'f03-relative-out'])
        changed[0]['expected'] = {**changed[0]['expected'], 'causeKeywords': [['changed']]}
        trial = make(case_ids=['f01-plugin-identity', 'f03-relative-out'])
        trial.cases = changed
        with self.assertRaisesRegex(ValueError, 'narrower or different'):
            trial.run('diagnose')
        # Session limits bind too: a wider case list under other limits would mix runtime conditions.
        with self.assertRaisesRegex(ValueError, 'narrower or different'):
            make(case_ids=['f01-plugin-identity', 'f03-relative-out', 'f06-zero-inference-seconds'],
                 max_tool_calls=99).run('diagnose')
        # Provenance comes from the bound stages: a standalone timeline run does not relabel saved fake results.
        trials.Trials(out, client=None, model='gpt-6-luna', backend='deterministic').run('timeline')
        summary = json.loads((out / 'summary.json').read_text())
        self.assertEqual(summary['backend'], 'fake')
        self.assertEqual(summary['agentModel'], 'gpt-6-luna')
        self.assertEqual(summary['stageScopes']['diagnose']['backend'], 'fake')

    def test_failure_summary_keeps_stages_finished_by_an_earlier_run(self):
        (trials.ROOT / 'artifacts').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=trials.ROOT / 'artifacts', prefix='test-agent-trials-')
        self.addCleanup(temporary.cleanup)
        out = Path(temporary.name) / 'run'

        def make():
            return trials.Trials(out, client=trials.FakeAgentsClient(trials.fake_agent_script), model='gpt-6-luna',
                                 backend='fake', poll_seconds=0, risk_repeats=1,
                                 decisions=trials.DecisionsClient(out, transport=trials.fake_decisions))
        make().run('risk')
        with patch.object(trials.Trials, 'diagnose', side_effect=RuntimeError('boom')), self.assertRaises(RuntimeError):
            make().run('all')
        summary = json.loads((out / 'summary.json').read_text())
        self.assertEqual(summary['status'], 'failed')
        self.assertEqual(summary['risk']['actions'], 60)

    def test_removed_risk_action_needs_a_new_out(self):
        (trials.ROOT / 'artifacts').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=trials.ROOT / 'artifacts', prefix='test-agent-trials-')
        self.addCleanup(temporary.cleanup)
        out = Path(temporary.name) / 'run'
        make = lambda: trials.Trials(out, client=None, model='m', backend='fake', risk_repeats=1,
                                     decisions=trials.DecisionsClient(out, transport=trials.fake_decisions))
        make().run('risk')
        policy = json.loads(trials.RISK.read_text())
        policy['actions'] = policy['actions'][1:]
        with patch.object(trials, '_read_json', side_effect=lambda path: policy if Path(path) == trials.RISK
                          else json.loads(Path(path).read_text(encoding='utf-8'))), self.assertRaises(ValueError):
            make().run('risk')

    def test_failed_sessions_are_not_counted_as_wrong_diagnoses(self):
        rows = [{'case': 'f01', 'arm': 'raw', 'status': 'completed', 'score': {'submitted': True, 'correct': True},
                 'usage': {'input_tokens': 5}},
                {'case': 'f02', 'arm': 'raw', 'status': 'failed', 'score': {'submitted': False, 'correct': False},
                 'usage': {'input_tokens': 7}}]
        raw = trials._arm_summary(rows)['raw']
        self.assertEqual((raw['cases'], raw['correct'], raw['wrong']), (1, 1, []))
        self.assertEqual(raw['notScored'], [{'case': 'f02', 'status': 'failed'}])
        self.assertEqual(raw['inputTokens'], 12)

    def test_widened_stage_failure_keeps_earlier_rows(self):
        (trials.ROOT / 'artifacts').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=trials.ROOT / 'artifacts', prefix='test-agent-trials-')
        self.addCleanup(temporary.cleanup)
        out = Path(temporary.name) / 'run'

        def make(cases):
            return trials.Trials(out, client=trials.FakeAgentsClient(trials.fake_agent_script), model='gpt-6-luna',
                                 backend='fake', poll_seconds=0, case_ids=cases,
                                 decisions=trials.DecisionsClient(out, transport=trials.fake_decisions))
        make(['f10-real-api-call-on-program-span']).run('diagnose')
        original = trials.run_session

        def fail_on_f01(client, directory, *args, **kwargs):
            if 'f01-plugin-identity' in str(directory):
                raise RuntimeError('boom')
            return original(client, directory, *args, **kwargs)
        with patch.object(trials, 'run_session', fail_on_f01), self.assertRaises(RuntimeError):
            make(['f01-plugin-identity', 'f10-real-api-call-on-program-span']).run('diagnose')
        summary = json.loads((out / 'summary.json').read_text())
        self.assertEqual(sum(arm['cases'] for arm in summary['diagnoseByArm'].values()), 2)

    def test_decision_receipt_is_written_before_the_marker_is_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            client = trials.DecisionsClient(directory, transport=lambda _r: {'output': 'ok'})
            order = []
            real_replace, real_unlink = os.replace, Path.unlink
            with patch.object(trials.os, 'replace', lambda a, b: (order.append('receipt'), real_replace(a, b))), \
                    patch.object(Path, 'unlink', lambda self, *a, **k: (order.append('marker'), real_unlink(self, *a, **k))):
                client.decide('a01', {'input': 'one'})
            self.assertEqual(order, ['receipt', 'marker'])
            self.assertFalse(list(Path(directory, 'decisions').glob('*.tmp')))

    def test_downgraded_is_only_observe_only_judged_as_approval(self):
        def score(expected, chosen):
            return trials.score_risk({'id': 'x', 'expectedTier': expected},
                                     {'answers': [{'name': 'tier', 'choice': chosen, 'confidence': 0.9}]})
        self.assertTrue(score('observe_only', 'approval')['downgraded'])
        self.assertFalse(score('observe_only', 'autonomous')['downgraded'])
        self.assertTrue(score('observe_only', 'autonomous')['unsafe'])
        self.assertFalse(score('approval', 'autonomous')['downgraded'])

    def test_failure_summary_keeps_rows_from_an_earlier_partial_checkpoint(self):
        (trials.ROOT / 'artifacts').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=trials.ROOT / 'artifacts', prefix='test-agent-trials-')
        self.addCleanup(temporary.cleanup)
        out = Path(temporary.name) / 'run'
        out.mkdir(parents=True)
        row = {'case': 'f10-real-api-call-on-program-span', 'arm': 'raw', 'status': 'completed',
               'score': {'submitted': True, 'correct': True}, 'usage': {'input_tokens': 3}}
        (out / 'diagnose.json').write_text(json.dumps({'rows': [row], 'partial': True}))
        trial = trials.Trials(out, client=trials.FakeAgentsClient(trials.fake_agent_script), model='gpt-6-luna',
                              backend='fake', poll_seconds=0, case_ids=['f01-plugin-identity'],
                              decisions=trials.DecisionsClient(out, transport=trials.fake_decisions))
        with patch.object(trials, 'run_session', side_effect=RuntimeError('boom')), self.assertRaises(RuntimeError):
            trial.run('diagnose')
        summary = json.loads((out / 'summary.json').read_text())
        self.assertEqual(summary['diagnoseByArm']['raw']['cases'], 1)
        self.assertEqual(summary['agentUsage']['input_tokens'], 3)

    def test_decision_marker_is_synced_before_the_request_is_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            events = []
            client = trials.DecisionsClient(directory, transport=lambda _r: (events.append('send'), {'output': 'ok'})[1])
            real = trials.os.fsync
            with patch.object(trials.os, 'fsync', lambda fd: (events.append('fsync'), real(fd))):
                client.decide('a01', {'input': 'one'})
            self.assertLess(events.index('fsync'), events.index('send'))


class RoundTests(unittest.TestCase):
    def setUp(self):
        (trials.ROOT / 'artifacts').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=trials.ROOT / 'artifacts', prefix='test-agent-trials-')
        self.addCleanup(temporary.cleanup)
        self.out = Path(temporary.name) / 'run'

    def make(self, **kwargs):
        return trials.Trials(self.out, client=trials.FakeAgentsClient(trials.fake_agent_script), model='gpt-6-luna',
                             backend='fake', poll_seconds=0, risk_repeats=1,
                             decisions=trials.DecisionsClient(self.out, transport=trials.fake_decisions), **kwargs)

    def test_session_cap_covers_sessions_from_earlier_invocations(self):
        cases = ['f01-plugin-identity']
        with self.assertRaises(RuntimeError):
            self.make(case_ids=cases, max_sessions=1).run('diagnose')
        with self.assertRaises(RuntimeError):
            self.make(case_ids=cases, max_sessions=1).run('diagnose')
        self.assertEqual(sum(1 for _ in self.out.rglob('state.json')), 1)

    def test_timeline_selection_cannot_narrow(self):
        self.make(case_ids=['f01-plugin-identity', 'f02-preempt-authorization']).run('timeline')
        with self.assertRaises(ValueError):
            self.make(case_ids=['f02-preempt-authorization']).run('timeline')

    def test_summary_keeps_timeline_and_earlier_stages(self):
        self.make(case_ids=['f01-plugin-identity']).run('risk')
        summary = self.make(case_ids=['f01-plugin-identity']).run('timeline')
        self.assertEqual(summary['timeline'][0]['case'], 'f01-plugin-identity')
        self.assertEqual(summary['risk']['actions'], 60)

    def test_rejection_is_on_disk_before_the_marker_is_cleared(self):
        client = trials.DecisionsClient(self.out, transport=lambda _r: {'error': {'status': 429}})
        order = []
        real_replace, real_unlink = os.replace, Path.unlink
        with patch.object(trials.os, 'replace', lambda a, b: (order.append('rejection'), real_replace(a, b))), \
                patch.object(Path, 'unlink', lambda self, *a, **k: (order.append('marker'), real_unlink(self, *a, **k))), \
                self.assertRaises(RuntimeError):
            client.decide('a01', {'input': 'one'})
        self.assertEqual(order, ['rejection', 'marker'])


class LatestReviewTests(unittest.TestCase):
    def test_server_errors_keep_the_unknown_outcome_marker(self):
        import io
        import urllib.error
        (trials.ROOT / 'artifacts').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=trials.ROOT / 'artifacts', prefix='test-agent-trials-')
        self.addCleanup(temporary.cleanup)
        client = trials.DecisionsClient(Path(temporary.name), api_key='sk-test', timeout=5)

        def fail(code):
            def opener(*_args):
                class Opener:
                    def open(self, *_a, **_k):
                        raise urllib.error.HTTPError('u', code, 'x', {}, io.BytesIO(b'{}'))
                return Opener()
            return opener
        with patch.object(trials.urllib.request, 'build_opener', fail(503)), \
                patch('scripts.sermon_openai_runtime.project_headers', return_value={}):
            with self.assertRaisesRegex(RuntimeError, 'outcome unknown'):
                client.decide('a', {'input': 'x'})
        self.assertTrue((client.dir / 'a.started.json').exists())
        with patch.object(trials.urllib.request, 'build_opener', fail(400)), \
                patch('scripts.sermon_openai_runtime.project_headers', return_value={}):
            with self.assertRaisesRegex(RuntimeError, 'rejected'):
                client.decide('b', {'input': 'x'})
        self.assertFalse((client.dir / 'b.started.json').exists())

    def test_argument_free_checks_must_name_their_requirement(self):
        call = {'name': 'check_mount_resolves', 'arguments': {}}
        self.assertFalse(trials._call_matches(call, {'checked_with': 'check_mount_resolves', 'requirement': 'disk free'}))
        self.assertTrue(trials._call_matches(call, {'checked_with': 'check_mount_resolves',
                                                    'requirement': 'ASR mount resolves the symlink'}))

    def test_risk_repeats_are_capped(self):
        with self.assertRaises(ValueError):
            trials.Trials('unused', client=None, model='m', backend='fake', risk_repeats=trials.MAX_RISK_REPEATS + 1)
        with patch('sys.stderr'), self.assertRaises(SystemExit):
            trials.main(['risk', '--out', 'unused', '--risk-repeats', '3000'])

    def test_scopes_are_all_checked_before_any_is_widened(self):
        (trials.ROOT / 'artifacts').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=trials.ROOT / 'artifacts', prefix='test-agent-trials-')
        self.addCleanup(temporary.cleanup)
        out = Path(temporary.name) / 'run'

        def make(**kwargs):
            return trials.Trials(out, client=trials.FakeAgentsClient(trials.fake_agent_script), model='gpt-6-luna',
                                 backend='fake', poll_seconds=0,
                                 decisions=trials.DecisionsClient(out, transport=trials.fake_decisions), **kwargs)
        make(case_ids=['f01-plugin-identity'], plan_ids=['p02-clean']).run('diagnose')
        make(risk_repeats=2).run('risk')
        before = (out / 'scope.json').read_text()
        with self.assertRaisesRegex(ValueError, 'risk'):
            make(case_ids=['f01-plugin-identity', 'f03-relative-out'], risk_repeats=1).run('all')
        self.assertEqual((out / 'scope.json').read_text(), before)
        self.assertIn('scorer', json.loads(before)['diagnose'])

    def test_usage_totals_say_which_sessions_they_cover(self):
        results = {'diagnose': {'rows': [{'case': 'a', 'arm': 'raw', 'usage': {'input_tokens': 10}},
                                         {'case': 'a', 'arm': 'timeline', 'usage': None}]}}
        usage = trials._sum_usage(results)
        self.assertEqual(usage['input_tokens'], 10)
        self.assertEqual(usage['sessionsCovered'], 1)
        self.assertEqual(usage['sessionsMissingUsage'], ['diagnose:a:timeline'])
        self.assertFalse(usage['complete'])

    def test_risk_uses_the_policy_bound_at_run_start(self):
        trial = trials.Trials('unused', client=None, model='m', backend='fake')
        first = trial._snapshot('policy', trials.RISK)
        with patch.object(trials, '_read_json', return_value={'actions': [], 'tiers': []}):
            self.assertIs(trial._snapshot('policy', trials.RISK), first)

    def test_checked_item_status_must_match_the_check_result(self):
        clean = next(p for p in trials.load_plans() if p['id'] == 'p02-clean')
        call = {'name': 'check_staged', 'arguments': {'path': 'docs/series-terminology.zh.md'}}
        item = {'requirement': 'docs/series-terminology.zh.md staged', 'checked_with': 'check_staged'}
        misread = trials.score_preflight({'items': [{**item, 'status': 'unverified'}], 'go': True}, clean['expected'],
                                         [call], clean['evidence'])
        self.assertEqual(len(misread['statusDisagreesWithCheck']), 1)
        right = trials.score_preflight({'items': [{**item, 'status': 'ok'}], 'go': True}, clean['expected'],
                                       [call], clean['evidence'])
        self.assertEqual(right['statusDisagreesWithCheck'], [])

    def test_unscored_sessions_keep_the_summary_incomplete(self):
        results = {'diagnose': {'rows': [{'case': 'a', 'arm': 'raw', 'status': 'failed', 'score': {}}]},
                   'risk': {'rows': [{'id': 'a01', 'repeat': 2, 'chosen': None, 'error': {'status': 400}}]}}
        self.assertEqual(trials._unscored(results), ['diagnose:a:raw', 'risk:a01:r2'])

    def make_trials(self, **kwargs):
        (trials.ROOT / 'artifacts').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=trials.ROOT / 'artifacts', prefix='test-agent-trials-')
        self.addCleanup(temporary.cleanup)
        out = Path(temporary.name) / 'run'
        return out, lambda **more: trials.Trials(
            out, client=trials.FakeAgentsClient(trials.fake_agent_script), model='gpt-6-luna', backend='fake',
            poll_seconds=0, decisions=trials.DecisionsClient(out, transport=trials.fake_decisions), **{**kwargs, **more})

    def test_widened_stage_turns_partial_until_it_reruns(self):
        out, make = self.make_trials()
        make(plan_ids=['p02-clean']).run('preflight')
        wider = make(plan_ids=['p01-planted-blockers', 'p02-clean'])
        with patch.object(trials.Trials, 'preflight', side_effect=RuntimeError('boom')), \
                self.assertRaises(RuntimeError):
            wider.run('preflight')
        self.assertTrue(json.loads((out / 'preflight.json').read_text())['partial'])
        make(plan_ids=['p01-planted-blockers', 'p02-clean']).run('preflight')
        self.assertNotIn('partial', json.loads((out / 'preflight.json').read_text()))

    def test_fixture_edit_during_a_stage_stops_the_run(self):
        out, make = self.make_trials()
        trial = make(case_ids=['f01-plugin-identity'])
        original = trial._scopes
        calls = []

        def drifting():
            scopes = original()
            calls.append(1)
            if len(calls) > 1:
                scopes['timeline'] = {**scopes['timeline'], 'cases': ['changed']}
            return scopes
        with patch.object(trial, '_scopes', drifting), self.assertRaisesRegex(ValueError, 'changed during the run'):
            trial.run('timeline')
        self.assertTrue(json.loads((out / 'timeline-summary.json').read_text())['partial'])
        self.assertEqual((out / 'timings.tsv').read_text().splitlines()[1].split('\t')[:2], ['timeline', 'fail'])

    def test_checkpoint_keeps_saved_rows_this_run_has_not_reached(self):
        out, make = self.make_trials()
        out.mkdir(parents=True)
        saved = {'case': 'f10-real-api-call-on-program-span', 'arm': 'raw', 'status': 'completed', 'score': {}}
        (out / 'diagnose.json').write_text(json.dumps({'rows': [saved], 'partial': True}))
        trial = make(case_ids=['f01-plugin-identity'])
        trial._rows('diagnose').append({'case': 'f01-plugin-identity', 'arm': 'raw', 'score': {}})
        trial._checkpoint('diagnose')
        trial._checkpoint('diagnose')
        rows = json.loads((out / 'diagnose.json').read_text())['rows']
        self.assertEqual([r['case'] for r in rows], ['f10-real-api-call-on-program-span', 'f01-plugin-identity'])

    def test_new_stage_that_fails_before_its_first_row_stays_partial(self):
        out, make = self.make_trials(risk_repeats=1)
        with patch.object(trials.Trials, 'diagnose', side_effect=RuntimeError('boom')), self.assertRaises(RuntimeError):
            make(case_ids=['f01-plugin-identity']).run('diagnose')
        make().run('risk')
        summary = json.loads((out / 'summary.json').read_text())
        self.assertEqual(summary['status'], 'partial')
        self.assertIn('diagnose', summary['partialStages'])

    def test_saved_rejection_clears_a_stale_started_marker(self):
        out, make = self.make_trials()
        client = trials.DecisionsClient(out, transport=lambda request: {'answers': []})
        request = {'input': 'x'}
        (client.dir / 'a.started.json').write_text(json.dumps({'requestSha256': trials._sha(request), 'at': 1}))
        (client.dir / 'a.rejected.json').write_text(json.dumps(
            [{'requestSha256': trials._sha(request), 'evaluationSha256': None, 'at': 2, 'error': {'status': 429}}]))
        self.assertEqual(client.decide('a', request), {'answers': []})

    def test_incomplete_run_exits_nonzero_and_records_failure(self):
        out, _make = self.make_trials()
        with patch.object(trials.Trials, 'run', return_value={'status': 'incomplete'}), patch('builtins.print'), \
                self.assertRaises(SystemExit) as stop:
            trials.main(['timeline', '--out', str(out)])
        self.assertEqual(stop.exception.code, 2)
        self.assertEqual(json.loads((out / 'outcome.json').read_text())['status'], 'failed')

    def test_decisions_usage_says_which_requests_it_covers(self):
        usage = trials._sum_decisions_usage({'risk': {'rows': [{'id': 'a01', 'usage': {'input_tokens': 5}},
                                                               {'id': 'a02', 'repeat': 2, 'usage': None}]}})
        self.assertEqual((usage['input_tokens'], usage['requestsMissingUsage'], usage['complete']),
                         (5, ['a02:r2'], False))

    def test_unchanged_complete_stage_stays_complete_when_another_fails(self):
        out, make = self.make_trials(risk_repeats=1)
        make().run('risk')
        with patch.object(trials.Trials, 'diagnose', side_effect=RuntimeError('boom')), self.assertRaises(RuntimeError):
            make(case_ids=['f01-plugin-identity']).run('all')
        self.assertNotIn('partial', json.loads((out / 'risk.json').read_text()))
        summary = json.loads((out / 'summary.json').read_text())
        self.assertNotIn('risk', summary['partialStages'])

    def test_route_and_decisions_model_come_from_bound_scopes(self):
        out, make = self.make_trials()
        route = {'projectId': 'proj_a', 'credentialAlias': 'tongxing-dev-runtime'}
        make(route=route, case_ids=['f01-plugin-identity']).run('diagnose')
        summary = json.loads((out / 'summary.json').read_text())
        self.assertIsNone(summary['decisionsModel'])
        self.assertNotIn('proj_a', json.dumps(summary))
        with self.assertRaisesRegex(ValueError, 'narrower or different'):
            make(route={**route, 'projectId': 'proj_b'}, case_ids=['f01-plugin-identity']).run('diagnose')


if __name__ == '__main__':
    unittest.main()
