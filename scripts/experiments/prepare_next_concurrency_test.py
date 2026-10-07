#!/usr/bin/env python3
"""Freeze three-locale 605s diagnostics without calling models or creating approvals."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import sys
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts import codex_layer2_diagnostic as diagnostic, target_language_policy as policies
from scripts.language_review_plugins import diagnostic_pinned_quotes as quotes
from scripts.production_concurrency_profile import profile_v1

# Trial surfaces only, pending human verification; no Bible edition claim.
TARGETS={
'zh-Hans':['我立刻被灵感动，见有一个宝座安置在天上，又有一位坐在宝座上。',
           '看那坐着的，好像碧玉和红宝石；又有虹围着宝座，好像绿宝石。'],
'es':['Inmediatamente estaba en el Espíritu, y había un trono en el cielo, y alguien estaba sentado en él.',
      'El que estaba sentado allí tenía el aspecto de jaspe y cornalina; un arcoíris con el aspecto de una esmeralda rodeaba el trono.'],
'ko':['즉시 나는 성령 안에 있었고, 하늘에 보좌가 있었으며, 그 보좌에 누군가 앉아 있었습니다.',
      '거기 앉아 계신 분은 벽옥과 홍옥 같은 모습이었고, 에메랄드 같은 모습의 무지개가 그 보좌를 둘러싸고 있었습니다.']}
TERMS={
'zh-Hans':['小亚细亚','If I Had More Time','主神','主神全能者','尼古拉斯·卡尔','旧约','罗马帝国','Super Bloom','世界大战'],
'es':['Asia Menor','If I Had More Time','Señor Dios','Señor Dios Todopoderoso','Nicholas Carr','Antiguo Testamento','Imperio romano','Super Bloom','Guerra Mundial'],
'ko':['소아시아','If I Had More Time','주 하나님','주 하나님 전능자','니컬러스 카','구약','로마 제국','Super Bloom','세계 대전']}
NAMES=['Asia Minor','If I Had More Time','Lord God','Lord God Almighty','Nicholas Carr','Old Testament','Roman Empire','Super Bloom','World War']


def prepare(sample,baseline_policy,out,code_commit):
    out=diagnostic.artifact_directory(out)
    diagnostic.require(not out.exists(),'new preparation directory required')
    sample=Path(sample).resolve()
    source=json.loads((sample/'source.json').read_text())
    anchor=json.loads((sample/'anchor.json').read_text())
    plan=json.loads((sample/'group-plan.json').read_text())
    baseline=json.loads(Path(baseline_policy).read_text())
    units={u['sourceUnitId']:u for u in anchor['sourceUnits']}
    quote_group=next(g for g in plan if '0-u067' in g['sourceUnitIds'])
    diagnostic.require(quote_group['sourceUnitIds']==['0-u066','0-u067','0-u068'],'605s quote group changed')
    spans=[('0-u067',26,122),('0-u068',0,141)]
    profile=profile_v1()
    diagnostic.save(out/'profile.json',profile)
    resource={'schemaVersion':'sermon-unified-resource-policy-v1','brokerRoot':str(out/'broker'),
        'capacities':{'cpu':4,'online_api':4,'codex_cli':24,'spark_tts':1,'publisher':1}}
    diagnostic.save(out/'resource-policy.json',resource)
    locales={}
    for locale in ('zh-Hans','ko','es'):
        policy=copy.deepcopy(baseline);policy['targetLocale']=locale
        policy['sourceScope']['englishSourcePackageJsonSha256']=policies.canonical_sha256(source)
        policy['sourceScope']['anchorManifestSha256']=policies.canonical_sha256(anchor)
        policy['terminology']['properNames']=[{'source':s,'target':t,'reviewStatus':'pending'} for s,t in zip(NAMES,TERMS[locale])]
        if locale!='zh-Hans':
            for row in policy['terminology']['seriesNames']:
                row.update(target=row['source'],reviewStatus='pending')
        policy['formatting']['speechRegister']={'zh-Hans':'natural_spoken_simplified_chinese','ko':'natural_spoken_korean','es':'natural_spoken_spanish'}[locale]
        language={'zh-Hans':'Simplified Chinese','ko':'Korean','es':'Spanish'}[locale]
        policy['languageReview']['registerRules']=[f'Natural spoken {language}; preserve complete meaning and explicit names/numbers. Diagnostic trial surfaces remain human pending.']
        for role in ('translator','reviewer'):
            policy[role]['promptVersion']=f'sermon-target-language-{role}-{locale}-diagnostic-v1'
        for name in policy['componentSha256']:
            policy['componentSha256'][name]=policies.canonical_sha256(policy[name])
        provenance=out/locale/'pending-quote-draft.json'
        diagnostic.save(provenance,{'diagnosticOnly':True,'humanApproval':False,'editionVerified':False,
            'status':'pending','targetLocale':locale,'drafts':TARGETS[locale]})
        parts=[]
        for (unit,start,end),target in zip(spans,TARGETS[locale]):
            english=units[unit]['english'][start:end]
            parts.append({'sourceUnitId':unit,'englishStartOffset':start,'englishEndOffset':end,
                'englishExcerpt':english,'englishExcerptSha256':quotes.text_hash(english),
                'targetText':target,'targetTextSha256':quotes.text_hash(target)})
        bindings={'schemaVersion':quotes.SCHEMA,'sourceSha256':policies.canonical_sha256(source),
            'anchorSha256':policies.canonical_sha256(anchor),'groupPlanSha256':policies.canonical_sha256(plan),
            'targetLocale':locale,'editionId':quotes.EDITION,'citationUseStatus':'pending',
            'provenance':{'status':'pending','artifactPath':str(provenance),'artifactSha256':policies.file_sha256(provenance)},
            'quotes':[{'translationGroupId':quote_group['translationGroupId'],'sourceUnitIds':quote_group['sourceUnitIds'],
                      'reference':'REV.4:2-3','parts':parts}]}
        plugin=out/locale/'pinned-quotes.py'
        policy=quotes.freeze_quote_plugin(source,anchor,plan,policy,bindings,plugin)
        fixture=out/locale/'fixture'
        diagnostic.freeze_fixture(source,anchor,policy,plan,plugin,fixture,
            authorization_ref='User authorized next diagnostic concurrency test and simulated human receipts only',
            code_commit=code_commit,translator_model='gpt-6.1-sol',
            scripture_classification='contains_direct_quotations',source_quotation_units=['0-u067','0-u068'],
            concurrency_profile=profile)
        diagnostic.load_fixture(fixture)
        locales[locale]={'fixture':str(fixture),'outDir':str(out/locale/'layer2'),'groups':len(plan)}
    result={'schemaVersion':'next-concurrency-fixture-preparation-v1','status':'prepared_no_model_calls',
        'realModelCalls':0,'productionEligible':False,'humanApproval':False,'sourceMode':'reuse_frozen_source',
        'sourceUnits':len(anchor['sourceUnits']),'sourceSentences':len({u['sourceSentenceId'] for u in units.values()}),
        'groupsPerLocale':len(plan),'profile':profile,'locales':locales,
        'baselineCodeCommit':code_commit,'preparationImplementationSha256':policies.file_sha256(Path(__file__)),
        'sourceMediaSha256':source['source']['media']['sha256'],
        'sourceWindow':{k:source['source']['approvedWindow'][k] for k in ('startSeconds','endSeconds')},
        'quoteQuality':'pending_diagnostic_drafts_no_edition_or_human_approval'}
    diagnostic.save(out/'preparation.json',result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sample',type=Path,required=True);p.add_argument('--baseline-policy',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--code-commit',required=True)
    a=p.parse_args();print(json.dumps(prepare(a.sample,a.baseline_policy,a.out,a.code_commit),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
