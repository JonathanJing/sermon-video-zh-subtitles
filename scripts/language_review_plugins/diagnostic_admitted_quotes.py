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
    _require(type(admitted) is list, 'admitted_quotes_missing')
    seen = set()
    for row in admitted:
        _require(type(row) is dict and set(row) == {'candidateId', 'sourceUnitIds', 'classification',
            'canonicalRef', 'editionId', 'editionVerification', 'exactSentence', 'textSha256'}, 'admitted_quote_schema')
        _require(row['classification'] in QUOTE_CLASSES and type(row['exactSentence']) is str
                 and row['exactSentence'] and type(row['sourceUnitIds']) is list and row['sourceUnitIds'],
                 'admitted_quote_invalid')
        _require(not seen.intersection(row['sourceUnitIds']), 'admitted_unit_repeated')
        seen.update(row['sourceUnitIds'])
    return sorted(seen)


def validate_speaker_words(units, admitted_units):
    """Units the receipt settled as the speaker's words: distinct, and never also an admitted quotation."""
    _require(type(units) is list and all(type(u) is str and u for u in units) and len(set(units)) == len(units)
             and not set(units) & set(admitted_units), 'speaker_words_units_invalid')
    return list(units)


def _exact_result(english_ids, target, admitted, speaker_words=()):
    spoken = [unit for unit in speaker_words if unit in english_ids]
    note = (' Units adjudicated as the speaker\'s words, translated as spoken with no pinned sentence: '
            + ','.join(spoken) + '.') if spoken else ''
    relevant = [row for row in admitted if set(row['sourceUnitIds']) & set(english_ids)]
    if not relevant:
        return result(EXACT_CHECK, True, 'No admitted direct or partial quotation in this group.' + note)
    split = [row['candidateId'] for row in relevant if not set(row['sourceUnitIds']) <= set(english_ids)]
    if split:
        return result(EXACT_CHECK, False, 'Admitted quotation is split across groups: ' + ','.join(split))
    missing = [row['candidateId'] for row in relevant if row['exactSentence'] not in target]
    if missing:
        return result(EXACT_CHECK, False,
            'Admitted CUV sentence absent verbatim from target: ' + ','.join(missing))
    return result(EXACT_CHECK, True,
        'Every admitted CUV sentence appears verbatim in the target. Diagnostic check only; '
        'no translation or edition approval.' + note)


def review_group(policy, english_units, group, *, diagnostic_context, admitted_quotes, speaker_words_units=()):
    """Structural results for this group, with the exact-quote check replacing reference-only.

    ``speaker_words_units`` are flagged units the receipt settled as the
    speaker's own words: they take the ordinary translation path and the
    exact-quote check only records them."""
    admitted_units = validate_admitted(admitted_quotes)
    speaker_words = validate_speaker_words(list(speaker_words_units), admitted_units)
    _require(admitted_quotes or speaker_words, 'admitted_quotes_missing')
    _require(type(policy) is dict and policy.get('languageReview', {}).get('pluginId') == PLUGIN_ID
             and policy['languageReview'].get('requiredChecks') == REQUIRED, 'admitted_plugin_policy_mismatch')
    scripture = policy.get('scripture', {})
    edition = scripture.get('editionId')
    _require(type(edition) is str and edition and all(row['editionId'] == edition for row in admitted_quotes)
             and scripture.get('quoteCheckPolicy') == 'source_bound_exact_quote'
             and scripture.get('citationUseStatus') == 'project_source_reviewed', 'admitted_plugin_scripture_mismatch')
    # Run the real structural checks under their own identity, then substitute the scripture check.
    structural_policy = dict(policy)
    structural_policy['languageReview'] = dict(policy['languageReview'], pluginId=structural.PLUGIN_ID,
                                               requiredChecks=structural.REQUIRED)
    base = structural.review_group(structural_policy, english_units, group, diagnostic_context=diagnostic_context)
    checks = [row for row in base if row['checkId'] != 'scripture_reference_only']
    target = group.get('targetText') if type(group.get('targetText')) is str else ''
    checks.append(_exact_result([unit['sourceUnitId'] for unit in english_units], target, admitted_quotes,
                                speaker_words))
    _require([row['checkId'] for row in checks] == REQUIRED, 'admitted_plugin_check_order_changed')
    return checks


def freeze_admitted_plugin(summary, source, anchor, plan, policy, out_plugin):
    """Write a new generated plugin with admitted quotations as literals; return the updated policy.

    summary is the validated receipt summary from scripture_adjudication. The
    policy gains the exact-quote scripture block of the locale's pinned edition
    only for this plugin. Flagged units the receipt settled as the speaker's
    words are frozen beside the quotations, so a receipt with no admitted
    quotation at all still routes every flagged unit through plain translation.
    """
    import copy
    import os
    from pathlib import Path
    from scripts import produce_target_language_candidate as producer
    from scripts import scripture_adjudication as adjudication
    from scripts import target_language_policy as policies
    admitted = summary['admitted']
    speaker_words = validate_speaker_words(list(summary.get('speakerWordsUnits') or []), validate_admitted(admitted))
    _require(admitted or speaker_words, 'admitted_quotes_missing')
    policy = copy.deepcopy(policy)
    editions = {row['editionId'] for row in admitted}
    _require(len(editions) <= 1, 'admitted_quotes_mix_editions')
    _require(policy.get('targetLocale') in adjudication.PINNED_EDITIONS, 'admitted_plugin_locale_unpinned')
    edition = editions.pop() if editions else adjudication.PINNED_EDITIONS[policy['targetLocale']]
    policy['scripture'].update(editionId=edition, citationUseStatus='project_source_reviewed',
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
        f"SPEAKER_WORDS_UNITS = {speaker_words!r}\n"
        "def review_group(policy, english_units, group, *, diagnostic_context):\n"
        "    return helper.review_group(policy, english_units, group, diagnostic_context=diagnostic_context,\n"
        "                               admitted_quotes=ADMITTED_QUOTES, speaker_words_units=SPEAKER_WORDS_UNITS)\n")
    with path.open('x', encoding='utf-8') as handle:
        os.chmod(path, 0o600)
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    policy['languageReview']['pluginImplementationSha256'] = producer.plugin_implementation_sha256(path)
    policy['componentSha256']['languageReview'] = policies.canonical_sha256(policy['languageReview'])
    return policy
