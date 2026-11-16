#!/usr/bin/env python3
"""Replace one locale's App Store screenshots for a display type, in place.

Apple keeps exactly one screenshot set per (app store version localization, display type), so
replacing store art means deleting the old set and uploading a new one. This tool locates the
version and localization, deletes the old set, creates the new one, uploads each PNG through
the reserve/upload/patch flow, waits for every image to report ``COMPLETE`` and writes a receipt
with the file hashes.

Only a version in ``PREPARE_FOR_SUBMISSION`` can be changed; a submitted version must be edited
through a new submission. ``--dry-run`` prints what would be replaced without touching Apple.

The private App Store Connect key is the same one ``apps/tongxing-ios/scripts/testflight.py``
uses (``~/Library/Application Support/TongxingRelease/api-key.json``); credentials never enter
the repository.

  .venv/bin/python tools/ops/upload_appstore_screenshots.py \\
      --version 1.26.36 --locale zh-Hans --display-type APP_IPHONE_DUO \\
      --images shots/duo-outer.png shots/duo-inner.png \\
      --receipt artifacts/.../duo-receipt.json --execute

Display sizes are listed in apps/tongxing-ios/STORE-SCREENSHOTS.zh.md; the iPhone Duo cover
screen is ``APP_IPHONE_DUO`` at 1398x2034.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.parse

try:
    import jwt
    import requests
except ImportError:  # pragma: no cover - operator environment
    raise SystemExit('run with the repository .venv (needs pyjwt and requests)')

APP = '6809255441'
BASE = 'https://api.appstoreconnect.apple.com'
CONFIG = os.path.expanduser('~/Library/Application Support/TongxingRelease/api-key.json')


class StoreAPI:
    def __init__(self, config=CONFIG):
        cfg = json.load(open(config))
        self.key_id = cfg['key_id']
        self.issuer_id = cfg['issuer_id']
        self.key = open(cfg['key_filepath'], 'rb').read()

    def token(self):
        now = int(time.time())
        return jwt.encode({'iss': self.issuer_id, 'iat': now, 'exp': now + 900, 'aud': 'appstoreconnect-v1'},
                          self.key, algorithm='ES256', headers={'kid': self.key_id})

    def call(self, method, path, params=None, body=None):
        url = BASE + path + ('?' + urllib.parse.urlencode(params) if params else '')
        response = requests.request(method, url, headers={'Authorization': f'Bearer {self.token()}',
                                 'Content-Type': 'application/json'}, json=body, timeout=120)
        if response.status_code >= 400:
            raise SystemExit(f'{method} {path} -> {response.status_code}: {response.text[:500]}')
        return response.json() if response.text else {}

    def version(self, number):
        data = self.call('GET', f'/v1/apps/{APP}/appStoreVersions',
                         {'filter[versionString]': number, 'filter[platform]': 'IOS',
                          'fields[appStoreVersions]': 'versionString,appStoreState'})['data']
        if not data:
            raise SystemExit(f'version {number} not found')
        return data[0]['id'], data[0]['attributes']['appStoreState']

    def localization(self, version_id, locale):
        for row in self.call('GET', f'/v1/appStoreVersions/{version_id}/appStoreVersionLocalizations',
                             {'fields[appStoreVersionLocalizations]': 'locale'})['data']:
            if row['attributes']['locale'] == locale:
                return row['id']
        raise SystemExit(f'locale {locale} not found on the version')

    def screenshot_sets(self, localization_id, display_type):
        sets = self.call('GET', f'/v1/appStoreVersionLocalizations/{localization_id}/appScreenshotSets',
                         {'fields[appScreenshotSets]': 'screenshotDisplayType'})['data']
        return [row for row in sets if row['attributes']['screenshotDisplayType'] == display_type]

    def upload_one(self, set_id, path):
        raw = open(path, 'rb').read()
        shot = self.call('POST', '/v1/appScreenshots', body={'data': {
            'type': 'appScreenshots',
            'attributes': {'fileSize': len(raw), 'fileName': os.path.basename(path)},
            'relationships': {'appScreenshotSet': {'data': {'type': 'appScreenshotSets', 'id': set_id}}}}})['data']
        for operation in shot['attributes'].get('uploadOperations') or []:
            headers = {h['name']: h['value'] for h in operation.get('requestHeaders') or []}
            chunk = raw[operation['offset']:operation['offset'] + operation['length']]
            response = requests.request(operation['method'], operation['url'], data=chunk,
                                        headers=headers, timeout=300)
            if response.status_code not in (200, 201, 204):
                raise SystemExit(f'upload of {path} failed: HTTP {response.status_code} {response.text[:200]}')
        self.call('PATCH', f"/v1/appScreenshots/{shot['id']}", body={'data': {
            'type': 'appScreenshots', 'id': shot['id'], 'attributes': {'uploaded': True}}})
        state = None
        for _ in range(30):
            attributes = self.call('GET', f"/v1/appScreenshots/{shot['id']}",
                                   {'fields[appScreenshots]': 'assetDeliveryState,fileName'})['data']['attributes']
            state = (attributes.get('assetDeliveryState') or {}).get('state')
            if state in ('COMPLETE', 'FAILED'):
                break
            time.sleep(2)
        return {'id': shot['id'], 'fileName': attributes.get('fileName'), 'state': state, 'path': path}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--version', required=True, help='marketing version, e.g. 1.26.36')
    parser.add_argument('--locale', required=True, help='e.g. zh-Hans or en-US')
    parser.add_argument('--display-type', required=True, help='e.g. APP_IPHONE_DUO')
    parser.add_argument('--images', nargs='+', required=True, help='images in display order')
    parser.add_argument('--receipt', required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.dry_run == args.execute:
        raise SystemExit('pass exactly one of --dry-run / --execute')
    for path in args.images:
        if not os.path.exists(path):
            raise SystemExit(f'missing image {path}')

    api = StoreAPI()
    version_id, state = api.version(args.version)
    if state != 'PREPARE_FOR_SUBMISSION' and args.execute:
        raise SystemExit(f'version {args.version} is {state}; only PREPARE_FOR_SUBMISSION can be edited')
    localization = api.localization(version_id, args.locale)
    old = api.screenshot_sets(localization, args.display_type)
    receipt = {'version': args.version, 'versionId': version_id, 'versionState': state,
               'locale': args.locale, 'displayType': args.display_type,
               'replacedSetIds': [row['id'] for row in old], 'images': []}
    for path in args.images:
        raw = open(path, 'rb').read()
        receipt['images'].append({'path': path, 'bytes': len(raw),
                                  'sha256': hashlib.sha256(raw).hexdigest()})
    print(json.dumps({'version': args.version, 'versionState': state, 'locale': args.locale,
                      'displayType': args.display_type, 'replacing': receipt['replacedSetIds'],
                      'images': [(os.path.basename(row['path']), row['bytes']) for row in receipt['images']]},
                     ensure_ascii=False))
    if args.dry_run:
        json.dump(receipt, open(args.receipt, 'w'), ensure_ascii=False, indent=1)
        return 0

    for row in old:
        api.call('DELETE', f"/v1/appScreenshotSets/{row['id']}")
    created = api.call('POST', '/v1/appScreenshotSets', body={'data': {
        'type': 'appScreenshotSets', 'attributes': {'screenshotDisplayType': args.display_type},
        'relationships': {'appStoreVersionLocalization': {'data': {
            'type': 'appStoreVersionLocalizations', 'id': localization}}}}})['data']
    receipt['createdSetId'] = created['id']
    receipt['uploaded'] = [api.upload_one(created['id'], path) for path in args.images]
    json.dump(receipt, open(args.receipt, 'w'), ensure_ascii=False, indent=1)
    failed = [row for row in receipt['uploaded'] if row['state'] != 'COMPLETE']
    print(json.dumps({'createdSetId': created['id'], 'uploaded': len(receipt['uploaded']),
                      'states': [row['state'] for row in receipt['uploaded']],
                      'deleted': receipt['replacedSetIds']}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
