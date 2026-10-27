#!/usr/bin/env python3
"""Blind per-group ranking of the four translation variants from the Terra A/B.

The judge is ``gpt-6.1-sol`` high through the ChatGPT-authenticated Codex CLI,
a model that is not one of the arms. Arm labels are shuffled per group and the
mapping is written only after all judge calls finish; a judge failure stops the
run without exposing the key. Experiment only, machine evidence only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JUDGE_MODEL = 'gpt-6.1-sol'
LABELS = ('A', 'B', 'C', 'D')
SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'group': {'type': 'string'},
        'ranking': {'type': 'array', 'minItems': 4, 'maxItems': 4,
                    'items': {'type': 'string', 'enum': list(LABELS)}},
        'severe': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'properties': {'label': {'type': 'string', 'enum': list(LABELS)},
                           'sourceUnitId': {'type': 'string'},
                           'problem': {'type': 'string'}},
            'required': ['label', 'sourceUnitId', 'problem']}},
        'notes': {'type': 'object', 'additionalProperties': False,
                  'properties': {label: {'type': 'string'} for label in LABELS},
                  'required': list(LABELS)},
    },
    'required': ['group', 'ranking', 'severe', 'notes'],
}
SYSTEM = '''You are an independent bilingual evaluator for Chinese sermon subtitles.
You receive one English sermon excerpt and four Chinese translations A-D of the same units.

Rank the four versions from best (1st) to worst (4th) using these criteria, in order:
1. Fidelity: no added, dropped or strengthened meaning; negation, numbers, names, quotation
   boundaries and incomplete/self-corrected speech preserved.
2. Project terminology and format: use 沙盒 (not 沙箱), 人工智能 (not AI), book names in
   《》, 神/主/祂 for God/the Lord; do not add explanatory words that the source does not say.
3. Natural spoken Simplified Chinese suitable for sermon subtitles.

Mark a version "severe" only for a meaning-changing error (negation, number, name,
quotation, added or removed proposition). Style, register and terminology slips go in notes.
Do not reward or penalize by position. Return only JSON conforming to the schema.'''


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha(value) -> str:
    return sha_bytes(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


def save(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def save_new(path: Path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def judge_prompt(entry):
    lines = [SYSTEM, '', 'GROUP: ' + entry['group'], '', 'ENGLISH UNITS:']
    for unit in entry['englishUnits']:
        lines.append(f"[{unit['sourceUnitId']}] {unit['english']}")
    for label in LABELS:
        lines.append('')
        lines.append('VERSION ' + label + ':')
        for unit_id, text in zip([unit['sourceUnitId'] for unit in entry['englishUnits']],
                                 entry['variants'][label]):
            lines.append(f'  [{unit_id}] {text}')
    return '\n'.join(lines)


def run_judge(entry, job: Path, env, timeout=300):
    job.mkdir(parents=True, exist_ok=True)
    job = job.resolve()
    prompt = judge_prompt(entry)
    prompt_sha = sha_bytes(prompt.encode())
    if (job / 'result.json').is_file() and (job / 'meta.json').is_file():
        meta = json.loads((job / 'meta.json').read_text())
        if meta.get('promptSha256') == prompt_sha:
            return json.loads((job / 'result.json').read_text()), meta
    if job.exists() and any(job.iterdir()) and not (job / 'started.json').is_file():
        raise SystemExit('unidentified judge directory ' + str(job))
    save_new(job / 'started.json', {'promptSha256': prompt_sha,
                                    'startedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
    (job / 'prompt.txt').write_text(prompt, encoding='utf-8')
    save(job / 'schema.json', SCHEMA)
    cli = Path.home() / '.local/bin/codex'
    command = [str(cli), 'exec', '--ignore-user-config', '--ephemeral', '-m', JUDGE_MODEL,
               '-c', 'service_tier="fast"', '-c', 'model_reasoning_effort="high"', '--json',
               '-s', 'read-only', '--skip-git-repo-check',
               '--output-schema', str(job / 'schema.json'), '-o', str(job / 'result.json'),
               '--enable', 'fast_mode', '-']
    save(job / 'command.json', command)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='tongxing-blind-ab-') as cwd:
        with (job / 'events.jsonl').open('w') as stdout, (job / 'stderr.txt').open('w') as stderr:
            process = subprocess.run(command, input=prompt, env=env, cwd=cwd, text=True,
                                     stdout=stdout, stderr=stderr, timeout=timeout)
    elapsed = time.monotonic() - started
    rows = [json.loads(line) for line in (job / 'events.jsonl').read_text().splitlines() if line.strip()]
    threads = [row['thread_id'] for row in rows if row.get('type') == 'thread.started']
    completions = [row for row in rows if row.get('type') == 'turn.completed']
    tools = [row['item']['type'] for row in rows if row.get('type', '').startswith('item.')
             and row.get('item', {}).get('type') not in {None, 'agent_message', 'reasoning'}]
    if process.returncode or len(threads) != 1 or len(completions) != 1 or tools:
        raise RuntimeError('judge_terminal_or_tool_failure_inspect_events')
    result = json.loads((job / 'result.json').read_text())
    assert result['group'] == entry['group']
    assert sorted(result['ranking']) == list(LABELS), 'ranking is not a permutation'
    for row in result['severe']:
        assert row['label'] in LABELS
    meta = {'promptSha256': prompt_sha, 'model': JUDGE_MODEL, 'effort': 'high',
            'serviceTier': 'fast', 'elapsedSeconds': elapsed,
            'usage': completions[0].get('usage') or {}, 'threadId': threads[0],
            'promptSha256': prompt_sha, 'resultSha256': sha(result)}
    save(job / 'meta.json', meta)
    return result, meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--translations', type=Path,
                        default=Path('artifacts/terra-ab-20261026/run/translations.json'))
    parser.add_argument('--out', type=Path, default=Path('artifacts/terra-ab-20261026/run/blind'))
    args = parser.parse_args()
    translations = json.loads(args.translations.read_text())
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('OPENAI_') and key != 'CODEX_API_KEY'}
    auth = json.loads((Path(env.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'auth.json').read_text())
    assert auth.get('auth_mode') == 'chatgpt' and not auth.get('OPENAI_API_KEY')
    salt_path = out / 'salt.json'
    if salt_path.exists():
        salt = json.loads(salt_path.read_text())['salt']
    else:
        salt = os.urandom(8).hex()
        save_new(salt_path, {'salt': salt, 'purpose': 'per-group label permutation; revealed only after judging'})
    arms = sorted(translations[0]['arms'])
    entries, key = [], {}
    for row in translations:
        order = arms[:]
        random.Random(hashlib.sha256((salt + row['group']).encode()).hexdigest()).shuffle(order)
        mapping = dict(zip(LABELS, order))
        key[row['group']] = mapping
        entries.append({'group': row['group'],
                        'englishUnits': row['source']['englishUnits'],
                        'variants': {label: [unit['targetText'] for unit in row['arms'][arm]['validation']['units']]
                                     for label, arm in mapping.items()}})
    save(out / 'blind.json', entries)
    save(out / 'blind-key.json', key)
    results, meta_rows = [], []
    for entry in entries:
        result, meta = run_judge(entry, out / 'judge' / entry['group'], env)
        results.append(result)
        meta_rows.append({'group': entry['group'], **meta})
        print(json.dumps({'group': entry['group'], 'ranking': result['ranking'],
                          'seconds': round(meta['elapsedSeconds'], 3)}, ensure_ascii=False), flush=True)
    save(out / 'rankings.json', results)
    save(out / 'judge-summary.json', meta_rows)
    points = {label: 0 for label in LABELS}
    tally = {arm: {'first': 0, 'second': 0, 'third': 0, 'fourth': 0, 'borda': 0,
                   'severe': 0, 'ranks': []} for arm in arms}
    for result in results:
        for position, label in enumerate(result['ranking']):
            arm = key[result['group']][label]
            tally[arm]['ranks'].append(position + 1)
            tally[arm]['borda'] += len(LABELS) - position
            tally[arm][('first', 'second', 'third', 'fourth')[position]] += 1
        for row in result['severe']:
            tally[key[result['group']][row['label']]]['severe'] += 1
    for arm, values in tally.items():
        values['medianRank'] = sorted(values['ranks'])[len(values['ranks']) // 2]
    save(out / 'score.json', {'judge': JUDGE_MODEL, 'groups': len(results), 'arms': arms,
                              'bordaRule': '4/3/2/1 per group (4 = first)', 'tally': tally})
    print(json.dumps({'score': tally}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
