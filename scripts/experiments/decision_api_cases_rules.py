"""Developer-only frozen rule tasks; no provider calls or production mutations.

These compare decisions on supplied evidence, not complete producers. E04 is an
explicit wrapper of screening lines 196-207 (ASR itself is outside the task).
Program oracles measure rule fidelity, not independent semantic correctness.
"""
from __future__ import annotations
import copy
from dataclasses import asdict
import difflib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


CHOICES = {
    'action': ['repair_translation','retry_review','reconcile','request_source_review','request_human_review',
               'escalate_engineering','wait_for_source','inspect_state','waiting_for_matching_sunday',
               'restore_artifact_access','run_timeline_probe','waiting_for_post_live','operator_download_handoff',
               'request_window_approval','run_reading_pdf_generation','inspect_generation_failure',
               'review_quality_failure','complete'],
    'status': ['proposal','reconciliation_required','decision_proposal_required','blocked','no_repair',
               'pass','requires_review'],
    'reasonCode': ['known_content_failure','review_execution_failed','review_outcome_unknown','source_ambiguity',
                   'contradictory_reviews','evidence_insufficient','semantic_repair_scope_ambiguous',
                   'insufficient_quota','rate_limit_exceeded','invalid_api_key','json_mode_requires_json_word',
                   'http_request_rejected'],
    'humanActionRequired': ['true','false'],
    'formalScheduleStatus': ['pass','fail'],
    'unchangedAudioCannotFitSerialTimeline': ['true','false'],
}


def _questions(adapter, labels):
    return [{'name': key, 'type': 'choice',
             'instructions': f'Apply the supplied evidence and policy for {adapter}. Return {key}; '
                             'the task is an offline rule subtask and grants no execution or approval.',
             'choices': [{'value': value, 'description': value} for value in CHOICES[key]]}
            for key in labels]


def _case(stage, name, adapter, evidence, labels, *, cluster=None):
    evidence = json.loads(json.dumps(evidence, ensure_ascii=False))
    return {'caseId': f'{stage}.{name}', 'stageId': stage, 'subtaskId': adapter,
            'sourceKind': 'developer_fixture', 'clusterId': cluster or f'{stage}.{name}',
            'sharedEvidence': evidence, 'a': {'kind': 'program', 'adapter': adapter},
            'b': {'input': json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                  'questions': _questions(adapter, labels)},
            'expected': {'labels': labels}, 'oracleKind': 'program_oracle'}


def _repair_evidence(variant):
    from scripts import sermon_repair_planning as p, sermon_review_contracts as c
    fixtures = ROOT / 'tests/fixtures/rqc'
    def load(name):
        return json.loads((fixtures / (name + '.json')).read_text())
    review = load('review-fail')
    if variant in {'failed', 'unknown'}:
        review = load('review-pass')
        review.update(executionStatus='failed' if variant == 'failed' else 'outcome_unknown',
                      reviewVerdict='not_assessed', issues=[])
        review['coverage'].update(assessedUnitIds=[], unassessedUnitIds=['source.001'])
        for check in review['checks']:
            check['result'] = 'not_assessed'
    elif variant in {'source', 'conflict', 'insufficient'}:
        issue = copy.deepcopy(review['issues'][0])
        issue.update(issueId='issue-2', severity='uncertain', reasonCode={
            'source': 'source_ambiguity', 'conflict': 'contradictory_reviews',
            'insufficient': 'evidence_insufficient'}[variant])
        review['issues'].append(issue)
    review['receiptSha256'] = c.receipt_sha256(review)
    gate = load('gate-waiting')
    gate.update(admissionStatus='blocked', reasonCodes=['review_failed'],
                allowedNextActions=['repair_translation', 'retry_review', 'request_human_review',
                                    'request_source_review', 'reconcile', 'escalate_engineering'],
                reviewReceiptRefs=[{'artifactId': 'review-receipt', 'canonicalJsonSha256': c.canonical_sha256(review),
                                    'fileBytesSha256': c.bytes_sha256(c.canonical_bytes(review)),
                                    'mediaType': 'application/json'}])
    unit = 'l2.zh-Hans.group.001'
    budget = p.BudgetSnapshot(production_run_id='9'*64, state_revision='8'*64,
        candidate_id='synthetic-candidate', work_unit_id=unit, chain_root_revision_id='r1',
        current_revision_id='r1', authorization_sha256='a'*64, global_budget_sha256='b'*64,
        content_revisions_reserved=0, review_attempts_reserved=1, decision_proposals_reserved=0)
    def node(name, layer, locale, deps):
        return {'workUnitId': name, 'layer': layer, 'targetLocale': locale, 'dependsOn': deps}
    return {'candidate': load('candidate-revision'),
            'candidateArtifactUtf8': (fixtures/'candidate-artifact.json').read_text(),
            'review': review, 'rubric': load('rubric'), 'input_manifest': load('input-manifest'),
            'gate': gate, 'state_revision': '8'*64,
            'graph': [node('source',1,None,[]), node(unit,2,'zh-Hans',['source']),
                      node('l3.zh-Hans.audio',3,'zh-Hans',[unit]),
                      node('l4.zh-Hans.page',4,'zh-Hans',['l3.zh-Hans.audio'])],
            'budget': asdict(budget), 'scope_ambiguous': variant == 'ambiguous',
            'policy': {'routingVersion': p.ROUTING_VERSION, 'failureActions': dict(p.FAILURE_ACTIONS),
                       'unknownOutcome': 'reconcile', 'ambiguousContentScope': 'decision_proposal_required',
                       'executionAuthority': 'none'}}


