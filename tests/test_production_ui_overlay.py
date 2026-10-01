import io
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import stage_production_ui as ui


class Response(io.BytesIO):
    def __init__(self, url, data, status=200, headers=None):
        super().__init__(data)
        self.url, self.status, self.code = url, status, status
        self.headers = headers or {}

    def geturl(self):
        return self.url


class ProductionUIOverlayTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base, self.overlay = self.root / 'base', self.root / 'overlay'
        self.source, self.out = self.root / 'source', self.root / 'candidate'
        public = self.base / 'public'
        public.mkdir(parents=True)
        self.source_ui = self.source / 'experiments/sermon-dubbing-poc/web'
        self.source_ui.mkdir(parents=True)
        for name in ui.UI_FILES:
            if name not in ('icons.svg', 'icons.mjs', 'brand-icon.svg', 'brand-icon-light.svg'):
                (public / name).write_text('published ' + name)
        self.video = {'canonicalUrl': '/pages/week/full-video.mp4',
                      'storageUrl': 'https://storage.googleapis.com/ai-for-god-sermon-media-prod/video.mp4'}
        self.preserved = {
            'multilingual-v3.json': json.dumps({'schemaVersion': 'sermon-multilingual-catalog-v3',
                                               'pages': [{'videoDelivery': self.video}]}),
            'weekly.json': '{"weeks": [{"id":"week"}]}',
            'engagement.json': '{"enabled":true}',
            'media/audio.mp3': 'real existing audio bytes',
            'voice-demos/speaker/es.mp3': 'existing voice audition',
            'voice-demos/production-ko-es.json': '{"status":"audition_demo"}',
            'pages/week/zh-Hans/index.html': 'published content reader',
            'pages/week/text.json': '{"reviewed":true}',
            'downloads/reading.pdf': 'existing pdf',
            'brand-icon.png': 'existing png'}
        for name, data in self.preserved.items():
            path = public / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data)
        self.config = {'hosting': {'site': ui.SITE, 'public': 'public', 'rewrites': [
            {'source': '/api/**', 'function': {'functionId': 'sermon-feedback-api', 'region': 'us-west1'}}],
            'redirects': [{'source': self.video['canonicalUrl'], 'destination': self.video['storageUrl'], 'type': 302}]}}
        (self.base / 'firebase.json').write_text(json.dumps(self.config))
        shutil.copytree(self.base, self.overlay)
        for name in ui.UI_FILES:
            value = '<svg xmlns="http://www.w3.org/2000/svg"/>' if name.endswith('.svg') else 'icons ' + name
            (self.overlay / 'public' / name).write_text(value)
            if name in ui.DIRECT_SOURCE_FILES:
                (self.source_ui / name).write_text(value)

    def stage(self):
        with patch.object(ui, 'source_commit', return_value='a' * 40):
            return ui.stage(self.base, self.overlay, self.out, source_root=self.source)

    def test_complete_v3_snapshot_preserves_catalog_media_and_voice_assets(self):
        report = self.stage()
        self.assertEqual(report['schemaVersion'], ui.SCHEMA)
        self.assertEqual(report['files'], ui.inventory(self.overlay / 'public'))
        self.assertEqual(report['feedbackDeploymentStatus'], 'unchanged')
        self.assertIn('locales-feedback.mjs', report['modifiedFiles'])
        self.assertEqual(set(report['addedFiles']),
                         {'icons.svg', 'icons.mjs', 'brand-icon.svg', 'brand-icon-light.svg'})
        self.assertEqual([item['path'] for item in report['sourceFiles']], list(ui.UI_FILES))
        for name, value in self.preserved.items():
            self.assertEqual((self.out / 'public' / name).read_text(), value)
        self.assertEqual((self.out / 'firebase.json').read_bytes(), (self.base / 'firebase.json').read_bytes())
        self.assertEqual(ui.verify_candidate(self.out), report)

    def test_media_catalog_and_page_mutations_are_rejected(self):
        for name in ['media/audio.mp3', 'multilingual-v3.json', 'pages/week/text.json', 'engagement.json']:
            with self.subTest(name=name):
                path = self.overlay / 'public' / name
                original = path.read_bytes()
                path.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'non-UI'):
                    self.stage()
                path.write_bytes(original)
        self.assertFalse(self.out.exists())

    def test_baseline_removal_is_rejected(self):
        (self.overlay / 'public/media/audio.mp3').unlink()
        with self.assertRaisesRegex(ValueError, 'removed'):
            self.stage()

    def test_missing_required_icon_module_is_rejected(self):
        (self.overlay / 'public/icons.mjs').unlink()
        with self.assertRaisesRegex(ValueError, 'required UI'):
            self.stage()

    def test_extra_non_allowlisted_file_is_rejected(self):
        (self.overlay / 'public/new-player.js').write_text('unrelated feature')
        with self.assertRaisesRegex(ValueError, 'non-UI'):
            self.stage()

    def test_overlay_configuration_drift_is_rejected(self):
        (self.overlay / 'firebase.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'configuration'):
            self.stage()

    def test_wrong_destination_or_video_redirect_is_rejected(self):
        for field in ['site', 'redirects', 'rewrites']:
            with self.subTest(field=field):
                config = json.loads(json.dumps(self.config))
                config['hosting'][field] = 'other-site' if field == 'site' else []
                for root in [self.base, self.overlay]:
                    (root / 'firebase.json').write_text(json.dumps(config))
                with self.assertRaises(ValueError):
                    self.stage()

    def test_source_artwork_must_match_checked_code(self):
        (self.overlay / 'public/icons.svg').write_text('unreviewed')
        with self.assertRaisesRegex(ValueError, 'checked-in source'):
            self.stage()

    def test_symlink_input_is_rejected(self):
        path = self.overlay / 'public/icons.svg'
        path.unlink()
        path.symlink_to(self.source_ui / 'icons.svg')
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            self.stage()

    def test_post_stage_target_tamper_is_rejected(self):
        self.stage()
        (self.out / 'public/icons.svg').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'Candidate files'):
            ui.verify_candidate(self.out)

    def test_post_stage_extra_target_file_is_rejected(self):
        self.stage()
        (self.out / 'public/unrelated.js').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'Candidate files'):
            ui.verify_candidate(self.out)

    def test_post_stage_source_and_overlay_tamper_are_rejected(self):
        self.stage()
        for path, message in [(self.source_ui / 'icons.svg', 'UI source'),
                              (self.overlay / 'public/index.html', 'overlay UI')]:
            with self.subTest(path=path):
                original = path.read_bytes()
                path.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, message):
                    ui.verify_candidate(self.out)
                path.write_bytes(original)

    def test_non_icon_overlay_bytes_must_match_selected_release_code(self):
        for name in ('app.mjs', 'style.css', 'locales-interface.mjs', 'locales-feedback.mjs', 'fingerprint-ui.mjs', 'theme.js'):
            with self.subTest(name=name):
                path = self.overlay / 'public' / name
                original = path.read_bytes()
                path.write_bytes(b'unreviewed UI code')
                with self.assertRaisesRegex(ValueError, 'checked-in source'):
                    self.stage()
                path.write_bytes(original)
                self.assertFalse(self.out.exists())

    def test_non_icon_source_drift_invalidates_bound_candidate(self):
        self.stage()
        for name in ('app.mjs', 'style.css', 'locales-interface.mjs', 'locales-feedback.mjs', 'fingerprint-ui.mjs', 'theme.js'):
            with self.subTest(name=name):
                path = self.source_ui / name
                original = path.read_bytes()
                path.write_bytes(b'changed release code')
                with self.assertRaisesRegex(ValueError, 'UI source changed'):
                    ui.verify_candidate(self.out)
                path.write_bytes(original)

    def test_post_stage_baseline_or_config_tamper_is_rejected(self):
        self.stage()
        for path in [self.base / 'public/media/audio.mp3', self.out / 'firebase.json']:
            with self.subTest(path=path):
                original = path.read_bytes()
                path.write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    ui.verify_candidate(self.out)
                path.write_bytes(original)

    def test_post_stage_symlink_is_rejected(self):
        self.stage()
        path = self.out / 'public/media/audio.mp3'
        path.unlink()
        path.symlink_to(self.base / 'public/media/audio.mp3')
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            ui.verify_candidate(self.out)

    def opener(self, public, *, bad_svg=False, bad_range=False):
        def open_request(request, timeout):
            name = request.full_url.removeprefix(ui.ORIGIN + '/')
            path = public / name
            data = path.read_bytes()
            mime = 'image/svg+xml' if name.endswith('.svg') else 'application/octet-stream'
            if bad_svg and name.endswith('.svg'):
                mime = 'text/html'
            headers = {'content-type': mime}
            if request.get_header('Range'):
                if bad_range:
                    return Response(request.full_url, b'wrong', 206, headers)
                headers['content-range'] = f'bytes 0-0/{len(data)}'
                return Response(request.full_url, data[:1], 206, headers)
            return Response(request.full_url, data, 200, headers)
        return open_request

    def redirect_opener(self, request, timeout):
        raise HTTPError(request.full_url, 302, 'Found', {'Location': self.video['storageUrl']}, io.BytesIO())

    def test_http_baseline_and_published_receipts_bind_all_files_audio_and_redirect(self):
        report = self.stage()
        for baseline in [True, False]:
            with self.subTest(baseline=baseline):
                public = self.base / 'public' if baseline else self.out / 'public'
                receipt = ui.check_http(self.out, baseline=baseline, workers=2,
                                        opener=self.opener(public), redirect_opener=self.redirect_opener)
                self.assertEqual(receipt['status'], 'pass')
                self.assertEqual(receipt['phase'], 'baseline' if baseline else 'published')
                self.assertEqual(receipt['checkedFiles'], len(report['baseFiles' if baseline else 'files']))
                self.assertEqual(receipt['buildReportSha256'], ui.hosting.digest(self.out / 'build-report.json'))
                self.assertEqual(sum(item.get('range206', False) for item in receipt['results']), 2)
                self.assertEqual(receipt['results'][-1]['redirect'], self.video['storageUrl'])

    def test_http_svg_wrong_mime_and_audio_bad_range_are_rejected(self):
        self.stage()
        for options, message in [({'bad_svg': True}, 'SVG Content-Type'),
                                 ({'bad_range': True}, 'Audio Range')]:
            with self.subTest(options=options):
                with self.assertRaisesRegex(ValueError, message):
                    ui.check_http(self.out, baseline=False, workers=1,
                                  opener=self.opener(self.out / 'public', **options),
                                  redirect_opener=self.redirect_opener)

    def test_audio_full_body_fallback_is_bound_to_complete_hash(self):
        self.stage()
        def full_body(request, timeout):
            path = self.out / 'public' / request.full_url.removeprefix(ui.ORIGIN + '/')
            mime = 'image/svg+xml' if path.suffix == '.svg' else 'application/octet-stream'
            return Response(request.full_url, path.read_bytes(), 200, {'content-type': mime})
        receipt = ui.check_http(self.out, baseline=False, opener=full_body,
                                redirect_opener=self.redirect_opener)
        self.assertEqual(sum(item.get('fullBodyFallback', False)
                             for item in receipt['results']), 2)

    def test_http_wrong_bytes_and_redirect_are_rejected(self):
        self.stage()
        def wrong_bytes(request, timeout):
            return Response(request.full_url, b'wrong', 200, {})
        with self.assertRaisesRegex(ValueError, 'Production file'):
            ui.check_http(self.out, baseline=True, opener=wrong_bytes,
                          redirect_opener=self.redirect_opener)
        def wrong_redirect(request, timeout):
            return Response(request.full_url, b'', 200, {})
        with self.assertRaisesRegex(ValueError, 'redirect changed'):
            ui.check_http(self.out, baseline=False, opener=self.opener(self.out / 'public'),
                          redirect_opener=wrong_redirect)


if __name__ == '__main__':
    unittest.main()
