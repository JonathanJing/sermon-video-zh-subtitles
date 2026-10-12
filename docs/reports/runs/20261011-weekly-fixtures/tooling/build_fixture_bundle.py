"""Build a redacted fixture bundle from this week's local artifacts for next week's development."""
import json, glob, os, re, shutil, hashlib, collections
from pathlib import Path

WL = Path('artifacts/weekend-live')
S = Path('<scratchpad>')
OUT = S / 'wt-report/docs/reports/runs/20261011-weekly-fixtures'
shutil.rmtree(OUT, ignore_errors=True)
OUT.mkdir(parents=True)
manifest = []
HOME = str(Path.home())


def redact(text):
    text = text.replace(HOME, '~').replace('~', '~')
    text = re.sub(r'\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+(?:\.\d+)?\b', '<spark-ip>', text)
    text = re.sub(r'/home/[A-Za-z0-9_-]+', '/home/<spark-user>', text)
    text = re.sub(r'\b[A-Za-z0-9_-]+@<spark-ip>', '<spark-user>@<spark-ip>', text)
    text = re.sub(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', '<email>', text)
    text = re.sub(r'\bsk-[A-Za-z0-9_-]{16,}', '<redacted-key>', text)
    text = re.sub(r'(?i)(api[_-]?key|token|secret|password)(["\']?\s*[:=]\s*["\']?)[^"\'\s,}]+', r'\1\2<redacted>', text)
    return text


def put(rel, content, src=None):
    p = OUT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)):
        content = json.dumps(content, ensure_ascii=False, indent=1) + '\n'
    content = redact(content)
    p.write_text(content)
    manifest.append({'path': rel, 'bytes': len(content.encode()), 'sha256': hashlib.sha256(content.encode()).hexdigest(),
                     'source': redact(str(src)) if src else 'derived'})


def copy(rel, src):
    put(rel, Path(src).read_text(), src)


def rd(p):
    return json.loads(Path(p).read_text())


T = WL / 'text-qc-54475d42'; AQ = WL / 'audio-qc-54475d42'; L4 = WL / 'layer4-54475d42'; ST = WL / 'study-54475d42'; L3 = WL / 'layer3-54475d42'

# 1. decisions
for p in sorted(glob.glob(str(T / '*-human-acceptance*.json'))):
    copy('decisions/text/' + Path(p).name, p)
for p in sorted(glob.glob(str(AQ / '*-human-acceptance*.json'))):
    copy('decisions/audio/' + Path(p).name, p)
for L in ('zh-Hans', 'ko', 'es'):
    for k in ('outline', 'meditation'):
        copy(f'decisions/study/{L}/{k}-artifact.json', ST / L / f'{k}-artifact.json')
        copy(f'decisions/study/{L}/{k}-review.json', ST / L / f'{k}-review.json')
    q = L4 / 'audio-review' / f'{L}-worksheet.approved.json'
    if q.exists():
        copy(f'decisions/audio-review/{L}-worksheet.approved.json', q)
    copy(f'decisions/audio-review/{L}/audio-human-review-receipt.json', L4 / 'audio-review' / L / 'audio-human-review-receipt.json')
for f in ('metadata-proposal-v1.json', 'metadata-approval-v1.json', 'metadata-approval-v1.evidence.txt', 'release-plan-prod-v2.json'):
    copy('decisions/layer4/' + f, L4 / f)
for p in glob.glob(str(ST / '*/*.evidence.txt')) + glob.glob(str(L4 / 'audio-review/approval.evidence.txt')):
    copy('decisions/evidence/' + '__'.join(Path(p).parts[-2:]), p)

# 2. text QC flags, waivers, calibrations
heads = {'zh-Hans': ('state-zh', 'v3-zh', WL / 'layer2-54475d42/text-r12/zh-Hans/candidate.json'),
         'ko': ('state-v3', 'v15-ko', WL / 'layer2-54475d42/recovered/ko/candidate.json'),
         'es': ('state-es-v4', 'v15-es', WL / 'layer2-54475d42/recovered/es/candidate.json')}
flags = {}
for L, (sd, run, cand) in heads.items():
    c = rd(cand); tt = {g['translationGroupId']: g['targetText'] for g in c['groups']}
    rows = []
    for p in sorted(glob.glob(str(T / sd / 'qc-receipts/text' / L / '*/entry-*.json'))):
        if p.endswith('.inputs.json'):
            continue
        r = rd(p)
        for x in r['results']:
            if x['status'] != 'pass':
                rows.append({'receipt': Path(p).parent.name[:12] + '/' + Path(p).name, 'groupId': x['groupId'],
                             'problems': x['problems'], 'targetText': tt.get(x['groupId'])})
    flags[L] = rows
    for p in glob.glob(str(T / run / L / 'text-waiver-*.json')) + glob.glob(str(T / run / L / 'calibration-*.json')):
        if not p.endswith('inputs.json'):
            copy(f'text-qc/{L}/' + Path(p).name, p)
    put(f'text-qc/{L}/preflight.json', rd(T / run / L / 'preflight.json'))
