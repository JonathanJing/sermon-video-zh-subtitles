"""Offline stdlib transport tests: synthetic credentials, no provider requests."""
import io
import json
import ssl
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request
import urllib.response

from scripts import sermon_provider_http as http

URL = 'https://api.openai.com/v1/chat/completions'
TOKEN = 'Bearer synthetic-never-real-key'


def request(url=URL, body=b'{"model":"synthetic"}', **extra):
    return urllib.request.Request(url, data=body, method='POST',
        headers={'Authorization': TOKEN, 'Content-Type': 'application/json', **extra})


class Response(io.BytesIO):
    def __init__(self, body, *, headers=None, url=URL):
        super().__init__(body)
        self.headers = headers or {}
        self.status = 200
        self.url = url
        self.read_sizes = []

    def geturl(self):
        return self.url

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class StrictResponseTests(unittest.TestCase):
    def test_duplicate_json_identity_or_usage_is_unknown(self):
        for raw in (b'{"model":"one","model":"two"}',
                    b'{"usage":{"input_tokens":1,"input_tokens":2}}'):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError,'duplicate_provider_json_key'):
                http._strict_json(raw)


class ProviderHTTPTests(unittest.TestCase):
    def worker(self, response=None, *, error=None, req=None):
        opener = Mock()
        opener.open.side_effect = error
        opener.open.return_value = response
        output = io.BytesIO()
        http._worker(io.BytesIO(http._encode_request(req or request(), 1)), output, opener=opener)
        return json.loads(output.getvalue()), opener

    def test_one_request_returns_json_and_preserves_safe_routing_headers(self):
        response = Response(b'{"id":"fixture","usage":{"input_tokens":1}}')
        result, opener = self.worker(response, req=request(**{
            'OpenAI-Project': 'proj_fixture', 'OpenAI-Organization': 'org-fixture'}))
        self.assertEqual(result, {'status': 'ok', 'response': {'id': 'fixture', 'usage': {'input_tokens': 1}}})
        opener.open.assert_called_once()
        sent = opener.open.call_args.args[0]
        self.assertEqual(sent.full_url, URL)
        self.assertEqual(sent.get_method(), 'POST')
        self.assertEqual(dict((k.lower(), v) for k, v in sent.header_items())['openai-project'], 'proj_fixture')
        self.assertEqual(response.read_sizes, [http.MAX_RESPONSE_BYTES + 1])

    def test_credentials_only_in_private_stdin_not_command_environment_or_files(self):
        process = Mock(returncode=0)
        process.communicate.return_value = (b'{"status":"ok","response":{"id":"fixture"}}', None)
        with patch.object(http.subprocess, 'Popen', return_value=process) as popen:
            self.assertEqual(http.execute(request(), 3), {'id': 'fixture'})
        command = popen.call_args.args[0]
        self.assertEqual(command[:2], [sys.executable, '-I'])
        self.assertEqual(command[-1], '--worker')
        self.assertNotIn(TOKEN, repr(command))
        self.assertEqual(popen.call_args.kwargs['env'], {})
        self.assertEqual(popen.call_args.kwargs['stderr'], subprocess.DEVNULL)
        self.assertTrue(popen.call_args.kwargs['close_fds'])
        self.assertIn(TOKEN.encode(), process.communicate.call_args.args[0])
        process.communicate.assert_called_once()

    def test_encoding_delay_does_not_renew_absolute_deadline(self):
        clock = [100.]
        original = http._encode_request
        def delayed(*args, **kwargs):
            packet = original(*args, **kwargs)
            clock[0] = 106.
            return packet
        with patch.object(http.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(http, '_encode_request', side_effect=delayed), \
                patch.object(http.subprocess, 'Popen') as spawn:
            with self.assertRaises(http.ProviderTimeout):
                http.execute(request(), 5, deadline=105.)
            spawn.assert_not_called()

    def test_handoff_preemption_and_worker_packet_delay_never_dispatch(self):
        with patch.object(http.time, 'monotonic', return_value=106.), \
                patch.object(http.subprocess, 'Popen') as spawn:
            with self.assertRaises(http.ProviderTimeout):
                http.execute(request(), 5, deadline=105.)
            spawn.assert_not_called()
        packet = http._encode_request(request(), 5, deadline=105.)
        opener, output = Mock(), io.BytesIO()
        with patch.object(http.time, 'monotonic', return_value=106.):
            http._worker(io.BytesIO(packet), output, opener=opener)
        opener.open.assert_not_called()
        self.assertEqual(json.loads(output.getvalue()), {'status': 'outcome_unknown'})

    def test_spawn_delay_kills_worker_before_sending_request(self):
        clock, process = [100.], Mock()
        def spawn(*args, **kwargs):
            clock[0] = 106.
            return process
        with patch.object(http.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(http.subprocess, 'Popen', side_effect=spawn):
            with self.assertRaises(http.ProviderTimeout):
                http.execute(request(), 5, deadline=105.)
        process.kill.assert_called_once()
        process.communicate.assert_called_once_with()

    def test_actual_stalled_child_is_killed_reaped_with_hard_deadline(self):
        real_popen, children = subprocess.Popen, []
        def offline_child(command, **kwargs):
            child = real_popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'], **kwargs)
            children.append(child)
            return child
        started = time.monotonic()
        with patch.object(http.subprocess, 'Popen', side_effect=offline_child):
            with self.assertRaisesRegex(http.ProviderTimeout, 'outcome_unknown'):
                http.execute(request(), .15)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].returncode)
        self.assertLess(children[0].returncode, 0)
        self.assertTrue(children[0].stdin.closed)
        self.assertTrue(children[0].stdout.closed)

    def test_http_error_has_status_only_and_no_body_or_headers(self):
        class SecretBody(io.BytesIO):
            reads = 0
            def read(self, *_):
                self.reads += 1
                return super().read()
        body = SecretBody(b'synthetic-private-provider-body')
        result, opener = self.worker(error=urllib.error.HTTPError(URL, 429, 'private reason',
            {'Private': 'synthetic-secret'}, body))
        self.assertEqual(result, {'status': 'http_error', 'httpStatus': 429})
        self.assertEqual(body.reads, 0)
        self.assertTrue(body.closed)
        opener.open.assert_called_once()
        process = Mock(returncode=0)
        process.communicate.return_value = (json.dumps(result).encode(), None)
        with patch.object(http.subprocess, 'Popen', return_value=process):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                http.execute(request(), 1)
        self.assertEqual(caught.exception.code, 429)
        self.assertEqual(caught.exception.read(), b'')
        self.assertEqual(caught.exception.headers, {})
        self.assertNotIn('private', str(caught.exception))

    def test_redirect_is_rejected_without_forwarding_credentials(self):
        calls = []
        class RedirectTransport(urllib.request.HTTPSHandler):
            def https_open(self, req):
                calls.append(req.full_url)
                result = urllib.response.addinfourl(io.BytesIO(b'private redirect body'),
                    {'Location': 'https://example.invalid/steal'}, req.full_url, 302)
                result.msg = 'Found'
                return result
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            RedirectTransport(), http._NoRedirect())
        output = io.BytesIO()
        http._worker(io.BytesIO(http._encode_request(request(), 1)), output, opener=opener)
        self.assertEqual(json.loads(output.getvalue()), {'status': 'http_error', 'httpStatus': 302})
        self.assertEqual(calls, [URL])
        self.assertNotIn(b'private', output.getvalue())

    def test_default_opener_disables_proxy_and_uses_verified_tls(self):
        with patch.object(http.urllib.request, 'build_opener', return_value=object()) as build:
            http._opener()
        handlers = build.call_args.args
        proxy = next(h for h in handlers if isinstance(h, urllib.request.ProxyHandler))
        tls = next(h for h in handlers if isinstance(h, urllib.request.HTTPSHandler))
        self.assertEqual(proxy.proxies, {})
        self.assertTrue(tls._context.check_hostname)
        self.assertEqual(tls._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(any(isinstance(h, http._NoRedirect) for h in handlers))

    def test_response_limit_handles_declared_and_streamed_overflow(self):
        with patch.object(http, 'MAX_RESPONSE_BYTES', 32):
            declared = Response(b'{}', headers={'Content-Length': '33'})
            result, _ = self.worker(declared)
            self.assertEqual(result, {'status': 'outcome_unknown'})
            self.assertEqual(declared.read_sizes, [])
            streamed = Response(b'{"text":"' + b'x' * 100 + b'"}')
            result, _ = self.worker(streamed)
            self.assertEqual(result, {'status': 'outcome_unknown'})
            self.assertEqual(streamed.read_sizes, [33])

    def test_invalid_and_unknown_responses_are_sanitized_without_retry(self):
        for raw in (b'not json synthetic-private', b'[]', b'{"x":NaN}', b'\xff'):
            with self.subTest(raw=raw):
                result, opener = self.worker(Response(raw))
                self.assertEqual(result, {'status': 'outcome_unknown'})
                opener.open.assert_called_once()
        result, opener = self.worker(error=urllib.error.URLError('synthetic-secret'))
        self.assertEqual(result, {'status': 'outcome_unknown'})
        opener.open.assert_called_once()
        for output in (b'{"status":"outcome_unknown"}', b'private invalid output',
                       b'x' * (http.MAX_RESULT_BYTES + 1)):
            process = Mock(returncode=0)
            process.communicate.return_value = (output, None)
            with patch.object(http.subprocess, 'Popen', return_value=process):
                with self.assertRaises(http.ProviderOutcomeUnknown): http.execute(request(), 1)
            process.communicate.assert_called_once()

    def test_untrusted_endpoint_headers_size_and_timeout_reject_before_spawn(self):
        rejected = [request(url) for url in (
            'http://api.openai.com/v1/chat/completions', 'https://api.openai.com.evil/v1/chat/completions',
            URL + '?private=true', URL + '#fragment', 'https://user:pass@api.openai.com/v1/chat/completions',
            'https://api.openai.com:443/v1/chat/completions', 'https://api.openai.com/v1/responses')]
        rejected.extend([request(**{'Host': 'evil.invalid'}), request(**{'OpenAI-Project': 'bad\r\nHeader: value'})])
        with patch.object(http.subprocess, 'Popen') as popen:
            for req in rejected:
                with self.assertRaises(ValueError): http.execute(req, 1)
            for timeout in (0, -1, float('nan'), float('inf'), True, '1'):
                with self.assertRaises(ValueError): http.execute(request(), timeout)
            with patch.object(http, 'MAX_REQUEST_BYTES', 1):
                with self.assertRaises(ValueError): http.execute(request(), 1)
            popen.assert_not_called()

    def test_multipart_bytes_pass_without_disk_access_and_worker_revalidates_packet(self):
        req = urllib.request.Request('https://api.openai.com/v1/audio/transcriptions', method='POST',
            data=b'--fixture\r\nsynthetic-media\x00\xff\r\n--fixture--', headers={
                'Authorization': TOKEN, 'Content-Type': 'multipart/form-data; boundary=fixture'})
        response = Response(b'{"text":"fixture"}', url=req.full_url)
        result, opener = self.worker(response, req=req)
        self.assertEqual(result['response'], {'text': 'fixture'})
        self.assertEqual(opener.open.call_args.args[0].data, req.data)
        malformed = http._encode_request(request(), 1) + b'trailing'
        output, opener = io.BytesIO(), Mock()
        http._worker(io.BytesIO(malformed), output, opener=opener)
        self.assertEqual(json.loads(output.getvalue()), {'status': 'outcome_unknown'})
        opener.open.assert_not_called()


if __name__ == '__main__': unittest.main()
