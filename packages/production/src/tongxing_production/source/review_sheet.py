"""One Layer 1 review sheet, confirmed once.

After ASR the stage runs MFA, anchors and the machine judge speculatively and gathers every
decision a person still owns into one sheet: readings for numerals (proposed by rule),
transcript disagreements against a second transcript, the judge's rejected sentences, long
units without a safe boundary, and the four English source checks with their machine
evidence. The person edits one confirmation file. The stage then recomputes only what the
decisions touch (per-chunk MFA cache, content-addressed judge cache) and checks that nothing
else moved before it derives the English review from the confirmation.

This module is pure: it reads and returns data. The stage owns files, budgets and models.
"""
from __future__ import annotations

from datetime import datetime
import difflib
import hashlib
import json
import re
from typing import Any

from . import mfa_alignment as mfa
from . import sentence_interpretation as anchors

SHEET_SCHEMA = 'sermon-source-review-sheet-v1'
CONFIRMATION_SCHEMA = 'sermon-source-review-confirmation-v1'
DERIVATION_SCHEMA = 'sermon-source-review-derivation-v1'
CHECKS = ('sourceIdentity', 'transcriptCompleteness', 'wordAlignment', 'sentenceAndPauseBoundaries')
AMBIGUOUS = re.compile(r'\d[.,:/-]\d|\d(?:st|nd|rd|th)\b|[$€£%]', re.I)
MAGNITUDES = frozenset({'thousand', 'million', 'billion', 'trillion'})
# Words whose disagreement between two transcripts rarely changes meaning; such items stay on the
# sheet (every item is decided) but are grouped apart and default to keeping the ASR.
FILLERS = frozenset('um uh uhm mm hmm oh ah like yeah yes so and the a an i you know mean just kind of sort right okay ok well'.split())
ORDINAL_IRREGULAR = {'one': 'first', 'two': 'second', 'three': 'third', 'five': 'fifth', 'eight': 'eighth',
                     'nine': 'ninth', 'twelve': 'twelfth'}


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _core(token: str) -> str:
    token = re.sub(r'^[(\[\"\'“‘]+', '', token)
    return re.sub(r'[.,;:!?)\]\"\'”’]+$', '', token)


def _ordinal(words: list[str]) -> list[str]:
    last = words[-1]
    if last in ORDINAL_IRREGULAR:
        last = ORDINAL_IRREGULAR[last]
    elif last.endswith('y'):
        last = last[:-1] + 'ieth'
    else:
        last = last + 'th'
    return words[:-1] + [last]


def _integer(text: str) -> list[str] | None:
    if not text.isdigit() or (len(text) > 1 and text.startswith('0')):
        return None
    value = int(text)
    return mfa._number(value) if value < 1_000_000 else None


def propose_spoken_form(token: str, following: str | None = None) -> dict[str, Any] | None:
    """A rule-based reading for a numeral MFA refuses, or None when no rule is safe."""
    core = _core(token)
    following = _core(following or '').lower()
    match = re.fullmatch(r'\d{1,3}(?:,\d{3})+', core)
    if match:
        words = _integer(core.replace(',', ''))
        return {'words': words, 'rule': 'grouped_integer', 'confidence': 'high'} if words else None
    match = re.fullmatch(r'(\d+)(?:st|nd|rd|th)', core, re.I)
    if match:
        words = _integer(match.group(1))
        return {'words': _ordinal(words), 'rule': 'ordinal', 'confidence': 'high'} if words else None
    match = re.fullmatch(r'(\d+)\.(\d+)', core)
    if match:
        whole = _integer(match.group(1))
        return ({'words': whole + ['point'] + [mfa.SMALL[int(d)] for d in match.group(2)], 'rule': 'decimal',
                 'confidence': 'medium'} if whole else None)
    match = re.fullmatch(r'(\d+(?:\.\d+)?)%', core)
    if match:
        inner = propose_spoken_form(match.group(1)) if '.' in match.group(1) else None
        words = inner['words'] if inner else _integer(match.group(1))
        return {'words': words + ['percent'], 'rule': 'percent', 'confidence': 'high'} if words else None
    match = re.fullmatch(r'\$(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)', core)
    if match:
        amount = match.group(1)
        inner = propose_spoken_form(amount) if (',' in amount or '.' in amount) else None
        words = inner['words'] if inner else _integer(amount)
        if not words:
            return None
        if following in MAGNITUDES:
            # "$1.5 million" is said "one point five million dollars"; "dollars" belongs after the next token.
            return {'words': words, 'rule': 'currency_before_magnitude', 'confidence': 'medium',
                    'note': 'spoken "dollars" follows the magnitude word and is not in the transcript'}
        return {'words': words + ['dollars'], 'rule': 'currency', 'confidence': 'medium'}
    match = re.fullmatch(r'(\d{1,3}):(\d{1,3})', core)
    if match:
        chapter, verse = _integer(match.group(1)), _integer(match.group(2))
        return ({'words': chapter + verse, 'rule': 'chapter_verse', 'confidence': 'medium'}
                if chapter and verse else None)
    return None


