#!/usr/bin/env python3
"""Draft a weekly poster design (v2) from the published content, before any image.

The design stage is the slowest manual step: read the sermon, list candidate
objects with evidence and scores, then expand the poster prompt. This entry
uses the existing no-tool Codex text transport to produce that draft. The model
only *selects* evidence ids and proposes fields; this tool fills every quote
from the published cues and expands the prompt template itself, so the model
cannot invent text. The result still goes through ``design.validate_design`` and
is marked ``userChoice=pending`` until a human picks the concept.

The command never generates an image, never renders and never publishes.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import sys

from ...compute.transports import codex_cli
from . import design

SCHEMA = 'tongxing-poster-design-draft-v1'
TEMPLATE_PATH = 'docs/prompts/tongxing-weekly-poster-content-template-v1.txt'
HISTORY_PATH = 'docs/poster-concept-history.zh.md'

MODEL_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['centralMessage', 'tension', 'response', 'candidates', 'choice', 'promptFields'],
    'properties': {
        'centralMessage': {'type': 'string'},
        'tension': {'type': 'string'},
        'response': {'type': 'string'},
        'candidates': {
            'type': 'array', 'minItems': 2, 'maxItems': 4,
            'items': {
                'type': 'object', 'additionalProperties': False,
                'required': ['id', 'concept', 'primarySubject', 'supportingElement',
                             'anchorTier', 'anchorTerm', 'evidence', 'scores', 'risks'],
                'properties': {
                    'id': {'type': 'string'},
                    'concept': {'type': 'string'},
                    'primarySubject': {'type': 'string'},
                    'supportingElement': {'type': 'string'},
                    'anchorTier': {'enum': list(design.TIERS)},
                    'anchorTerm': {'type': 'string'},
                    'evidence': {
                        'type': 'array', 'minItems': 1, 'maxItems': 4,
                        'items': {
                            'type': 'object', 'additionalProperties': False,
                            'required': ['textGroupId', 'tier'],
                            'properties': {'textGroupId': {'type': 'string'},
                                           'tier': {'enum': list(design.TIERS)}},
                        },
                    },
                    'scores': {
                        'type': 'object', 'additionalProperties': False,
                        'required': list(design.SCORE_AXES),
                        'properties': {axis: {'type': 'integer', 'minimum': 0, 'maximum': 2}
                                       for axis in design.SCORE_AXES},
                    },
                    'risks': {'type': 'array', 'items': {'type': 'string'}},
                },
            },
        },
        'choice': {
            'type': 'object', 'additionalProperties': False,
            'required': ['candidateId', 'why', 'rejected'],
            'properties': {
                'candidateId': {'type': 'string'},
                'why': {'type': 'string'},
                'rejected': {
                    'type': 'array',
                    'items': {
                        'type': 'object', 'additionalProperties': False,
                        'required': ['candidateId', 'reason'],
                        'properties': {'candidateId': {'type': 'string'},
                                       'reason': {'type': 'string'}},
                    },
                },
            },
        },
        'promptFields': {
            'type': 'object', 'additionalProperties': False,
            'required': ['visualConcept', 'primarySubject', 'setting', 'supportingElement', 'mood',
                         'colorAndLight', 'meaningToPreserve', 'meaningToAvoid'],
            'properties': {
                'visualConcept': {'type': 'string'},
                'primarySubject': {'type': 'string'},
                'setting': {'type': 'string'},
                'supportingElement': {'type': 'string'},
                'mood': {'type': 'string'},
                'colorAndLight': {'type': 'string'},
                'meaningToPreserve': {'type': 'string'},
                'meaningToAvoid': {'type': 'string'},
            },
        },
    },
}


class DraftError(ValueError):
    pass


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def build_prompt(context, template_text, history_text):
    cue_lines = '\n'.join('[' + group + '] ' + text for group, text in context['cues'].items())
    fixed = template_text[template_text.index('FIXED POSTER STYLE'):]
    return f'''You are drafting this week's Tongxing sermon poster design (Chinese). Read the published
content below, choose 2-4 candidate visual concepts, score them, and pick one. The tool will fill
every evidence quote from the published cue text and expand the poster prompt template itself, so:

- cite evidence as {{"textGroupId": "...", "tier": "title|keyverse|passage|illustration"}};
- do not invent quotes, scripture, or facts outside the text;
- the chosen candidate's primarySubject must NOT be anchored only in a sermon illustration;
- prefer the passage's own concrete object; if the title names one, it is candidate #1;
- one primary subject, at most one supporting element; no text, letters, numbers, logos, watermarks or QR codes
  in the image; a restrained symbol is allowed only when the passage itself or a recorded user choice calls for it;
- the primary subject should sit around 40-66% of image height with the lower third quiet
  (a solid ivory footer will cover the bottom third).

PUBLISHED CONTENT
Title: {context['title']}
Series: {context['series']}
Scripture: {context['scripture']}
Speaker: {context['speaker']}
Date: {context['date']}

CUES (textGroupId -> exact text)
{cue_lines}

RECENT CONCEPT HISTORY
{history_text}

The history rows dated {context['date']} describe THIS week's recorded direction (the incumbent), not
previous-week duplicates: do not lower their freshness score for repeating them; only earlier weeks count
as repetition.

POSTER PROMPT TEMPLATE (fixed style, for the promptFields you propose)
{fixed}

Return a JSON object with: centralMessage, tension, response (one paragraph each, from the text);
candidates (2-4, each with id, concept, primarySubject, supportingElement, anchorTier, anchorTerm,
evidence, six 0-2 scores, risks); choice (candidateId, why, rejected as an array of candidateId/reason objects); promptFields
(visualConcept, primarySubject, setting, supportingElement, mood, colorAndLight, meaningToPreserve,
meaningToAvoid) for the chosen candidate. Scores: textualCentrality, depictability, directness,
misreadResistance, layoutFit, freshness.'''


def assemble(output, context, template_text, template_path, history_sha=None):
    """Fill quotes and expand the template from the model's selections; then validate."""
    if not isinstance(output, dict):
        raise DraftError('model output must be an object')
    fields = {
        'title': context['title'], 'series': context['series'], 'scripture': context['scripture'],
        'central_message': output['centralMessage'], 'tension': output['tension'],
        'response': output['response'],
    }
    prompt_fields = output['promptFields']
    mapping = {
        'visual_concept': 'visualConcept', 'primary_subject': 'primarySubject',
        'setting': 'setting', 'supporting_element': 'supportingElement', 'mood': 'mood',
        'color_and_light': 'colorAndLight', 'meaning_to_preserve': 'meaningToPreserve',
        'meaning_to_avoid': 'meaningToAvoid',
    }
    for template_key, model_key in mapping.items():
        fields[template_key] = prompt_fields[model_key]
    prompt = template_text
    for key, value in fields.items():
        prompt = prompt.replace('{{' + key + '}}', value)
    candidates = []
    for candidate in output['candidates']:
        evidence = []
        for row in candidate['evidence']:
            group = row['textGroupId']
            if group not in context['cues']:
                raise DraftError('model cited a textGroupId that is not in the published content: ' + group)
            evidence.append(dict(textGroupId=group, quote=context['cues'][group], tier=row['tier']))
        candidates.append(dict(id=candidate['id'], concept=candidate['concept'],
                               primarySubject=candidate['primarySubject'],
                               supportingElement=candidate.get('supportingElement', ''),
                               anchorTier=candidate['anchorTier'], anchorTerm=candidate['anchorTerm'],
                               evidence=evidence, scores=candidate['scores'],
                               risks=list(candidate.get('risks', []))))
    choice = dict(candidateId=output['choice']['candidateId'], why=output['choice']['why'],
                  rejected={row['candidateId']: row['reason']
                            for row in output['choice'].get('rejected', [])})
    draft = dict(schemaVersion=design.SCHEMA, pageId=context['pageId'], targetLocale=context['locale'],
                 date=context['date'], title=context['title'], series=context['series'],
                 scripture=context['scripture'], speaker=context['speaker'],
                 sourceIdentitySha256=context['sourceIdentitySha256'],
                 contentSha256=context['contentSha256'], candidates=candidates, choice=choice,
                 userChoice=dict(status='pending', source='auto draft; human review required'),
                 artPrompt=prompt,
                 template=dict(path=template_path, sha256=sha(template_text.encode('utf-8'))))
    if history_sha:
        draft['conceptHistorySha256'] = history_sha
    return design.validate_design(draft, context), prompt


