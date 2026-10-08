#!/usr/bin/env python3
"""Real 180-second Layer 2 test: Claude Opus 5.5 translation, Claude Haiku 5.5 review.

Isolated test only. Uses the frozen English units, anchors and group plan from an
existing fixed-clip baseline. Each group is translated once by Opus and then reviewed
once by Haiku against that Opus draft, each in an independent CLI session without
tools. The reviewer prompt is the frozen one, with only the draft field replaced.
No language plugin, candidate admission, human approval, TTS, ASR or publication.
Subscription login only: no API key, model substitution, fallback or automatic retry.
A started marker without a response blocks a rerun until the call is reconciled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from scripts.claude_layer2_transport import ClaudeLayer2Transport
from scripts.codex_layer2_transport import output_schema
from scripts.experiments.codex_translation_ab import save, save_or_check, sha, validate

TRANSLATOR_MODEL = 'claude-opus-5-5'
REVIEWER_MODEL = 'claude-haiku-5-5'
CHECKS = ('completeMeaning', 'negationsNumbersNames', 'quotationAttribution', 'noAddedMeaning')
TERMINAL_FAILURE = 'claude_language_terminal_failure_inspect_receipt'


def prompt_sha(messages):
    return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()


def load_groups(baseline):
    """Pair each frozen translator prompt with the frozen reviewer prompt of the same group."""
    translators = sorted(baseline.glob('group-*-astra.policy-preview.json'))
    assert len(translators) == 13, f'Expected 13 frozen groups, found {len(translators)}'
    groups = []
    for translator_preview in translators:
        stem = translator_preview.name.split('-astra.')[0]
        reviewer_preview = baseline / f'{stem}-sol.policy-preview.json'
        assert reviewer_preview.exists(), f'Missing frozen reviewer prompt for {stem}'
        messages = json.loads(translator_preview.read_text())['payload']['messages']
        source = json.loads(messages[1]['content'])
        groups.append({'name': stem, 'translatorPreview': translator_preview,
                       'reviewerPreview': reviewer_preview, 'translatorMessages': messages,
                       'reviewerMessages': json.loads(reviewer_preview.read_text())['payload']['messages'],
                       'source': source})
    units = sum(len(group['source']['sourceUnitIds']) for group in groups)
    assert units == 39, f'Expected 39 source units, found {units}'
    return groups


def reviewer_messages(frozen_messages, draft):
    """Replace only the candidate draft; the frozen system prompt and other fields stay unchanged."""
    messages = json.loads(json.dumps(frozen_messages))
    user = json.loads(messages[1]['content'])
    assert set(user['astraDraft']) == set(draft), 'Draft fields differ from the frozen reviewer prompt'
    user['astraDraft'] = draft
    messages[1]['content'] = json.dumps(user, ensure_ascii=False)
    return messages


def run_call(job, name, call, messages, *, max_attempts=1):
    """One call per directory, returning (response, fresh, attempts).

    Only an explicit CLI terminal failure is retried, up to max_attempts. Each failed attempt keeps
    its started marker as started.attempt-N.json and is listed in failures.json. Any other exception,
    including a timeout or an unreadable result, leaves started.json in place and blocks the rerun.
    A saved response is reused only for the same prompt.
    """
    directory = job / name
    directory.mkdir(parents=True, exist_ok=True)
    response_path, started_path = directory / 'response.json', directory / 'started.json'
    failures_path = directory / 'failures.json'
    digest = prompt_sha(messages)
    failures = json.loads(failures_path.read_text()) if failures_path.exists() else []
    if response_path.exists():
        assert json.loads(started_path.read_text())['promptSha256'] == digest, f'Cached prompt changed: {directory}'
        return json.loads(response_path.read_text()), False, len(failures) + 1
    assert not started_path.exists(), f'Unknown outcome in {directory}; reconcile receipts before retry'
    while len(failures) < max_attempts:
        attempt = len(failures) + 1
        save(started_path, {'startedAt': datetime.now(timezone.utc).isoformat(), 'promptSha256': digest,
                            'attempt': attempt})
        try:
            response = call(messages)
        except RuntimeError as error:
            if str(error) != TERMINAL_FAILURE:
                raise
            started_path.rename(directory / f'started.attempt-{attempt}.json')
            failures.append({'attempt': attempt, 'failure': str(error),
                             'failedAt': datetime.now(timezone.utc).isoformat()})
            failures_path.write_text(json.dumps(failures, ensure_ascii=False, indent=2) + '\n')
            continue
        save(response_path, response)
        return response, True, attempt
    raise RuntimeError(f'{name} terminal failure after {max_attempts} attempts: {directory}')


def review_passed(review):
    """Same strictness as the shared loop: any non-pass check, issue or uncertainty blocks the group."""
    semantic = review['semanticReview']
    return (semantic['status'] == 'pass' and all(semantic['checks'][name] == 'pass' for name in CHECKS)
            and not semantic['issues'] and not semantic['uncertainty'])


def usage_sum(responses, key):
    return sum((response['usage'].get(key) or 0) for response in responses)


def with_group_decision(messages, decision):
    """Append a project-owner decision to the system prompt; no decision leaves the frozen prompt unchanged."""
    if decision is None:
        return messages
    messages = json.loads(json.dumps(messages))
    messages[0]['content'] += ('\n\nProject decision for this group (approved by the project owner, not a model '
                               'judgment): ' + decision)
    return messages


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=Path('artifacts/codex-cli-layer2-180s-20261005'),
                        help='Directory with frozen group-*-astra and group-*-sol policy previews')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--claude-cli', type=Path)
    parser.add_argument('--translator-effort', choices=['medium', 'high', 'xhigh'], default='high')
    parser.add_argument('--reviewer-effort', choices=['low', 'medium', 'high'], default='medium')
    parser.add_argument('--translator-timeout', type=int, default=300)
    parser.add_argument('--reviewer-timeout', type=int, default=180)
    parser.add_argument('--max-review-attempts', type=int, choices=[1, 2], default=2,
                        help='Attempts per review after an explicit CLI terminal failure; timeouts never retry')
    parser.add_argument('--only-group', action='append', default=[],
                        help='Run only this group, e.g. group-0006; repeatable')
    parser.add_argument('--group-decision', action='append', default=[],
                        help='GROUP=TEXT, appended to that group\'s translator and reviewer system prompts')
    args = parser.parse_args(argv)
    baseline, out = args.baseline.resolve(), args.out.resolve()
    groups = load_groups(baseline)
    names = {group['name'] for group in groups}
    decisions = {}
    for item in args.group_decision:
        name, _, text = item.partition('=')
        assert name and text.strip(), f'Invalid --group-decision: {item}'
        decisions[name] = text.strip()
    assert set(decisions) <= names, 'A decision names an unknown group'
    if args.only_group:
        assert set(args.only_group) <= names, 'Unknown --only-group'
        groups = [group for group in groups if group['name'] in set(args.only_group)]
    translator = ClaudeLayer2Transport(args.claude_cli, model=TRANSLATOR_MODEL, effort=args.translator_effort,
                                       timeout_seconds=args.translator_timeout,
                                       receipts_dir=out / '_cli_calls' / 'translator')
    reviewer = ClaudeLayer2Transport(args.claude_cli, model=REVIEWER_MODEL, effort=args.reviewer_effort,
                                     timeout_seconds=args.reviewer_timeout,
                                     receipts_dir=out / '_cli_calls' / 'reviewer')
    identity = {'schemaVersion': 'claude-layer2-180s-test-v1', 'baseline': str(baseline),
                'baselineHashes': {group['translatorPreview'].name: sha(group['translatorPreview']) for group in groups}
                | {group['reviewerPreview'].name: sha(group['reviewerPreview']) for group in groups},
                'translator': {'role': 'translator', 'model': TRANSLATOR_MODEL, 'effort': args.translator_effort,
                               'transport': translator.execution_identity},
                'reviewer': {'role': 'reviewer', 'model': REVIEWER_MODEL, 'effort': args.reviewer_effort,
                             'transport': reviewer.execution_identity},
                'maxReviewAttempts': args.max_review_attempts,
                'onlyGroups': sorted(args.only_group), 'groupDecisions': dict(sorted(decisions.items())),
                'runnerSha256': sha(Path(__file__)), 'workers': 1, 'order': 'translate then review, per group',
                'humanApproval': False, 'productionEligible': False}
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'identity.json').exists():
        assert json.loads((out / 'identity.json').read_text()) == identity, 'Identity changed'
    else:
        assert not any(path.name != '_cli_calls' for path in out.iterdir()), 'Unidentified output directory'
        save(out / 'identity.json', identity)

    rows, fresh = [], {'translator': 0, 'reviewer': 0}
    for group in groups:
        job = out / group['name']
        source = group['source']
        decision = decisions.get(group['name'])
        draft_response, new_draft, draft_attempts = run_call(
            job, 'translator', lambda messages: translator('', {'messages': messages}, role='translator'),
            with_group_decision(group['translatorMessages'], decision))
        draft = json.loads(draft_response['content'])
        validate(draft, source, output_schema('translator'))
        fresh['translator'] += new_draft

        review_response, new_review, review_attempts = run_call(
            job, 'reviewer', lambda messages: reviewer('', {'messages': messages}, role='reviewer'),
            with_group_decision(reviewer_messages(group['reviewerMessages'], draft), decision),
            max_attempts=args.max_review_attempts)
        review = json.loads(review_response['content'])
        assert review['translationGroupId'] == source['translationGroupId'], 'Reviewer group identity changed'
        assert review['sourceUnitIds'] == source['sourceUnitIds'], 'Reviewer unit identity changed'
        fresh['reviewer'] += new_review

        row = {'group': group['name'], 'translationGroupId': source['translationGroupId'],
               'units': len(source['sourceUnitIds']), 'translatorSeconds': draft_response['elapsedSeconds'],
               'reviewerSeconds': review_response['elapsedSeconds'], 'reviewerPassed': review_passed(review),
               'translatorAttempts': draft_attempts, 'reviewerAttempts': review_attempts,
               'issues': review['semanticReview']['issues'], 'uncertainty': review['semanticReview']['uncertainty'],
               'translatorUsage': draft_response['usage'], 'reviewerUsage': review_response['usage'],
               'translatorListPriceUsd': draft_response.get('listPriceUsd'),
               'reviewerListPriceUsd': review_response.get('listPriceUsd')}
        rows.append(row)
        print(json.dumps({'group': group['name'], 'translatorSeconds': round(row['translatorSeconds'], 2),
                          'reviewerSeconds': round(row['reviewerSeconds'], 2),
                          'reviewerPassed': row['reviewerPassed']}, ensure_ascii=False), flush=True)

    translator_responses = [json.loads((out / group['name'] / 'translator' / 'response.json').read_text())
                            for group in groups]
    reviewer_responses = [json.loads((out / group['name'] / 'reviewer' / 'response.json').read_text())
                          for group in groups]
    failed = [row['group'] for row in rows if not row['reviewerPassed']]
    summary = {
        'schemaVersion': 'claude-layer2-180s-test-summary-v1', 'groups': len(rows),
        'units': sum(row['units'] for row in rows),
        'translatorModel': TRANSLATOR_MODEL, 'reviewerModel': REVIEWER_MODEL,
        'translatorValidation': 'schema, group/unit identity, coverage',
        'reviewerValidation': 'schema from CLI, group/unit identity, machine verdict (strict: non-pass, issue or uncertainty blocks)',
        'reviewerPassedGroups': len(rows) - len(failed), 'reviewerFailedGroups': failed,
        'translatorSumSeconds': sum(row['translatorSeconds'] for row in rows),
        'reviewerSumSeconds': sum(row['reviewerSeconds'] for row in rows),
        'translatorMedianSeconds': statistics.median(row['translatorSeconds'] for row in rows),
        'reviewerMedianSeconds': statistics.median(row['reviewerSeconds'] for row in rows),
        'translatorUsage': {key: usage_sum(translator_responses, key) for key in
                            ('inputTokens', 'cachedInputTokens', 'outputTokens', 'reasoningTokens')},
        'reviewerUsage': {key: usage_sum(reviewer_responses, key) for key in
                          ('inputTokens', 'cachedInputTokens', 'outputTokens', 'reasoningTokens')},
        'listPriceUsdEquivalent': sum((row['translatorListPriceUsd'] or 0) + (row['reviewerListPriceUsd'] or 0)
                                      for row in rows),
        'maxReviewAttempts': args.max_review_attempts,
        'reviewerAttemptsTotal': sum(row['reviewerAttempts'] for row in rows),
        'freshCalls': fresh, 'humanApproval': False, 'productionEligible': False, 'releaseEligible': False,
        'stages': {'translation': 'machine_schema_and_coverage_checked', 'review': 'haiku_machine_verdict',
                   'languagePlugin': 'not_run', 'candidateAdmission': 'not_run', 'humanReview': 'not_run',
                   'tts': 'not_run', 'asr': 'not_run', 'publication': 'not_run'},
    }
    save_or_check(out / 'rows.json', rows)
    save_or_check(out / 'summary.json', summary)
    print(json.dumps({'freshCalls': fresh, 'groups': len(rows), 'reviewerPassedGroups': summary['reviewerPassedGroups'],
                      'reviewerFailedGroups': failed}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
