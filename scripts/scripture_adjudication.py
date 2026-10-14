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
# Who may sign a receipt, and what kind of adjudication that makes. A machine
# receipt (scripture_machine_adjudication) is machine evidence, never human
# approval; a human receipt for the same bindings overrides it.
ROLES = {'human_reviewer': 'human', 'machine_adjudicator': 'machine'}
# Which signing roles each receipt contract admits. v1 is the human-only contract
# frozen runs carry and keep; v2 adds machine receipts, which the gate admits only by
# reproducing them from the bound inputs. A human receipt is valid under either.
SCHEMA_V2 = 'sermon-scripture-adjudication-v2'
SCHEMA_ROLES = {SCHEMA: frozenset({'human_reviewer'}), SCHEMA_V2: frozenset(ROLES)}


class AdjudicationError(ValueError):
    """A reason code, never free text, so a refusal can be compared and tested."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise AdjudicationError(code)


def receipt_sha256(receipt: dict[str, Any]) -> str:
    return policies.canonical_sha256(receipt)


def _verifier(edition_id: str, library: Any) -> tuple[Any, str]:
    """A loader for the edition's lookup object, and the edition's verification status.

    The status is recorded on every quotation; the file is read only when a
    quotation has to be verified, so a paraphrase-only receipt for a locale
    whose edition file is absent from the checkout still passes the gate."""
    if edition_id == 'CUV':
        return (lambda: library or cuv_scripture.CuvLibrary.from_path()), scripture_editions.VERIFIED
    lazy = scripture_editions.LazyEdition(edition_id)

    def load() -> Any:
        try:
            return lazy.load()
        except scripture_editions.EditionError as exc:
            raise AdjudicationError('edition_unavailable') from exc
    return load, lazy.verification


def generator_signature(version: str, implementation_sha256: str) -> str:
    return f'scripture_machine_adjudication {version} {implementation_sha256[:16]}'


def _reproduce_machine_receipt(receipt: dict[str, Any], *, target_locale: str, flagged_units: list[str],
                               inputs: Any, library: Any, frozen: Any = None) -> dict[str, Any]:
    """A machine receipt is admitted only when the generator reproduces it from the bound inputs.

    The role string and signature prove nothing by themselves: a hand-written
    receipt labelled machine would otherwise pass without the generator's
    evidence, with classifications the generator never emits.

    ``frozen`` is the generator record a fixture manifest stored when this
    receipt was admitted at freeze time (its version and implementation, and
    that it reproduced the receipt then). A frozen run keeps its identity: when
    the current generator is a later one, the receipt it wrote is admitted on
    that frozen evidence instead of being re-run against new behaviour."""
    from scripts import scripture_machine_adjudication as machine  # noqa: E402  (it imports this module)
    current = {'version': machine.VERSION, 'implementationSha256': machine.implementation_sha256()}
    if isinstance(frozen, dict) and frozen.get('reproduced') is True and frozen.get('signatureCurrent') is True:
        _require(isinstance(frozen.get('version'), str) and isinstance(frozen.get('implementationSha256'), str)
                 and receipt['decidedBy'] == generator_signature(frozen['version'], frozen['implementationSha256']),
                 'frozen_generator_mismatch')
        if {key: frozen[key] for key in current} != current:
            return {'reproduced': False, 'frozenAdmission': True, 'generator': 'scripture_machine_adjudication',
                    'version': frozen['version'], 'implementationSha256': frozen['implementationSha256'],
                    'signatureCurrent': False, 'current': current}
    _require(isinstance(inputs, dict) and all(isinstance(inputs.get(name), (dict, list)) for name in BINDING_KEYS),
             'machine_inputs_required')
    try:
        reproduced, basis = machine.adjudicate(inputs['source.json'], inputs['anchor.json'], inputs['group-plan.json'],
                                               target_locale=target_locale, flagged_units=list(flagged_units),
                                               library=library)
    except machine.MachineAdjudicationError as exc:
        raise AdjudicationError('machine_receipt_not_reproduced') from exc
    compared = ('targetLocale', 'bindings', 'decision', 'candidates')
    _require({key: receipt[key] for key in compared} == {key: reproduced[key] for key in compared},
             'machine_receipt_not_reproduced')
    return {'reproduced': True, 'generator': 'scripture_machine_adjudication', 'version': basis['version'],
            'implementationSha256': basis['implementationSha256'],
            'signatureCurrent': receipt['decidedBy'] == reproduced['decidedBy']}


def validate_receipt(receipt: Any, *, target_locale: str, bindings: dict[str, str],
                     flagged_units: list[str], library: cuv_scripture.CuvLibrary | None = None,
                     machine_inputs: dict[str, Any] | None = None,
                     frozen_generator: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a summary of an approved receipt, or raise AdjudicationError with a reason code.

    ``machine_inputs`` holds the bound ``source.json``, ``anchor.json`` and
    ``group-plan.json``; a machine receipt is admitted only when the generator
    reproduces it from them, or, under ``frozen_generator`` (the record a
    fixture stored when it admitted the receipt), when a later generator would
    otherwise re-run a frozen run."""
    _require(target_locale in PINNED_EDITIONS, 'no_pinned_edition_for_locale')
    edition_id = PINNED_EDITIONS[target_locale]
    load_verifier, edition_verification = _verifier(edition_id, library)
    verifier = None
    _require(isinstance(receipt, dict) and set(receipt) == TOP_KEYS, 'receipt_schema')
    _require(receipt['schemaVersion'] in SCHEMA_ROLES, 'receipt_schema_version')
    _require(receipt['targetLocale'] == target_locale, 'receipt_locale')
    _require(isinstance(receipt['bindings'], dict) and {k: receipt['bindings'].get(k) for k in BINDING_KEYS}
             == {k: bindings.get(k) for k in BINDING_KEYS}, 'receipt_binding_changed')
    _require(receipt['decision'] == 'approved', 'decision_not_approved')
    _require(receipt['decidedByRole'] in ROLES, 'decided_by_role_invalid')
    _require(receipt['decidedByRole'] in SCHEMA_ROLES[receipt['schemaVersion']], 'machine_receipt_requires_v2')
    _require(isinstance(receipt['decidedBy'], str) and receipt['decidedBy'].strip(), 'decided_by_missing')
    kind = ROLES[receipt['decidedByRole']]
    generator = None
    if kind == 'machine':
        generator = _reproduce_machine_receipt(receipt, target_locale=target_locale, flagged_units=flagged_units,
                                               inputs=machine_inputs, library=library, frozen=frozen_generator)
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
            verifier = verifier or load_verifier()  # the edition file is read only once a quotation needs it
            try:
                reference = cuv_scripture.parse_reference(row['reference'])
                partial = row['classification'] == 'partial_direct_quote'
                found = verifier.verify_text(reference, row['exactSentence'], excerpt=partial)
            except (cuv_scripture.CuvError, scripture_editions.EditionError) as exc:
                raise AdjudicationError('exact_sentence_mismatch') from exc
            quotes.append({'candidateId': row['candidateId'], 'sourceUnitIds': list(units),
                           'classification': row['classification'], 'canonicalRef': found['canonicalRef'],
                           'editionId': edition_id, 'editionVerification': edition_verification,
                           'exactSentence': row['exactSentence'], 'textSha256': found['textSha256']})
        else:
            _require(row['editionId'] is None and row['exactSentence'] is None, 'non_quote_has_edition')
    _require(len(covered) == len(set(covered)), 'unit_covered_twice')
    _require(set(covered) == set(flagged_units), 'coverage_mismatch')
    quoted = {unit for row in quotes for unit in row['sourceUnitIds']}
    return {'schemaVersion': SCHEMA, 'receiptSchemaVersion': receipt['schemaVersion'],
            'receiptSha256': receipt_sha256(receipt), 'targetLocale': target_locale,
            'decidedByRole': receipt['decidedByRole'], 'adjudicationKind': kind,
            'humanApproval': kind == 'human', 'generator': generator,
            'coveredUnits': sorted(covered), 'quotes': quotes, 'admitted': quotes,
            # Flagged units the receipt settles as the speaker's own words (paraphrase or reference only):
            # translated as spoken, with no pinned sentence.
            'speakerWordsUnits': sorted(unit for unit in covered if unit not in quoted)}