def run(release, page_id, locale, out, template_path, history_path, model, reasoning,
        timeout_seconds, dry_run=False):
    out = Path(out).resolve()
    template_path, history_path = Path(template_path), Path(history_path)
    template_text = template_path.read_text(encoding='utf-8')
    history_text = history_path.read_text(encoding='utf-8') if history_path.is_file() else '(no history)'
    context = design.load_context(release, page_id, locale)
    prompt = build_prompt(context, template_text, history_text)
    prompt_sha = sha(prompt.encode('utf-8'))
    out.mkdir(parents=True, exist_ok=True)
    (out / 'draft-prompt.txt').write_text(prompt, encoding='utf-8')
    if dry_run:
        return dict(status='dry_run', promptPath=str(out / 'draft-prompt.txt'),
                    promptSha256=prompt_sha, out=str(out))
    call_dir = out / 'codex-call'
    output = codex_cli.call_json(prompt, model=model, reasoning=reasoning,
                                 output_schema=MODEL_SCHEMA, output_dir=call_dir,
                                 timeout_seconds=timeout_seconds)
    (out / 'draft-raw.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n',
                                        encoding='utf-8')
    try:
        normalized, art_prompt = assemble(output, context, template_text, str(template_path),
                                          sha(history_text.encode('utf-8')))
    except (DraftError, design.DesignError) as error:
        (out / 'draft-error.txt').write_text(str(error) + '\n', encoding='utf-8')
        raise
    (out / 'poster-design.draft.json').write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (out / 'art-prompt.txt').write_text(art_prompt, encoding='utf-8')
    call_receipt = {}
    receipt_path = call_dir / 'response.json'
    if receipt_path.is_file():
        saved = json.loads(receipt_path.read_text(encoding='utf-8'))
        call_receipt = {key: saved.get(key) for key in
                        ('id', 'threadId', 'requestedModel', 'requestedReasoningEffort',
                         'usage', 'elapsedSeconds', 'requestedServiceTier')}
    receipt = dict(schemaVersion=SCHEMA, pageId=page_id, locale=locale,
                   promptSha256=prompt_sha, responseSha256=sha(json.dumps(output, sort_keys=True).encode()),
                   chosenCandidate=normalized['choice']['candidateId'],
                   candidateTotals={row['id']: row['total'] for row in normalized['candidates']},
                   warnings=normalized['validation']['warnings'],
                   codexCall=str(call_dir), codexCallReceipt=call_receipt,
                   validatedAt=normalized['validation']['validatedAt'])
    (out / 'draft-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n',
                                            encoding='utf-8')
    return dict(status='drafted', chosen=receipt['chosenCandidate'], totals=receipt['candidateTotals'],
                warnings=receipt['warnings'], designPath=str(out / 'poster-design.draft.json'),
                promptPath=str(out / 'art-prompt.txt'), out=str(out))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--release', required=True)
    parser.add_argument('--page-id', required=True)
    parser.add_argument('--locale', default='zh-Hans')
    parser.add_argument('--out', required=True, help='fresh directory for the draft, prompt and receipts')
    parser.add_argument('--template', default=TEMPLATE_PATH)
    parser.add_argument('--concept-history', default=HISTORY_PATH)
    parser.add_argument('--model', default=codex_cli.TEXT_MODEL)
    parser.add_argument('--reasoning', default='medium', choices=('medium', 'high'))
    parser.add_argument('--timeout-seconds', type=int, default=300)
    parser.add_argument('--dry-run', action='store_true', help='write the drafting prompt and stop before any model call')
    args = parser.parse_args(argv)
    try:
        result = run(args.release, args.page_id, args.locale, args.out, args.template,
                     args.concept_history, args.model, args.reasoning, args.timeout_seconds,
                     args.dry_run)
    except (DraftError, design.DesignError, OSError, ValueError, KeyError) as error:
        sys.exit(str(error))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
