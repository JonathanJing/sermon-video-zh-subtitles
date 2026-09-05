import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

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


if __name__ == '__main__':
    unittest.main()
