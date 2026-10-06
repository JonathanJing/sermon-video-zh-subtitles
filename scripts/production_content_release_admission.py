"""DEV-PROD-001 content-deploy gate. No network and no deployment.

Code promotion, device playback, and venue acceptance are recorded separately.
None of them authorizes a Production content deploy. Admission requires one
page identity across weekly production, Dev HTTP, a rollback baseline, a human
production authorization, and a pre-deploy verification.
"""
from __future__ import annotations

SCHEMA = 'sermon-production-content-release-admission-v1'
REQUIRED = {
    'weeklyProduction': 'complete',
    'devHttp': 'published_http_verified',
    'rollbackBaseline': 'captured',
    'productionAuthorization': 'approved',
    'preDeployVerification': 'pass',
}


def _blocked(missing, page_id=None):
    return {'schemaVersion': SCHEMA, 'decision': 'blocked', 'contentDeploy': False,
            'pageId': page_id, 'missing': missing,
            'codePromotionAuthorizesContent': False,
            'deviceOrVenueAuthorizesContent': False}


def admit(evidence):
    """Return a closed decision. This function never deploys."""
    if type(evidence) is not dict:
        raise ValueError('content_release_evidence_invalid')
    missing = []
    pages = []
    for key, status in REQUIRED.items():
        value = evidence.get(key)
        if (type(value) is not dict or value.get('status') != status
                or type(value.get('pageId')) is not str or not value['pageId']):
            missing.append(key)
            continue
        if key == 'productionAuthorization' and value.get('humanApproval') is not True:
            missing.append(key)
            continue
        pages.append(value['pageId'])
    if missing:
        return _blocked(missing)
    page_id = pages[0]
    if any(page != page_id for page in pages):
        return _blocked(['page_id_mismatch'])
    return {'schemaVersion': SCHEMA, 'decision': 'admitted', 'contentDeploy': False,
            'pageId': page_id, 'missing': [],
            'codePromotionAuthorizesContent': False,
            'deviceOrVenueAuthorizesContent': False,
            'deployPerformed': False}
