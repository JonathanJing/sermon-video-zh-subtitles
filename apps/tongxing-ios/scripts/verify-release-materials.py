#!/usr/bin/env python3
"""Check local submission material without signing, uploading, or changing ASC."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshots', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    metadata_path = root / 'release/metadata.json'
    errors = []
    lengths = {}
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
        locales = metadata.get('localizations', metadata.get('locales', {}))
        for locale, values in locales.items():
            lengths[locale] = {}
            for field, maximum in {'name': 30, 'subtitle': 30, 'description': 4000,
                                   'promotionalText': 170, 'keywords': 100}.items():
                value = values.get(field)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f'{locale}.{field}: missing text')
                    continue
                count = len(value.encode('utf-8')) if field == 'keywords' else len(value)
                lengths[locale][field] = count
                if count > maximum:
                    errors.append(f'{locale}.{field}: {count} exceeds {maximum}')
        if not locales:
            errors.append('No localized metadata found')
    else:
        errors.append('metadata.json is missing')
    screenshots = []
    allowed = {(1260, 2736), (1290, 2796), (1320, 2868), (2064, 2752), (2048, 2732)}
    if args.screenshots:
        for p in sorted(p for p in args.screenshots.rglob('*') if p.suffix.lower() in {'.png', '.jpg', '.jpeg'}):
            if any(part.startswith('evidence-') for part in p.relative_to(args.screenshots).parts):
                continue
            data = p.read_bytes()
            if data[:8] == b'\x89PNG\r\n\x1a\n':
                width, height = struct.unpack('>II', data[16:24])
            elif data[:2] == b'\xff\xd8':
                result = subprocess.run(['sips', '-g', 'pixelWidth', '-g', 'pixelHeight', str(p)],
                                        capture_output=True, text=True, check=True)
                width = int(re.search(r'pixelWidth: (\d+)', result.stdout).group(1))
                height = int(re.search(r'pixelHeight: (\d+)', result.stdout).group(1))
            else:
                errors.append(f'{p.name}: unsupported image encoding')
                continue
            dimensions_valid = (width, height) in allowed or (height, width) in allowed
            screenshots.append({'file': str(p.relative_to(args.screenshots)),
                                'width': width, 'height': height,
                                'sha256': hashlib.sha256(data).hexdigest(),
                                'supportedDimensions': dimensions_valid})
            if not dimensions_valid:
                errors.append(f'{p.name}: unexpected screenshot dimensions {width}x{height}')
    if args.screenshots and not screenshots:
        errors.append('No candidate screenshots found')
    report = {'schemaVersion': 'tongxing-release-material-check-v1',
              'metadataLengths': lengths, 'screenshots': screenshots,
              'errors': errors, 'checksPassed': not errors,
              'submissionApproved': False,
              'note': 'Local structure checks do not establish content rights, privacy approval, visual QA, signing, or Apple acceptance.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'checksPassed': not errors, 'screenshotCount': len(screenshots), 'errors': errors}, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
