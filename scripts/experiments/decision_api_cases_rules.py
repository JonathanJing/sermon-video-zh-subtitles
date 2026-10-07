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
import hashlib
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


RULES_VERSION = 'weekly-rules-explicit-v2'
TASK_CHOICES = {
    'plan_repair': {
        'action': CHOICES['action'][:6],
        'status': CHOICES['status'][:5],
        'reasonCode': CHOICES['reasonCode'][:7]+[
            'recover_persisted_review_evidence','invalid_gate_evidence','unsupported_content_failure',
            'language_plugin_failed','gate_requires_review','no_repair_required','gate_action_not_allowed',
            'durable_budget_snapshot_required','content_revision_limit_reached','review_execution_limit_reached',
            'repeated_failure_without_new_evidence','decision_proposal_limit_reached']},
    'provider_error': {'reasonCode': ['http_request_rejected','unsupported_parameter','unsupported_value',
        'json_mode_requires_json_word','invalid_api_key','insufficient_quota','rate_limit_exceeded',
        'context_length_exceeded','model_not_found','audio_file_invalid']},
    'asr_screening_rule_wrapper': {'status': ['pass','requires_review']},
    'target_audio_timing_plan': {'formalScheduleStatus':['pass','fail'],
                               'unchangedAudioCannotFitSerialTimeline':['true','false']},
    'supervisor_recommend_action': {
        'action':['wait_for_source','inspect_state','waiting_for_matching_sunday','restore_artifact_access',
                  'request_window_approval','inspect_publication_evidence','complete','inspect_quality_evidence',
                  'review_quality_failure','inspect_generation_failure','wait_for_active_run','run_timeline_probe',
                  'waiting_for_source','waiting_for_post_live','operator_download_handoff','run_reading_pdf_generation',
                  'resume_failed_timeline','inspect_timeline_failure','inspect_unrecognized_state'],
        'humanActionRequired':['true','false']},
}
RULE_INSTRUCTIONS = {
    'plan_repair': '''Reproduce a pure repair proposal, not execution. Evaluate in order: (1) review executionStatus=outcome_unknown or unresolved budget operation -> reconcile/reconciliation_required/review_outcome_unknown; (2) persistence_failed, or saved_review_response with failed/cancelled -> reconcile/reconciliation_required/recover_persisted_review_evidence; (3) stale_identity or unknown_rubric gate reason -> reconcile/reconciliation_required/invalid_gate_evidence; (4) review_conflict gate or contradictory_reviews issue -> request_human_review/proposal/contradictory_reviews; (5) source_not_ready gate or source_ambiguity issue -> request_source_review/proposal/source_ambiguity; (6) failed/cancelled execution -> retry_review/proposal/review_execution_failed; (7) inconclusive/not_assessed verdict or evidence_insufficient issue -> request_human_review/proposal/evidence_insufficient; (8) needs_rework verdict -> repair_translation/proposal/known_content_failure if all issue codes are content codes; otherwise escalate_engineering/proposal/unsupported_content_failure; (9) gate language_plugin_failed -> escalate_engineering/proposal/language_plugin_failed; (10) gate not admitted -> request_human_review/proposal/gate_requires_review; otherwise no repair. Reconcile always stops. A non-reconcile action absent from gate.allowedNextActions is blocked/gate_action_not_allowed. Paid repair/retry without budget is blocked/durable_budget_snapshot_required. Repair with content_revisions_reserved >= limits.content_revisions is blocked/content_revision_limit_reached; retry with review_attempts_reserved >= limits.review_attempts_per_revision is blocked/review_execution_limit_reached. A repeated failure fingerprint blocks repair. Only when scope_ambiguous is true and a content repair is otherwise a proposal, change status to decision_proposal_required and reason to semantic_repair_scope_ambiguous (or blocked/decision_proposal_limit_reached when proposals consumed). Human/source review actions remain status proposal; no approval or actual execution occurs.''',
    'provider_error': '''Reproduce bounded provider_error.diagnostic: default reason http_request_rejected. Use allowlisted error code when it is a supported reason. On HTTP 400, messages param or absent param and message contains both 'must contain the word' and 'json' -> json_mode_requires_json_word. On HTTP 400, an allowlisted non-messages param and message starts 'unsupported parameter:' -> unsupported_parameter. On HTTP 400 with known audio corruption phrase -> audio_file_invalid. Unknown codes/messages preserve default. This task diagnoses fixed error evidence only.''',
    'asr_screening_rule_wrapper': '''Compare the shared already-frozen ASR with expectedText; do not transcribe or judge actual audio. Normalize both with Unicode NFKC then casefold. For zh-Hans/ko, tokens are individual alphanumeric characters; for other locales use Unicode word tokens excluding underscores. Compute difflib.SequenceMatcher(expectedTokens, recognizedTokens, autojunk=False).ratio(), rounded to 6 digits. status is pass ONLY IF rounded similarity >= policy.minSimilarity AND (expected token count >= 4 OR normalized token sequences exactly equal). Otherwise status is requires_review, including empty recognized text. A semantic paraphrase, homophone, or tiny material difference does not override this literal rule. This is rule fidelity, not correctness/naturalness/approval.''',
    'target_audio_timing_plan': '''Reproduce measured formal scheduling, not physical feasibility beyond supplied measurements. Initialize cursor=0. For each ordered row, plannedStart=max(sourceStart + reactionLagSeconds, cursor + (interUtteranceGapSeconds if not first else 0)); plannedEnd=plannedStart+audioSeconds; cursor=plannedEnd. formalScheduleStatus is fail if ANY plannedEnd > source_seconds + 0.000001 OR plannedEnd-sourceEnd > maxEndLagSeconds + 0.000001; otherwise pass. Exceeding a row's own source span alone is NOT formal failure. Compute serialLowerBound=first sourceStart + reactionLagSeconds + sum(audioSeconds) + (rowCount-1)*interUtteranceGapSeconds. unchangedAudioCannotFitSerialTimeline is true ONLY IF serialLowerBound-source_seconds > 0.000001, else false. This second question is a total-duration lower-bound test independent of end-lag violations: formal fail can coexist with serial false. Nothing grants approval.''',
    'supervisor_recommend_action': '''Reproduce recommend_action on stateInputs. Apply these conditions in strict order, returning the exact action and current human flag: (1) missing live_url -> wait_for_source/true; invalid non-string nonempty state.lastSunday -> inspect_state/true; different lastSunday -> waiting_for_matching_sunday/false; any access_issues -> restore_artifact_access/true. (2) generation completed: all THREE reading_qa, reading_quality, interpretation_qa status pass required; any missing/fail -> inspect_quality_evidence/true; all pass but approval_valid false -> request_window_approval/true; publication_required and generation publication.status != pass -> inspect_publication_evidence/true; otherwise complete/false. (3) run_status.blocker.reason reading_quality_needs_review or pdf_qa_needs_review -> review_quality_failure/true. (4) generation failed/error -> inspect_generation_failure/true. (5) active generation/timeline lease -> wait_for_active_run/false. (6) missing timeline_report -> run_timeline_probe/false. Timeline status waiting_for_source, waiting_for_matching_sunday, waiting_for_post_live -> same action/false; waiting_for_download_access -> operator_download_handoff/true; requires_operator_review or already_requires_operator_review with approval_valid false -> request_window_approval/true, with approval_valid true -> run_reading_pdf_generation/false. Failed/error timeline requires source-bound archive resumability: only verified resumable archive failure -> resume_failed_timeline/false; otherwise inspect_timeline_failure/true. Unknown timeline -> inspect_unrecognized_state/true. humanActionRequired means a HUMAN ACTION IS STILL NEEDED NOW, not that the workflow generally requires human approval; an already valid approval satisfies that requirement. A waiting state has false unless a condition explicitly says true.''',
}
DESCRIPTIONS = {
    'pass':'The exact task-specific deterministic predicate passes; no human approval implied.',
    'requires_review':'The literal ASR screening predicate fails; not an audio correctness verdict.',
    'proposal':'A deterministic next-action proposal; no execution or approval granted.',
    'decision_proposal_required':'Explicit scope_ambiguous asks for bounded content-repair decision.',
    'reconciliation_required':'Unknown/stale/persistence state needs reconciliation before operations.',
    'fail':'A formal schedule end-lag or clip-tail constraint is violated.',
}


