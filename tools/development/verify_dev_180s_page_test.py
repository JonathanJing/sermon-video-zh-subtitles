"""Zero-provider preflight for the fixed diagnostic clip; never creates approval or publishes."""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timedelta, timezone
import html
import json
import os
from pathlib import Path
import subprocess
import sys
# Support both python -m scripts.<name> and direct script invocation.
if __package__ in (None, ''):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.sermon_unified import contracts as c

MEDIA_SHA = '79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b'
MEDIA_DURATION = 180.013167
LOCALES = ('zh-Hans', 'ko', 'es')


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def verify(source_run, out):
    source_run, out = Path(source_run).resolve(), Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    media_root = source_run / 'dev-candidate/hosting/public/media/dryrun-20261001-dev-full-180s'
    media = media_root / 'source.mp4'
    if c.file_sha(media) != MEDIA_SHA:
        raise ValueError('Fixed clip SHA changed')
    source = c.read(source_run / 'source.json')
    anchors = c.read(source_run / 'anchor-manifest.json')
    media_rows = []
    for path in [media] + [next(media_root.glob(locale + '-*.mp3')) for locale in LOCALES]:
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                '-of', 'json', str(path)], capture_output=True, text=True, check=True)
        duration = float(json.loads(probe.stdout)['format']['duration'])
        subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-map', '0:a:0',
                        '-f', 'null', '-'], capture_output=True, check=True, timeout=600)
        media_rows.append({'path': str(path), 'sha256': c.file_sha(path),
                           'durationSeconds': duration, 'fullAudioDecode': 'passed'})
    if abs(media_rows[0]['durationSeconds'] - MEDIA_DURATION) > .002:
        raise ValueError('Fixed clip duration changed')
    now = datetime.now(timezone.utc)
    modules = c.required_modules()
    manifest = {
        'schemaVersion': 'sermon-unified-run-manifest-v2', 'productionRunId': out.name,
        'runRevision': 1, 'jobRoot': str(out / 'jobs'),
        'content': {'contentId': out.name, 'pageId': 'mockup-20261005-dev-180s',
                    'category': 'podcast', 'sourceDate': '2026-09-27'},
        # This file is already a clip: execution coordinates start at zero.
        # Original [60,240] context is retained in the report, not silently used here.
        'source': {'sourceId': 'fixed-180s-diagnostic-clip', 'mediaSha256': MEDIA_SHA,
                   'durationSeconds': MEDIA_DURATION, 'window': {'startSeconds': 0,
                   'endSeconds': MEDIA_DURATION, 'timeBase': 'source_media',
                   'approvalReceiptSha256': None}},
        'locales': [], 'policies': [], 'canaryScope': 'media_verified',
        'activeScope': 'media_verified', 'finalScope': 'dual_production_verified',
        'budget': {'currency': 'USD', 'limitMicroUsd': 0}, 'transport': 'fixture',
        'fixtureSetId': 'dev-180s-20261001',
        'executionAdmission': {'modules': modules, 'closureSha256': c.closure(modules)},
        'bindings': {'media': {'path': str(media), 'sha256': MEDIA_SHA}},
        'executionWindow': {'timezone': 'America/Los_Angeles',
                            'startsAt': (now - timedelta(minutes=1)).isoformat(),
                            'deadlineAt': (now + timedelta(hours=1)).isoformat()},
        'steps': [{'id': 'media', 'stageId': 'media_verify', 'adapter': 'media.verify',
                   'dependsOn': [], 'scope': 'media_verified'}]}
    save(out / 'media-manifest.json', manifest)
    env = {k: v for k, v in os.environ.items() if k not in ('OPENAI_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY')}
    def cli(label, *args, accepted=(0,)):
        result = subprocess.run([sys.executable, str(c.ROOT / 'scripts/sermon.py'), *args,
                                 '--state-root', str(out / 'store'), '--json'],
                                capture_output=True, text=True, timeout=180, env=env)
        (out / (label + '.stderr.log')).write_text(result.stderr)
        value = json.loads(result.stdout)
        save(out / (label + '.json'), value)
        if result.returncode not in accepted:
            raise RuntimeError(f'{label}: exit {result.returncode}')
        return value
    plan = cli('media-plan', 'run', 'plan', '--manifest', str(out / 'media-manifest.json'))
    submitted = cli('media-submit', 'run', 'submit', '--manifest', str(out / 'media-manifest.json'),
                    '--plan-hash', plan['plan']['planHash'])
    result = cli('media-result', 'job', 'wait', '--run-id', submitted['subject']['id'], '--timeout', '60')
    if result['outcome'] != 'succeeded' or result['execution']['productionEligible']:
        raise ValueError('Media-only result differs')
    gated = copy.deepcopy(manifest)
    gated.update(activeScope='layer2_machine_candidate', canaryScope='layer2_machine_candidate')
    save(out / 'unapproved-source-manifest.json', gated)
    blocked = cli('unapproved-source-plan', 'run', 'plan', '--manifest', str(out / 'unapproved-source-manifest.json'), accepted=(4,))
    forbidden = copy.deepcopy(manifest)
    forbidden['steps'].append({'id': 'delivery', 'stageId': 'publish_endpoint',
                               'adapter': 'app.delivery', 'dependsOn': ['media'], 'scope': 'dev_reader_verified'})
    blockers = c.admit(forbidden, out)
    if 'fixture_provider_forbidden' not in blockers:
        raise ValueError('Fixture unexpectedly allowed production adapter')
    unit_text = {x['sourceUnitId']: x['english'] for x in anchors['sourceUnits']}
    sections = ['<!doctype html><meta charset="utf-8"><title>固定三分钟审核材料</title>',
                '<style>body{max-width:1000px;margin:40px auto;font:18px/1.6 sans-serif}td{vertical-align:top;padding:12px}table{width:100%}audio,video{max-width:100%}</style>',
                '<h1>固定三分钟：待审核的历史诊断输出</h1>',
                '<p>测试材料，非正常四层发行。未创建批准；大纲、默想尚无产物。视频为原素材60–240秒；下列机器译文和音频未经本轮人工批准。</p>',
                f'<video controls src="{html.escape(media.as_uri(), quote=True)}"></video>']
    candidates = {}
    for locale in LOCALES:
        candidate_path = next((source_run / 'locales' / locale / 'machine-candidates').glob('*/candidate.json'))
        candidate = c.read(candidate_path)
        candidates[locale] = {'path': str(candidate_path), 'sha256': c.file_sha(candidate_path), 'groups': len(candidate['groups'])}
        track = next(media_root.glob(locale + '-*.mp3'))
        sections.extend([f'<h2>{locale}</h2>', f'<audio controls src="{html.escape(track.as_uri(), quote=True)}"></audio>', '<table>'])
        for group in candidate['groups']:
            english = ' '.join(unit_text[x] for x in group['sourceUnitIds'])
            sections.append(f'<tr><td>{html.escape(english)}</td><td>{html.escape(group["targetText"])}</td></tr>')
        sections.append('</table>')
    (out / 'review.html').write_text('\n'.join(sections))
    report = {'schemaVersion': 'dev-180s-page-test-preflight-v1', 'baseCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=c.ROOT, text=True).strip(),
              'status': 'blocked_before_page_generation', 'scope': 'real_clip_media_and_normal_admission',
              'originalWindow': {'startSeconds': 60, 'endSeconds': 240}, 'media': media_rows,
              'mediaCliOutcome': result['outcome'], 'productionEligible': False,
              'newPaidRequests': 0, 'providerDispatches': 0, 'modelReplayExecuted': False,
              'sourceStatus': source['status'], 'sourceUrlHash': source['source']['sourceUrlHash'],
              'sourceWindow': source['source']['approvedWindow'], 'translationCandidates': candidates,
              'admissionProbe': {'fixtureDeliveryBlockers': blockers, 'unapprovedSourceResult': blocked['outcome']},
              'study': {'outline': 'missing', 'meditation': 'missing'},
              'publication': {'beta': 'not_started', 'dev': 'not_started'},
              'deviceAcceptance': 'not_run'}
    save(out / 'summary.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.source_run, args.out), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