def _supervisor_evidence():
    return dict(sunday='2026-10-04', live_url='https://example.invalid/public-sermon', state={},
                timeline_report=None, approval_valid=False, approval_reason=None,
                generation_report=None, run_status=None, reading_qa=None, reading_quality=None,
                interpretation_qa=None, access_issues=None, timeline_lease=None,
                generation_lease=None, publication_required=False)


def build_rule_cases():
    cases = []
    for name, action, status, reason in [
        ('content','repair_translation','proposal','known_content_failure'),
        ('failed','retry_review','proposal','review_execution_failed'),
        ('unknown','reconcile','reconciliation_required','review_outcome_unknown'),
        ('source','request_source_review','proposal','source_ambiguity'),
        ('conflict','request_human_review','proposal','contradictory_reviews'),
        ('insufficient','request_human_review','proposal','evidence_insufficient'),
        ('ambiguous','repair_translation','decision_proposal_required','semantic_repair_scope_ambiguous')]:
        cases.append(_case('E03',name,'plan_repair',_repair_evidence(name),
                           {'action':action,'status':status,'reasonCode':reason}))
    for name, http, error, reason in [
        ('quota',429,{'code':'insufficient_quota'},'insufficient_quota'),
        ('rate',429,{'code':'rate_limit_exceeded'},'rate_limit_exceeded'),
        ('key',401,{'code':'invalid_api_key'},'invalid_api_key'),
        ('json',400,{'param':'messages','message':'messages must contain the word json'},'json_mode_requires_json_word'),
        ('unrecognized',503,{'code':'not_allowlisted','message':'private test body'},'http_request_rejected')]:
        cases.append(_case('E03',name,'provider_error',{'httpStatus':http,'error':error,
            'policy':{'fallback':'http_request_rejected','knownCodes':['insufficient_quota','rate_limit_exceeded','invalid_api_key'],
                      'jsonPattern':'HTTP 400 + messages must contain the word json'}}, {'reasonCode':reason}))
    # E04 matches actual normalized token + SequenceMatcher/short-unit predicate.
    rows = [
        ('zh-exact','zh-Hans','神爱世人','神爱世人',.9,'pass'),
        ('zh-punctuation','zh-Hans','神，爱世人！','神爱世人',.9,'pass'),
        ('zh-omission','zh-Hans','神爱世人','神世人',.9,'requires_review'),
        ('zh-short-exact','zh-Hans','信主','信主',.5,'pass'),
        ('zh-short-diff','zh-Hans','信主','信神',.5,'requires_review'),
        ('en-case','es','God Loves Us','god loves us',.9,'pass'),
        ('en-short-diff','es','love god','love man',.5,'requires_review'),
        ('en-long-diff','es','we always love all people','we really love all people',.7,'pass'),
        ('empty-asr','zh-Hans','神爱世人','',.9,'requires_review'),
        ('threshold-pass','zh-Hans','神爱所有世人','神爱所有人',.8,'pass'),
        ('threshold-fail','zh-Hans','神爱所有世人','神爱所有人',.99,'requires_review'),
        ('ko-exact','ko','하나님은 우리를 사랑합니다','하나님은 우리를 사랑합니다',.9,'pass')]
    for name,locale,expected,recognized,threshold,status in rows:
        cases.append(_case('E04',name,'asr_screening_rule_wrapper',
            {'targetLocale':locale,'expectedText':expected,'recognizedText':recognized,
             'policy':{'minSimilarity':threshold,'sequenceMatcherAutojunk':False,
                       'roundDigits':6,'normalization':'NFKC then casefold; zh-Hans/ko use alphanumeric characters; other locales use Unicode word tokens excluding underscore','shortUnitRule':'fewer than 4 expected tokens require no differences',
                       'scope':'text comparison wrapper; no ASR/media identity/full-producer validation'}}, {'status':status}))
    # Formal scheduler: raw measured rows and policy only, no A-derived plan.
    timings = [
        ('short-fit',20,[{'gid':'g1','sourceStart':0,'sourceEnd':4,'audioSeconds':3}], 'pass','false'),
        ('own-span-warning',20,[{'gid':'g1','sourceStart':0,'sourceEnd':4,'audioSeconds':6}], 'pass','false'),
        ('lag-failure',30,[{'gid':'g1','sourceStart':0,'sourceEnd':4,'audioSeconds':13}], 'fail','false'),
        ('tail-failure',10,[{'gid':'g1','sourceStart':0,'sourceEnd':4,'audioSeconds':11}], 'fail','true'),
        ('gap-fit',20,[{'gid':'g1','sourceStart':0,'sourceEnd':4,'audioSeconds':3},
                      {'gid':'g2','sourceStart':10,'sourceEnd':14,'audioSeconds':3}], 'pass','false'),
        ('propagation-failure',30,[{'gid':'g1','sourceStart':0,'sourceEnd':4,'audioSeconds':10},
                                  {'gid':'g2','sourceStart':5,'sourceEnd':9,'audioSeconds':10}], 'fail','false'),
    ]
    for index in range(12):
        name,duration,rows,status,serial=copy.deepcopy(timings[index%6])
        if index>=6:
            for row in rows:row['gid']='second.'+row['gid']
        evidence={'source_seconds':duration,'rows':rows,
                  'policy':{'reactionLagSeconds':.05,'interUtteranceGapSeconds':.05,'maxEndLagSeconds':8.0},
                  'locale':'zh-Hans','identities':{},
                  'taskPolicy':{'scope':'measured formal scheduling only; no WAV measurement/approval',
                                'source':'scripts/target_audio_timing_plan.py:32',
                                'scheduleRule':'start=max(sourceStart+reactionLag,cursor+interGroupGap); end=start+audioSeconds; fail if end exceeds source_seconds or end-sourceEnd exceeds maxEndLagSeconds',
                                'serialRule':'first sourceStart + reactionLag + sum(audioSeconds) + interGroup gaps exceeds source_seconds'}}
        cases.append(_case('E05',f'{name}-{index+1:02d}','target_audio_timing_plan',evidence,
            {'formalScheduleStatus':status,'unchangedAudioCannotFitSerialTimeline':serial},
            cluster=f'E05.{name}'))
    for name,patch,action,human in [
        ('missing-source',{'live_url':None},'wait_for_source',True),
        ('invalid-date',{'state':{'lastSunday':42}},'inspect_state',True),
        ('wrong-week',{'state':{'lastSunday':'2026-09-27'}},'waiting_for_matching_sunday',False),
        ('access',{'access_issues':[{'artifact':'timeline','reason':'missing'}]},'restore_artifact_access',True),
        ('timeline-needed',{},'run_timeline_probe',False),
        ('post-live',{'timeline_report':{'status':'waiting_for_post_live'}},'waiting_for_post_live',False),
        ('download',{'timeline_report':{'status':'waiting_for_download_access'}},'operator_download_handoff',True),
        ('approval',{'timeline_report':{'status':'requires_operator_review'}},'request_window_approval',True),
        ('generation-ready',{'timeline_report':{'status':'requires_operator_review'},'approval_valid':True},'run_reading_pdf_generation',False),
        ('generation-failed',{'generation_report':{'status':'failed'}},'inspect_generation_failure',True),
        ('quality',{'run_status':{'blocker':{'reason':'reading_quality_needs_review','stage':'quality'}}},'review_quality_failure',True),
        ('complete',{'approval_valid':True,'generation_report':{'status':'completed'},
                     'reading_qa':{'status':'pass'},'reading_quality':{'status':'pass'},
                     'interpretation_qa':{'status':'pass'}},'complete',False)]:
        evidence=_supervisor_evidence();evidence.update(patch)
        evidence={'stateInputs':evidence,'policy':{'source':'scripts/sermon_production_supervisor.py:224-373',
                   'precedence':['source/date/access','completed generation + three QA + approval + publication',
                                 'quality blocker','generation failure','active leases','timeline'],
                   'operatorApprovalRequired':True,'scope':'deterministic dual-PDF recommendation'}}
        cases.append(_case('E07',name,'supervisor_recommend_action',evidence,
                           {'action':action,'humanActionRequired':str(human).lower()}))
    for stage,task in [('E06','study_semantic_triage'),('E08','feedback_comment_triage')]:
        cases.append({'caseId':stage+'.baseline-missing','stageId':stage,'subtaskId':task,
            'sourceKind':'developer_fixture','clusterId':stage+'.baseline-missing','sharedEvidence':{},
            'a':{'kind':'no_executable_baseline','adapter':None},'b':{'input':'{}','questions':[]},
            'expected':None,'oracleKind':'no_executable_baseline'})
    return cases


