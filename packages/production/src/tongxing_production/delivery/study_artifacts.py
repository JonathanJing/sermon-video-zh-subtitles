"""Produce and ingest independently reviewed outline/meditation artifacts.

Text is supplied by the configured producer. This module freezes it against the
approved text and source; it never fabricates model output or human approval.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
try:
    from scripts.delivery_contract import sha, require
except ImportError:
    from delivery_contract import sha, require

ROOT = Path(__file__).resolve().parents[1]


def validate(value, schema):
    Draft202012Validator(json.loads((ROOT / 'schemas' / schema).read_text()), format_checker=FormatChecker()).validate(value)


def produce(kind, text, *, page_id, locale, source_sha, text_sha, producer_identity):
    result = {'schemaVersion': 'sermon-study-artifact-v1', 'kind': kind,
              'pageId': page_id, 'locale': locale, 'sourcePackageSha256': source_sha,
              'textCandidateSha256': text_sha, 'producerIdentity': producer_identity,
              'sections': text}
    validate(result, 'sermon-study-artifact-v1.schema.json')
    return result


def ingest_review(artifact, review):
    validate(artifact, 'sermon-study-artifact-v1.schema.json')
    validate(review, 'sermon-study-review-v1.schema.json')
    require(review['artifactSha256'] == sha(artifact), 'Study review does not bind artifact')
    require(all(review[key] == artifact[key] for key in ('kind', 'pageId', 'locale', 'sourcePackageSha256', 'textCandidateSha256')), 'Study review identity differs')
    require(review['decision'] == 'approved', 'Study artifact not approved')
    require(all(v == 'pass' for v in review['checks'].values()), 'Study review checks failed')
    return {'status': 'human_reviewed', 'artifactSha256': sha(artifact), 'reviewSha256': sha(review)}


def join_artifacts(*, source_sha, text_sha, audio_sha, outline=None, outline_review=None, meditation=None, meditation_review=None):
    """Four App products: approved text/audio and independently approved study artifacts.

    Inputs are hashes of validated upstream packages supplied by the caller;
    PDFs are deliberately absent from this App candidate identity.
    """
    require(all(isinstance(v, str) and re.fullmatch(r'[a-f0-9]{64}', v) for v in (source_sha, text_sha, audio_sha)), 'Validated upstream identities required')
    products = {'text': text_sha, 'audio': audio_sha}
    missing = []
    for kind, artifact, review in [('outline', outline, outline_review), ('meditation', meditation, meditation_review)]:
        if artifact is None or review is None:
            missing.append(kind)
            continue
        require(artifact['kind'] == kind and artifact['sourcePackageSha256'] == source_sha and artifact['textCandidateSha256'] == text_sha, 'Study source/text mismatch')
        products[kind] = ingest_review(artifact, review)
    return {'schemaVersion': 'sermon-app-product-join-v1', 'status': 'partial' if missing else 'complete',
            'sourcePackageSha256': source_sha, 'products': products, 'missing': missing,
            'candidateSha256': sha({'source': source_sha, 'products': products}) if not missing else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['produce', 'review'])
    parser.add_argument('--input', type=Path, required=True, help='Producer kwargs JSON or artifact JSON')
    parser.add_argument('--review', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    value = json.loads(args.input.read_text())
    result = produce(**value) if args.command == 'produce' else ingest_review(value, json.loads(args.review.read_text()))
    with args.out.open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


if __name__ == '__main__':
    main()