def _questions(adapter, labels):
    result=[]
    for key in labels:
        choices=[]
        for value in TASK_CHOICES[adapter][key]:
            description=DESCRIPTIONS.get(value,'Select this exact named route only when its ordered condition holds.')
            if value in ('true','false'):
                if key=='unchangedAudioCannotFitSerialTimeline':
                    description=('Serial lower bound EXCEEDS clip duration plus epsilon: unchanged audio cannot fit.' if value=='true'
                                 else 'Serial lower bound DOES NOT exceed duration: this test does not prove impossibility.')
                else:
                    description=('An unmet condition needs human action NOW.' if value=='true'
                                 else 'Execute, wait, or complete without a NEW human action.')
            choices.append({'value':value,'description':description})
        result.append({'name':key,'type':'choice','instructions':RULE_INSTRUCTIONS[adapter]+f' Return the label for {key}.',
                       'choices':choices})
    return result


def _json_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _read_frozen_json(path):
    """Read JSON only; never probe media or dispatch an ASR model."""
    path=Path(path)
    if path.suffix != '.json' or path.is_symlink() or path.stat().st_size > 32*1024*1024:
        raise ValueError('invalid_real_rule_json_artifact')
    raw=path.read_bytes()
    value=json.loads(raw)
    return value,hashlib.sha256(raw).hexdigest()


