#!/usr/bin/env python3
"""CLI study branches from re-admitted diagnostic text; never human approval."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts import codex_layer2_diagnostic as diagnostic, sermon_codex_transport as codex, sermon_accounting as accounting
from scripts import sermon_study_generation as generation, study_artifacts
from scripts.experiments import diagnostic_audio_inputs as admission
from scripts.sermon_execution_harness import work_lock
from scripts.sermon_unified import resources
from scripts.production_concurrency_profile import load_profile


def execute(*,fixture,candidate,evidence,media,out_dir,kind,profile,resource_policy,cli_path=None,caller=None):
    diagnostic.require(kind in ('outline','meditation'),'diagnostic study kind')
    out=diagnostic.artifact_directory(out_dir)
    args=SimpleNamespace(diagnostic_fixture=fixture,diagnostic_candidate=candidate,evidence=evidence,media=media)
    groups,bound=admission.checked_inputs(args)
    diagnostic.require(bound.get('concurrencyProfile')==profile,'study profile differs from fixture')
    resource_policy=resources.validate_policy(resource_policy)
    diagnostic.require(resource_policy['capacities']['codex_cli']==profile['totalCodexSlots'],'study shared CLI capacity')
    source,anchor,policy,*_=diagnostic.load_fixture(fixture)
    units={u['sourceUnitId']:u for u in anchor['sourceUnits']}
    identity={'schemaVersion':'diagnostic-study-execution-v1','kind':kind,'input':bound,
              'profile':profile,'resourcePolicySha256':admission.digest(resource_policy),
              'implementationSha256':admission.sha(__file__),'generatorSha256':admission.sha(generation.__file__),
              'transportSha256':admission.sha(codex.__file__),'batchGroups':12,
              'productionEligible':False,'humanApproval':False,'simulationOnly':True}
    call=caller or codex.call_json
    schema={'type':'object','additionalProperties':False,'required':['sections'],'properties':{'sections':{
        'type':'array','minItems':1,'maxItems':32,'items':{'type':'object','additionalProperties':False,
        'required':['title','body','sourceUnitIds'],'properties':{'title':{'type':'string','minLength':1,'maxLength':512},
        'body':{'type':'string','minLength':1,'maxLength':16000},'sourceUnitIds':{'type':'array','minItems':1,
        'uniqueItems':True,'items':{'type':'string'}}}}}}}
    with accounting.accounting_session(out/'accounting','diagnostic_study_'+kind,
            {'targetLocale':bound['targetLocale']},evidence_directory=out), work_lock(out):
        diagnostic.save(out/'identity.json',identity)
        sections=[]
        for index,offset in enumerate(range(0,len(groups),12)):
            admission.check_frozen(bound)
            batch=groups[offset:offset+12]
            ids=list(dict.fromkeys(i for row in batch for i in row['sourceUnitIds']))
            task={'kind':kind,'locale':bound['targetLocale'],'terminology':policy['terminology'],
                  'sourceUnits':[units[i] for i in ids],'diagnosticTranslationGroups':batch,
                  'humanApproval':False,'productionEligible':False}
            prompt=generation.PROMPT.replace('approved translation','diagnostic translation')+'\nDIAGNOSTIC ONLY; all human decisions pending.\nINPUT:\n'+json.dumps(task,ensure_ascii=False)
            result=call(prompt,model='gpt-6.1-sol',reasoning='high',service_tier='fast',output_schema=schema,
                output_dir=out/f'call-{index:03d}',cli_path=cli_path,resource_policy=resource_policy,
                concurrency_profile=profile,resource_class='business')
            import jsonschema
            jsonschema.Draft202012Validator(schema).validate(result)
            diagnostic.require(all(set(s['sourceUnitIds'])<=set(ids) for s in result['sections']),
                               'study response cites unknown source units')
            sections.extend(result['sections'])
        admission.check_frozen(bound)
        artifact=study_artifacts.produce(kind,sections,page_id='diagnostic-605s',locale=bound['targetLocale'],
            source_sha=admission.digest(source),text_sha=bound['candidateFileSha256'],producer_identity=admission.digest(identity))
        result={'schemaVersion':'diagnostic-study-result-v1','simulationOnly':True,'productionEligible':False,
                'humanApproval':False,'releaseEligible':False,'humanReview':'pending','artifact':artifact,
                'executionSha256':admission.digest(identity),'callsPlanned':(len(groups)+11)//12}
        diagnostic.save(out/'result.json',result)
        return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('fixture','candidate','evidence','media','out-dir','profile','resource-policy'):
        p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--kind',choices=('outline','meditation'),required=True)
    p.add_argument('--codex-cli',type=Path)
    a=p.parse_args()
    result=execute(fixture=a.fixture,candidate=a.candidate,evidence=a.evidence,media=a.media,out_dir=a.out_dir,
        kind=a.kind,profile=load_profile(a.profile),resource_policy=json.loads(a.resource_policy.read_text()),cli_path=a.codex_cli)
    print(json.dumps({'status':'diagnostic_study_human_pending','productionEligible':False,'humanApproval':False,
                      'executionSha256':result['executionSha256']},ensure_ascii=False))
if __name__=='__main__':main()
