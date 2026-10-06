"""Local Production admission, bound to verified receipts and Hosting candidate.

V2 requires receiptPath/receiptSha256 for every stage and current candidate
binding. V1 digest-only evidence must be regenerated; it cannot authorize deploy.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA = 'sermon-production-content-release-admission-v2'
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


def admit(evidence, *, candidate_sha256=None, preflight_sha256=None, evidence_dir=None):
    """Hash receipt bytes and check contents against the prepared deployment."""
    if type(evidence) is not dict:
        raise ValueError('content_release_evidence_invalid')
    if not _sha256(candidate_sha256) or not _sha256(preflight_sha256):
        return _blocked(['current_candidate_binding'])
    missing = []
    pages = []
    for key, (status, digest_key) in REQUIRED.items():
        value = evidence.get(key)
        page_id = value.get('pageId') if type(value) is dict else None
        if (type(value) is not dict or value.get('status') != status
                or type(page_id) is not str or not page_id or page_id.strip() != page_id
                or any(character.isspace() for character in page_id)
                or not _sha256(value.get(digest_key))
                or not _sha256(value.get('receiptSha256'))
                or type(value.get('receiptPath')) is not str or not value['receiptPath']):
            missing.append(key)
            continue
        try:
            path = Path(value['receiptPath'])
            if not path.is_absolute():
                if evidence_dir is None:
                    raise ValueError('relative_receipt_requires_evidence_dir')
                path = Path(evidence_dir) / path
            raw = path.read_bytes()
            receipt = json.loads(raw)
            digest = hashlib.sha256(raw).hexdigest()
            if type(receipt) is not dict:
                raise ValueError('receipt_object_required')
        except (OSError, UnicodeError, ValueError):
            missing.append(key)
            continue
        binding = receipt.get('buildReportSha256') if key == 'preDeployVerification' else receipt.get('candidateSha256')
        if (digest != value['receiptSha256'] or receipt.get('status') != status
                or receipt.get('pageId') != page_id or binding != candidate_sha256
                or (key != 'preDeployVerification' and value[digest_key] != digest)
                or (key == 'preDeployVerification' and
                    (value[digest_key] != candidate_sha256 or digest != preflight_sha256))
                or (key == 'productionAuthorization' and
                    (value.get('humanApproval') is not True or receipt.get('humanApproval') is not True))):
            missing.append(key)
            continue
        pages.append(page_id)
    if missing:
        return _blocked(missing)
    page_id = pages[0]
    if any(page != page_id for page in pages):
        return _blocked(['page_id_mismatch'])
    return {'schemaVersion': SCHEMA, 'decision': 'admitted', 'contentDeploy': False,
            'pageId': page_id, 'candidateSha256': candidate_sha256, 'missing': [],
            'codePromotionAuthorizesContent': False,
            'deviceOrVenueAuthorizesContent': False, 'deployPerformed': False}


def load(path, *, candidate_sha256=None, preflight_sha256=None):
    """Resolve relative receipt paths from the evidence file, never the cwd."""
    try:
        evidence = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('content_release_evidence_invalid') from exc
    return admit(evidence, candidate_sha256=candidate_sha256,
                 preflight_sha256=preflight_sha256, evidence_dir=Path(path).parent)
