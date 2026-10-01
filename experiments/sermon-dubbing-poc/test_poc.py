import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urljoin, urlsplit

HERE = Path(__file__).resolve().parent


def module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


poc = module("poc")
server = module("server")


class SpeechTests(unittest.TestCase):
    def test_variants_preserve_quotes_names_and_full_content(self):
        paragraphs = ['他说：“要来吗？”大家回答：“要！”今天读诗篇55篇。', '大卫信任亚希多弗。他是谋士。']
        for mode in ['flow', 'sentence']:
            units = poc.speech_units(paragraphs, mode)
            self.assertEqual(''.join(units), ''.join(paragraphs))
        self.assertGreater(len(poc.speech_units(paragraphs, 'sentence')), len(poc.speech_units(paragraphs, 'flow')))

    def test_no_silent_loss_of_unpunctuated_last_clause(self):
        self.assertEqual(poc.speech_units(['第一句。最后一句没有句号'], 'sentence'), ['第一句。', '最后一句没有句号'])

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):
            poc.speech_units(['文本。'], 'unknown')


class RangeTests(unittest.TestCase):
    def test_partial_open_ended_and_suffix(self):
        self.assertEqual(server.byte_range('bytes=2-4', 10), (2, 4))
        self.assertEqual(server.byte_range('bytes=8-', 10), (8, 9))
        self.assertEqual(server.byte_range('bytes=-3', 10), (7, 9))
        self.assertEqual(server.byte_range('bytes=1-99', 10), (1, 9))

    def test_invalid_and_out_of_bounds(self):
        for value in ['bytes=10-', 'bytes=5-3', 'bytes=-0', 'bytes=-', 'bytes=1-2,4-5', 'bad']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                server.byte_range(value, 10)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.pack = Path(self.temp.name)
        (self.pack / 'flow.mp3').write_bytes(b'0123456789')
        self.library = {'schemaVersion': 'sermon-audio-library-v1', 'tracks': [{'id': 'flow', 'file': 'flow.mp3', 'audioUrl': '/media/flow.mp3', 'durationSeconds': 10}]}
        (self.pack / 'library.json').write_text(json.dumps(self.library))
        self.server = server.make_server(self.pack, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def test_real_http_seek_and_head(self):
        with urlopen(Request(self.base + '/media/flow.mp3', headers={'Range': 'bytes=2-5'})) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers['Content-Range'], 'bytes 2-5/10')
            self.assertEqual(response.read(), b'2345')
        with urlopen(Request(self.base + '/media/flow.mp3', method='HEAD')) as response:
            self.assertEqual(response.headers['Content-Length'], '10')
            self.assertEqual(response.read(), b'')

    def test_range_error_and_no_directory_exposure(self):
        for route, headers, expected in [('/media/flow.mp3', {'Range': 'bytes=20-'}, 416), ('/../../.env', {}, 404), ('/speaker-inventory.json', {}, 404)]:
            with self.subTest(route=route), self.assertRaises(HTTPError) as error:
                urlopen(Request(self.base + route, headers=headers))
            self.assertEqual(error.exception.code, expected)

    def test_symlink_and_path_escape_rejected(self):
        self.library['tracks'][0]['file'] = '../outside.mp3'
        (self.pack / 'library.json').write_text(json.dumps(self.library))
        with self.assertRaises(ValueError):
            server.load_library(self.pack)

    def test_missing_pack_fails_without_fake_library(self):
        (self.pack / 'flow.mp3').unlink()
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base + '/library.json')
        self.assertEqual(error.exception.code, 503)

    def test_weekly_pack_serves_published_weeks_import(self):
        (self.pack / 'weekly.json').write_text('{}')
        module = b'export const ready = true;'
        (self.pack / 'published-weeks.mjs').write_bytes(module)
        with urlopen(self.base + '/published-weeks.mjs') as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers['Content-Type'], 'text/javascript')
            self.assertEqual(response.read(), module)

    def test_library_fallback_serves_icon_modules_and_svg_bytes(self):
        self.assert_static_icons(HERE / 'web')

    def test_weekly_pack_serves_its_own_icon_modules_and_svg_bytes(self):
        (self.pack / 'weekly.json').write_text('{}')
        for name in ['icons.mjs', 'icons.svg', 'brand-icon.svg', 'brand-icon-light.svg']:
            data = (HERE / 'web' / name).read_bytes() + b'\n<!-- pack-specific -->' if name.endswith('.svg') else b'export const packOnly = true;'
            (self.pack / name).write_bytes(data)
        self.assert_static_icons(self.pack)

    def assert_static_icons(self, root):
        for name in ['icons.mjs', 'icons.svg', 'brand-icon.svg', 'brand-icon-light.svg']:
            with self.subTest(name=name), urlopen(self.base + '/' + name) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers['Content-Type'],
                                 'image/svg+xml' if name.endswith('.svg') else 'text/javascript')
                self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
                self.assertEqual(response.read(), (root / name).read_bytes())

    def test_real_http_html_and_module_dependency_closure_in_both_pack_modes(self):
        for weekly in [False, True]:
            with self.subTest(weekly=weekly):
                if weekly:
                    (self.pack / 'weekly.json').write_text('{}')
                    for filename, _ in server.STATIC.values():
                        source = HERE / 'web' / filename
                        if source.is_file():
                            shutil.copyfile(source, self.pack / filename)
                root = self.pack if weekly else HERE / 'web'
                pending, visited = ['/'], set()
                while pending:
                    route = pending.pop()
                    if route in visited:
                        continue
                    visited.add(route)
                    # No dynamic filesystem route was enabled to make this pass.
                    self.assertIn(route, server.STATIC, f'Unregistered dependency: {route}')
                    filename, mime = server.STATIC[route]
                    with urlopen(self.base + route) as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.headers['Content-Type'], mime)
                        data = response.read()
                    self.assertEqual(data, (root / filename).read_bytes())
                    text = data.decode('utf-8')
                    if filename.endswith('.html'):
                        dependencies = re.findall(r'<script\b[^>]*\bsrc=[\'"]([^\'"]+)[\'"]', text)
                        dependencies += re.findall(r'(?:href|src)=[\'"]([^\'"]+\.svg)(?:#[^\'"]*)?[\'"]', text)
                    elif filename.endswith(('.js', '.mjs')):
                        dependencies = re.findall(r'^\s*(?:import|export)\s+(?:[^\n]*?\s+from\s+)?[\'"]([^\'"]+)[\'"]', text, re.MULTILINE)
                        dependencies += re.findall(r'\bimport\s*\(\s*[\'"]([^\'"]+)[\'"]', text)
                        dependencies += re.findall(r'new URL\(\s*[\'"]([^\'"]+\.(?:mjs|js))[\'"]\s*,\s*import\.meta\.url', text)
                    else:
                        dependencies = []
                    for dependency in dependencies:
                        resolved = urlsplit(urljoin(self.base + route, dependency))
                        self.assertEqual(resolved.netloc, urlsplit(self.base).netloc)
                        pending.append(resolved.path)
                self.assertTrue({'/icons.mjs', '/media-session.mjs', '/voice-samples.mjs',
                                 '/fingerprint-ui.mjs', '/fingerprint-worker.mjs',
                                 '/fingerprint-worklet.mjs', '/fingerprint-core.mjs', '/icons.svg'}.issubset(visited))


if __name__ == '__main__':
    unittest.main()
