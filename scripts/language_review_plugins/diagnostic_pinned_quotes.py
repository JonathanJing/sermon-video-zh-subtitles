"""Diagnostic excerpt integrity, never Bible-edition or human approval.

Generated modules freeze literal bindings and delegate to this helper. Pending
local target artifact provenance is preserved, not promoted to reviewed wording.
"""
import copy
import hashlib
import json
from pathlib import Path
import re

from scripts import target_language_policy as policies
from scripts import sermon_diagnostic_context as diagnostic
from scripts.language_review_plugins import diagnostic_structural as structural
from scripts.language_review_plugins.common import result

PLUGIN_ID = 'diagnostic-pinned-quotes-v1'
PLUGIN_VERSION = '2026-10-05-v1'
EDITION = 'diagnostic-pinned-excerpts'
SCHEMA = 'diagnostic-pinned-quote-bindings-v1'
REQUIRED = ['target_script', 'term_surface_preservation', 'number_surface_preservation',
            'utterance_structure', 'pinned_quote_integrity']


def require(condition, message):
    if not condition:
        raise ValueError('Diagnostic pinned quotes: ' + message)


def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def is_policy(policy):
    return (policy.get('languageReview', {}).get('pluginId') == PLUGIN_ID
            and policy.get('languageReview', {}).get('requiredChecks') == REQUIRED
            and policy.get('scripture', {}).get('editionId') == EDITION
            and policy['scripture'].get('citationUseStatus') == 'pending'
            and policy['scripture'].get('quoteCheckPolicy') == 'source_bound_exact_quote')


def validate_bindings(bindings, request, policy, plan):
    require(is_policy(policy), 'policy differs from pending diagnostic baseline')
    require(type(bindings) is dict and set(bindings) == {'schemaVersion', 'sourceSha256', 'anchorSha256',
        'groupPlanSha256', 'targetLocale', 'editionId', 'citationUseStatus', 'provenance', 'quotes'}, 'binding schema')
    require(bindings['schemaVersion'] == SCHEMA and bindings['editionId'] == EDITION
        and bindings['citationUseStatus'] == 'pending' and bindings['targetLocale'] == policy['targetLocale']
        and bindings['sourceSha256'] == request['englishSourcePackageJsonSha256']
        and bindings['anchorSha256'] == request['anchorManifestSha256']
        and bindings['groupPlanSha256'] == policies.canonical_sha256(plan), 'source/anchor/group/locale changed')
    provenance = bindings['provenance']
    require(type(provenance) is dict and set(provenance) == {'status', 'artifactSha256', 'artifactPath'}
        and provenance['status'] == 'pending' and type(provenance['artifactPath']) is str
        and bool(provenance['artifactPath'].strip())
        and type(provenance['artifactSha256']) is str
        and re.fullmatch('[a-f0-9]{64}', provenance['artifactSha256']), 'pending target provenance missing')
    rows = {row['sourceUnitId']: row['english'] for row in request['sourceUnits']}
    groups = {row['translationGroupId']: row['sourceUnitIds'] for row in plan}
    quotes = bindings['quotes']
    require(type(quotes) is list and bool(quotes), 'quotation inventory empty')
    previous = (-1, -1, -1)
    seen_targets = set()
    unit_order = {unit: i for i, unit in enumerate(rows)}
    ordered_groups = {group: i for i, group in enumerate(groups)}
    for quote in quotes:
        require(type(quote) is dict and set(quote) == {'translationGroupId', 'sourceUnitIds', 'reference', 'parts'}, 'quote schema')
        group = quote['translationGroupId']
        require(group in groups and quote['sourceUnitIds'] == groups[group]
            and type(quote['reference']) is str and re.fullmatch(r'[A-Z0-9]+\.\d+:\d+(?:-\d+)?', quote['reference'])
            and type(quote['parts']) is list and bool(quote['parts']), 'quote group/reference changed')
        for part in quote['parts']:
            require(type(part) is dict and set(part) == {'sourceUnitId', 'englishStartOffset', 'englishEndOffset',
                'englishExcerpt', 'englishExcerptSha256', 'targetText', 'targetTextSha256'}, 'quote part schema')
            unit, start, end = part['sourceUnitId'], part['englishStartOffset'], part['englishEndOffset']
            require(unit in quote['sourceUnitIds'] and type(start) is int and type(end) is int
                and 0 <= start < end <= len(rows[unit]), 'English character offsets invalid')
            require(rows[unit][start:end] == part['englishExcerpt']
                and text_hash(part['englishExcerpt']) == part['englishExcerptSha256'], 'English span bytes changed')
            position = (ordered_groups[group], unit_order[unit], start)
            require(position > previous, 'quote parts reordered or overlapping')
            if previous[:2] == position[:2]:
                require(start >= previous[2], 'quote parts overlap')
            previous = (position[0], position[1], end)
            target = part['targetText']
            require(type(target) is str and bool(target.strip()) and not structural._unsafe(target)
                and text_hash(target) == part['targetTextSha256'] and target not in seen_targets,
                'target excerpt hash/plain text/uniqueness changed')
            seen_targets.add(target)
    return copy.deepcopy(quotes)


