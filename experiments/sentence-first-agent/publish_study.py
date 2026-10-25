#!/usr/bin/env python3
"""Publish this week's outline and meditation with the page (release v3, four products).

The study artifacts come from build_study.py. This driver stages two deploys through the
in-place replacement channel:

1. ``assets``: the page gains the study sections, the study files appear, and the page's
   content bytes stay as published; the live release still describes the previous bytes
   (pending replacement).
2. ``finish``: the v3 releases (four products), the catalogs that hash them, and the
   refreshed alignment sidecar are published together and validated strictly.

    .venv/bin/python experiments/sentence-first-agent/publish_study.py assets
    .venv/bin/python experiments/sentence-first-agent/publish_study.py verify
    .venv/bin/python experiments/sentence-first-agent/publish_study.py finish
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments/sentence-first-agent'))
sys.path.insert(0, str(ROOT / 'packages/production/src'))
import publish_sat400_20261025 as base  # noqa: E402
from tongxing_production.delivery import contract  # noqa: E402
from tongxing_production.delivery import published_page_replace as replace  # noqa: E402

PAGE_ID = 'revelation-jesus-wins-20261025'
DATE = '2026-10-24'
LOCALES = ('zh-Hans', 'ko', 'es')
A = ROOT / 'artifacts/sentence-first-agent'
LIVE = A / '20261024-sat400-v2-study-publish/baseline-8'
STUDY = A / '20261024-sat400-v2-study'
OUT = A / '20261024-sat400-v2-study-publish'
ORIGIN = 'https://ai-for-god-sermon-audio.web.app'
TITLES = {'zh-Hans': '耶稣得胜 · 启示录 12–13 章', 'ko': '예수님은 승리자이십니다 · 요한계시록 12–13장',
          'es': 'Jesús es el vencedor · Apocalipsis 12–13'}
SPEAKER = 'Eric Geiger'
SERIES = {'zh-Hans': '启示录：耶稣带来的安慰与盼望', 'ko': '요한계시록: 예수님이 주시는 위로와 소망',
          'es': 'Apocalipsis: el consuelo y la esperanza que trae Jesús'}
SOURCE_URL = 'https://www.youtube.com/watch?v=4gcPgvARNaM'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def page_html(locale, content, outline, meditation):
    body = ''.join(f"<p>{html.escape(cue['text'])}</p>" for cue in content['cues'])
    def section(anchor, title, sections):
        blocks = ''.join(
            f"<h3>{html.escape(s['title'])}</h3>"
            + ''.join(f"<p>{html.escape(line)}</p>" for line in s['body'].split('\n') if line.strip())
            for s in sections)
        return f'<section id="{anchor}"><h2>{html.escape(title)}</h2>{blocks}</section>'
    return (f'<!doctype html><html lang="{locale}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(TITLES[locale])}</title>'
            '<style>body{max-width:48rem;margin:auto;padding:1.2rem;font:1.1rem/1.7 system-ui}'
            'audio{width:100%}section{margin-top:2.2rem;border-top:1px solid #ddd;padding-top:1rem}</style></head>'
            f'<body><h1>{html.escape(TITLES[locale])}</h1><p>{DATE} · {SPEAKER} · {html.escape(SERIES[locale])}</p>'
            f'<audio controls preload="none" src="/media/{PAGE_ID}/{locale}.mp3"></audio>'
            f'<p><a href="{SOURCE_URL}">来源 / source</a></p>'
            f'{section("study-outline", "大纲 / 개요 / Bosquejo", outline["sections"])}'
            f'{section("study-meditation", "默想 / 묵상 / Meditación", meditation["sections"])}'
            f'<section id="transcript"><h2>全文</h2>{body}</section></body></html>')


def build():
    """Write the public study files, the study page HTML and the v3 release drafts."""
    for stale in (OUT / 'assets', OUT / 'releases'):
        if stale.exists():
            shutil.rmtree(stale)
    public = OUT / 'assets/public'
    live = LIVE / 'public'
    for locale in LOCALES:
        outline = read(STUDY / f'assets/public/study/{PAGE_ID}/{locale}/outline.json')
        meditation = read(STUDY / f'assets/public/study/{PAGE_ID}/{locale}/meditation.json')
        for rel in (f'content/{PAGE_ID}/{locale}.json', f'captions/{PAGE_ID}/{locale}.json',
                    f'media/{PAGE_ID}/{locale}.mp3'):
            dst = public / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(live / rel, dst)
        content = read(live / f'content/{PAGE_ID}/{locale}.json')
        content_bytes = (live / f'content/{PAGE_ID}/{locale}.json').read_bytes()
        content_sha = hashlib.sha256(content_bytes).hexdigest()
        page = page_html(locale, content, outline, meditation)
        page_path = public / f'pages/{PAGE_ID}/{locale}/index.html'
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(page, encoding='utf-8')
        for kind in ('outline', 'meditation'):
            dst = public / f'study/{PAGE_ID}/{locale}/{kind}.json'
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(STUDY / f'assets/public/study/{PAGE_ID}/{locale}/{kind}.json', dst)
        approval = read(STUDY / 'metadata-approval.json')
        metadata_sha = sha_file(STUDY / 'metadata-approval.json')
        window_sha = read(STUDY / 'study-hashes.json')['windowReceiptSha256']
        source_sha = read(STUDY / 'study-hashes.json')['sourcePackageSha256']
        package = read(ROOT / 'artifacts/sentence-first-agent/20261024-sat400-v2-english/layer2/zh-Hans/english-source.json')
        source_identity = {'sourceId': package['source']['sourceId'], 'sourceUrlHash': package['source']['sourceUrlHash'],
                           'mediaSha256': package['source']['media']['sha256'], 'durationSeconds': 1853.056,
                           'window': {'startSeconds': 0.0, 'endSeconds': 1853.056, 'approvalReceiptSha256': window_sha}}
        previous = read(live / f'releases-v2/{PAGE_ID}/{locale}.json')
        text_sha = previous['targetLanguageCandidateJsonSha256']
        audio_sha = previous['targetLanguageAudioPackageJsonSha256']
        outline_bytes = (public / f'study/{PAGE_ID}/{locale}/outline.json').read_bytes()
        meditation_bytes = (public / f'study/{PAGE_ID}/{locale}/meditation.json').read_bytes()
        review_dir = STUDY / 'reviews' / locale
        products = {'sourcePackageSha256': source_sha, 'textCandidateSha256': text_sha, 'audioPackageSha256': audio_sha,
                    'outlineArtifactSha256': contract.sha(outline), 'meditationArtifactSha256': contract.sha(meditation),
                    'outlineReviewSha256': sha_file(review_dir / 'outline-review.json'),
                    'meditationReviewSha256': sha_file(review_dir / 'meditation-review.json'),
                    'metadataApprovalSha256': metadata_sha, 'contentSha256': content_sha, 'candidateSha256': None}
        join = {'source': source_sha, 'products': {
            'text': text_sha, 'audio': audio_sha,
            'outline': {'status': 'human_reviewed', 'artifactSha256': products['outlineArtifactSha256'],
                        'reviewSha256': products['outlineReviewSha256']},
            'meditation': {'status': 'human_reviewed', 'artifactSha256': products['meditationArtifactSha256'],
                           'reviewSha256': products['meditationReviewSha256']}}}
        products['candidateSha256'] = contract.sha({'products': contract.sha(join),
                                                    'metadataApproval': metadata_sha, 'contentSha256': content_sha})
        manifest = {'schemaVersion': 'sermon-public-app-products-v1', 'pageId': PAGE_ID, 'locale': locale,
                    'sourceIdentity': source_identity, 'fourProducts': products}
        manifest_path = public / f'study/{PAGE_ID}/{locale}/products.json'
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + '\n', encoding='utf-8')
        assets = [('page', f'/pages/{PAGE_ID}/{locale}/index.html'),
                  ('content', f'/content/{PAGE_ID}/{locale}.json'),
                  ('audio', f'/media/{PAGE_ID}/{locale}.mp3'),
                  ('captions', f'/captions/{PAGE_ID}/{locale}.json'),
                  ('outline', f'/study/{PAGE_ID}/{locale}/outline.json'),
                  ('meditation', f'/study/{PAGE_ID}/{locale}/meditation.json'),
                  ('product_manifest', f'/study/{PAGE_ID}/{locale}/products.json')]
        release = {'schemaVersion': 'sermon-target-language-release-package-v3',
                   'packageId': f'{PAGE_ID}-{locale}-production-v3', 'pageId': PAGE_ID, 'sourceLocale': 'en',
                   'targetLocale': locale, 'interfaceLocale': locale, 'contentLocale': locale, 'audioLocale': locale,
                   'targetLanguageCandidateJsonSha256': text_sha, 'spokenTargetLanguageCandidateJsonSha256': text_sha,
                   'targetLanguageAudioPackageJsonSha256': audio_sha, 'status': 'candidate',
                   'contentStatus': 'human_reviewed', 'audioStatus': 'human_reviewed',
                   'englishSourcePackageJsonSha256': source_sha, 'sourceIdentity': source_identity,
                   'fourProducts': products,
                   'assets': [{'role': role, 'path': path,
                               'sha256': sha_file(public / path.lstrip('/'))} for role, path in assets],
                   'httpVerification': {'status': 'not_run', 'evidenceSha256': None},
                   'deviceAcceptance': {'status': 'not_run', 'evidenceSha256': None},
                   'venueAcceptance': {'status': 'not_run', 'evidenceSha256': None}, 'issues': []}
        contract.validate_release_schema(release)
        contract.validate_public_study(release, reader=lambda p: (public / p.lstrip('/')).read_bytes())
        (OUT / 'releases' / f'{locale}.json').parent.mkdir(parents=True, exist_ok=True)
        (OUT / 'releases' / f'{locale}.json').write_text(json.dumps(release, ensure_ascii=False, indent=1, sort_keys=True) + '\n')
    print(json.dumps({'built': str(OUT), 'locales': list(LOCALES)}, ensure_ascii=False))


def assets():
    """Snapshot A: study page sections and study files; live release stays pending."""
    files = {f'pages/{PAGE_ID}/{locale}/index.html': (OUT / f'assets/public/pages/{PAGE_ID}/{locale}/index.html').read_bytes()
             for locale in LOCALES}
    extra = {}
    for locale in LOCALES:
        for name in ('outline', 'meditation', 'products'):
            extra[f'study/{PAGE_ID}/{locale}/{name}.json'] = (OUT / f'assets/public/study/{PAGE_ID}/{locale}/{name}.json').read_bytes()
    result = replace.replace_assets(LIVE, OUT / 'stage-assets', PAGE_ID, files, extra_paths=extra)
    result['publishConfig'] = replace.write_publish_config(LIVE, OUT / 'stage-assets', 'production')
    config_path = OUT / 'stage-assets/publish-config.json'
    config = read(config_path)
    config['allowPendingReplacements'] = [PAGE_ID]
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps(result, ensure_ascii=False))


def verify():
    evidence = {'schemaVersion': 'sermon-study-asset-verification-v1', 'status': 'pass', 'origin': ORIGIN,
                'checkedAt': None, 'checks': []}
    import urllib.request
    ok = True
    for locale in LOCALES:
        for path in (f'/pages/{PAGE_ID}/{locale}/index.html', f'/content/{PAGE_ID}/{locale}.json',
                     f'/study/{PAGE_ID}/{locale}/outline.json', f'/study/{PAGE_ID}/{locale}/meditation.json',
                     f'/study/{PAGE_ID}/{locale}/products.json'):
            request = urllib.request.Request(ORIGIN + path, headers={'Cache-Control': 'no-cache'})
            data = urllib.request.urlopen(request, timeout=120).read()
            local = (OUT / 'stage-assets/public' / path.lstrip('/')).read_bytes()
            same = hashlib.sha256(data).hexdigest() == hashlib.sha256(local).hexdigest()
            ok = ok and same
            evidence['checks'].append({'path': path, 'status': 200, 'sha256': hashlib.sha256(data).hexdigest(),
                                       'matchesStagedBytes': same})
    evidence['status'] = 'pass' if ok else 'fail'
    from datetime import datetime, timezone
    evidence['checkedAt'] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    (OUT / 'asset-verification.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({'status': evidence['status'], 'checks': len(evidence['checks'])}, ensure_ascii=False))
    if not ok:
        raise SystemExit(1)


def finish():
    """Snapshot B: verified v3 releases, catalogs and the refreshed alignment sidecar."""
    evidence_sha = sha_file(OUT / 'asset-verification.json')
    live = LIVE / 'public'
    releases = {}
    for locale in LOCALES:
        release = read(OUT / 'releases' / f'{locale}.json')
        release['status'] = 'published_http_verified'
        release['httpVerification'] = {'status': 'pass', 'evidenceSha256': evidence_sha}
        releases[locale] = (json.dumps(release, ensure_ascii=False, indent=1, sort_keys=True) + '\n').encode()
    sidecar = read(live / f'alignment/{PAGE_ID}.json')
    for locale, data in releases.items():
        sidecar['targets'][locale]['releasePackageJsonSha256'] = hashlib.sha256(data).hexdigest()
    sidecar_bytes = (json.dumps(sidecar, ensure_ascii=False, indent=1) + '\n').encode()
    result = replace.finish_replace(OUT / 'stage-assets', OUT / 'stage-release', PAGE_ID, releases, evidence_sha,
                                    extra_paths={f'alignment/{PAGE_ID}.json': sidecar_bytes})
    result['publishConfig'] = replace.write_publish_config(OUT / 'stage-assets', OUT / 'stage-release', 'production')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['build', 'assets', 'verify', 'finish'])
    args = parser.parse_args()
    {'build': build, 'assets': assets, 'verify': verify, 'finish': finish}[args.command]()