def _unresolved(text: str, forms: dict[str, list[str]]) -> list[str]:
    try:
        mfa._reference(text, forms)
        return []
    except ValueError:
        return [token for token in text.split() if token not in forms and (
            AMBIGUOUS.search(token) or any(len(p) > 1 and p.startswith('0')
                                           for p in mfa.WORD_RE.findall(token) if p.isdecimal()))] or ['<reference>']


def spoken_form_items(references: list[dict[str, Any]], base_forms: dict[str, list[str]]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for row in references:
        tokens = row['text'].split()
        for position, token in enumerate(tokens):
            if token in base_forms or not (AMBIGUOUS.search(token) or any(
                    len(p) > 1 and p.startswith('0') for p in mfa.WORD_RE.findall(token) if p.isdecimal())):
                continue
            item = found.setdefault(token, {'token': token, 'rows': [], 'following': []})
            if row['id'] not in item['rows']:
                item['rows'].append(row['id'])
            item['following'].append(tokens[position + 1] if position + 1 < len(tokens) else None)
    items = []
    for number, token in enumerate(sorted(found), start=1):
        item = found[token]
        proposals = [propose_spoken_form(token, following) for following in item['following']]
        distinct = {json.dumps(p, sort_keys=True) for p in proposals}
        proposal = proposals[0] if len(distinct) == 1 else None
        items.append({'id': f'reading-{number:03d}', 'kind': 'spoken_form', 'token': token, 'rows': item['rows'],
                      'occurrences': len(item['following']), 'proposal': proposal,
                      'default': {'action': 'accept'} if proposal else {'action': 'words', 'words': None}})
    return items


def speculative_forms(base_forms: dict[str, list[str]], items: list[dict[str, Any]]) -> dict[str, list[str]]:
    forms = dict(base_forms)
    for item in items:
        if item['proposal']:
            forms[item['token']] = item['proposal']['words']
    return forms


def _norm(token: str) -> str:
    core = _core(token).lower().replace('’', "'")
    words = _integer(core)
    return ' '.join(words) if words else core


def row_word_times(row: dict[str, Any], aligned: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    words = [word for segment in aligned if str(segment.get('referenceChunkId')) == str(row['id'])
             for word in segment.get('wordTimes') or []]
    return words if len(words) == len(row['text'].split()) else None


def _subwords(tokens: list[str]) -> tuple[list[str], list[int]]:
    """Compare at sub-word level so dash spellings ("so—and" / "so, and") are not disagreements."""
    words, owners = [], []
    for index, token in enumerate(tokens):
        for part in re.split(r'[—–-]+', token):
            norm = _norm(part)
            if norm:
                words.append(norm)
                owners.append(index)
    return words, owners


def _token_bounds(owner: list[int], start: int, end: int) -> tuple[int, int]:
    """Smallest sub-word range covering whole tokens around [start, end); an empty range inside a token grows to it."""
    if end > start:
        while start > 0 and owner[start - 1] == owner[start]:
            start -= 1
        while end < len(owner) and owner[end] == owner[end - 1]:
            end += 1
        return start, end
    if 0 < start < len(owner) and owner[start - 1] == owner[start]:
        return _token_bounds(owner, start - 1, start + 1)
    return start, end


def _token_range(owner: list[int], start: int, end: int, tokens: int) -> tuple[int, int]:
    if end > start:
        return owner[start], owner[end - 1] + 1
    position = owner[start] if start < len(owner) else tokens
    return position, position


def cross_check(references: list[dict[str, Any]], secondary_text: str, label: str,
                aligned: list[dict[str, Any]], window_start: float) -> list[dict[str, Any]]:
    """Transcript disagreements: where a second transcript of the same window reads differently."""
    primary = [(r, i, token) for r, row in enumerate(references) for i, token in enumerate(row['text'].split())]
    secondary = secondary_text.split()
    a, a_owner = _subwords([token for _, _, token in primary])
    b, b_owner = _subwords(secondary)
    times = [row_word_times(row, aligned) for row in references]
    items = []
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            continue
        # Widen to whole tokens on both sides together. The neighbouring opcodes are equal blocks, so
        # sub-words added on one side pair one-to-one with sub-words on the other; repeat until stable.
        ws, we, xs, xe = i1, i2, j1, j2
        while True:
            ns, ne = _token_bounds(a_owner, ws, we)
            ms, me = _token_bounds(b_owner, max(0, xs - (ws - ns)), min(len(b), xe + (ne - we)))
            grown = (max(0, ns - (max(0, xs - (ws - ns)) - ms)), min(len(a), ne + (me - min(len(b), xe + (ne - we)))), ms, me)
            if grown == (ws, we, xs, xe):
                break
            ws, we, xs, xe = grown
        p1, p2 = _token_range(a_owner, ws, we, len(primary))
        s1, s2 = _token_range(b_owner, xs, xe, len(secondary))
        anchor = primary[min(p1, len(primary) - 1)]
        rows = {primary[k][0] for k in range(p1, p2)} or {anchor[0]}
        row_index = anchor[0]
        start = anchor[1] if p1 < len(primary) else anchor[1] + 1
        end = start + (p2 - p1)
        ours = [primary[k][2] for k in range(p1, p2)]
        theirs = secondary[s1:s2]
        if [_norm(t) for t in ours] == [_norm(t) for t in theirs]:
            continue
        words = {w for w in (_norm(t) for t in ours + theirs) if w}
        klass = 'filler' if words and words <= FILLERS else ('punctuation' if not words else 'content')
        word_times = times[row_index]
        at = None
        if word_times:
            position = min(start, len(word_times) - 1)
            at = round(window_start + float(word_times[position]['start']), 2)
        tokens = references[row_index]['text'].split()
        items.append({'kind': 'text_correction', 'class': klass, 'row': references[row_index]['id'],
                      'rowIndex': row_index, 'start': start, 'end': end, 'asr': ' '.join(ours),
                      'alternative': ' '.join(theirs), 'alternativeSource': label,
                      'crossesRows': len(rows) > 1, 'mediaSeconds': at,
                      'context': ' '.join(tokens[max(0, start - 6):start] + ['[' + ' '.join(ours) + ']']
                                          + tokens[end:end + 6]),
                      'default': {'action': 'keep'}})
    for number, item in enumerate(items, start=1):
        item['id'] = f'text-{number:03d}'
    return items


def _split_candidates(words: list[dict[str, Any]], current: set[str]) -> list[dict[str, Any]]:
    candidates = []
    for index in range(len(words) - 1):
        text = str(words[index]['text'])
        gap = float(words[index + 1]['start']) - float(words[index]['end'])
        if not (anchors.BREAK_PUNCTUATION.search(text) or gap >= 0.35):
            continue
        if anchors._dependent_clause_boundary(words, index) or words[index]['wordId'] in current:
            continue
        candidates.append({'afterWordId': words[index]['wordId'], 'after': text, 'pauseSeconds': round(gap, 2),
                           'firstUnitSeconds': round(float(words[index]['end']) - float(words[0]['start']), 2)})
    return candidates


def judge_items(manifest: dict[str, Any], judged: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    units: dict[str, list[dict[str, Any]]] = {}
    for unit in manifest['sourceUnits']:
        units.setdefault(unit['sourceSentenceId'], []).append(unit)
    failing = [row for row in judged.get('sentences', [])
               if not (row.get('verdict') == 'pass' and row.get('risk') != 'high'
                       and all(v == 'pass' for v in row.get('checks', {}).values()) and not row.get('unresolvedIssues'))]
    findings = []
    for number, row in enumerate(failing, start=1):
        sentence = units.get(row['sourceSentenceId'], [])
        words = [w for unit in sentence for w in unit['words']]
        current = {unit['words'][-1]['wordId'] for unit in sentence[:-1]}
        findings.append({'id': f'judge-{number:03d}', 'kind': 'judge_finding', 'sentenceId': row['sourceSentenceId'],
                         'units': [unit['english'] for unit in sentence], 'risk': row.get('risk'),
                         'failedChecks': sorted(k for k, v in row.get('checks', {}).items() if v != 'pass'),
                         'issues': row.get('unresolvedIssues', []), 'evidence': row.get('evidence', ''),
                         'splitCandidates': _split_candidates(words, current), 'default': {'action': 'keep'}})
    long_units = []
    verdicts = {row['sourceSentenceId']: row for row in judged.get('sentences', [])}
    for number, issue in enumerate([i for i in manifest.get('issues', [])
                                    if i.get('type') == 'clause_unit_exceeds_target_without_safe_boundary'], start=1):
        sentence = units.get(issue['sourceSentenceId'], [])
        words = [w for unit in sentence for w in unit['words']]
        verdict = verdicts.get(issue['sourceSentenceId'], {})
        long_units.append({'id': f'long-{number:03d}', 'kind': 'long_unit', 'sentenceId': issue['sourceSentenceId'],
                           'durationSeconds': round(issue['durationSeconds'], 2), 'english': issue.get('english'),
                           'judgeVerdict': verdict.get('verdict'), 'judgeFailedChecks':
                               sorted(k for k, v in verdict.get('checks', {}).items() if v != 'pass'),
                           'splitCandidates': _split_candidates(words, set()), 'default': {'action': 'accept'}})
    return findings, long_units


def check_evidence(*, identity: dict[str, Any], references: list[dict[str, Any]], aligned: list[dict[str, Any]],
                   manifest: dict[str, Any], judged: dict[str, Any], excluded_rows: list[str],
                   text_items: list[dict[str, Any]], backend: str | None) -> dict[str, Any]:
    rates = []
    for row in references:
        minutes = max((float(row['end']) - float(row['start'])) / 60, 1e-6)
        rates.append({'row': row['id'], 'words': len(row['text'].split()), 'wordsPerMinute': round(len(row['text'].split()) / minutes)})
    ordered = sorted(r['wordsPerMinute'] for r in rates)
    median = ordered[len(ordered) // 2] if ordered else 0
    content = [i for i in text_items if i['class'] == 'content']
    reference_words = sum(len(row['text'].split()) for row in references if row['id'] not in excluded_rows)
    aligned_words = sum(len(s.get('wordTimes') or []) for s in aligned)
    counts = judged.get('counts', {})
    return {
        'sourceIdentity': identity,
        'transcriptCompleteness': {'rows': len(references), 'wordsPerMinuteMedian': median,
                                   'slowRows': [r for r in rates if median and r['wordsPerMinute'] < median / 2],
                                   'contentDisagreements': len(content),
                                   'fillerDisagreements': sum(i['class'] == 'filler' for i in text_items)},
        'wordAlignment': {'backend': backend, 'referenceWords': reference_words, 'alignedWords': aligned_words,
                          'rowsNotSpeculativelyAligned': excluded_rows,
                          'durationOutliers': sum(i.get('type') == 'alignment_word_duration_outlier'
                                                  for i in manifest.get('issues', []))},
        'sentenceAndPauseBoundaries': {'unitPolicy': manifest['policy']['unitPolicy'],
                                       'maxUnitSeconds': manifest['policy']['maxUnitSeconds'],
                                       'sentences': manifest['counts']['sourceSentences'],
                                       'units': manifest['counts']['sourceUnits'],
                                       'longUnits': sum(i.get('type') == 'clause_unit_exceeds_target_without_safe_boundary'
                                                        for i in manifest.get('issues', [])),
                                       'judgePass': counts.get('sentencePass'), 'judgeFail': counts.get('sentenceFail'),
                                       'judgeStatus': judged.get('status')},
    }


def build_sheet(*, bindings: dict[str, Any], readings: list[dict[str, Any]], texts: list[dict[str, Any]],
                findings: list[dict[str, Any]], long_units: list[dict[str, Any]], evidence: dict[str, Any]) -> dict[str, Any]:
    items = readings + texts + findings + long_units
    return {'schemaVersion': SHEET_SCHEMA, 'bindings': bindings, 'items': items, 'checks': evidence,
            'counts': {'readings': len(readings), 'readingsUnresolved': sum(not i['proposal'] for i in readings),
                       'textContent': sum(i['class'] == 'content' for i in texts),
                       'textFiller': sum(i['class'] != 'content' for i in texts),
                       'judgeFindings': len(findings), 'longUnits': len(long_units)},
            'meaning': ('Confirming this sheet approves the four Layer 1 checks for the package the stage derives '
                        'from these decisions, provided the recomputation changes nothing outside them; '
                        'otherwise the stage stops and lists what moved, and no approval is written.')}


def confirmation_template(sheet: dict[str, Any], sheet_sha256: str) -> dict[str, Any]:
    return {'schemaVersion': CONFIRMATION_SCHEMA, 'sheetSha256': sheet_sha256, 'humanApproval': True,
            'simulation': False, 'confirmedBy': None, 'confirmedAt': None,
            'decisions': {item['id']: item['default'] for item in sheet['items']},
            'checks': {name: 'pending' for name in CHECKS}}


def validate_confirmation(sheet: dict[str, Any], sheet_sha256: str, value: dict[str, Any]) -> dict[str, Any]:
    fields = {'schemaVersion', 'sheetSha256', 'humanApproval', 'simulation', 'confirmedBy', 'confirmedAt', 'decisions', 'checks'}
    if not (isinstance(value, dict) and set(value) == fields and value['schemaVersion'] == CONFIRMATION_SCHEMA):
        raise ValueError('source_review_confirmation_invalid')
    if value['sheetSha256'] != sheet_sha256:
        raise ValueError('source_review_confirmation_for_another_sheet')
    simulation = value['simulation']
    if type(simulation) is not bool or value['humanApproval'] is not (not simulation):
        raise ValueError('source_review_confirmation_label_invalid')
    if not (isinstance(value['confirmedBy'], str) and value['confirmedBy'].strip()):
        raise ValueError('source_review_confirmation_unsigned')
    try:
        stamp = datetime.fromisoformat(str(value['confirmedAt']).replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError('source_review_confirmation_unsigned') from error
    if stamp.utcoffset() is None:
        raise ValueError('source_review_confirmation_unsigned')
    checks = value['checks']
    if not (isinstance(checks, dict) and set(checks) == set(CHECKS)
            and all(checks[name] in {'approved', 'rejected'} for name in CHECKS)):
        raise ValueError('source_review_confirmation_checks_undecided')
    items = {item['id']: item for item in sheet['items']}
    decisions = value['decisions']
    if not (isinstance(decisions, dict) and set(decisions) == set(items)):
        raise ValueError('source_review_confirmation_items_undecided')
    for item_id, decision in decisions.items():
        kind, action = items[item_id]['kind'], (decision or {}).get('action')
        ok = False
        if kind == 'spoken_form':
            ok = (action == 'accept' and items[item_id]['proposal'] and set(decision) == {'action'}) or (
                action == 'words' and set(decision) == {'action', 'words'} and isinstance(decision['words'], list)
                and decision['words'] and all(isinstance(w, str) and re.fullmatch(r"[a-z]+(?:'[a-z]+)*", w)
                                              for w in decision['words']))
        elif kind == 'text_correction':
            ok = (action == 'keep' and set(decision) == {'action'}) or (
                not items[item_id]['crossesRows'] and (
                    (action == 'take_alternative' and set(decision) == {'action'}) or
                    (action == 'replace' and set(decision) == {'action', 'text'} and isinstance(decision['text'], str))))
        elif kind in {'judge_finding', 'long_unit'}:
            keep = 'keep' if kind == 'judge_finding' else 'accept'
            ok = (action == keep and set(decision) == {'action'}) or (
                action == 'split_after' and set(decision) == {'action', 'wordIds'} and isinstance(decision['wordIds'], list)
                and decision['wordIds'] and all(isinstance(w, str) for w in decision['wordIds']))
        if not ok:
            raise ValueError(f'source_review_confirmation_decision_invalid:{item_id}')
    return {'decisions': decisions, 'checks': checks, 'simulation': simulation,
            'confirmedBy': value['confirmedBy'], 'confirmedAt': value['confirmedAt'],
            'rejectedChecks': [name for name in CHECKS if checks[name] == 'rejected']}


def derive(sheet: dict[str, Any], decided: dict[str, Any], base_forms: dict[str, list[str]],
           references: list[dict[str, Any]]) -> dict[str, Any]:
    """Spoken forms, per-row corrected text, boundary overrides and accepted long units from the decisions."""
    items = {item['id']: item for item in sheet['items']}
    decisions = decided['decisions']
    forms = dict(base_forms)
    changed_tokens = []
    for item_id, decision in decisions.items():
        item = items[item_id]
        if item['kind'] != 'spoken_form':
            continue
        words = item['proposal']['words'] if decision['action'] == 'accept' else decision['words']
        forms[item['token']] = words
        if not item['proposal'] or words != item['proposal']['words']:
            changed_tokens.append(item['token'])
    edits: dict[int, list[tuple[int, int, list[str], str]]] = {}
    for item_id, decision in decisions.items():
        item = items[item_id]
        if item['kind'] != 'text_correction' or decision['action'] == 'keep':
            continue
        replacement = (item['alternative'] if decision['action'] == 'take_alternative' else decision['text']).split()
        edits.setdefault(item['rowIndex'], []).append((item['start'], item['end'], replacement, item_id))
    corrected = {}
    for row_index, row_edits in edits.items():
        tokens = references[row_index]['text'].split()
        spans = sorted(row_edits, key=lambda e: e[0])
        for (s1, e1, _, a), (s2, _, _, b) in zip(spans, spans[1:]):
            if s2 < e1:
                raise ValueError(f'source_review_confirmation_overlapping_corrections:{a},{b}')
        for start, end, replacement, _ in reversed(spans):
            tokens = tokens[:start] + replacement + tokens[end:]
        text = ' '.join(tokens)
        if not text.strip():
            raise ValueError('source_review_confirmation_empties_a_row')
        corrected[row_index] = {'text': text, 'items': [e[3] for e in spans]}
    overrides, accepted = {}, []
    for item_id, decision in decisions.items():
        item = items[item_id]
        if item['kind'] in {'judge_finding', 'long_unit'} and decision['action'] == 'split_after':
            overrides[item['sentenceId']] = list(decision['wordIds'])
        elif item['kind'] == 'long_unit' and decision['action'] == 'accept':
            accepted.append(item['sentenceId'])
    token_rows = {row['id'] for row in references for token in changed_tokens if token in row['text'].split()}
    return {'forms': forms, 'corrected': corrected, 'overrides': overrides, 'acceptedLongUnits': accepted,
            'rowsWithChangedText': sorted(references[i]['id'] for i in corrected),
            'rowsWithChangedReadings': sorted(token_rows)}


def _sentences(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for unit in manifest['sourceUnits']:
        out.setdefault(unit['sourceSentenceId'], []).append(
            {'english': unit['english'], 'sourceWordIds': unit['sourceWordIds'], 'start': unit['start'], 'end': unit['end']})
    return out


def derivation_check(*, speculative_refs, final_refs, speculative_manifest, final_manifest, allowed_rows,
                     override_sentences) -> dict[str, Any]:
    """Whether recomputation changed anything the confirmation did not decide."""
    spec_rows = {row['id']: row['text'] for row in speculative_refs}
    unexpected_rows = [row['id'] for row in final_refs
                       if spec_rows.get(row['id']) != row['text'] and row['id'] not in allowed_rows]
    spec, final = _sentences(speculative_manifest), _sentences(final_manifest)
    def row_of(sentence_id):
        return sentence_id.rsplit('-s', 1)[0]
    unexpected_sentences, changed_sentences = [], []
    for sentence_id in sorted(set(spec) | set(final)):
        if spec.get(sentence_id) == final.get(sentence_id):
            continue
        changed_sentences.append(sentence_id)
        if row_of(sentence_id) not in allowed_rows and sentence_id not in override_sentences:
            unexpected_sentences.append(sentence_id)
    return {'withinConfirmation': not unexpected_rows and not unexpected_sentences,
            'unexpectedRows': unexpected_rows, 'unexpectedSentences': unexpected_sentences,
            'changedSentences': changed_sentences}


def render_markdown(sheet: dict[str, Any], sheet_sha256: str, *, confirmation_path: str, window_start: float) -> str:
    def clock(seconds):
        if seconds is None:
            return '—'
        seconds = int(seconds)
        return f'{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}'
    lines = ['# Layer 1 汇总单', '',
             f'汇总单哈希 `{sheet_sha256[:16]}`。确认方式：把同目录的 `review-confirmation.template.json` 另存为 `{confirmation_path}`，'
             '填 `confirmedBy` 和带时区的 `confirmedAt`，四项检查改成 `approved` 或 `rejected`，只改你不同意的决定，其余保持默认。', '',
             '确认的含义：同意下列决定，并同意按这些决定重算后的英文源包通过四项检查。系统只重算受影响的块和批；'
             '重算若改动了决定之外的任何句子，会停下并列出差异，不写批准。', '']
    c = sheet['counts']
    lines += ['| 类别 | 条数 | 默认 |', '|---|---|---|',
              f"| 读法（数字） | {c['readings']}，其中无法自动提议 {c['readingsUnresolved']} | 接受提议；无提议的必须填词 |",
              f"| 文字分歧：内容 | {c['textContent']} | 保留 ASR |",
              f"| 文字分歧：仅填充词或标点 | {c['textFiller']} | 保留 ASR |",
              f"| 裁判未通过的句子 | {c['judgeFindings']} | 保持（重算后仍会不通过） |",
              f"| 没有安全切点的长句 | {c['longUnits']} | 接受 |", '']
    items = sheet['items']
    readings = [i for i in items if i['kind'] == 'spoken_form']
    if readings:
        lines += ['## 一、读法', '', '| 编号 | 原文 | 出现 | 提议读法 | 规则 |', '|---|---|---|---|---|']
        for i in readings:
            p = i['proposal']
            lines.append(f"| {i['id']} | `{i['token']}` | {i['occurrences']} | {' '.join(p['words']) if p else '**需要你填**'} | "
                         f"{(p['rule'] + ('；' + p['note'] if p.get('note') else '')) if p else '—'} |")
        lines.append('')
    texts = [i for i in items if i['kind'] == 'text_correction' and i['class'] == 'content']
    if texts:
        lines += ['## 二、文字分歧（内容）', '', '两份转写不一致处。可选：`keep`、`take_alternative`、`replace`（给出替换整段 ASR 原文的文字）。', '',
                  '| 编号 | 时间 | ASR | 另一份 | 上下文 |', '|---|---|---|---|---|']
        for i in texts:
            lines.append(f"| {i['id']} | {clock(i['mediaSeconds'])} | {i['asr'] or '（无）'} | {i['alternative'] or '（无）'} | {i['context']} |")
        lines.append('')
    fillers = [i for i in items if i['kind'] == 'text_correction' and i['class'] != 'content']
    if fillers:
        lines += ['## 三、文字分歧（仅填充词或标点）', '', f'{len(fillers)} 处，默认保留 ASR，前 10 处：', '']
        for i in fillers[:10]:
            lines.append(f"- {i['id']} {clock(i['mediaSeconds'])}：「{i['asr'] or '（无）'}」/「{i['alternative'] or '（无）'}」")
        lines.append('')
    findings = [i for i in items if i['kind'] == 'judge_finding']
    if findings:
        lines += ['## 四、裁判未通过的句子', '']
        for i in findings:
            lines += [f"### {i['id']} `{i['sentenceId']}`（{i['risk']}，失败：{', '.join(i['failedChecks'])}）", '',
                      ' ‖ '.join(i['units']), '', '裁判：' + '；'.join(i['issues'] or [i['evidence'][:300]]), '',
                      '可选切点：' + ('、'.join(f"`{c['afterWordId']}`（{c['after']}，停 {c['pauseSeconds']}s）"
                                          for c in i['splitCandidates']) or '无'), '']
    long_units = [i for i in items if i['kind'] == 'long_unit']
    if long_units:
        lines += ['## 五、没有安全切点的长句', '', '| 编号 | 句子 | 时长 | 裁判 | 文本 |', '|---|---|---|---|---|']
        for i in long_units:
            lines.append(f"| {i['id']} | `{i['sentenceId']}` | {i['durationSeconds']}s | {i['judgeVerdict']} | {i['english']} |")
        lines.append('')
    lines += ['## 六、四项检查的机器证据', '', '```json', json.dumps(sheet['checks'], ensure_ascii=False, indent=1), '```', '']
    return '\n'.join(lines)
