"""Diagnostic-only deterministic surfaces, never simulated machine approval.

Only explicit simulated HUMAN gates permit pending terminology review here;
policy and source review fields stay unchanged. This plugin measures target
script presence, declared term surfaces, explicit Arabic numeral preservation,
and bounded plain-text utterance structure. It does not assess translation
meaning, exact Bible wording, native fluency, audio quality or human acceptance.
The actual independent strict reviewer and every machine gate remain mandatory.

This narrow reference-only/no-edition plugin is unsuitable for direct scripture
quotations. It requires the explicit diagnostic context and source/anchor/group
bindings. Ordinary production callers must reject DIAGNOSTIC_ONLY modules.
"""
from __future__ import annotations

from collections import Counter
import re
import unicodedata

try:
    from scripts import sermon_diagnostic_context as diagnostic
    from scripts.language_review_plugins.common import result
except ImportError:
    import sermon_diagnostic_context as diagnostic
    from language_review_plugins.common import result

DIAGNOSTIC_ONLY = True
PLUGIN_ID = 'diagnostic-structural-v1'
PLUGIN_VERSION = '2026-10-01-v1'
REQUIRED = ['target_script', 'term_surface_preservation', 'number_surface_preservation',
            'utterance_structure', 'scripture_reference_only']
LOCALES = ('zh-Hans', 'ko', 'es')
MAX_UTTERANCES = 64
MAX_UTTERANCE_CHARS = 4096
MAX_GROUP_CHARS = 16384


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _label(value):
    return type(value) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', value) is not None


def _unsafe(text):
    return (any(character in '<>[]{}' for character in text) or '`' in text or
            bool(re.search(r'&(?:lt|gt|#0*60|#0*62|#x0*3c|#x0*3e);', text, re.I)) or
            any(unicodedata.category(character).startswith('C') for character in text))


def _contains(surface, text, *, latin_boundary):
    surface = unicodedata.normalize('NFC', surface).casefold()
    text = unicodedata.normalize('NFC', text).casefold()
    if not latin_boundary:
        return surface in text
    prefix = r'(?<!\w)' if surface[0].isalnum() else ''
    suffix = r'(?!\w)' if surface[-1].isalnum() else ''
    return re.search(prefix + re.escape(surface) + suffix, text) is not None


def _script(text, locale):
    letters = [unicodedata.name(character, '') for character in text if character.isalpha()]
    han = any(name.startswith(('CJK UNIFIED IDEOGRAPH', 'CJK COMPATIBILITY IDEOGRAPH')) for name in letters)
    hangul = any(name.startswith('HANGUL') for name in letters)
    latin = any(name.startswith('LATIN') for name in letters)
    if locale == 'zh-Hans':
        return han and not hangul
    if locale == 'ko':
        return hangul  # Hanja/proper-name Latin may occur; this is presence only.
    return latin and all(name.startswith('LATIN') for name in letters)


def _term_check(policy, english, target, locale):
    terminology = policy.get('terminology')
    if type(terminology) is not dict:
        return False, 0, 0
    pending, missing = 0, 0
    for kind in ('seriesNames', 'properNames'):
        terms = terminology.get(kind)
        if type(terms) is not list or len(terms) > 256:
            return False, pending, missing
        for term in terms:
            if (type(term) is not dict or set(term) != {'source', 'target', 'reviewStatus'} or
                type(term['source']) is not str or not term['source'].strip() or len(term['source']) > 4096 or
                type(term['target']) is not str or not term['target'].strip() or len(term['target']) > 4096 or
                term['reviewStatus'] not in ('pending', 'project_established', 'human_reviewed') or
                _unsafe(term['source']) or _unsafe(term['target'])):
                return False, pending, missing
            pending += term['reviewStatus'] == 'pending'
            if _contains(term['source'], english, latin_boundary=True) and not _contains(
                    term['target'], target, latin_boundary=locale == 'es'):
                missing += 1
    return missing == 0, pending, missing