def require_admitted(manifest: dict[str, Any], directory: Path, *, target_locale: str,
                     bindings: dict[str, str], flagged_units: list[str]) -> dict[str, Any]:
    """Admit the receipt named by the fixture manifest, or refuse before any paid request."""
    entry = manifest.get('scriptureAdjudication')
    _require(isinstance(entry, dict) and {'path', 'sha256'} <= set(entry) <= {'path', 'sha256', 'generator'},
             'scripture_adjudication_required')
    directory = Path(directory).resolve()
    path = (directory / entry['path']).resolve()
    _require(path.is_relative_to(directory) and path.is_file(), 'receipt_file_missing')
    _require(hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256'], 'receipt_file_changed')
    receipt = json.loads(path.read_text(encoding='utf-8'))
    inputs = None
    if isinstance(receipt, dict) and ROLES.get(receipt.get('decidedByRole')) == 'machine':
        # The frozen inputs the receipt is bound to; the generator must reproduce it from them.
        files = [(directory / name).resolve() for name in BINDING_KEYS]
        _require(all(f.is_relative_to(directory) and f.is_file() for f in files), 'machine_inputs_required')
        inputs = {name: json.loads(f.read_text(encoding='utf-8')) for name, f in zip(BINDING_KEYS, files)}
    return validate_receipt(receipt, target_locale=target_locale, bindings=bindings, flagged_units=flagged_units,
                            machine_inputs=inputs, frozen_generator=entry.get('generator'))