put('text-qc/flagged-groups.json', {'note': 'every group the text QC back-translation judge flagged in any screening of the final candidates (status != pass), with the translated text',
                                    'counts': {L: len(v) for L, v in flags.items()}, 'rows': flags})

# 3. audio QC flags and screening flags (c5)
aflags = {}; screen = {}
for L, sd in (('zh-Hans', 'state-zh'), ('ko', 'state-v3'), ('es', 'state-es-v4')):
    fs = [p for p in sorted(glob.glob(str(T / sd / 'qc-receipts/audio' / L / '*/entry-*.json')), key=os.path.getmtime) if not p.endswith('.inputs.json')]
    r = rd(fs[-1]); cand = rd(heads[L][2]); tt = {g['translationGroupId']: g['targetText'] for g in cand['groups']}
    aflags[L] = [{k: x.get(k) for k in ('groupId', 'status', 'issues', 'asrPrimary', 'asrPrimaryRecognized', 'asrSecondary', 'asrSecondaryRecognized', 'metrics')} | {'targetText': tt[x['groupId']]}
                 for x in r['results'] if x['status'] != 'pass']
    rn = {'zh-Hans': 'zh-Hans', 'ko': 'ko-v2', 'es': 'es-v2'}[L]
    sc = rd(L3 / L / f'spark-{rn}-c5/speech-job/asr-screening-receipt-c5.json')
    st = collections.Counter(x['status'] for x in sc['results'])
    screen[L] = {'status': sc['status'], 'counts': dict(st), 'asrSettings': sc.get('asrSettings'),
                 'flagged': [{k: x.get(k) for k in ('textGroupId', 'similarity', 'recognized', 'differences', 'status')} | {'targetText': tt[x['textGroupId']]}
                             for x in sc['results'] if x['status'] != 'pass']}
put('audio-qc/failed-units.json', {'note': 'units the audio QC (c5 packages) failed, with both ASR transcripts and metrics; ground truth for scoring-normalization work',
                                   'counts': {L: len(v) for L, v in aflags.items()}, 'rows': aflags})
put('audio-qc/screening-flags.json', {'note': 'Qwen3-ASR screening (c5) flagged units per locale with recognized text and differences', 'locales': screen})
for p in glob.glob(str(AQ / 'ko-c5b/ko/audio-calibration-*.json')) + glob.glob(str(AQ / '*-c5/*/track-check-*.json')):
    if not p.endswith('.inputs.json'):
        copy('audio-qc/' + '/'.join(Path(p).parts[-3:]), p)

# 4. timing fixtures
anchor = rd(WL / 'layer1-54475d42/output4-rebuild4/anchor-manifest.json')
put('timing/anchor-units.json', [{k: u[k] for k in ('sourceUnitId', 'start', 'end')} for u in anchor['sourceUnits']])
sched = {}
for L, rn in (('zh-Hans', 'zh-Hans'), ('ko', 'ko-v2'), ('es', 'es-v2')):
    final = rd(L3 / L / f'spark-{rn}-c5/speech-job/languages/{L}/synchronization/schedule.json')
    entry = {'final_c5': {'policy': final['policy'], 'trackDurationSeconds': final['trackDurationSeconds'], 'entries': final['entries']}}
    for tag in ('c', 'c2', 'c3', 'c4'):
        d = L3 / L / f'spark-{rn}-{tag}/speech-job/render-diagnostics.json'
        if d.exists():
            x = rd(d)
            entry[f'attempt_{tag}'] = {'status': x['status'], 'policy': x['schedule']['policy'], 'issues': len(x['schedule']['issues']),
                                      'lastPlannedEnd': x['schedule']['entries'][-1]['plannedEnd'] if x['schedule']['entries'] else None}
    raw = L3 / L / 'spark-output/speech-job/render-diagnostics.json' if L == 'zh-Hans' else None
    if raw and raw.exists():
        x = rd(raw)
        entry['raw_render'] = {'status': x['status'], 'policy': x['schedule']['policy'], 'issues': len(x['schedule']['issues']),
                               'maxLag': round(max(i['plannedEnd'] - i['sourceEnd'] for i in x['schedule']['issues']), 2),
                               'lastPlannedEnd': x['schedule']['entries'][-1]['plannedEnd'], 'entries': x['schedule']['entries']}
    sched[L] = entry