def _reference_only(policy, english, target):
    scripture = policy.get('scripture')
    if (type(scripture) is not dict or set(scripture) !=
        {'editionId', 'citationUseStatus', 'quoteCheckPolicy', 'referenceStyle'} or
        scripture['editionId'] is not None or scripture['quoteCheckPolicy'] != 'references_only' or
        scripture['citationUseStatus'] not in ('pending', 'project_source_reviewed') or
        type(scripture['referenceStyle']) is not str or not scripture['referenceStyle'].strip()):
        return False
    # This detects only explicit surface claims, not every possible quotation.
    # No field in the accepted policy can approve a direct/edition quotation.
    edition_claim = r'\b(?:CUV|KJV|NKJV|ESV|NIV|RVR\s*1960|RVR60)\b|和合本|新译本|개역개정|Reina[ -]Valera'
    quote_claim = r'\b(?:Bible|Scripture|verse)\s+(?:says|reads)\b[^\n]{0,80}["“]|\bit is written\b|经上(?:记着|说)|성경에\s*기록|est[aá]\s+escrito'
    return not re.search(edition_claim + '|' + quote_claim, english + '\n' + target, re.I)


def review_group(policy, english_units, group, *, diagnostic_context):
    """Return real structural check results; preserve every input unchanged."""
    context = diagnostic.validate_context(diagnostic_context)
    _require(type(policy) is dict and policy.get('schemaVersion') == 'sermon-target-language-policy-v3'
             and policy.get('targetLocale') in LOCALES, 'diagnostic_plugin_policy_invalid')
    locale = policy['targetLocale']
    review = policy.get('languageReview', {})
    _require(type(review) is dict and review.get('pluginId') == PLUGIN_ID and
             review.get('requiredChecks') == REQUIRED, 'diagnostic_plugin_checks_mismatch')
    scope = policy.get('sourceScope')
    _require(type(scope) is dict and scope.get('englishSourcePackageJsonSha256') == context['sourceCanonicalSha256']
             and scope.get('anchorManifestSha256') == context['anchorCanonicalSha256'],
             'diagnostic_plugin_source_scope_changed')
    _require(type(group) is dict and _label(group.get('translationGroupId')) and
             group.get('englishSourcePackageJsonSha256') == context['sourceCanonicalSha256'],
             'diagnostic_plugin_group_identity_changed')
    _require(type(english_units) is list and 1 <= len(english_units) <= 64 and
             all(type(unit) is dict and _label(unit.get('sourceUnitId')) and
                 type(unit.get('english')) is str and 0 < len(unit['english'].strip()) <= MAX_GROUP_CHARS
                 for unit in english_units), 'diagnostic_plugin_source_units_invalid')
    ids = [unit['sourceUnitId'] for unit in english_units]
    _require(len(ids) == len(set(ids)) and group.get('sourceUnitIds') == ids,
             'diagnostic_plugin_source_unit_binding_changed')
    english = ' '.join(unit['english'] for unit in english_units)
    text = group.get('targetText')
    text_valid = type(text) is str and 0 < len(text.strip()) <= MAX_GROUP_CHARS
    target = text if text_valid else ''
    utterances = group.get('targetUtterances')
    structure = (text_valid and type(utterances) is list and 1 <= len(utterances) <= MAX_UTTERANCES and
        all(type(value) is str and 0 < len(value.strip()) <= MAX_UTTERANCE_CHARS and not _unsafe(value)
            for value in utterances))
    structure = bool(structure and ''.join(utterances) == target)
    term_ok, pending, missing = _term_check(policy, english, target, locale)
    source_numbers = Counter(re.findall(r'\d+(?:[.,]\d+)*', unicodedata.normalize('NFKC', english)))
    target_numbers = Counter(re.findall(r'\d+(?:[.,]\d+)*', unicodedata.normalize('NFKC', target)))
    numbers = text_valid and all(target_numbers[number] >= count for number, count in source_numbers.items())
    return [
        result('target_script', bool(text_valid and _script(target, locale)),
            'Target script presence screen only; no native fluency, simplified-character completeness or semantic approval.'),
        result('term_surface_preservation', bool(text_valid and term_ok),
            f'Declared term surfaces checked; missing matched surfaces={missing}; pending human term reviews={pending}. '
            'Simulated HUMAN review context only: pending policy fields stay pending; this is not semantic approval.'),
        result('number_surface_preservation', bool(numbers),
            'Explicit Arabic numeral surface/multiplicity screen only; number words, reading and meaning require the real strict reviewer.'),
        result('utterance_structure', structure,
            'Bounded nonempty plain-text utterances and exact concatenation checked; no speech/prosody or content approval.'),
        result('scripture_reference_only', bool(text_valid and _reference_only(policy, english, target)),
            'Reference-only/no-edition policy and explicit quote/edition surface guard; no direct quotations approved, '
            'no exact Bible wording verified. The real strict semantic reviewer remains mandatory.'),
    ]