def review_group(policy, english_units, group, *, diagnostic_context, bindings):
    context = diagnostic.validate_context(diagnostic_context)
    require(is_policy(policy) and policy['targetLocale'] in structural.LOCALES, 'diagnostic policy mismatch')
    require(bindings['sourceSha256'] == context['sourceCanonicalSha256']
        and bindings['anchorSha256'] == context['anchorCanonicalSha256'], 'context binding mismatch')
    # Reuse unchanged surface checks, never its reference-only quotation claim.
    surface_policy = copy.deepcopy(policy)
    surface_policy['languageReview'].update(pluginId=structural.PLUGIN_ID, requiredChecks=structural.REQUIRED)
    checks = structural.review_group(surface_policy, english_units, group, diagnostic_context=context)[:4]
    english_by_id = {row['sourceUnitId']: row['english'] for row in english_units}
    target = group['targetText']
    ok = True
    cursor = 0
    for quote in bindings['quotes']:
        own = quote['translationGroupId'] == group['translationGroupId']
        if own:
            ok = ok and quote['sourceUnitIds'] == group['sourceUnitIds']
        for part in quote['parts']:
            fragment = part['targetText']
            if own:
                english = english_by_id.get(part['sourceUnitId'], '')
                ok = ok and english[part['englishStartOffset']:part['englishEndOffset']] == part['englishExcerpt']
                position = target.find(fragment, cursor)
                ok = ok and position >= cursor and target.count(fragment) == 1
                cursor = max(cursor, position + len(fragment))
            else:
                ok = ok and fragment not in target
    # No newly spoken chapter:verse notation or quote reference metadata.
    english = ' '.join(english_by_id.values())
    refs = re.findall(r'\d+\s*:\s*\d+(?:\s*[-–]\s*\d+)?', target)
    ok = ok and all(reference in english for reference in refs)
    ok = ok and not any(quote['reference'] in target and quote['reference'] not in english for quote in bindings['quotes'])
    checks.append(result('pinned_quote_integrity', bool(ok),
        'Complete frozen diagnostic target fragments checked once, in source order, only in their bound group; '
        'English spans and pending target provenance retained. No specified Bible edition, translation quality, '
        'citation permission or human approval verified.'))
    return checks


def freeze_quote_plugin(source, anchor, plan, policy, bindings, out_plugin):
    """Return a new pending diagnostic policy; create a new literal plugin only."""
    from scripts import produce_target_language_candidate as producer
    policy = copy.deepcopy(policy)
    policy['scripture'].update(editionId=EDITION, citationUseStatus='pending', quoteCheckPolicy='source_bound_exact_quote')
    policy['languageReview'].update(pluginId=PLUGIN_ID, requiredChecks=copy.deepcopy(REQUIRED), implementationStatus='verified')
    for component in ('scripture', 'languageReview'):
        policy['componentSha256'][component] = policies.canonical_sha256(policy[component])
    request = {'englishSourcePackageJsonSha256': policies.canonical_sha256(source),
        'anchorManifestSha256': policies.canonical_sha256(anchor), 'sourceUnits': anchor['sourceUnits']}
    validate_bindings(bindings, request, policy, plan)
    provenance_path = Path(bindings['provenance']['artifactPath'])
    require(provenance_path.is_file() and policies.file_sha256(provenance_path) == bindings['provenance']['artifactSha256'],
            'pending target artifact bytes differ from provenance')
    def surfaces(value):
        if type(value) is str:
            yield value
        elif type(value) is list:
            if all(type(item) is str for item in value):
                yield ''.join(value)
            for item in value:
                yield from surfaces(item)
        elif type(value) is dict:
            for item in value.values():
                yield from surfaces(item)
    target_surfaces = list(surfaces(json.loads(provenance_path.read_text(encoding='utf-8'))))
    require(all(any(part['targetText'] in surface for surface in target_surfaces)
                for quote in bindings['quotes'] for part in quote['parts']),
            'target fragment absent from pending provenance artifact')
    path = Path(out_plugin)
    require(not path.exists(), 'requires new frozen plugin path')
    path.parent.mkdir(parents=True, exist_ok=True)
    text = ("from scripts.language_review_plugins import diagnostic_pinned_quotes as helper\n"
        "DIAGNOSTIC_ONLY = True\nDIAGNOSTIC_PINNED_QUOTES = True\n"
        f"PLUGIN_ID = {PLUGIN_ID!r}\nPLUGIN_VERSION = {PLUGIN_VERSION!r}\nREQUIRED = {REQUIRED!r}\n"
        f"DIAGNOSTIC_QUOTE_BINDINGS = {bindings!r}\n"
        "def review_group(policy, english_units, group, *, diagnostic_context):\n"
        "    return helper.review_group(policy, english_units, group, diagnostic_context=diagnostic_context, bindings=DIAGNOSTIC_QUOTE_BINDINGS)\n")
    with path.open('x', encoding='utf-8') as handle:
        import os
        os.chmod(path, 0o600)
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    policy['languageReview']['pluginImplementationSha256'] = producer.plugin_implementation_sha256(path)
    policy['componentSha256']['languageReview'] = policies.canonical_sha256(policy['languageReview'])
    return policy
