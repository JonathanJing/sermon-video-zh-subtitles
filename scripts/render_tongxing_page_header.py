#!/usr/bin/env python3
"""Render a local, review-only App Store header from provenance-bound UI crops.

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

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS, FRAMES = 3840, 1646, 30, 300
S = 2


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def smooth(x):
    x = max(0, min(1, x))
    return x * x * (3 - 2 * x)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--screens', type=Path, required=True)
    p.add_argument('--logo', type=Path, required=True)
    p.add_argument('--font', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--stills-only', action='store_true')
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    original_dir = args.output / 'sources'
    original_dir.mkdir(exist_ok=True)
    source_names = ['04a-full-transcript-zh-en-pairs.png', 'MANIFEST.md']
    evidence = []
    for name in source_names:
        source = args.screens / name
        shutil.copy2(source, original_dir / name)
        evidence.append({'file': name, 'sha256': sha(source)})
    shutil.copy2(args.logo, original_dir / 'brand-icon.png')
    evidence.append({'file': 'brand-icon.png', 'sha256': sha(args.logo)})
    screenshot = Image.open(original_dir / source_names[0]).convert('RGB')
    # These boxes retain each entire visible bilingual card; no retyping.
    if screenshot.size != (1398, 2034):
        raise ValueError('Screenshot dimensions differ from the source manifest')
    boxes = [(60, 420, 1088, 794), (60, 1534, 1088, 1906)]
    cards = [screenshot.crop(box).resize((680, 248), Image.Resampling.LANCZOS)
             for box in boxes]
    logo = Image.open(args.logo).convert('RGB')
    logo_small = logo.resize((80, 80), Image.Resampling.LANCZOS)
    logo_hero = logo.resize((300, 300), Image.Resampling.LANCZOS)

    @lru_cache(maxsize=32)
    def font(size, english=False):
        path = '/System/Library/Fonts/Supplemental/Arial.ttf' if english else str(args.font)
        return ImageFont.truetype(path, size * S, index=0 if english else (7 if size >= 28 else 3))

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

    for locale in ['zh', 'en']:
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
                'sourceScope': 'Beta simulator UI crops, editorial crossfade; not a screen recording',
                'sourceRevision': '65b56bb83d70bb81e18cdb236f5f9cd1efb4ea55',
                'dimensions': [W, H], 'fps': FPS, 'durationSeconds': 10,
                'sources': evidence, 'cropBoxes': boxes,
                'firstLastRenderedFramesIdentical': all(frame(0, l).tobytes() == frame(299, l).tobytes()
                                                       for l in ['zh', 'en'])}
    (args.output / 'manifest.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
