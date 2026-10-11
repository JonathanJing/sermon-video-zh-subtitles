#!/usr/bin/env python3
"""Render a review-only App Store header from UI crops or verified sermon text.

Requires Pillow and NumPy, ffmpeg and ffprobe. No upload or remote write occurs.
"""
import argparse
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
import shutil
import subprocess


W, H, FPS, FRAMES = 3840, 1646, 30, 300
S = 2


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def smooth(x):
    x = max(0, min(1, x))
    return x * x * (3 - 2 * x)


def preflight_outputs(output, languages):
    paths = [output / "manifest.json", output / "caption-layout.json"]
    for locale in languages:
        stem = f"tongxing-page-header-{locale}"
        paths += [output / f"{stem}{suffix}" for suffix in
                  (".mp4", "-preview.mp4", "-poster.png", "-encode.log", "-ffprobe.json")]
        paths += [output / f"{stem}-frame-{index:03}.png" for index in (0, 60, 150, 240, 299)]
    for path in paths:
        if path.exists():
            raise FileExistsError(path)


def validate_target_binding(quote, page, locale, content, release):
    target = page["targets"][locale]
    if target.get("simulationOnly") or target.get("diagnosticOnly"):
        raise ValueError("Synthetic target cannot be used for sermon marketing")
    for value in (release, content):
        if (value.get("pageId"), value.get("targetLocale"),
                value.get("englishSourcePackageJsonSha256")) != (
                quote["pageId"], locale, quote["sourceIdentitySha256"]):
            raise ValueError("Quote release/content page, locale or source binding mismatch")
    candidate = release.get("targetLanguageCandidateJsonSha256")
    if not candidate or content.get("targetLanguageCandidateJsonSha256") != candidate:
        raise ValueError("Quote release/content candidate binding mismatch")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument('--screens', type=Path)
    source.add_argument('--quote', type=Path, help='Quote selection bound to published JSON in sibling sources/')
    p.add_argument('--logo', type=Path, required=True)
    p.add_argument('--font', type=Path, required=True)
    p.add_argument('--korean-font', type=Path, default=Path('/System/Library/Fonts/AppleSDGothicNeo.ttc'))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--stills-only', action='store_true')
    args = p.parse_args()
    preflight_outputs(args.output, ["zh", "en", "ko", "es"] if args.quote else ["zh", "en"])
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    args.output.mkdir(parents=True, exist_ok=True)
    original_dir = args.output / 'sources'
    original_dir.mkdir(exist_ok=True)
    quote = json.loads(args.quote.read_text()) if args.quote else None
    source_names = ['04a-full-transcript-zh-en-pairs.png', 'MANIFEST.md'] if args.screens else []
    evidence = []
    for name in source_names:
        source = args.screens / name
        shutil.copy2(source, original_dir / name)
        evidence.append({'file': name, 'sha256': sha(source)})
    shutil.copy2(args.logo, original_dir / 'brand-icon.png')
    evidence.append({'file': 'brand-icon.png', 'sha256': sha(args.logo)})
    if quote:
        if quote['schemaVersion'] != 'tongxing-marketing-sermon-quote-v1':
            raise ValueError('Unsupported quote selection schema')
        records = [quote['catalog'], quote['englishReference']]
        for item in quote['translations'].values():
            records += [item, {'file': item['releaseFile'], 'sha256': item['releaseSHA256']}]
        for record in records:
            src = args.quote.parent / 'sources' / record['file']
            if Path(record['file']).name != record['file'] or sha(src) != record['sha256']:
                raise ValueError('Published source file identity mismatch')
            dest = original_dir / record['file']
            if src.resolve() != dest.resolve():
                shutil.copy2(src, dest)
            evidence.append({'file': record['file'], 'sha256': record['sha256']})
        reference = json.loads((original_dir / quote['englishReference']['file']).read_text())
        catalog = json.loads((original_dir / quote['catalog']['file']).read_text())
        page = next(p for p in catalog['pages'] if p['id'] == quote['pageId'])
        if page.get('simulationOnly') or page.get('diagnosticOnly'):
            raise ValueError('Synthetic content cannot be used for sermon marketing')
        if (page['sourceIdentitySha256'], page['sourceMediaSha256']) != (quote['sourceIdentitySha256'], quote['sourceMediaSha256']):
            raise ValueError('Quote source differs from catalog')
        if reference['reviewState'] != 'human_approved' or reference['sourceIdentitySha256'] != quote['sourceIdentitySha256']:
            raise ValueError('English reference binding or review mismatch')
        for locale, item in quote['translations'].items():
            content = json.loads((original_dir / item['file']).read_text())
            release = json.loads((original_dir / item['releaseFile']).read_text())
            validate_target_binding(quote, page, locale, content, release)
            if (release['status'], release['contentStatus']) != ('published_http_verified', 'human_reviewed'):
                raise ValueError('Quote requires reviewed published content')
            if page['targets'][locale]['releasePackageJsonSha256'] != item['releaseSHA256']:
                raise ValueError('Release is not the catalog-selected revision')
            if next(a['sha256'] for a in release['assets'] if a['role'] == 'content') != item['sha256']:
                raise ValueError('Content differs from release asset identity')
            if content['englishSourcePackageJsonSha256'] != quote['sourceIdentitySha256']:
                raise ValueError('Target source binding mismatch')
            cue = next(c for c in content['cues'] if c['sourceUnitIds'] == [quote['unitId']])
            english = next(c for c in reference['targets'][locale]['blocks'] if c['sourceUnitIds'] == [quote['unitId']])
            if (cue['text'], english['english'], cue['textGroupId']) != (item['text'], item['english'], item['textGroupId']):
                raise ValueError('Quote does not exactly match published sentence')
        if len({x['english'] for x in quote['translations'].values()}) != 1:
            raise ValueError('Languages differ in English source sentence')
        if args.quote.resolve() != (args.output / 'sermon-quote.json').resolve():
            shutil.copy2(args.quote, args.output / 'sermon-quote.json')
    screenshot = Image.open(original_dir / source_names[0]).convert('RGB') if args.screens else None
    # These boxes retain each entire visible bilingual card; no retyping.
    if screenshot and screenshot.size != (1398, 2034):
        raise ValueError('Screenshot dimensions differ from the source manifest')
    boxes = [(60, 420, 1088, 794), (60, 1534, 1088, 1906)]
    cards = [screenshot.crop(box).resize((680, 248), Image.Resampling.LANCZOS)
             for box in boxes] if screenshot else []
    logo = Image.open(args.logo).convert('RGB')
    logo_small = logo.resize((80, 80), Image.Resampling.LANCZOS)
    logo_hero = logo.resize((300, 300), Image.Resampling.LANCZOS)

    @lru_cache(maxsize=32)
    def font(size, english=False):
        path = '/System/Library/Fonts/Supplemental/Arial.ttf' if english else str(args.font)
        return ImageFont.truetype(path, size * S, index=0 if english else (7 if size >= 28 else 3))

    @lru_cache(maxsize=48)
    def language_font(size, locale):
        if locale == 'ko':
            return ImageFont.truetype(str(args.korean_font), size * S, index=2 if size >= 28 else 0)
        return font(size, locale in ['en', 'es'])

    def wrap(text, selected_font, width):
        words = list(text) if not ' ' in text else text.split(' ')
        separator = '' if not ' ' in text else ' '
        lines, current = [], ''
        for word in words:
            candidate = current + (separator if current else '') + word
            if selected_font.getlength(candidate) > width and current:
                lines.append(current)
                current = word
            else:
                current = candidate
            if selected_font.getlength(current) > width:
                raise ValueError('Unbreakable word exceeds caption width')
        if current:
            lines.append(current)
        if separator.join(lines) != text:
            raise ValueError('Wrapping changed quote text')
        return lines

    localized = {
        'zh': ('同行', '一起听懂，', '一路同行。', '中文 · English', '证道字幕', 54),
        'en': ('Tongxing', 'Understand.', 'Walk together.', 'English · 中文', 'Sermon captions', 42),
        'ko': ('Tongxing', '함께 듣고,', '함께 걸어요.', '한국어 · English', '설교 자막', 43),
        'es': ('Tongxing', 'Escucha.', 'Caminemos juntos.', 'Español · English', 'Subtítulos del sermón', 32),
    }
    quote_cards = {}
    layout_receipts = []
    if quote:
        for locale in localized:
            item = quote['translations'][{'zh': 'zh-Hans', 'en': 'zh-Hans', 'ko': 'ko', 'es': 'es'}[locale]]
            primary, secondary = (item['english'], item['text']) if locale == 'en' else (item['text'], item['english'])
            secondary_locale = 'zh' if locale == 'en' else 'en'
            selected = None
            for size in range(21, 16, -1):
                main_font = language_font(size, locale)
                small_font = language_font(15, secondary_locale)
                main_lines, sub_lines = wrap(primary, main_font, 788), wrap(secondary, small_font, 788)
                main_height, sub_height = (size * 2 + 8), 36
                needed = 40 + len(main_lines) * main_height + 16 + len(sub_lines) * sub_height
                if needed <= 350:
                    selected = size
                    break
            if selected is None:
                raise ValueError('Complete quote cannot fit; use a shorter whole source sentence')
            card = Image.new('RGB', (836, 350), '#112E2C')
            cd = ImageDraw.Draw(card)
            yy = 18
            for line in main_lines:
                cd.text((24, yy), line, font=main_font, fill='#F5F2E9')
                yy += main_height
            yy += 16
            for line in sub_lines:
                cd.text((24, yy), line, font=small_font, fill='#A7D6C2')
                yy += sub_height
            quote_cards[locale] = card
            layout_receipts.append({'locale': locale, 'primary': primary, 'secondary': secondary,
                                    'mainLines': main_lines, 'secondaryLines': sub_lines,
                                    'mainFontPixels': selected * 2, 'contentHeight': needed,
                                    'cardSize': [836, 350], 'ellipsized': False})
        (args.output / 'caption-layout.json').write_text(json.dumps(layout_receipts, ensure_ascii=False, indent=2))

    y, x = np.mgrid[0:H, 0:W]
    glow = np.exp(-(((x - W * .57) / (W * .52))**2 + ((y - H * .46) / (H * .9))**2) * 2)
    pixels = np.stack([9 + 13 * glow, 31 + 35 * glow, 33 + 28 * glow], axis=-1).astype('uint8')
    bg = Image.fromarray(pixels, 'RGB')
    d = ImageDraw.Draw(bg)
    # Peripheral book-page contours are atmosphere, never necessary to read.
    for n in range(5):
        inset = n * 40
        d.arc((70 + inset, -200 + inset, 1800 + inset, 1820 + inset), 230, 330,
              fill=(34, 73, 69), width=2)
        d.arc((2450 - inset, -300 + inset, 4650 - inset, 1680 + inset), 135, 225,
              fill=(35, 74, 69), width=2)
    warm, sage = '#F5F2E9', '#A7D6C2'

    def frame(index, locale):
        t = 10 * index / (FRAMES - 1)
        im = bg.copy()
        draw = ImageDraw.Draw(im)
        if quote:
            brand, first, second, support, caption_label, title_size = localized[locale]
            im.paste(logo_small, (1140, 540))
            draw.text((1244, 542), brand, font=language_font(29, locale), fill=warm)
            draw.text((1140, 671), first, font=language_font(title_size, locale), fill=warm)
            draw.text((1140, 802), second, font=language_font(title_size, locale), fill=sage)
            # English branding also includes 中文; Arial has no CJK glyph fallback.
            draw.text((1146, 972), support, font=language_font(19, 'zh' if locale == 'en' else locale), fill=sage)
            opacity = smooth((t - .5) / .6) * smooth((9.5 - t) / .6)
            floating = round(10 * math.sin(2 * math.pi * t / 10))
            hero = Image.new('RGB', (900, 548), '#173B39')
            hd = ImageDraw.Draw(hero)
            hero.paste(logo_hero, (300, 85))
            hd.text((315, 416), brand, font=language_font(28, locale), fill=warm)
            ui = Image.new('RGB', hero.size, '#173B39')
            ud = ImageDraw.Draw(ui)
            ud.text((32, 24), caption_label, font=language_font(21, locale), fill=sage)
            ui.paste(quote_cards[locale], (32, 100))
            for j in range(40):
                height = round(8 + 19 * (.5 + .5 * math.sin(2 * math.pi * t / 10 * 3 + j * .5)))
                xx = 33 + j * 21
                ud.rounded_rectangle((xx, 494 - height, xx + 7, 494 + height), radius=3, fill=sage)
            im.paste(Image.blend(hero, ui, opacity), (1830, 545 + floating))
            draw.rounded_rectangle((1829, 544 + floating, 2731, 1094 + floating), radius=34,
                                   outline='#38685A', width=2)
            return im
        im.paste(logo_small, (1140, 540))
        draw.text((1244, 542), '同行' if locale == 'zh' else 'Tongxing',
                  font=font(29, locale == 'en'), fill=warm)
        if locale == 'zh':
            draw.text((1140, 671), '一起听懂，', font=font(54), fill=warm)
            draw.text((1140, 802), '一路同行。', font=font(54), fill=sage)
            draw.text((1146, 972), '中英对照 · 用心聆听', font=font(20), fill=sage)
        else:
            draw.text((1140, 667), 'Understand.', font=font(47, True), fill=warm)
            draw.text((1140, 796), 'Walk together.', font=font(42, True), fill=sage)
            draw.text((1146, 972), 'Chinese + English. Side by side.', font=font(16, True), fill=sage)
        opacity = smooth((t - .7) / .9) * smooth((9.3 - t) / .9)
        floating = round(10 * math.sin(2 * math.pi * t / 10))
        hero = Image.new('RGB', (740, 470), '#173B39')
        hd = ImageDraw.Draw(hero)
        # The central object remains legible even before playback starts.
        hero.paste(logo_hero, (220, 65))
        hd.text((260, 390), '同行' if locale == 'zh' else 'Tongxing',
                font=font(28, locale == 'en'), fill=warm)
        ui = Image.new('RGB', hero.size, '#173B39')
        ud = ImageDraw.Draw(ui)
        ud.text((30, 32), '双语字幕' if locale == 'zh' else 'Bilingual captions',
                font=font(22, locale == 'en'), fill=sage)
        # Never crossfade two text cards over each other: fade through empty space.
        if t < 4.9:
            selected, visibility = cards[0], smooth((4.9 - t) / .4)
        else:
            selected, visibility = cards[1], smooth((t - 4.9) / .4)
        empty = Image.new('RGB', selected.size, '#173B39')
        ui.paste(Image.blend(empty, selected, visibility), (30, 115))
        for j in range(35):
            height = round(10 + 26 * (.5 + .5 * math.sin(2 * math.pi * t / 10 * 3 + j * .5)))
            xx = 31 + j * 19
            ud.rounded_rectangle((xx, 412 - height, xx + 7, 412 + height), radius=3, fill=sage)
        panel = Image.blend(hero, ui, opacity)
        im.paste(panel, (2000, 568 + floating))
        draw.rounded_rectangle((1999, 567 + floating, 2740, 1039 + floating), radius=34,
                               outline='#38685A', width=2)
        return im

    languages = list(localized) if quote else ['zh', 'en']
    for locale in languages:
        stem = f'tongxing-page-header-{locale}'
        for index in [0, 60, 150, 240, 299]:
            frame(index, locale).save(args.output / f'{stem}-frame-{index:03}.png')
        frame(60, locale).save(args.output / f'{stem}-poster.png')
        if args.stills_only:
            continue
        video = args.output / f'{stem}.mp4'
        if video.exists():
            raise FileExistsError(video)
        command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'rawvideo',
                   '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                   '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                   '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                   '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
                   str(video)]
        with (args.output / f'{stem}-encode.log').open('wb') as log:
            proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
            try:
                for i in range(FRAMES):
                    proc.stdin.write(frame(i, locale).tobytes())
                    if i % 60 == 0:
                        print(f'{locale}: {i}/{FRAMES}', flush=True)
                proc.stdin.close()
                if proc.wait() != 0:
                    raise RuntimeError('ffmpeg encode failed; inspect local log')
            except BaseException:
                proc.kill()
                proc.wait()
                raise
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', str(video),
                        '-vf', 'scale=1920:824', '-an', '-c:v', 'libx264', '-crf', '23',
                        '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                        str(args.output / f'{stem}-preview.mp4')], check=True)
        probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                                                   '-show_format', '-of', 'json', str(video)]))
        (args.output / f'{stem}-ffprobe.json').write_text(json.dumps(probe, indent=2))
    metadata = {'status': 'local_review_candidate', 'upload': 'not_run', 'approval': 'not_run',
                'sourceScope': 'Published sermon quote, designed typography; not App UI or a screen recording' if quote else 'Beta simulator UI crops, editorial crossfade; not a screen recording',
                'sourceRevision': quote['sourceIdentitySha256'] if quote else '65b56bb83d70bb81e18cdb236f5f9cd1efb4ea55',
                'dimensions': [W, H], 'fps': FPS, 'durationSeconds': 10,
                'sources': evidence, 'cropBoxes': None if quote else boxes, 'languages': languages,
                'firstLastRenderedFramesIdentical': all(frame(0, l).tobytes() == frame(299, l).tobytes()
                                                       for l in languages)}
    (args.output / 'manifest.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
