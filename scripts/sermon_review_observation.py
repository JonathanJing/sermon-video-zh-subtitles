"""Bounded safe projections of private RQC evidence, never execution authority."""
from scripts import sermon_review_contracts as contracts

CODE = 'rqc_observation'
ROLES = {'sermon-candidate-revision-v1':'generation','sermon-review-receipt-v1':'quality_review',
         'sermon-review-gate-decision-v1':'gate','sermon-review-repair-plan-v1':'repair'}
NULL_FIELDS = ('receiptContentSha256','artifactSha256','rubricSha256','executionStatus','reviewVerdict',
    'admissionStatus','coverage','modelCallId','reviewAttemptId','reviewerInputManifestSha256',
    'repairAction','triggerReceiptSha256','fromRevisionId','toRevisionId')


def project_receipt(receipt):
    contracts.validate_contract(receipt)
    version=receipt['schemaVersion']
    if version not in ROLES:raise ValueError('unsupported_review_observation')
    result={k:None for k in NULL_FIELDS}
    result.update(schemaVersion='sermon-review-observation-v1',receiptType=version,
        receiptCanonicalJsonSha256=contracts.canonical_sha256(receipt),
        candidateId=receipt['candidateId'],revisionId=receipt.get('revisionId',receipt.get('fromRevisionId')),
        targetLocale=receipt['targetLocale'],workUnitIds=receipt.get('workUnitIds',receipt.get('affectedWorkUnitIds')),
        policySha256=receipt['policySha256'],reasonCodes=[],issues=[],checks=[],allowedNextActions=[])
    for key in NULL_FIELDS:
        if key in receipt:result[key]=receipt[key]
    if version=='sermon-candidate-revision-v1':
        # Manifest validation describes a frozen revision, not generation runtime.
        result['fromRevisionId']=receipt['parentRevisionId']
        result['toRevisionId']=receipt['revisionId']
    elif version=='sermon-review-receipt-v1':
        result['receiptContentSha256']=receipt['receiptSha256']
        result['artifactSha256']=receipt['reviewedArtifactSha256']
        result['checks']=[{**{k:check[k] for k in ('checkId','result')},
            'evidenceHashes':sorted({ref['canonicalJsonSha256'] for ref in check['evidenceRefs']})} for check in receipt['checks']]
        result['issues']=[{**{k:issue[k] for k in ('issueId','reasonCode','severity','sourceUnitIds','targetUnitIds')},
            'evidenceHashes':sorted({ref['canonicalJsonSha256'] for ref in issue['evidenceRefs']})} for issue in receipt['issues']]
        result['reasonCodes']=sorted({issue['reasonCode'] for issue in receipt['issues']})
    else:
        result['reasonCodes']=receipt['reasonCodes']
        result['allowedNextActions']=receipt.get('allowedNextActions',[])
    result['missingReasons']={k:'not_applicable' for k in NULL_FIELDS if result[k] is None}
    return result


def validate_observation(row):
    """Semantic checks after the closed schema, including state separation."""
    value=row['rqcEvidence'];version=value['receiptType']
    if row['role']!=ROLES[version] or row['revisionId']!=value['revisionId']:
        raise ValueError('review_observation_identity_conflict')
    if row.get('workUnitId') not in value['workUnitIds']:
        raise ValueError('review_observation_unit_conflict')
    if any(k not in value['missingReasons'] for k in NULL_FIELDS if value[k] is None):
        raise ValueError('review_observation_missing_null_reason')
    if version=='sermon-review-receipt-v1':
        if value['executionStatus'] is None or value['reviewVerdict'] is None or value['admissionStatus'] is not None:
            raise ValueError('review_observation_state_conflict')
        if value['executionStatus']!='succeeded' and value['reviewVerdict']!='not_assessed':
            raise ValueError('review_execution_failure_not_content_failure')
    elif value['executionStatus'] is not None or value['reviewVerdict'] is not None:
        raise ValueError('review_observation_state_conflict')
    if value['reviewVerdict']=='pass':
        coverage=value['coverage']
        if (value['issues'] or coverage is None or coverage['unassessedUnitIds'] or
            set(coverage['expectedUnitIds']) != set(coverage['assessedUnitIds']) or
            {c['checkId'] for c in value['checks']} != contracts.HARD_CHECKS or
            any(c['result']!='pass' or not c['evidenceHashes'] for c in value['checks'])):
            raise ValueError('unsupported_observed_content_pass')
    if (version=='sermon-review-gate-decision-v1') != (value['admissionStatus'] is not None):
        raise ValueError('review_observation_gate_conflict')
    if version=='sermon-review-gate-decision-v1':
        contracts.validate_gate_admission(value['admissionStatus'], value['reasonCodes'], value['allowedNextActions'])


def record(receipt):
    from scripts import sermon_accounting as accounting
    from scripts import sermon_log_profile as profile
    if profile.current() is None:raise ValueError('review_observation_requires_log_profile')
    evidence=project_receipt(receipt)
    # This first rollout freezes one group per revision; no accidental locale summary.
    if len(evidence['workUnitIds'])!=1:raise ValueError('review_observation_requires_unit_scope')
    with profile.context(role=ROLES[evidence['receiptType']],revisionId=evidence['revisionId'],
                         workUnitId=evidence['workUnitIds'][0]):
        return accounting._emit({'event':CODE,'rqcEvidence':evidence})


def observations(events):
    return [{'eventId':e['eventId'],'runId':e['runId'],'workflowId':e['workflowId'],
             'spanId':e.get('spanId'),'attemptId':e.get('attemptId'),'recordedAt':e['recordedAt'],
             'role':e['role'],'workUnitId':e['workUnitId'],'evidenceMode':e['evidenceMode'],
             'evidence':e['rqcEvidence'],'executionAuthority':'none'}
            for e in sorted(events,key=lambda e:(e['recordedAt'],e['eventId'])) if e['event']==CODE]