put('timing/schedules.json', {'note': 'planned unit starts/ends per locale: raw 8 s policy (zh), compaction attempts c..c4, and final c5 (120 s end-lag, 1 s tail); clipDurationSeconds 2131', 'locales': sched})
put('timing/mp3-bitrate-waveform-check.json', {
    'note': 'ko c3 PCM master re-encoded at three bitrates and compared with target_audio_auto_qc._waveform_comparison (TRACK_ENVELOPE settings)',
    'results': {'64k': {'audibleWindows': 34820, 'deviantWindows': 53, 'minCorrelation': 0.732888, 'maxRelativeError': 0.827209},
                '96k': {'audibleWindows': 34819, 'deviantWindows': 0, 'minCorrelation': 0.970151, 'maxRelativeError': 0.243291},
                '128k': {'audibleWindows': 34819, 'deviantWindows': 0, 'minCorrelation': 0.985098, 'maxRelativeError': 0.175409}}})

# 5. token usage per ledger
usage = {}
for root in sorted(glob.glob(str(T / '.api-budget-*'))) + sorted(glob.glob(str(WL / 'layer2-54475d42/.layer2-jobs*.layer2-budget'))):
    n = tok = ptok = ctok = rtok = 0
    for p in glob.glob(root + '/responses/**/*.json', recursive=True):
        try:
            j = rd(p)
        except Exception:
            continue
        u = (j.get('response') or {}).get('usage') or j.get('usage') or {}
        if u:
            n += 1; tok += u.get('total_tokens', 0); ptok += u.get('prompt_tokens', 0); ctok += u.get('completion_tokens', 0)
            rtok += (u.get('completion_tokens_details') or {}).get('reasoning_tokens', 0)
    usage[Path(root).name] = {'responses': n, 'totalTokens': tok, 'promptTokens': ptok, 'completionTokens': ctok, 'reasoningTokens': rtok}
put('cost/token-usage-by-ledger.json', {'note': "summed from cached provider responses; the ledgers' own costMicrousd fields are 0 for every request (gap noted in the retrospective)",
                                        'ledgers': usage, 'totals': {'responses': sum(v['responses'] for v in usage.values()), 'totalTokens': sum(v['totalTokens'] for v in usage.values())}})

# 6. Layer 2 reviewer repair records and executions
reps = []
for d in glob.glob(str(WL / 'layer2-54475d42/.layer2-jobs*.layer2-repair')):
    for p in glob.glob(d + '/**/*.json', recursive=True):
        try:
            reps.append({'ledger': Path(d).name, 'file': '/'.join(Path(p).parts[-2:]), 'record': rd(p)})
        except Exception:
            pass
put('layer2/reviewer-repair-records.json', {'note': 'every auto-repair record the Layer 2 independent review triggered; input for deciding whether the second-model pass earns its cost', 'count': len(reps), 'records': reps})
for p in glob.glob(str(WL / 'layer2-54475d42/execution-*.json')):
    copy('layer2/' + Path(p).name, p)

# 7. publication summaries and receipts (both sessions)
for d in ('publish-shell-v1', 'publish-shell-v2', 'publish-video-v1', 'publish-posters-v1', 'publish-default-week-v1', 'beta-sync-v1', 'push-preparation-v1'):
    for f in ('summary.json', 'deployment-receipt.json', 'http-receipt.json'):
        q = L4 / d / f
        if q.exists():
            copy(f'publication/{d}/{f}', q)
for f in ('http-verification-prod-v1.json', 'production-http-verification-v1.json', 'prod-asset-first-v2/asset-first-report.json',
          'sealed-prod-v2/seal-report.json', 'prod-shell-v1/shell-report.json', 'live-baseline-7089e037/baseline-receipt.json'):
    q = L4 / f
    if q.exists():
        j = rd(q)
        if isinstance(j.get('files'), list) and len(j['files']) > 50:
            j = {**j, 'files': f"<{len(j['files'])} rows omitted>"}
        put('publication/' + f.replace('/', '__'), j, q)

# 8. tooling from both sessions
for p in glob.glob(str(L3 / 'run_spark_*.py')) + glob.glob(str(L3 / 'tooling/chains/*.sh')) + glob.glob(str(L4 / '*.py')) + glob.glob(str(L4 / '*.sh')) + glob.glob(str(ST / '*.py')):
    copy('tooling/' + Path(p).name, p)
for d in ('publish-shell-v1', 'publish-video-v1', 'publish-posters-v1', 'publish-default-week-v1', 'beta-sync-v1'):
    for f in ('prepare.py', 'verify.py', 'config.json'):
        q = L4 / d / f
        if q.exists():
            copy(f'tooling/{d}/{f}', q)

put('manifest.json', {'schemaVersion': 'sermon-weekly-fixture-bundle-v1', 'week': '2026-10-11', 'pageId': 'resi-20261011-54475d42',
                      'redaction': 'home paths -> ~, Spark host/user/IP -> placeholders, emails, keys; applied to every file', 'files': manifest})
print('files', len(manifest), 'bytes', sum(m['bytes'] for m in manifest))