def _screen_values(expected_text, recognized_text, locale, threshold):
    from scripts.screen_target_language_audio_units import tokens
    expected=tokens(expected_text,locale);actual=tokens(recognized_text,locale)
    if not expected:
        raise ValueError('empty_expected_asr_tokens')
    matcher=difflib.SequenceMatcher(None,expected,actual,autojunk=False)
    similarity=round(matcher.ratio(),6)
    differences=[{'kind':kind,'expected':expected[a:b],'recognized':actual[c:d]}
                 for kind,a,b,c,d in matcher.get_opcodes() if kind!='equal']
    status='pass' if similarity>=threshold and (len(expected)>=4 or not differences) else 'requires_review'
    return status,similarity,differences,len(expected)


REAL_RULE_CORPUS = Path('artifacts/drive-source-20260926-1730/layer3-analysis/spoken-script-drafts/zh-Hans/formal-audio-20260927-1100/compacted-xing')


def build_real_rule_cases(source_root, max_cases=60):
    """Export stratified real shared-ASR inputs, with NO independent semantic gold.

    Validate every retained unit before sampling. Selection uses the existing
    literal rule flag and distance to threshold, never an invented human verdict.
    All units from the same original source/media share one cluster; audio
    revisions are not independent source events. Source_root is an explicit
    authorized local checkout. Only JSON is read, including source bindings.
    """
    if type(max_cases) is not int or not 1<=max_cases<=1000:
        raise ValueError('invalid_real_rule_sample_limit')
    root=Path(source_root).resolve();folder=root/REAL_RULE_CORPUS
    receipt_path=folder/'review/asr-screening.json';job_path=folder/'job.json'
    manifest_path=folder/'render-manifest.json'
    receipt,receipt_sha=_read_frozen_json(receipt_path)
    job,job_sha=_read_frozen_json(job_path)
    manifest,manifest_sha=_read_frozen_json(manifest_path)
    if (receipt.get('schemaVersion')!='sermon-target-language-audio-screening-v1'
        or receipt.get('targetLanguageSpeechJobJsonSha256')!=_json_sha(job)
        or manifest.get('targetLanguageSpeechJobJsonSha256')!=_json_sha(job)
        or receipt.get('trackSha256')!=manifest.get('track',{}).get('sha256')
        or receipt.get('targetLocale')!=job.get('targetLocale')
        or manifest.get('targetLocale')!=job.get('targetLocale')
        or receipt.get('coverage')!=1.0):
        raise ValueError('real_asr_identity_or_coverage_mismatch')
    threshold=receipt.get('minSimilarity')
    if type(threshold) not in (int,float) or not 0<threshold<=1:
        raise ValueError('real_asr_threshold_invalid')
    bindings={}
    for key in ('englishSourcePackage','anchorManifest'):
        ref=job['inputs'][key];path=Path(ref['path'])
        if not path.is_absolute():path=folder/path
        value,file_sha=_read_frozen_json(path)
        if ref.get('sha256')!=file_sha or ref.get('jsonSha256')!=_json_sha(value):
            raise ValueError('real_asr_source_binding_mismatch')
        bindings[key]=(value,file_sha,path)
    source=bindings['englishSourcePackage'][0]
    if manifest.get('englishSourcePackageJsonSha256')!=_json_sha(source):
        raise ValueError('real_asr_manifest_source_mismatch')
    anchor_ids={unit['sourceUnitId'] for unit in bindings['anchorManifest'][0]['sourceUnits']}
    source_identity=source.get('source',{})
    media_sha=source_identity.get('media',{}).get('sha256')
    if not isinstance(media_sha,str) or len(media_sha)!=64 or not source_identity.get('sourceId'):
        raise ValueError('real_asr_original_source_identity_required')
    cluster='E04.source.'+_json_sha({'sourceId':source_identity['sourceId'],'sourceMediaSha256':media_sha})[:24]
    rows=receipt['results'];units=job['units'];rendered=manifest['units']
    if not rows or len(rows)!=len(units) or len(rows)!=len(rendered):
        raise ValueError('real_asr_full_unit_coverage_mismatch')
    group_ids=[unit['translationGroupId'] for unit in units]
    if (len(set(group_ids))!=len(group_ids) or receipt.get('reviewedGroupIds')!=group_ids
        or receipt.get('unitAudioSha256s')!=[row['audioSha256'] for row in rows]):
        raise ValueError('real_asr_unit_order_or_coverage_mismatch')
    candidates=[]
    for index,(row,unit,rendered_unit) in enumerate(zip(rows,units,rendered)):
        expected_text=unit['text'];recognized=row['recognized']
        text_sha=hashlib.sha256(expected_text.encode()).hexdigest()
        if (unit.get('unitIndex')!=index or row['textGroupId']!=unit['translationGroupId']
            or rendered_unit['textGroupId']!=unit['translationGroupId']
            or row['targetTextSha256']!=text_sha or rendered_unit['targetTextSha256']!=text_sha
            or row['audioSha256']!=rendered_unit['audio']['sha256']
            or not set(unit['sourceUnitIds'])<=anchor_ids):
            raise ValueError('real_asr_unit_text_or_media_binding_mismatch')
        status,similarity,differences,token_count=_screen_values(expected_text,recognized,job['targetLocale'],threshold)
        if row.get('status')!=status or abs(row.get('similarity',-1)-similarity)>1e-6 or row.get('differences')!=differences:
            raise ValueError('real_asr_retained_derived_rule_mismatch')
        evidence={'targetLocale':job['targetLocale'],'expectedText':expected_text,'recognizedText':recognized,
            'policy':{'minSimilarity':threshold,'sequenceMatcherAutojunk':False,'roundDigits':6,
                      'normalization':'NFKC then casefold; zh-Hans/ko alphanumeric characters; others Unicode words excluding underscore',
                      'shortUnitRule':'fewer than 4 expected tokens require exact token equality',
                      'scope':'frozen shared-ASR literal comparison only; no media loading or semantic gold'}}
        # The receipt and media hashes are provenance, not labels or model input.
        semantic_id=_json_sha({'sourceMediaSha256':media_sha,'sourceUnitIds':unit['sourceUnitIds'],
                               'locale':job['targetLocale'],'expected':expected_text,'recognized':recognized,
                               'threshold':threshold})
        case=_case('E04','real-'+semantic_id[:20],'asr_screening_rule_wrapper',evidence,{'status':status},cluster=cluster)
        case.update(sourceKind='frozen_real_shared_asr',expected=None,oracleKind='unadjudicated_real_input',
            provenance={'sourcePath':str(receipt_path.relative_to(root)),'sourceFileSha256':receipt_sha,
                'jobPath':str(job_path.relative_to(root)),'jobFileSha256':job_sha,'jobJsonSha256':_json_sha(job),
                'renderManifestPath':str(manifest_path.relative_to(root)),'renderManifestFileSha256':manifest_sha,
                'sourcePackageJsonSha256':_json_sha(source),'sourcePackageFileSha256':bindings['englishSourcePackage'][1],
                'anchorManifestJsonSha256':_json_sha(bindings['anchorManifest'][0]),
                'anchorManifestFileSha256':bindings['anchorManifest'][1],'sourceMediaSha256':media_sha,
                'sourceIdentitySha256':_json_sha(source_identity),'sourceUnitIds':unit['sourceUnitIds'],
                'unitIndex':index,'textGroupId':unit['translationGroupId'],'targetTextSha256':text_sha,
                'unitAudioSha256':row['audioSha256'],'sharedASRModel':receipt.get('model'),
                'sharedASRModelRevision':receipt.get('modelRevision'),'fullCorpusUnitCount':len(rows),
                'fullCorpusUnitCoverageVerified':True,'independentSemanticGold':False,
                'samplingPolicy':'balance literal-rule flags and passes, prioritize threshold-near/short units; deterministic coverage across original ordering',
                'sampleGap':'one original source event; shared ASR text is not independently adjudicated audio truth'})
        candidates.append((status,abs(similarity-threshold),token_count,index,case))
    # Stratification is private preparation; neither status nor similarity enters B.
    flagged=sorted([row for row in candidates if row[0]=='requires_review'],key=lambda row:(row[1],row[2],row[3]))
    passed=sorted([row for row in candidates if row[0]=='pass'],key=lambda row:(row[1],row[2],row[3]))
    flag_limit=min(len(flagged),(max_cases+1)//2)
    selected=flagged[:flag_limit]+passed[:max_cases-flag_limit]
    if len(selected)<max_cases:
        selected+=flagged[flag_limit:flag_limit+max_cases-len(selected)]
    selected.sort(key=lambda row:row[3])
    return [row[-1] for row in selected]


def _case(stage, name, adapter, evidence, labels, *, cluster=None):
    evidence = json.loads(json.dumps(evidence, ensure_ascii=False))
    evidence['decisionTask']={'rulesVersion':RULES_VERSION,'adapter':adapter,'rules':RULE_INSTRUCTIONS[adapter]}
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
    evidence=copy.deepcopy(case['sharedEvidence']);evidence.pop('decisionTask',None);adapter=case['a']['adapter']
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
        status,*_=_screen_values(evidence['expectedText'],evidence['recognizedText'],
                                evidence['targetLocale'],evidence['policy']['minSimilarity'])
        return {'labels':{'status':status}}
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
