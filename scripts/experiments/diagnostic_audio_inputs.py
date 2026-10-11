"""Read-only audio admission for a source-bound, unapproved L2 diagnostic.

Uses the current fixture and candidate producers' actual machine gates. This
adapter grants no human approval, formal package, dispatch, or resource release.
"""
import hashlib
import json
from pathlib import Path

from scripts import codex_layer2_diagnostic as diagnostic


def digest(value):
    return diagnostic.policies.canonical_sha256(value)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(data)
    return result.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def checked_inputs(args):
    directory = Path(args.diagnostic_fixture).resolve()
    candidate_path = Path(args.diagnostic_candidate).resolve()
    evidence_path, media = Path(args.evidence).resolve(), Path(args.media).resolve()
    files = [directory / name for name in ('fixture-manifest.json', 'diagnostic-context.json',
             'source.json', 'anchor.json', 'policy.json', 'group-plan.json')]
    language_path = candidate_path.parent / 'diagnostic-language-review.json'
    files.extend([candidate_path, evidence_path, language_path])
    before = {str(path): sha(path) for path in files}
    source, anchor, policy, plan, plugin, request, rule, context, fixture = diagnostic.load_fixture(directory)
    diagnostic.require(sha(media) == fixture['sourceMediaSha256'], 'diagnostic_media_sha_changed')
    envelope = read(candidate_path)
    diagnostic.require(envelope.get('schemaVersion') == 'codex-layer2-diagnostic-candidate-v1'
                       and envelope.get('simulationOnly') is True
                       and all(envelope.get(key) is False for key in
                               ('productionEligible', 'actualHumanApproval', 'releaseEligible')),
                       'diagnostic_candidate_scope_changed')
    evidence = read(evidence_path)
    candidate = diagnostic.producer.admit_evidence(source, anchor, policy, request, evidence,
        read(language_path), plugin, fixture['pluginImplementationSha256'],
        diagnostic_context=context, rule_preflight_receipt=rule)
    diagnostic.require(candidate == envelope.get('candidate')
                       and digest(candidate) == envelope.get('candidateSha256')
                       and digest(context) == envelope.get('diagnosticContextSha256')
                       and digest(rule) == envelope.get('rulePreflightSha256'),
                       'diagnostic_candidate_admission_changed')
    diagnostic.require(evidence.get('targetLocale') in ('zh-Hans', 'ko', 'es') and evidence.get('sourceLocale') == 'en',
                       'diagnostic_audio_requires_existing_supported_voice')
    diagnostic.require(len(candidate['groups']) == len(plan), 'diagnostic_audio_group_count_changed')
    groups = []
    for group, expected in zip(candidate['groups'], plan):
        diagnostic.require(group['translationGroupId'] == expected['translationGroupId']
                           and group['sourceUnitIds'] == expected['sourceUnitIds'],
                           'diagnostic_audio_group_coverage_changed')
        gid, text = group['translationGroupId'], group['targetText']
        diagnostic.require(isinstance(gid, str) and gid and Path(gid).name == gid and gid not in ('.', '..')
                           and isinstance(text, str) and text.strip(), 'diagnostic_audio_group_invalid')
        groups.append({'groupId': gid, 'sourceUnitIds': group['sourceUnitIds'], 'text': text,
                       'textSha256': hashlib.sha256(text.encode()).hexdigest()})
    diagnostic.require(len({row['groupId'] for row in groups}) == len(groups), 'diagnostic_audio_duplicate_group')
    binding = {'schemaVersion': 'source-bound-diagnostic-audio-input-v1',
               'admissionImplementationSha256': sha(__file__),
               'fixtureDirectory': str(directory), 'candidatePath': str(candidate_path),
               'evidencePath': str(evidence_path), 'mediaPath': str(media),
               'fixtureSha256': digest(fixture), 'candidateFileSha256': sha(candidate_path),
               'evidenceFileSha256': sha(evidence_path), 'languageReceiptSha256': sha(language_path),
               'sourcePackageJsonSha256': digest(source), 'anchorManifestSha256': digest(anchor),
               'sourceMediaSha256': fixture['sourceMediaSha256'], 'sourceWindow': fixture['sourceWindow'],
               'sourceUnitCount': len(anchor['sourceUnits']), 'groupCount': len(groups),
               'targetLocale': evidence['targetLocale'],
               'simulationOnly': True, 'productionEligible': False, 'actualHumanApproval': False,
               'releaseEligible': False}
    diagnostic.require(before == {str(path): sha(path) for path in files}, 'diagnostic_inputs_changed_during_admission')
    binding['inputFileSha256'] = {**before, str(plugin.resolve()): sha(plugin)}
    if fixture.get('concurrencyProfile') is not None:
        binding['concurrencyProfile'] = fixture['concurrencyProfile']
    return groups, binding


def check_frozen(binding):
    diagnostic.require(all(Path(path).is_file() and sha(path) == expected
                       for path, expected in binding['inputFileSha256'].items()),
                       'diagnostic_audio_frozen_input_changed')
