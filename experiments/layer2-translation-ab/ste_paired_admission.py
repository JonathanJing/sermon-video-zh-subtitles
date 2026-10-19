"""Offline admission for the existing STE paired A/B plan; never edits or calls production prompts.

See docs/backlog-2026-10-04.zh.md for the candidate wording and paired protocol.
This is a preregistration gate, not a second model-execution harness.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import secrets
from urllib.parse import urlsplit
from scripts import sermon_sentence_interpretation as identity
from scripts import produce_target_language_candidate as candidate
from scripts.experiments import layer2_ab
from scripts.experiments.build_blind_review_scores import blank_score

SCHEMA = 'sermon-ste-paired-plan-v1'
CASE_TAGS = {'spoken_reference', 'omitted_reference', 'quote_or_paraphrase',
             'partially_repaired', 'fully_repaired', 'unresolved_concern'}
METRICS = {'fidelityLossMax', 'unauthorizedReferencesMax', 'missedConcernRateDeltaMax',
           'naturalnessDeltaMin', 'criticalErrorsMax'}


def require(ok, message):
    if not ok: raise ValueError(message)


def digest(plan):
    return identity.json_sha256({key:value for key,value in plan.items() if key != 'approval'})


def artifact(ref, base):
    require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'Frozen artifact reference required')
    path = (Path(base) / ref['path']).resolve()
    require(path.is_file() and identity.sha256(path) == ref['sha256'], 'Frozen experiment artifact changed')
    return path


def _time(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'Experiment timestamp needs timezone')
    return parsed


def admit(plan, base, *, now=None):
    require(plan.get('schemaVersion') == SCHEMA, 'Unsupported STE preregistration')
    require(set(plan) == {'schemaVersion','experimentId','revision','changeKind','candidateA','candidateB',
                         'replacement','referenceRules','source','anchor','samples','model','parameters',
                         'promptVersions','policyVersions','payloads','budget','pricing','blinding',
                         'noninferiority','execution','approval'}, 'Incomplete or unknown STE plan fields')
    require(plan['changeKind'] in {'reviewer_issues','scripture_reading','scripture_metadata','scripture_spoken'},
            'Compare one candidate change at a time before a combined experiment')
    require(isinstance(plan['experimentId'], str) and plan['experimentId']
            and type(plan['revision']) is int and plan['revision'] > 0, 'Experiment identity required')
    a = artifact(plan['candidateA'], base).read_text(); b = artifact(plan['candidateB'], base).read_text()
    replacement = plan['replacement']
    require(set(replacement) == {'start','end','text'} and type(replacement['start']) is int
            and type(replacement['end']) is int and 0 <= replacement['start'] < replacement['end'] <= len(a)
            and isinstance(replacement['text'], str) and replacement['text'].strip(),
            'Explicit replacement span required; do not append a contradictory rule')
    require(a != b and b == a[:replacement['start']] + replacement['text'] + a[replacement['end']:],
            'Candidate B differs beyond the frozen replacement')
    require(set(plan['referenceRules']) == {'reading','metadata','spoken'}
            and all(isinstance(text, str) and text.strip() for text in plan['referenceRules'].values()),
            'Reading, metadata, and spoken citation scope must each be explicit')
    source = json.loads(artifact(plan['source'], base).read_text())
    anchor = json.loads(artifact(plan['anchor'], base).read_text())
    candidate.validate_source_for_translation(source, anchor)
    english = {unit["sourceUnitId"]: unit["english"] for unit in anchor["sourceUnits"]}
    known = set(english)
    samples = plan['samples']
    require(isinstance(samples, list) and samples, 'Frozen paired sample list required')
    ids, tags = set(), set()
    for sample in samples:
        require(set(sample) == {'id','locale','stratum','split','sourceUnitIds','caseTags','fixedDraft'},
                'Incomplete paired sample')
        require(isinstance(sample['id'], str) and sample['id'] and sample['id'] not in ids,
                'Unique paired sample id required')
        ids.add(sample['id']); tags.update(sample['caseTags'])
        require(sample['locale'] in {'zh-Hans','ko','es','vi'} and sample['stratum'] in {'reading','metadata','spoken'}
                and sample['split'] in {'evaluation','holdout'} and sample['sourceUnitIds']
                and len(set(sample['sourceUnitIds'])) == len(sample['sourceUnitIds'])
                and set(sample['sourceUnitIds']) <= known, 'Paired source or sample stratum differs')
        if plan['changeKind'] == 'reviewer_issues':
            artifact(sample['fixedDraft'], base)
        elif sample['fixedDraft'] is not None:
            artifact(sample['fixedDraft'], base)
    require(tags == CASE_TAGS and {'evaluation','holdout'} <= {s['split'] for s in samples},
            'Preregister all issue/reference strata and a held-out set')
    require(isinstance(plan['model'], str) and plan['model'] and isinstance(plan['parameters'], dict),
            'One shared model and sampling configuration required')
    for key in ('promptVersions','policyVersions'):
        require(set(plan[key]) == {'A','B'} and all(isinstance(v,str) and v for v in plan[key].values())
                and plan[key]['A'] != plan[key]['B'], 'Independent version identities required')
    payloads = plan['payloads']
    require(isinstance(payloads, list) and len(payloads) == len(samples)*2, 'Both frozen payloads per sample required')
    pairs, shared_inputs = set(), {}
    sample_map = {s['id']:s for s in samples}
    for payload in payloads:
        require(set(payload) == {'sampleId','arm','artifact'} and payload['sampleId'] in ids
                and payload['arm'] in {'A','B'}, 'Invalid paired payload binding')
        pair = (payload['sampleId'], payload['arm']); require(pair not in pairs, 'Duplicate paired payload'); pairs.add(pair)
        body = json.loads(artifact(payload['artifact'], base).read_text())
        sample = sample_map[payload['sampleId']]
        require(body.get('model') == plan['model']
                and {k:v for k,v in body.items() if k not in {'model','messages'}} == plan['parameters'],
                'Paired payload changes model or fixed API parameters')
        messages = body.get('messages')
        require(isinstance(messages,list) and len(messages)==2
                and messages[0] == {'role':'system','content': a if payload['arm']=='A' else b}
                and set(messages[1]) == {'role','content'} and messages[1]['role']=='user',
                'Frozen complete API messages differ from the candidate prompt')
        user_input = json.loads(messages[1]['content'])
        require(user_input.get('translationGroupId') == sample['id']
                and user_input.get('sourceUnitIds') == sample['sourceUnitIds']
                and user_input.get('targetLocale') == sample['locale']
                and user_input.get('englishUnits') == [{'sourceUnitId':uid,'english':english[uid]}
                                                     for uid in sample['sourceUnitIds']],
                'Payload does not consume the approved English sample')
        if sample['fixedDraft'] is not None:
            require(user_input.get('draft') == json.loads(artifact(sample['fixedDraft'],base).read_text()),
                    'Reviewer pair must consume the same frozen draft')
        if sample['id'] in shared_inputs:
            require(messages[1]['content'] == shared_inputs[sample['id']], 'Paired user inputs differ')
        shared_inputs[sample['id']] = messages[1]['content']
    budget = plan['budget']; pricing = json.loads(artifact(plan['pricing'], base).read_text())
    require(set(budget) == {'maxCostMicroUsd','perArmMaxCalls','maxInputTokens','maxOutputTokens','repeats','maxWallSeconds'}
            and all(type(v) is int and v > 0 for v in budget.values()), 'Explicit positive integer hard budgets required')
    require(budget['perArmMaxCalls'] >= len(samples)*budget['repeats'], 'Call budget does not cover preregistered samples')
    require(pricing.get('model') == plan['model']
            and all(type(pricing.get(k)) is int and pricing[k] >= 0 for k in
                    ('inputMicroUsdPerMillionTokens','outputMicroUsdPerMillionTokens'))
            and isinstance(pricing.get('sourceUrl'), str) and pricing['sourceUrl'].startswith('https://')
            and urlsplit(pricing['sourceUrl']).hostname in {'openai.com','platform.openai.com','developers.openai.com'},
            'Verified model-specific price snapshot required; do not guess prices')
    _time(pricing['verifiedAt'])
    numerator = 2 * budget['perArmMaxCalls'] * (budget['maxInputTokens']*pricing['inputMicroUsdPerMillionTokens']
        + budget['maxOutputTokens']*pricing['outputMicroUsdPerMillionTokens'])
    worst = (numerator + 999_999) // 1_000_000
    require(plan['parameters'].get('max_completion_tokens') == budget['maxOutputTokens'],
            'Frozen API output token cap differs from the experiment budget')
    require(worst <= budget['maxCostMicroUsd'], 'Worst-case token budget exceeds signed cost limit')
    blind = plan['blinding']
    require(set(blind) == {'reviewersRequired','codeMode','keyOpening','adjudicationRule'}
            and type(blind['reviewersRequired']) is int and blind['reviewersRequired'] >= 2
            and blind['codeMode'] == 'random_per_pair' and blind['keyOpening'] == 'after_scores_frozen'
            and isinstance(blind['adjudicationRule'],str) and blind['adjudicationRule'].strip(),
            'Independent blind review and disagreement adjudication required')
    rules = plan['noninferiority']
    require(set(rules) == METRICS | {'uncertaintyMethod'}
            and all(type(rules[key]) in (int,float) and math.isfinite(rules[key]) for key in METRICS)
            and isinstance(rules['uncertaintyMethod'],str) and rules['uncertaintyMethod'].strip(),
            'Freeze noninferiority margins and uncertainty method before viewing results')
    require(rules['criticalErrorsMax'] == 0 and all(rules[k] >= 0 for k in METRICS - {'naturalnessDeltaMin'}),
            'Critical errors must stop the experiment; noninferiority loss margins must be nonnegative')
    execution = plan['execution']
    require(set(execution) == {'startsAt','endsAt','cacheNamespace','unknownOutcome','rollback','productionPromptMutation'}
            and execution['unknownOutcome'] == 'reconcile_without_retry'
            and execution['productionPromptMutation'] is False
            and execution['rollback'] == 'keep_production_A_unchanged'
            and isinstance(execution['cacheNamespace'],str) and execution['cacheNamespace'].startswith('artifacts/ste-ab/'),
            'Isolated cache, rollback and unknown reconciliation required')
    require('..' not in Path(execution['cacheNamespace']).parts, 'Experiment cache namespace escapes isolation')
    require(_time(execution['startsAt']) < _time(execution['endsAt']), 'Invalid experiment execution window')
    blockers = []
    if plan['approval'] is None:
        blockers.append('candidate_samples_budget_window_approval_required')
    else:
        approval = json.loads(artifact(plan['approval'], base).read_text())
        require(approval.get('schemaVersion') == 'sermon-ste-experiment-approval-v1'
                and approval.get('planSha256') == digest(plan) and approval.get('humanApproval') is True
                and set(approval.get('approvedScopes',[])) == {'candidate','samples','budget','window'}
                and isinstance(approval.get('reviewedBy'),str) and approval['reviewedBy'].strip(),
                'Human experiment approval is not bound to this frozen plan')
        require(_time(approval['reviewedAt']) <= _time(execution['endsAt']), 'Experiment approval is outside its window')
    current = now or datetime.now(timezone.utc)
    if not _time(execution['startsAt']) <= current <= _time(execution['endsAt']): blockers.append('outside_execution_window')
    return {'schemaVersion':'sermon-ste-paired-admission-v1','planSha256':digest(plan),
            'status':'blocked' if blockers else 'admitted_for_isolated_runner', 'blockers':blockers,
            'worstCaseMicroUsd':worst, 'productionPromptMutation':False, 'apiCallsMade':0,
            'sampleCount':len(samples),'blindingRequired':True,'productionPromotion':'separate_review_required',
            'requestIdentities':[identity.json_sha256({'planSha256':digest(plan), 'sampleId':row['sampleId'],
                'arm':row['arm'],'repeat':repeat,'payloadSha256':row['artifact']['sha256']})
                for row in payloads for repeat in range(budget['repeats'])]}


def check_unresolved_concerns(known_ids, resolved_ids, retained_ids, *, status):
    """Offline gold-label check: fixing one issue cannot clear remaining labels."""
    known, resolved, retained = set(known_ids), set(resolved_ids), set(retained_ids)
    require(resolved <= known and retained == known - resolved, 'Unresolved concern was lost or falsely retained')
    require(status == ('fail' if retained else 'pass'), 'Reviewer status differs from unresolved concerns')


def blind_pairs(plan, outputs):
    """Use the existing semantic result gate and rating fields; expose no arm/model labels."""
    samples = {row['id']:row for row in plan['samples']}
    require(set(outputs) == set(samples), 'Blind outputs must cover every preregistered sample')
    public, secret = [], []
    for sample_id, sample in samples.items():
        require(set(outputs[sample_id]) == {'A','B'}, 'Both paired arms required')
        options = []
        for arm, result in outputs[sample_id].items():
            group = {'translationGroupId':sample_id, 'sourceUnitIds':sample['sourceUnitIds']}
            passed = layer2_ab._validate_group(result, group, reviewer=True)
            code = secrets.token_hex(12)
            secret.append({'code':code,'sampleId':sample_id,'arm':arm,
                           'machineGate':'pass' if passed else 'fail',
                           'resultJsonSha256':identity.json_sha256(result)})
            options.append({'code':code,'text':result['targetUtterances'],
                            'reviews':[], 'scoreTemplate':blank_score()})
        random.SystemRandom().shuffle(options)
        public.append({'sampleId':sample_id,'locale':sample['locale'],'stratum':sample['stratum'],'options':options})
    return ({'schemaVersion':'sermon-ste-paired-blind-v1','planSha256':digest(plan),'samples':public},
            {'schemaVersion':'sermon-ste-paired-blinding-key-v1','planSha256':digest(plan),'codes':secret})


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    result = admit(plan, args.plan.parent)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x') as handle: json.dump(result, handle, indent=2); handle.write('\n')
    print(json.dumps({'status':result['status'],'apiCallsMade':0,'out':str(args.out.resolve())}))


if __name__ == '__main__': main()