def run_rule_a(case):
    evidence=copy.deepcopy(case['sharedEvidence']);adapter=case['a']['adapter']
    if case['a']['kind']=='no_executable_baseline':
        return {'status':'no_executable_baseline','labels':{}}
    if adapter=='plan_repair':
        from scripts import sermon_repair_planning as p, sermon_review_contracts as c
        evidence.pop('policy');evidence['candidate_bytes']=evidence.pop('candidateArtifactUtf8').encode()
        evidence['review_bytes']=c.canonical_bytes(evidence['review'])
        row=evidence['budget'];row['limits']=p.Limits(**row['limits'])
        for key in ('unresolved_operation_ids','prior_failure_fingerprints'):row[key]=tuple(row[key])
        evidence['budget']=p.BudgetSnapshot(**row)
        result=p.plan_repair(**evidence)
        return {'labels':{key:result[key] for key in ('action','status','reasonCode')}}
    if adapter=='provider_error':
        from scripts import sermon_provider_error as p
        result=p.diagnostic(evidence['httpStatus'],json.dumps({'error':evidence['error']}).encode())
        return {'labels':{'reasonCode':result['reasonCode']}}
    if adapter=='asr_screening_rule_wrapper':
        from scripts.screen_target_language_audio_units import tokens
        expected=tokens(evidence['expectedText'],evidence['targetLocale'])
        actual=tokens(evidence['recognizedText'],evidence['targetLocale'])
        matcher=difflib.SequenceMatcher(None,expected,actual,autojunk=False)
        differences=[op for op,*_ in matcher.get_opcodes() if op!='equal']
        passed=round(matcher.ratio(),6)>=evidence['policy']['minSimilarity'] and (len(expected)>=4 or not differences)
        return {'labels':{'status':'pass' if passed else 'requires_review'}}
    if adapter=='target_audio_timing_plan':
        from scripts.target_audio_timing_plan import plan
        evidence.pop('taskPolicy');result=plan(**evidence)
        return {'labels':{'formalScheduleStatus':result['formalScheduleStatus'],
                          'unchangedAudioCannotFitSerialTimeline':str(result['unchangedAudioCannotFitSerialTimeline']).lower()}}
    if adapter=='supervisor_recommend_action':
        from scripts.sermon_production_supervisor import recommend_action
        result=recommend_action(**evidence['stateInputs'])
        return {'labels':{'action':result['action'],'humanActionRequired':str(result['humanActionRequired']).lower()}}
    raise ValueError('unsupported_rule_adapter')
