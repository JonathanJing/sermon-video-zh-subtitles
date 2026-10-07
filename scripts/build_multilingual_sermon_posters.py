#!/usr/bin/env python3
"""Build source-bound Chinese, Korean and Spanish posters for the existing App."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from build_sermon_poster import digest, read, write, verify_outputs

COPY = {
    'zh-Hans': dict(lang='zh', brand='同行', eyebrow='本周证道 · 中文',
                    tagline='一起听懂，一路同行。', cta='扫码收听本周证道',
                    serviceLine='中文配音 · 英文对照 · 完整文稿',
                    qrCaption='直接打开本周 · 中文', reviewLabel='译文与配音已审核',
                    disclaimer='独立制作 · 含 AI 辅助翻译与配音 · 非教会官方出品'),
    'ko': dict(lang='ko', brand='Tongxing', eyebrow='이번 주 설교 · 한국어',
               tagline='함께 듣고, 함께 걸어갑니다.', cta='QR 코드로 이번 주 설교 듣기',
               serviceLine='한국어 음성 · 영어 대조 · 전체 원고',
               qrCaption='이번 주 한국어로 바로 열기', reviewLabel='번역과 음성 검토 완료',
               disclaimer='독립 제작 · AI 보조 번역 및 음성 포함 · 교회 공식 제작물이 아닙니다'),
    'es': dict(lang='es', brand='Tongxing', eyebrow='SERMÓN SEMANAL · ESPAÑOL',
               tagline='Escuchamos y caminamos juntos.', cta='Escanea para escuchar el sermón',
               serviceLine='Audio en español · Texto en inglés · Transcripción completa',
               qrCaption='Esta semana, en español', reviewLabel='Traducción y audio revisados',
               disclaimer='Producción independiente · Traducción y voz asistidas por IA · No es una publicación oficial de la iglesia'),
}

# A machine quality waiver is never a human review: name what each product went through.
MACHINE_REVIEW_LABELS = {
    'zh-Hans': {('machine_checked', 'machine_checked'): '译文与配音经机器质检 · 未经人工审核',
                ('human_reviewed', 'machine_checked'): '译文已审核 · 配音经机器质检',
                ('machine_checked', 'human_reviewed'): '译文经机器质检 · 配音已审核'},
    'ko': {('machine_checked', 'machine_checked'): '번역과 음성 기계 품질 검사 · 사람 검토 없음',
           ('human_reviewed', 'machine_checked'): '번역 검토 완료 · 음성 기계 품질 검사',
           ('machine_checked', 'human_reviewed'): '번역 기계 품질 검사 · 음성 검토 완료'},
    'es': {('machine_checked', 'machine_checked'): 'Traducción y audio con control de calidad automático · Sin revisión humana',
           ('human_reviewed', 'machine_checked'): 'Traducción revisada · Audio con control de calidad automático',
           ('machine_checked', 'human_reviewed'): 'Traducción con control de calidad automático · Audio revisado'},
}
CATALOGS = (('multilingual-v4.json', 'sermon-multilingual-catalog-v4'),
            ('multilingual-v3.json', 'sermon-multilingual-catalog-v3'))


def review_label(locale, package):
    statuses = (package.get('contentStatus'), package.get('audioStatus'))
    if statuses == ('human_reviewed', 'human_reviewed'):
        return COPY[locale]['reviewLabel']
    disclosure = package.get('disclosure')
    if (statuses not in MACHINE_REVIEW_LABELS[locale]
            or package.get('schemaVersion') != 'sermon-target-language-release-package-v4'
            or not isinstance(disclosure, dict) or disclosure.get('locale') != locale
            or not str(disclosure.get('text', '')).strip()):
        raise ValueError('locale must have a published, reviewed text and audio package: ' + locale)
    return MACHINE_REVIEW_LABELS[locale][statuses]


def origin_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise ValueError('origin must be an HTTPS origin with no path, query or credentials')
    return value.rstrip('/')


def asset_file(public, url):
    parsed = urlsplit(url)
    if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or
            not url.startswith('/') or '\\' in url or '%' in url):
        raise ValueError('asset must be a safe same-origin path')
    path = (public / url.lstrip('/')).resolve()
    if not path.is_relative_to(public.resolve()):
        raise ValueError('asset escapes public directory')
    return path


def checked_json(path, expected=None):
    value = digest(path)
    if expected is not None and value != expected:
        raise ValueError('asset SHA-256 mismatch: ' + str(path))
    return read(path), value


def load_sources(release, page_id, origin):
    public = release / 'public'
    # New clients read v4 first; v3 is its human-only projection and lacks machine-checked weeks.
    name, version = next((row for row in CATALOGS if (public / row[0]).is_file()), CATALOGS[-1])
    catalog, catalog_sha = checked_json(public / name)
    if catalog.get('schemaVersion') != version:
        raise ValueError('expected multilingual v3 or v4 catalog')
    pages = [page for page in catalog['pages'] if page['id'] == page_id]
    if len(pages) != 1:
        raise ValueError('page ID must match exactly one published page')
    page = pages[0]
    datetime.date.fromisoformat(page['date'])
    checks = {'/' + name: catalog_sha}
    bundles = {}
    for locale, copy in COPY.items():
        target = page['targets'][locale]
        release_path = target['releasePackageUrl']
        package, package_sha = checked_json(asset_file(public, release_path), target['releasePackageJsonSha256'])
        if (package.get('pageId') != page_id or package.get('targetLocale') != locale or
                package.get('status') != 'published_http_verified' or
                (package.get('contentStatus'), package.get('audioStatus')) !=
                (target.get('contentStatus', 'human_reviewed'), target.get('audioStatus', 'human_reviewed'))):
            raise ValueError('locale must have a published, reviewed text and audio package: ' + locale)
        label = review_label(locale, package)
        assets = [a for a in package['assets'] if a['role'] == 'content']
        if len(assets) != 1:
            raise ValueError('expected one approved content asset')
        content, content_sha = checked_json(asset_file(public, assets[0]['path']), assets[0]['sha256'])
        if (content.get('pageId') != page_id or content.get('targetLocale') != locale or
                content.get('englishSourcePackageJsonSha256') != page['sourceIdentitySha256'] or
                content.get('targetLanguageCandidateJsonSha256') != package['targetLanguageCandidateJsonSha256']):
            raise ValueError('content source or locale identity mismatch')
        for key in ('title', 'series', 'scripture', 'speaker'):
            if not isinstance(content.get(key), str) or not content[key].strip():
                raise ValueError('missing content metadata: ' + key)
        labels = {k: v for k, v in copy.items() if k not in ('lang', 'tagline', 'reviewLabel')}
        brief = dict(locale=locale, date=page['date'], origin=origin,
                     **{key: content[key] for key in ('title', 'series', 'scripture', 'speaker')},
                     tagline=copy['tagline'], reviewLabel=label, labels=labels,
                     qrURL=origin + '/?' + urlencode(dict(week=page_id, contentLang=locale, lang=copy['lang'])))
        checks.update({release_path: package_sha, assets[0]['path']: content_sha})
        bundles[locale] = dict(brief=brief, source=dict(pageId=page_id, targetLocale=locale,
            sourceIdentitySha256=page['sourceIdentitySha256'], catalogSha256=catalog_sha,
            releasePackageSha256=package_sha, contentSha256=content_sha, brief=brief))
    return bundles, checks


def verify_public(origin, checks):
    verified = []
    for path, expected in checks.items():
        request = Request(origin + path, headers={'Cache-Control': 'no-cache'})
        with urlopen(request, timeout=40) as response:
            body = response.read(4 * 1024 * 1024 + 1)
            if response.status != 200 or len(body) > 4 * 1024 * 1024:
                raise ValueError('invalid public JSON response: ' + path)
            actual = hashlib.sha256(body).hexdigest()
            if actual != expected:
                raise ValueError('public JSON SHA-256 mismatch: ' + path)
            verified.append(dict(path=path, sha256=actual, status=response.status))
    return dict(checkedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                origin=origin, status='pass', checks=verified)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('release', 'page-id', 'origin', 'out'):
        parser.add_argument('--' + key, required=True)
    parser.add_argument('--art')
    parser.add_argument('--art-prompt')
    parser.add_argument('--visual-reviewed', action='store_true')
    args = parser.parse_args()
    release, out = Path(args.release).resolve(), Path(args.out).resolve()
    if out.is_relative_to(release) or release.is_relative_to(out):
        raise ValueError('poster output must be separate from the release')
    origin = origin_url(args.origin)
    bundles, checks = load_sources(release, args.page_id, origin)
    if bool(args.art) != bool(args.art_prompt) or (args.visual_reviewed and not args.art):
        raise ValueError('render/review requires both --art and --art-prompt')
    out.mkdir(parents=True, exist_ok=True)
    for locale, bundle in bundles.items():
        folder = out / locale
        folder.mkdir(exist_ok=True)
        receipt_path = folder / 'poster-receipt.json'
        previous = read(receipt_path) if receipt_path.exists() else None
        if previous and previous['source'] != bundle['source']:
            raise ValueError('source changed; use a fresh output directory')
        if not previous and any(folder.iterdir()):
            raise ValueError('locale output directory is not empty')
        write(folder / 'poster-brief.json', bundle['brief'])
        if not previous:
            write(receipt_path, dict(schemaVersion='sermon-multilingual-poster-v1',
                                     source=bundle['source'], status='awaiting_image_generation'))
    if not args.art:
        print(json.dumps(dict(status='awaiting_image_generation', out=str(out), locales=list(bundles))))
        return
    public_receipt = verify_public(origin, checks)
    write(out / 'public-input-verification.json', public_receipt)
    renderer = Path(__file__).with_name('render_sermon_poster.swift')
    art, prompt = Path(args.art).resolve(), Path(args.art_prompt).resolve()
    provenance = dict(artSha256=digest(art), promptSha256=digest(prompt),
                      rendererSha256=digest(renderer), builderSha256=digest(__file__))
    swift = shutil.which('swift')
    if not swift:
        raise ValueError('macOS Swift, AppKit, CoreImage and Vision are required')
    for locale, bundle in bundles.items():
        folder = out / locale
        receipt_path = folder / 'poster-receipt.json'
        receipt = read(receipt_path)
        if receipt.get('provenance') and receipt['provenance'] != provenance:
            raise ValueError('render inputs changed; use a fresh output directory')
        if receipt.get('outputs'):
            hashes = verify_outputs(folder, bundle['brief']['qrURL'])
            if hashes != receipt['outputs'] or digest(folder / 'artwork.png') != provenance['artSha256'] or digest(folder / 'art-prompt-used.txt') != provenance['promptSha256']:
                raise ValueError('saved outputs or inputs were modified')
        else:
            if args.visual_reviewed:
                raise ValueError('visual review requires previously rendered unchanged outputs')
            shutil.copyfile(art, folder / 'artwork.png')
            shutil.copyfile(prompt, folder / 'art-prompt-used.txt')
            with tempfile.TemporaryDirectory(prefix='render-', dir=folder) as temporary:
                subprocess.run([swift, '-module-cache-path', str(Path(tempfile.gettempdir()) / 'sermon-poster-swift-cache'),
                                str(renderer), str(folder / 'poster-brief.json'), str(art), temporary], check=True)
                hashes = verify_outputs(Path(temporary), bundle['brief']['qrURL'])
                for name in hashes:
                    shutil.copyfile(Path(temporary) / name, folder / name)
        receipt.update(provenance=provenance, outputs=hashes, publicVerification=public_receipt,
                       status='complete' if args.visual_reviewed or receipt.get('status') == 'complete' else 'qr_verified_visual_review_pending')
        if args.visual_reviewed:
            receipt.update(visualReview=dict(reviewer='codex', humanApproval=False),
                           visualReviewedAt=datetime.datetime.now(datetime.timezone.utc).isoformat())
        write(receipt_path, receipt)
    print(json.dumps(dict(status='complete' if args.visual_reviewed else 'qr_verified_visual_review_pending',
                          out=str(out), locales=list(bundles))))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
