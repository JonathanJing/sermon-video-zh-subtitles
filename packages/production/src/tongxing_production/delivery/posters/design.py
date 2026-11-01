#!/usr/bin/env python3
"""Validate a weekly poster design before any image is generated.

The design stage decides which *object* the artwork shows. 2026-11-01 showed
that an invented, multi-step illustration (a storm shelter taken from a sermon
anecdote) is less apt than the passage's own object (the seal named in the
title). This entry turns that lesson into a contract:

    poster-design.json (v2) -> validate -> poster-design.json + art-prompt.txt + design-receipt.json

Each candidate names a primary subject, the anchor tier it comes from
(title / keyverse / passage / illustration), the exact anchor term, exact
published-text evidence, and six 0-2 scores. The chosen candidate must not be
anchored in an illustration, its anchor term must appear in the title or in a
non-illustration evidence quote, and the highest total wins unless a written
override explains why. The command never calls a model, never renders and
never publishes.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import sys

from . import build

SCHEMA = 'tongxing-poster-design-v2'
RECEIPT_SCHEMA = 'tongxing-poster-design-receipt-v1'
TIERS = ('title', 'keyverse', 'passage', 'illustration')
ANCHORED_TIERS = ('title', 'keyverse', 'passage')
SCORE_AXES = ('textualCentrality', 'depictability', 'directness',
              'misreadResistance', 'layoutFit', 'freshness')
TEMPLATE_MARKERS = ('FIXED POSTER STYLE AND COMPOSITION', 'Absolutely NO text')
PROMPT_LIMIT = 8000


class DesignError(ValueError):
    pass


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _require(condition, message):
    if not condition:
        raise DesignError(message)


def load_context(release, page_id, locale='zh-Hans'):
    """Published title, source identity, content hash and exact cue text for one page."""
    public = Path(release).resolve() / 'public'
    name, version = next((row for row in build.CATALOGS if (public / row[0]).is_file()), build.CATALOGS[-1])
    catalog, _ = build.checked_json(public / name)
    _require(catalog.get('schemaVersion') == version, 'unexpected catalog version')
    pages = [page for page in catalog['pages'] if page['id'] == page_id]
    _require(len(pages) == 1, 'page ID must match exactly one published page')
    page = pages[0]
    _require(locale in page['targets'], 'page has no published ' + locale + ' target')
    target = page['targets'][locale]
    _, source_identity, _ = build.target_source(page, target, version)
    package, _ = build.checked_json(build.asset_file(public, target['releasePackageUrl']),
                                    target['releasePackageJsonSha256'])
    assets = [asset for asset in package['assets'] if asset['role'] == 'content']
    _require(len(assets) == 1, 'expected one approved content asset')
    content, content_sha = build.checked_json(build.asset_file(public, assets[0]['path']),
                                              assets[0]['sha256'])
    cues = {cue['textGroupId']: cue['text'] for cue in content.get('cues', [])
            if cue.get('textGroupId') and cue.get('text')}
    return dict(pageId=page_id, locale=locale, title=content.get('title'),
                series=content.get('series'), scripture=content.get('scripture'),
                speaker=content.get('speaker'), date=content.get('date') or page.get('date'),
                sourceIdentitySha256=source_identity, contentSha256=content_sha, cues=cues)


def _candidate(candidate, cues):
    _require(isinstance(candidate, dict), 'candidate must be an object')
    for key in ('id', 'concept', 'primarySubject', 'anchorTier', 'anchorTerm'):
        _require(isinstance(candidate.get(key), str) and candidate[key].strip(),
                 'candidate needs a non-empty ' + key)
    _require(candidate['anchorTier'] in TIERS, 'unknown anchor tier: ' + candidate['anchorTier'])
    _require(isinstance(candidate.get('supportingElement', ''), str), 'supportingElement must be text')
    evidence = candidate.get('evidence')
    _require(isinstance(evidence, list) and evidence, 'candidate needs evidence')
    seen = set()
    for row in evidence:
        _require(isinstance(row, dict), 'evidence must be objects')
        _require(row.get('tier') in TIERS, 'evidence tier must be one of ' + ', '.join(TIERS))
        group = row.get('textGroupId')
        _require(group in cues, 'evidence textGroupId is not in the published content: ' + str(group))
        _require(row.get('quote') == cues[group], 'evidence quote is not the exact published text: ' + str(group))
        seen.add(group)
    scores = candidate.get('scores')
    _require(isinstance(scores, dict) and set(scores) == set(SCORE_AXES), 'candidate needs exactly the six scores')
    for axis in SCORE_AXES:
        _require(isinstance(scores[axis], int) and 0 <= scores[axis] <= 2,
                 'score must be an integer 0-2: ' + axis)
    normalized = dict(candidate)
    normalized['total'] = sum(scores[axis] for axis in SCORE_AXES)
    normalized['evidence'] = evidence
    return normalized


def validate_design(design, context):
    """Return the normalized design or raise DesignError with the first violated rule."""
    _require(isinstance(design, dict), 'design must be an object')
    _require(design.get('schemaVersion') == SCHEMA, 'expected ' + SCHEMA)
    _require(design.get('pageId') == context['pageId'], 'pageId does not match the release')
    _require(design.get('sourceIdentitySha256') == context['sourceIdentitySha256'],
             'sourceIdentitySha256 does not match the published source')
    _require(design.get('contentSha256') == context['contentSha256'],
             'contentSha256 does not match the published content')
    _require(design.get('title') == context['title'], 'title does not match the published title')
    candidates = design.get('candidates')
    _require(isinstance(candidates, list) and 2 <= len(candidates) <= 4, 'design needs 2-4 candidates')
    candidates = [_candidate(candidate, context['cues']) for candidate in candidates]
    _require(len({candidate['id'] for candidate in candidates}) == len(candidates), 'candidate ids must be unique')
    chosen_id = (design.get('choice') or {}).get('candidateId')
    chosen = next((candidate for candidate in candidates if candidate['id'] == chosen_id), None)
    _require(chosen is not None, 'choice.candidateId must name a candidate')
    _require(chosen['anchorTier'] != 'illustration',
             'the chosen primary subject cannot be anchored only in a sermon illustration')
    anchored = (chosen['anchorTerm'] in (design.get('title') or '') or
                any(chosen['anchorTerm'] in row['quote'] for row in chosen['evidence']
                    if row['tier'] != 'illustration'))
    _require(anchored, 'the chosen anchor term must appear in the title or in a non-illustration evidence quote')
    best = max(candidate['total'] for candidate in candidates)
    if chosen['total'] < best:
        _require(str((design.get('choice') or {}).get('overrideReason', '')).strip(),
                 'the chosen candidate is not the highest score; add choice.overrideReason')
    prompt = design.get('artPrompt')
    _require(isinstance(prompt, str) and prompt.strip(), 'design needs an expanded artPrompt')
    _require('{{' not in prompt and '}}' not in prompt, 'artPrompt still contains placeholders')
    _require(len(prompt) <= PROMPT_LIMIT, 'artPrompt is too long')
    for marker in TEMPLATE_MARKERS:
        _require(marker in prompt, 'artPrompt must be expanded from the poster prompt template (missing: ' + marker + ')')
    user = design.get('userChoice') or {}
    _require(user.get('status') in ('pending', 'confirmed'), 'userChoice.status must be pending or confirmed')
    if user.get('status') == 'confirmed' and user.get('candidateId') is not None:
        _require(any(candidate['id'] == user['candidateId'] for candidate in candidates),
                 'userChoice.candidateId must name a candidate')
    normalized = dict(design)
    normalized['candidates'] = candidates
    normalized['choice'] = dict(design.get('choice') or {},
                                total=chosen['total'],
                                bestTotal=best)
    normalized['validation'] = dict(validatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                    chosenTier=chosen['anchorTier'],
                                    chosenTotal=chosen['total'],
                                    warnings=(['user choice is pending'] if user.get('status') == 'pending' else []))
    return normalized


def run(design_path, release, page_id, locale, out):
    design_path, out = Path(design_path).resolve(), Path(out).resolve()
    raw = design_path.read_bytes()
    design = json.loads(raw.decode('utf-8'))
    context = load_context(release, page_id, locale)
    normalized = validate_design(design, context)
    prompt = normalized['artPrompt']
    prompt_sha = sha(prompt.encode('utf-8'))
    receipt = dict(schemaVersion=RECEIPT_SCHEMA, pageId=page_id, locale=locale,
                   designSha256=sha(raw), designPath=str(design_path),
                   sourceIdentitySha256=context['sourceIdentitySha256'],
                   contentSha256=context['contentSha256'],
                   chosenCandidate=normalized['choice']['candidateId'],
                   chosenTotal=normalized['choice']['total'],
                   candidateTotals={candidate['id']: candidate['total'] for candidate in normalized['candidates']},
                   promptSha256=prompt_sha, promptBytes=len(prompt.encode('utf-8')),
                   userChoice=normalized.get('userChoice', {}),
                   warnings=normalized['validation']['warnings'],
                   validatedAt=normalized['validation']['validatedAt'])
    out.mkdir(parents=True, exist_ok=True)
    for name in ('poster-design.json', 'art-prompt.txt', 'design-receipt.json'):
        _require(not (out / name).exists(), 'output is not empty; use a fresh directory: ' + name)
    (out / 'poster-design.json').write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (out / 'art-prompt.txt').write_text(prompt, encoding='utf-8')
    (out / 'design-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--design', required=True, help='poster-design.json v2 written from the published brief')
    parser.add_argument('--release', required=True, help='release snapshot containing public/multilingual-v*.json')
    parser.add_argument('--page-id', required=True)
    parser.add_argument('--locale', default='zh-Hans', help='content locale the design was drafted from')
    parser.add_argument('--out', required=True, help='fresh directory for the validated design, art prompt and receipt')
    args = parser.parse_args(argv)
    try:
        receipt = run(args.design, args.release, args.page_id, args.locale, args.out)
    except (DesignError, OSError, ValueError, KeyError) as error:
        sys.exit(str(error))
    print(json.dumps(dict(status='validated', chosen=receipt['chosenCandidate'],
                          totals=receipt['candidateTotals'], promptSHA256=receipt['promptSha256'],
                          warnings=receipt['warnings'], out=args.out)))


if __name__ == '__main__':
    main()
