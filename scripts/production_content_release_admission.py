"""DEV-PROD-001 content-deploy gate. No network and no deployment.

Code promotion, device playback, and venue acceptance are recorded separately.
None of them authorizes a Production content deploy. Admission requires one
page identity across weekly production, Dev HTTP, a rollback baseline, a human
production authorization, and a pre-deploy verification, each bound by a hash.
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA = 'sermon-production-content-release-admission-v1'
REQUIRED = {
    'weeklyProduction': ('complete', 'packageSha256'),
    'devHttp': ('published_http_verified', 'httpReceiptSha256'),
    'rollbackBaseline': ('captured', 'baselineSha256'),
    'productionAuthorization': ('approved', 'approvalSha256'),
    'preDeployVerification': ('pass', 'candidateSha256'),
}


def _sha256(value):
    return type(value) is str and len(value) == 64 and all(character in '0123456789abcdef' for character in value)


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
    for key, (status, digest_key) in REQUIRED.items():
        value = evidence.get(key)
        page_id = value.get('pageId') if type(value) is dict else None
        if (type(value) is not dict or value.get('status') != status
                or type(page_id) is not str or not page_id or page_id.strip() != page_id
                or any(character.isspace() for character in page_id)
                or not _sha256(value.get(digest_key))):
            missing.append(key)
            continue
        if key == 'productionAuthorization' and value.get('humanApproval') is not True:
            missing.append(key)
            continue
        pages.append(page_id)
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


def load(path):
    """Read one admission file. Invalid JSON stays a closed local error."""
    try:
        evidence = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('content_release_evidence_invalid') from exc
    return admit(evidence)
