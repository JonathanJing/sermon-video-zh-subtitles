"""Shared v1 typography, official badges, dual-QR verification and English reference binding."""
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
import copy
import struct

from build_sermon_poster import digest, read

STORE_URL = 'https://apps.apple.com/app/id6809255441'
BADGE_CODES = {'zh-Hans': 'zh-cn', 'ko': 'ko-kr', 'es': 'es-es', 'en': 'en-us'}
COPY = {
    'zh-Hans': dict(header='同行   ───   本周证道', cta='扫码开启本周证道', web='网页版', caption='扫码阅读 · 收听',
        disclaimer='独立个人项目，与 Mariners Church 无隶属或背书关系。\nAI 合成中文音频与整理文字仅供个人跟读参考。'),
    'ko': dict(header='Tongxing   ───   이번 주 설교', cta='이번 주 설교 읽기 · 듣기', web='웹 버전', caption='QR 코드로 읽기 · 듣기',
        disclaimer='Mariners Church와 제휴하거나 공식 후원을 받지 않는 개인 독립 프로젝트입니다.\nAI로 합성한 한국어 오디오와 정리한 텍스트는 개인 참고용입니다.'),
    'es': dict(header='Tongxing   ───   SERMÓN SEMANAL', cta='Lee y escucha el sermón de esta semana', web='Versión web', caption='Escanea para leer y escuchar',
        disclaimer='Proyecto personal independiente, sin afiliación ni respaldo de Mariners Church. El audio en español sintetizado por IA y el texto preparado por IA son para consulta personal.'),
    'en': dict(header='Tongxing   ───   THIS WEEK’S SERMON', cta='Read and listen to this week’s sermon', web='Web version', caption='Chinese audio · English reference',
        disclaimer='An independent personal project, not affiliated with or endorsed by Mariners Church. AI-synthesized Chinese audio and AI-prepared text are for personal reference.'),
}


def title_lines(title, locale):
    if '\n' in title:
        return title
    words = title.split()
    if locale == 'zh-Hans' and len(words) == 1 and len(title) > 5:
        middle = (len(title)+1)//2
        return title[:middle] + '\n' + title[middle:]
    if len(words) >= 2:
        # Break only between words, including Hangul; never split a Korean word.
        split = min(range(1,len(words)), key=lambda i:abs(len(' '.join(words[:i]))-len(' '.join(words[i:]))))
        return ' '.join(words[:split]) + '\n' + ' '.join(words[split:])
    return title


def apply_template(bundle):
    brief = bundle['brief']
    locale = brief['locale']
    # Keep the full original machine/mixed-review disclosure visible, never call it human approval.
    brief['labels'].update(COPY[locale])
    brief['displayTitle'] = title_lines(brief['title'], locale)
    human_label = {'zh-Hans':'译文与配音已审核', 'ko':'번역과 음성 검토 완료', 'es':'Traducción y audio revisados'}
    brief['labels']['showReview'] = str(brief['reviewLabel'] != human_label[locale]).lower()
    brief['storeURL'] = STORE_URL
    bundle['source']['brief'] = brief


def add_english_reference(bundles, metadata):
    source = bundles['zh-Hans']['source']
    for key in ('pageId', 'sourceIdentitySha256', 'contentSha256'):
        if metadata.get(key) != source[key]:
            raise ValueError('English reference must bind unchanged Chinese source/content: ' + key)
    for key in ('title', 'series', 'scripture'):
        if not isinstance(metadata.get(key), str) or not metadata[key].strip():
            raise ValueError('missing English reference metadata: ' + key)
    bundle = copy.deepcopy(bundles['zh-Hans'])
    brief = bundle['brief']
    brief.update(locale='en', **{k:metadata[k] for k in ('title','series','scripture')})
    brief['displayTitle'] = title_lines(brief['title'], 'en')
    brief['labels'].update(COPY['en'])
    brief['labels']['showReview'] = 'true' if bundles['zh-Hans']['brief']['labels']['showReview'] == 'true' else 'false'
    if brief['labels']['showReview'] == 'true':
        brief['reviewLabel'] = 'Chinese reference content includes machine-checked text or audio; not fully human reviewed.'
    else:
        brief['reviewLabel'] = 'English reference artwork · Chinese content'
    brief['qrURL'] = brief['origin'] + '/?' + urlencode(dict(week=source['pageId'],contentLang='zh-Hans',lang='en'))
    # targetLocale remains zh-Hans: never synthesize an English content release or announcement.
    bundle['source'].update(artworkLocale='en', contentLocale='zh-Hans', announcementEligible=False,
                            englishReference=metadata, brief=brief)
    bundles['en'] = bundle


def prepare_badges(out, bundles):
    folder = out / 'official-badges'
    folder.mkdir(exist_ok=True)
    paths = {}
    for locale in bundles:
        path = folder / (locale + '.svg')
        if not path.exists():
            url = 'https://tools.applemediaservices.com/api/badges/download-on-the-app-store/black/' + BADGE_CODES[locale] + '?size=250x83'
            with urlopen(url, timeout=40) as response:
                data = response.read(512 * 1024 + 1)
            if len(data) > 512 * 1024 or b'<svg' not in data:
                raise ValueError('invalid official badge response')
            path.write_bytes(data)
        paths[locale] = path
    return paths


def verify_outputs(out, brief):
    validation = read(out / 'qr-validation.json')
    checks = validation.get('checks', [])
    if validation.get('schemaVersion') != 'tongxing-dual-qr-validation-v1' or len(checks) != 2:
        raise ValueError('dual QR verification required for full and preview PNGs')
    expected_files = {'poster.png': (1200,1800), 'poster-preview.png':(600,900)}
    if {x.get('file') for x in checks} != set(expected_files):
        raise ValueError('QR verification must cover both images exactly once')
    for check in checks:
        payloads = check.get('decodedPayloads', [])
        if check.get('passed') is not True or len(payloads) != 2 or set(payloads) != {STORE_URL, brief['qrURL']}:
            raise ValueError('two exact QR payloads required')
        data = (out / check['file']).read_bytes()
        if data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR' or struct.unpack('>II',data[16:24]) != expected_files[check['file']]:
            raise ValueError('invalid PNG dimensions')
    return {name:digest(out / name) for name in (*expected_files,'qr-validation.json')}
