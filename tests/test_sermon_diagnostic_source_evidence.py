"""Synthetic source-review preservation; no credentials, provider calls or private text."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import sermon_accounting as accounting
from scripts import sermon_diagnostic_source_evidence as evidence
from scripts import sermon_provider_limits as limits
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_transcription_request as transcription
from tests import test_sermon_diagnostic_context as source_fixtures
from tests.test_sermon_diagnostic_provider import config


class SourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        fixture = source_fixtures.DiagnosticContextTests(); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.config = config()
        self.source, self.anchor = deepcopy(fixture.source), deepcopy(fixture.anchor)
        self.aligned = [dict(id=i, start=float(i), end=float(i+1), text='Synthetic fragment '+str(i)+' end.')
                        for i in range(4)]
        text = ' '.join(row['text'] for row in self.aligned)
        aligned_raw = self.write('aligned-segments.json', self.aligned)
        self.write('reference-chunks.json', [dict(id='chunk',start=0,end=180,text=text)])
        self.anchor['input']['mfaSegmentsSha256'] = c.bytes_sha256(aligned_raw)
        anchor_raw = self.write('anchor-manifest.json', self.anchor)
        self.source['source']['media']['sha256'] = self.config['sourceMediaSha256']
        self.source['source']['approvedWindow'].update(startSeconds=60., endSeconds=240.)
        for key, name, value, raw in (('transcript','aligned-segments.json',self.aligned,aligned_raw),
                                     ('anchors','anchor-manifest.json',self.anchor,anchor_raw)):
            self.source[key]['artifact'] = dict(path=str(self.root/name),sha256=c.bytes_sha256(raw),jsonSha256=c.canonical_sha256(value))
        self.source['alignment']['artifact'] = deepcopy(self.source['transcript']['artifact'])
        source_fixtures.reidentify(self.source)
        self.write('simulated-review-inputs/source.json', self.source)
        self.content = dict(sourceAudioSha256=self.config['sourceAudioSha256'],sourceWindowSeconds=[60,240],
            issues=[dict(type=reason,text='fragment '+str(i),issue='Synthetic review candidate',uncertainty='Unconfirmed text-only candidate')
                    for i,reason in enumerate(evidence.REASONS)],
            uncertainty=dict(scope='Text-internal review only; factual claims were not evaluated.',audio_available=False,
                explicit_uncertainty_markers_present=False,confirmed_asr_errors=0,summary='Human review remains pending.'))
        payload = evidence.source_payload(self.config, text)
        response = dict(model='gpt-6-astra',id='synthetic-response',choices=[dict(finish_reason='stop',message={
            'content':json.dumps(self.content)})],usage=dict(prompt_tokens=100,completion_tokens=20))
        observed = dict(requestedModel='gpt-6-astra',providerModel='gpt-6-astra',
            providerUsage=accounting.normalize_usage(response['usage']),elapsedSeconds=.1,serviceTier='default')
        self.review = dict(modelCallId='review',payloadSha256=c.canonical_sha256(payload),response=response,
            usageObservation=observed,elapsedSeconds=.1,costEvidence=limits.usage_cost_evidence(observed))
        asr_response = dict(text=text,usage=dict(type='duration',seconds=180))
        self.asr = dict(modelCallId='asr',payloadSha256='f'*64,response=asr_response,
            costEvidence=transcription.usage_cost_evidence(asr_response,180))
        self.state = dict(config=self.config,requests={
            'review':dict(operationId='source.initial',model='gpt-6-astra',state='returned',
                requestSha256=self.review['payloadSha256'],bounds=limits.request_bounds(payload,limits.MAX_REQUEST_LIMITS)),
            'asr':dict(operationId='transcription.initial',model='gpt-transcribe',state='returned',requestSha256='f'*64,
                bounds=dict(costMicrousd=100000))})
        self.request = dict(schemaVersion='sermon-english-source-review-request-v1',humanApproval=False,status='pending',
            alignedSegmentsSha256=c.bytes_sha256(aligned_raw),anchorManifestJsonSha256=c.canonical_sha256(self.anchor),
            sourceUnitIds=[u['sourceUnitId'] for u in self.anchor['sourceUnits']], requiredChecks=list(evidence.diagnostic.PENDING_CHECKS),
            machineIssues=[dict(issueId='source.issue.'+str(i+1),reasonCode=reason,confirmedError=False,reviewStatus='human_pending',
                matchedSegmentIds=[i],clipTimeRangesSeconds=[[float(i),float(i+1)]],matchingMethod='literal_normalized_text_substring_not_verified_audio',
                privateEvidenceSha256=c.canonical_sha256(self.content['issues'][i])) for i,reason in enumerate(evidence.REASONS)],
            sourceMediaSha256=self.config['sourceMediaSha256'],sourceWindowSeconds=[60,240],scope='review_request_not_approval_receipt')
        self.auth = dict(schemaVersion='isolated-diagnostic-simulation-authorization-v1',
            allowedScope='isolated_diagnostic_L2_machine_review_preview_TTS_delivery_preflight',humanAcceptance='pending',productionEligible=False,
            originalRunConfigSha256=c.canonical_sha256(self.config),sourceCanonicalSha256=c.canonical_sha256(self.source),
            prohibited=sorted(evidence.PROHIBITED),userInstruction='Synthetic authorization only.',userInstructionAt='2026-10-01T00:00:00Z')
        self.context = dict(schemaVersion='sermon-diagnostic-context-v1',runId=self.config['runId'],
            runConfigSha256=c.canonical_sha256(self.config),storeSha256=c.canonical_sha256({'root':str(self.root/'budget'),'schemaVersion':budget.SCHEMA}),
            sourceCanonicalSha256=c.canonical_sha256(self.source),anchorCanonicalSha256=c.canonical_sha256(self.anchor),
            continuationCodeCommit='a'*40,humanAcceptance='pending',productionEligible=False)
        self.refresh()

    def write(self,name,value):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        raw=c.canonical_bytes(value)+b'\n';path.write_bytes(raw);return raw

    def refresh(self):
        self.review['response']['choices'][0]['message']['content']=json.dumps(self.content)
        for call,value in (('review',self.review),('asr',self.asr)):
            raw=self.write('budget/'+budget.STORE_ID+'/provider-run/'+call+'.json',value)
            self.state['requests'][call]['receiptSha256']=c.bytes_sha256(raw)
        self.request['sourceReviewReceiptSha256']=self.state['requests']['review']['receiptSha256']
        self.write('source-review-request.json',self.request)
        self.auth['sourceReviewRequestSha256']=c.canonical_sha256(self.request)
        self.write('simulated-review-inputs/simulation-authorization.json',self.auth)
        self.context['simulationAuthorizationRef']=c.canonical_sha256(self.auth)

    def validate(self):return evidence.validate_prior_source_evidence(self.root,self.state,self.context)

    def test_exact_pending_evidence_returns_only_hashes_and_does_not_write(self):
        before={p:p.read_bytes() for p in self.root.rglob('*.json')}
        result=self.validate()
        self.assertEqual(len(result),10)
        self.assertTrue(all(k.endswith('Sha256') and len(v)==64 for k,v in result.items()))
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*.json')})
        self.assertFalse(self.source['review']['humanApproval'])
        self.assertTrue(all(i['reviewStatus']=='human_pending' for i in self.request['machineIssues']))

    def test_missing_asr_model_tokens_and_cost_are_not_fabricated_or_blocked(self):
        self.asr['response'].pop('usage')
        self.asr['costEvidence']=transcription.usage_cost_evidence(self.asr['response'],180)
        self.refresh();self.validate()
        self.assertIsNone(self.asr['costEvidence']['costMicrousd'])
        self.assertIsNone(self.asr['costEvidence']['inputTokens'])
        self.assertNotIn('model',self.asr['response'])

    def test_authorization_or_original_request_tampering_blocks(self):
        self.request['machineIssues'][0]['reviewStatus']='approved'
        self.write('source-review-request.json',self.request)
        with self.assertRaises(ValueError):self.validate()
        self.refresh()
        with self.assertRaisesRegex(ValueError,'disposition_changed'):self.validate()

    def test_explicit_confirmed_unknown_or_added_failure_blocks_even_when_rebound(self):
        for key,value in [('confirmed_asr_errors',1),('confirmed_asr_errors',None),('audio_available',True),
                          ('explicit_uncertainty_markers_present',True)]:
            old=self.content['uncertainty'][key];self.content['uncertainty'][key]=value;self.refresh()
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate()
            self.content['uncertainty'][key]=old
        self.content['status']='failed';self.refresh()
        with self.assertRaises(ValueError):self.validate()

    def test_unknown_transport_changed_raw_usage_and_unrecognized_reason_block(self):
        self.state['requests']['review']['state']='outcome_unknown'
        with self.assertRaises(ValueError):self.validate()
        self.state['requests']['review']['state']='returned'
        self.review['usageObservation']['providerUsage']['inputTokens']+=1;self.refresh()
        with self.assertRaisesRegex(ValueError,'usage_or_payload'):self.validate()
        self.review['usageObservation']['providerUsage']['inputTokens']-=1
        self.content['issues'][0]['type']='confirmed_meaning_error';self.refresh()
        with self.assertRaises(ValueError):self.validate()

    def test_original_transcript_anchor_or_nonnull_machine_judge_cannot_be_overridden(self):
        original=(self.root/'aligned-segments.json').read_bytes()
        (self.root/'aligned-segments.json').write_bytes(original+b' ')
        with self.assertRaises(ValueError):self.validate()
        (self.root/'aligned-segments.json').write_bytes(original)
        self.source['evidence']['machineJudge']=deepcopy(self.source['anchors']['artifact'])
        source_fixtures.reidentify(self.source)
        self.context['sourceCanonicalSha256']=self.auth['sourceCanonicalSha256']=c.canonical_sha256(self.source)
        self.write('simulated-review-inputs/source.json',self.source);self.refresh()
        with self.assertRaisesRegex(ValueError,'machine_judge'):self.validate()


if __name__=='__main__':unittest.main()
