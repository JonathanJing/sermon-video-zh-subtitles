import copy
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
import urllib.error

from scripts import align_firebase_dev_v3 as dev


class DevBucketHostingTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.public = Path(tmp.name) / 'public'
        self.public.mkdir()
        self.data = b'verified-mp4'
        sha = hashlib.sha256(self.data).hexdigest()
        self.delivery = {'schemaVersion': 'sermon-video-delivery-v1',
                         'canonicalUrl': '/pages/week/full-video-browser.mp4',
                         'storageUrl': f'https://storage.googleapis.com/ai-for-god-sermon-media-prod/weekly/week/{sha}.mp4',
                         'sha256': sha, 'bytes': len(self.data)}
        (self.public / 'multilingual-v3.json').write_text(json.dumps(
            {'defaultPageId': 'week', 'pages': [{'id': 'week', 'videoDelivery': self.delivery}]}))
        (self.public.parent / 'bucket-video-receipt.json').write_text(json.dumps(
            {'schemaVersion': 'sermon-v3-bucket-video-http-verification-v1', 'status': 'pass',
             'pageId': 'week', 'videoDelivery': self.delivery, 'redirectStatus': 302, 'rangeStatus': 206,
             'fullGetBytes': len(self.data), 'fullGetSha256': sha}))
        self.config = {'hosting': {'site': dev.SITE, 'public': 'public',
                                  'rewrites': [{'source': '/pages/**', 'destination': '/index.html'}],
                                  'headers': [{'source': '**', 'headers': [{'key': 'Content-Security-Policy',
                                               'value': "default-src 'self'; media-src 'self' blob:;"}]}]}}

    def test_reconstructs_exact_redirect_and_csp_without_mutating_base(self):
        before = copy.deepcopy(self.config)
        staged = dev.bucket_hosting_config(self.config, self.public)
        self.assertEqual(self.config, before)
        self.assertEqual(staged['hosting']['site'], dev.SITE)
        dev.validate_bucket_hosting(staged, self.public)
        self.assertEqual(staged['hosting']['redirects'], [{'source': self.delivery['canonicalUrl'],
                          'destination': self.delivery['storageUrl'], 'type': 302}])
        self.assertEqual(dev.bucket_hosting_config(staged, self.public), staged)

    def test_missing_or_wrong_redirect_and_csp_rejected(self):
        with self.assertRaisesRegex(ValueError, 'redirect'):
            dev.validate_bucket_hosting(self.config, self.public)
        staged = dev.bucket_hosting_config(self.config, self.public)
        staged['hosting']['headers'] = self.config['hosting']['headers']
        with self.assertRaisesRegex(ValueError, 'CSP'):
            dev.validate_bucket_hosting(staged, self.public)
        staged['hosting']['redirects'][0]['destination'] += 'wrong'
        with self.assertRaisesRegex(ValueError, 'redirect'):
            dev.bucket_hosting_config(staged, self.public)

    def response(self, body, status, headers=None):
        response = io.BytesIO(body)
        response.status = status
        response.url = self.delivery['storageUrl']
        response.headers = headers or {}
        return response

    def test_http_requires_redirect_range_cors_and_full_hash(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError('video', 302, 'redirect',
                                                        {'Location': self.delivery['storageUrl']}, None)
        headers = {'Content-Range': f"bytes 0-0/{len(self.data)}", 'Access-Control-Allow-Origin': dev.ORIGIN}
        with patch.object(dev.urllib.request, 'build_opener', return_value=opener), patch.object(
                dev.bucket_http, 'request', side_effect=[self.response(self.data[:1], 206, headers),
                                                       self.response(self.data, 200)]):
            self.assertTrue(dev.verify_bucket_route(self.delivery)['videoRedirect302'])
        with patch.object(dev.urllib.request, 'build_opener', return_value=Mock(open=Mock(return_value=io.BytesIO(b'<html>')))):
            with self.assertRaisesRegex(ValueError, 'did not redirect'):
                dev.verify_bucket_route(self.delivery)
        with patch.object(dev.urllib.request, 'build_opener', return_value=opener), patch.object(
                dev.bucket_http, 'request', side_effect=[self.response(self.data[:1], 206, headers),
                                                       self.response(b'x' * len(self.data), 200)]):
            with self.assertRaisesRegex(ValueError, 'hash differs'):
                dev.verify_bucket_route(self.delivery)
