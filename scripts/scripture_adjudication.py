"""Human scripture adjudication receipts: validation only, never approval by code.

A receipt is written by a human reviewer after looking at each flagged source
unit. This module checks the receipt's schema, its bindings to the frozen
source, anchor and group plan, that it covers exactly the flagged units, and
that every direct or partial quotation is an exact substring of the pinned
edition. It never creates, edits or upgrades a receipt. A pending, rejected,
machine-written or unbound decision is refused before any paid request.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts import cuv_scripture
from scripts import scripture_editions
from scripts import target_language_policy as policies

SCHEMA = 'sermon-scripture-adjudication-v1'
# Only locales with a pinned, hash-verified edition may admit a direct quotation.
# Policy edition ids. CUV is verified against its source archive; NKRV-1998 and
# RVR60-1960 are admitted only when their pinned source is publisher-verified.
PINNED_EDITIONS = {'zh-Hans': 'CUV', 'ko': 'NKRV-1998', 'es': 'RVR60-1960'}
CLASSIFICATIONS = {'direct_quote', 'partial_direct_quote', 'speaker_paraphrase', 'reference_only'}
QUOTE_CLASSES = {'direct_quote', 'partial_direct_quote'}
TOP_KEYS = {'schemaVersion', 'targetLocale', 'bindings', 'decision', 'decidedBy', 'decidedByRole',
            'reviewedAt', 'candidates'}
CANDIDATE_KEYS = {'candidateId', 'sourceUnitIds', 'classification', 'reference', 'editionId', 'exactSentence'}
BINDING_KEYS = ('source.json', 'anchor.json', 'group-plan.json')


class AdjudicationError(ValueError):
    """A reason code, never free text, so a refusal can be compared and tested."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise AdjudicationError(code)


def receipt_sha256(receipt: dict[str, Any]) -> str:
    return policies.canonical_sha256(receipt)


def _verifier(edition_id: str, library: Any) -> Any:
    """The lookup object for an edition, or a refusal when its source is not verified."""
    if edition_id == 'CUV':
        return library or cuv_scripture.CuvLibrary.from_path()
    try:
        edition = scripture_editions.load(edition_id)
    except scripture_editions.EditionError as exc:
        raise AdjudicationError('edition_unavailable') from exc
    _require(edition.verification == scripture_editions.VERIFIED, 'edition_not_verified')
    return edition


def validate_receipt(receipt: Any, *, target_locale: str, bindings: dict[str, str],
                     flagged_units: list[str], library: cuv_scripture.CuvLibrary | None = None) -> dict[str, Any]:
    """Return a summary of an approved receipt, or raise AdjudicationError with a reason code."""
    _require(target_locale in PINNED_EDITIONS, 'no_pinned_edition_for_locale')
    edition_id = PINNED_EDITIONS[target_locale]
    verifier = _verifier(edition_id, library)
    _require(isinstance(receipt, dict) and set(receipt) == TOP_KEYS, 'receipt_schema')
    _require(receipt['schemaVersion'] == SCHEMA, 'receipt_schema_version')
    _require(receipt['targetLocale'] == target_locale, 'receipt_locale')
    _require(isinstance(receipt['bindings'], dict) and {k: receipt['bindings'].get(k) for k in BINDING_KEYS}
             == {k: bindings.get(k) for k in BINDING_KEYS}, 'receipt_binding_changed')
    _require(receipt['decision'] == 'approved', 'decision_not_approved')
    _require(receipt['decidedByRole'] == 'human_reviewer', 'decided_by_not_human')
    _require(isinstance(receipt['decidedBy'], str) and receipt['decidedBy'].strip(), 'decided_by_missing')
    try:
        datetime.fromisoformat(receipt['reviewedAt'])
    except (TypeError, ValueError) as exc:
        raise AdjudicationError('reviewed_at_invalid') from exc
    candidates = receipt['candidates']
    _require(isinstance(candidates, list) and candidates, 'candidates_missing')
    _require(len({row.get('candidateId') for row in candidates if isinstance(row, dict)}) == len(candidates),
             'candidate_id_repeated')
    covered: list[str] = []
    quotes: list[dict[str, Any]] = []
    for row in candidates:
        _require(isinstance(row, dict) and set(row) == CANDIDATE_KEYS, 'candidate_schema')
        _require(row['classification'] in CLASSIFICATIONS, 'classification_invalid')
        units = row['sourceUnitIds']
        _require(isinstance(units, list) and units and len(set(units)) == len(units)
                 and all(isinstance(unit, str) and unit for unit in units), 'candidate_units_invalid')
        covered.extend(units)
        if row['classification'] in QUOTE_CLASSES:
            _require(row['editionId'] == edition_id, 'edition_mismatch')
            _require(isinstance(row['reference'], str) and row['reference'].strip(), 'reference_missing')
            _require(isinstance(row['exactSentence'], str) and row['exactSentence'], 'exact_sentence_missing')
            try:
                reference = cuv_scripture.parse_reference(row['reference'])
                partial = row['classification'] == 'partial_direct_quote'
                found = verifier.verify_text(reference, row['exactSentence'], excerpt=partial)
            except (cuv_scripture.CuvError, scripture_editions.EditionError) as exc:
                raise AdjudicationError('exact_sentence_mismatch') from exc
            quotes.append({'candidateId': row['candidateId'], 'sourceUnitIds': list(units),
                           'classification': row['classification'], 'canonicalRef': found['canonicalRef'],
                           'editionId': edition_id, 'exactSentence': row['exactSentence'],
                           'textSha256': found['textSha256']})
        else:
            _require(row['editionId'] is None and row['exactSentence'] is None, 'non_quote_has_edition')
    _require(len(covered) == len(set(covered)), 'unit_covered_twice')
    _require(set(covered) == set(flagged_units), 'coverage_mismatch')
    return {'schemaVersion': SCHEMA, 'receiptSha256': receipt_sha256(receipt), 'targetLocale': target_locale,
            'coveredUnits': sorted(covered), 'quotes': quotes, 'admitted': quotes}


def require_admitted(manifest: dict[str, Any], directory: Path, *, target_locale: str,
                     bindings: dict[str, str], flagged_units: list[str]) -> dict[str, Any]:
    """Admit the receipt named by the fixture manifest, or refuse before any paid request."""
    entry = manifest.get('scriptureAdjudication')
    _require(isinstance(entry, dict) and set(entry) == {'path', 'sha256'}, 'scripture_adjudication_required')
    directory = Path(directory).resolve()
    path = (directory / entry['path']).resolve()
    _require(path.is_relative_to(directory) and path.is_file(), 'receipt_file_missing')
    _require(hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256'], 'receipt_file_changed')
    receipt = json.loads(path.read_text(encoding='utf-8'))
    return validate_receipt(receipt, target_locale=target_locale, bindings=bindings, flagged_units=flagged_units)
