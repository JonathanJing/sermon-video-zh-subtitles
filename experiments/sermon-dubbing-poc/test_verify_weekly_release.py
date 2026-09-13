"""Offline public-release delivery checks; no network or private media."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.request

import verify_weekly_release as verify


ORIGIN = "https://listening.example.test"


class FakeResponse:
    def __init__(self, url, body, *, status=200, headers=None, chunk_size=31):
        self.url, self.body, self.status = url, body, status
        self.headers = headers if headers is not None else {"Content-Length": str(len(body))}
        self.chunk_size = chunk_size
        self.closed = False
        self.chunks = 0

    def iter_bytes(self):
        for offset in range(0, len(self.body), self.chunk_size):
            self.chunks += 1
            yield self.body[offset:offset+self.chunk_size]

    def close(self):
        self.closed = True


class PublicReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release = self.root / "release"
        self.files = {"weekly.json": b'{"fixture":"catalog"}\n', "index.html": b"<html>fixture</html>",
                      "app.mjs": b"export const fixture = true;", "alignment/fixture.json": b'{"fixture":"alignment"}',
                      "media/fixture.mp3": bytes(range(256)) * 9}
        rows = []
        for name, body in self.files.items():
            path = self.release / "public" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            rows.append({"path": name, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)})
        self.report = {"files": rows}
        (self.release / "build-report.json").write_text(json.dumps(self.report))
        self.reader = patch.object(verify, "read_release", return_value=(self.report, {"fixture": "validated catalog"})).start()
        self.addCleanup(patch.stopall)
        self.requests = []
        self.responses = []

    def fetcher(self, url, *, headers, timeout):
        self.requests.append((url, headers, timeout))
        path = url.removeprefix(ORIGIN + "/")
        body = self.files[path]
        if "Range" in headers:
            response = FakeResponse(url, body[:1024], status=206,
                headers={"Content-Range": f"bytes 0-{min(1023,len(body)-1)}/{len(body)}"})
        else:
            response = FakeResponse(url, body)
        self.responses.append(response)
        return response

    def run_verify(self, **kwargs):
        return verify.verify_public_release(self.release, ORIGIN, fetcher=kwargs.pop("fetcher", self.fetcher), **kwargs)

    def test_all_files_catalog_first_streamed_media_range_and_bound_report(self):
        result = self.run_verify()
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["origin"], ORIGIN)
        self.assertEqual(result["buildReportSha256"], hashlib.sha256((self.release / "build-report.json").read_bytes()).hexdigest())
        self.assertEqual(result["client_smoke"], "not_run")
        self.assertEqual(self.requests[0][0], ORIGIN + "/weekly.json")
        self.assertEqual({row["path"] for row in result["checkedFiles"]}, set(self.files))
        self.assertEqual(result["expectedFileCount"], len(self.files))
        self.assertEqual(result["checkedFileCount"], len(self.files))
        self.assertEqual(result["totalDownloadedBytes"], sum(map(len, self.files.values())) + 1024)
        for row in result["checkedFiles"]:
            self.assertEqual(row["observedSha256"], row["expectedSha256"])
            self.assertEqual(row["receivedBytes"], row["expectedBytes"])
        self.assertEqual(len(result["audioRanges"]), 1)
        audio_range = result["audioRanges"][0]
        self.assertEqual(audio_range["httpStatus"], 206)
        self.assertEqual(audio_range["contentRange"], "bytes 0-1023/2304")
        self.assertEqual(audio_range["expectedSha256"], audio_range["observedSha256"])
        self.assertTrue(all(r.closed for r in self.responses))
        self.assertTrue(any(r.chunks > 10 for r in self.responses))
        for _url, headers, timeout in self.requests:
            self.assertNotIn("Authorization", headers)
            self.assertNotIn("Cookie", headers)
            self.assertEqual(headers["Accept-Encoding"], "identity")
            self.assertGreater(timeout, 0)

    def test_weekly_mismatch_fails_even_when_other_files_match(self):
        self.files["weekly.json"] = self.files["weekly.json"].replace(b"catalog", b"changed")
        result = self.run_verify()
        self.assertFalse(result["passed"])
        self.assertIn({"path": "weekly.json", "check": "file", "code": "sha256_mismatch"}, result["failures"])

    def test_receipt_matches_release_registry_contract(self):
        import weekly_release
        receipt = self.run_verify()
        with patch.object(weekly_release, "read_release", return_value=(self.report, {})):
            self.assertEqual(weekly_release.check_verification(self.release, receipt, ORIGIN), self.report)

    def test_missing_ui_or_alignment_is_not_ignored(self):
        def missing(url, **kwargs):
            if url.endswith("alignment/fixture.json"):
                raise verify.VerificationError("http_error", http_status=404)
            return self.fetcher(url, **kwargs)
        result = self.run_verify(fetcher=missing)
        self.assertFalse(result["passed"])
        row = next(r for r in result["checkedFiles"] if r["path"] == "alignment/fixture.json")
        self.assertEqual(row["httpStatus"], 404)
        self.assertFalse(row["passed"])

    def test_range_200_wrong_header_and_wrong_prefix_all_fail(self):
        for mode in ("ignored", "header", "prefix"):
            with self.subTest(mode=mode):
                def bad_range(url, **kwargs):
                    response = self.fetcher(url, **kwargs)
                    if "Range" in kwargs["headers"]:
                        if mode == "ignored":
                            response.status = 200
                        elif mode == "header":
                            response.headers["Content-Range"] = "bytes 0-1023/9999"
                        else:
                            response.body = b"x" * 1024
                    return response
                result = self.run_verify(fetcher=bad_range)
                self.assertFalse(result["passed"])
                self.assertEqual(result["audioRanges"][0]["code"], {
                    "ignored": "unexpected_http_status", "header": "invalid_content_range", "prefix": "range_prefix_mismatch"}[mode])

    def test_small_audio_uses_actual_short_range_prefix(self):
        body = b"small-audio"
        self.files["media/fixture.mp3"] = body
        (self.release / "public/media/fixture.mp3").write_bytes(body)
        row = next(r for r in self.report["files"] if r["path"].endswith(".mp3"))
        row.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
        result = self.run_verify()
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["audioRanges"][0]["contentRange"], "bytes 0-10/11")
        self.assertEqual(self.requests[-1][1]["Range"], "bytes=0-1023")

    def test_redirected_response_other_host_or_plain_http_fails(self):
        for target in ("https://other.example.test/file", "http://listening.example.test/file", "https://secret@listening.example.test/file"):
            with self.subTest(target=target):
                def redirect(url, **kwargs):
                    response = self.fetcher(url, **kwargs)
                    response.url = target
                    return response
                result = self.run_verify(fetcher=redirect)
                self.assertFalse(result["passed"])
                self.assertEqual(result["checkedFiles"][0]["code"], "redirect_not_allowed")

    def test_invalid_origins_do_not_fetch_or_echo_userinfo(self):
        for origin in ("http://example.test", "https://secret@example.test", "https://example.test/path",
                       "https://example.test?token=secret", "https://example.test?", "https://example.test#", "https://example.test:0"):
            with self.subTest(origin=origin):
                fetcher = Mock()
                result = verify.verify_public_release(self.release, origin, fetcher=fetcher)
                self.assertFalse(result["passed"])
                self.assertIsNone(result["origin"])
                self.assertNotIn("secret", json.dumps(result))
                fetcher.assert_not_called()

    def test_local_validation_failure_prevents_any_request(self):
        self.reader.side_effect = ValueError("private/file changed; secret")
        fetch = Mock()
        result = self.run_verify(fetcher=fetch)
        self.assertFalse(result["passed"])
        self.assertEqual(result["failures"][0]["code"], "local_release_invalid")
        self.assertNotIn("secret", json.dumps(result))
        fetch.assert_not_called()

    def test_total_download_budget_and_timeout_stop_further_work(self):
        with patch.object(verify, "MAX_TOTAL_BYTES", 40):
            result = self.run_verify()
        self.assertFalse(result["passed"])
        self.assertEqual(result["failures"][-1]["code"], "total_byte_limit")
        self.assertLess(result["checkedFileCount"], result["expectedFileCount"])
        with patch.object(verify, "MAX_TOTAL_SECONDS", -1):
            result = self.run_verify()
        self.assertFalse(result["passed"])
        self.assertEqual(result["failures"][0]["code"], "total_timeout")

    def test_request_timeout_stays_failed_and_response_does_not_leak_details(self):
        result = self.run_verify(fetcher=Mock(side_effect=TimeoutError("private origin details")))
        self.assertFalse(result["passed"])
        self.assertEqual(result["checkedFiles"][0]["code"], "request_timeout")
        self.assertNotIn("private origin", json.dumps(result))

    def test_zero_byte_audio_never_passes_a_range_check(self):
        self.files["media/fixture.mp3"] = b""
        (self.release / "public/media/fixture.mp3").write_bytes(b"")
        row = next(r for r in self.report["files"] if r["path"].endswith(".mp3"))
        row.update(bytes=0, sha256=hashlib.sha256(b"").hexdigest())
        result = self.run_verify()
        self.assertFalse(result["passed"])
        self.assertEqual(result["audioRanges"][0]["code"], "empty_audio")

    def test_changed_local_build_report_during_network_check_is_rejected(self):
        def mutate(url, **kwargs):
            response = self.fetcher(url, **kwargs)
            if url.endswith("weekly.json"):
                (self.release / "build-report.json").write_text('{"changed":true}')
            return response
        result = self.run_verify(fetcher=mutate)
        self.assertFalse(result["passed"])
        self.assertEqual(result["failures"][-1]["code"], "local_release_changed")

    def test_unexpected_fetch_exception_is_reported_without_private_message(self):
        result = self.run_verify(fetcher=Mock(side_effect=ValueError("secret/path/token")))
        self.assertFalse(result["passed"])
        self.assertEqual(result["checkedFiles"][0]["code"], "fetch_error")
        self.assertNotIn("secret", json.dumps(result))

    def test_truncated_and_oversized_bodies_fail_without_content_length(self):
        for delta in (-1, 1):
            with self.subTest(delta=delta):
                def body_problem(url, **kwargs):
                    response = self.fetcher(url, **kwargs)
                    if url.endswith("app.mjs"):
                        response.headers = {}
                        response.body = response.body[:-1] if delta == -1 else response.body + b"x"
                    return response
                result = self.run_verify(fetcher=body_problem)
                self.assertFalse(result["passed"])
                row = next(r for r in result["checkedFiles"] if r["path"] == "app.mjs")
                self.assertEqual(row["code"], "response_size_mismatch" if delta == -1 else "response_size_exceeded")

    def test_cli_failure_writes_new_report_and_returns_one(self):
        out = self.root / "report.json"
        with patch.object(verify, "verify_public_release", return_value={"passed": False, "client_smoke": "not_run", "checkedFileCount": 0}), contextlib.redirect_stdout(io.StringIO()):
            code = verify.main(["--release", str(self.release), "--origin", ORIGIN, "--out", str(out)])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out.read_text())["passed"])
        previous = out.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
            verify.main(["--release", str(self.release), "--origin", ORIGIN, "--out", str(out)])
        self.assertEqual(stopped.exception.code, 2)
        self.assertEqual(out.read_bytes(), previous)


class RedirectPolicyTests(unittest.TestCase):
    def test_same_origin_redirect_allowed_but_host_port_and_scheme_changes_blocked(self):
        handler = verify._SameOriginRedirect(ORIGIN)
        request = urllib.request.Request(ORIGIN + "/index.html")
        accepted = handler.redirect_request(request, None, 302, "Moved", {}, ORIGIN + "/canonical/index.html")
        self.assertEqual(accepted.full_url, ORIGIN + "/canonical/index.html")
        for target in ("https://other.example.test/file", ORIGIN + ":444/file", "http://listening.example.test/file"):
            with self.subTest(target=target), self.assertRaisesRegex(verify.VerificationError, "redirect_not_allowed"):
                handler.redirect_request(request, None, 302, "Moved", {}, target)

    def test_default_opener_disables_environment_proxy_credentials(self):
        with patch.object(urllib.request, "build_opener") as build:
            verify._default_fetcher(ORIGIN)
        self.assertEqual(build.call_args.args[0].proxies, {})
        self.assertIsInstance(build.call_args.args[1], verify._SameOriginRedirect)


if __name__ == "__main__":
    unittest.main()
