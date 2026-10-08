"""Diagnostic review for quotations admitted by a human adjudication receipt.

A frozen module carries the admitted quotations as literals and delegates here.
This helper reuses every non-scripture structural check, drops the reference-only
check (it cannot pass for an admitted direct quotation), and adds an exact-quote
check: the translated group must contain each admitted CUV sentence verbatim.

It is diagnostic only. It never approves a quotation, a translation or a
candidate. The admitted quotations come from a human-written receipt that the
adjudication gate has already validated.
"""
from __future__ import annotations

from scripts.language_review_plugins import diagnostic_structural as structural
from scripts.language_review_plugins.common import result

DIAGNOSTIC_ONLY = True
PLUGIN_ID = 'diagnostic-admitted-quotes-v1'
PLUGIN_VERSION = '2026-10-08-v1'
EXACT_CHECK = 'scripture_exact_quotes'
REQUIRED = [name for name in structural.REQUIRED if name != 'scripture_reference_only'] + [EXACT_CHECK]
QUOTE_CLASSES = {'direct_quote', 'partial_direct_quote'}


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def validate_admitted(admitted):
    """Shape check only; the receipt itself was validated before freezing."""
    _require(type(admitted) is list and admitted, 'admitted_quotes_missing')
    seen = set()
    for row in admitted:
        _require(type(row) is dict and set(row) == {'candidateId', 'sourceUnitIds', 'classification',
            'canonicalRef', 'exactSentence', 'textSha256'}, 'admitted_quote_schema')
        _require(row['classification'] in QUOTE_CLASSES and type(row['exactSentence']) is str
                 and row['exactSentence'] and type(row['sourceUnitIds']) is list and row['sourceUnitIds'],
                 'admitted_quote_invalid')
        _require(not seen.intersection(row['sourceUnitIds']), 'admitted_unit_repeated')
        seen.update(row['sourceUnitIds'])
    return sorted(seen)


def _exact_result(english_ids, target, admitted):
    relevant = [row for row in admitted if set(row['sourceUnitIds']) & set(english_ids)]
    if not relevant:
        return result(EXACT_CHECK, True, 'No admitted direct or partial quotation in this group.')
    split = [row['candidateId'] for row in relevant if not set(row['sourceUnitIds']) <= set(english_ids)]
    if split:
        return result(EXACT_CHECK, False, 'Admitted quotation is split across groups: ' + ','.join(split))
    missing = [row['candidateId'] for row in relevant if row['exactSentence'] not in target]
    if missing:
        return result(EXACT_CHECK, False,
            'Admitted CUV sentence absent verbatim from target: ' + ','.join(missing))
    return result(EXACT_CHECK, True,
        'Every admitted CUV sentence appears verbatim in the target. Diagnostic check only; '
        'no translation or edition approval.')


def review_group(policy, english_units, group, *, diagnostic_context, admitted_quotes):
    """Structural results for this group, with the exact-quote check replacing reference-only."""
    validate_admitted(admitted_quotes)
    _require(type(policy) is dict and policy.get('languageReview', {}).get('pluginId') == PLUGIN_ID
             and policy['languageReview'].get('requiredChecks') == REQUIRED, 'admitted_plugin_policy_mismatch')
    scripture = policy.get('scripture', {})
    _require(scripture.get('editionId') == 'CUV' and scripture.get('quoteCheckPolicy') == 'source_bound_exact_quote'
             and scripture.get('citationUseStatus') == 'project_source_reviewed', 'admitted_plugin_scripture_mismatch')
    # Run the real structural checks under their own identity, then substitute the scripture check.
    structural_policy = dict(policy)
    structural_policy['languageReview'] = dict(policy['languageReview'], pluginId=structural.PLUGIN_ID,
                                               requiredChecks=structural.REQUIRED)
    base = structural.review_group(structural_policy, english_units, group, diagnostic_context=diagnostic_context)
    checks = [row for row in base if row['checkId'] != 'scripture_reference_only']
    target = group.get('targetText') if type(group.get('targetText')) is str else ''
    checks.append(_exact_result([unit['sourceUnitId'] for unit in english_units], target, admitted_quotes))
    _require([row['checkId'] for row in checks] == REQUIRED, 'admitted_plugin_check_order_changed')
    return checks


def freeze_admitted_plugin(summary, source, anchor, plan, policy, out_plugin):
    """Write a new generated plugin with admitted quotations as literals; return the updated policy.

    summary is the validated receipt summary from scripture_adjudication. The
    policy gains the CUV exact-quote scripture block only for this plugin.
    """
    import copy
    import os
    from pathlib import Path
    from scripts import produce_target_language_candidate as producer
    from scripts import target_language_policy as policies
    admitted = summary['admitted']
    validate_admitted(admitted)
    policy = copy.deepcopy(policy)
    policy['scripture'].update(editionId='CUV', citationUseStatus='project_source_reviewed',
                               quoteCheckPolicy='source_bound_exact_quote')
    policy['languageReview'].update(pluginId=PLUGIN_ID, requiredChecks=copy.deepcopy(REQUIRED),
                                    implementationStatus='verified')
    for component in ('scripture', 'languageReview'):
        policy['componentSha256'][component] = policies.canonical_sha256(policy[component])
    path = Path(out_plugin)
    _require(not path.exists(), 'requires new frozen plugin path')
    path.parent.mkdir(parents=True, exist_ok=True)
    text = ("# Generated diagnostic plugin: admitted quotations are frozen literals. Do not edit.\n"
        "from scripts.language_review_plugins import diagnostic_admitted_quotes as helper\n"
        f"DIAGNOSTIC_ONLY = True\nDIAGNOSTIC_ADMITTED_QUOTES = True\n"
        f"PLUGIN_ID = {PLUGIN_ID!r}\nPLUGIN_VERSION = {PLUGIN_VERSION!r}\nREQUIRED = {REQUIRED!r}\n"
        f"ADMITTED_RECEIPT_SHA256 = {summary['receiptSha256']!r}\n"
        f"ADMITTED_QUOTES = {admitted!r}\n"
        "def review_group(policy, english_units, group, *, diagnostic_context):\n"
        "    return helper.review_group(policy, english_units, group, diagnostic_context=diagnostic_context,\n"
        "                               admitted_quotes=ADMITTED_QUOTES)\n")
    with path.open('x', encoding='utf-8') as handle:
        os.chmod(path, 0o600)
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    policy['languageReview']['pluginImplementationSha256'] = producer.plugin_implementation_sha256(path)
    policy['componentSha256']['languageReview'] = policies.canonical_sha256(policy['languageReview'])
    return policy
