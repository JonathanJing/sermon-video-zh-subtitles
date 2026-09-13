#!/usr/bin/env python3
"""Verify a public static release against its validated local bytes.

This checks HTTP delivery and audio byte ranges, not browser/device playback.
The injectable fetcher has signature ``fetcher(url, *, headers, timeout)`` and
returns ``status``, ``headers``, ``url``, ``iter_bytes()`` and ``close()``.
No credentials, cookies, environment proxy credentials or deployment tools are
used by the default fetcher. Bodies are hashed incrementally, including media.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
MAX_TOTAL_SECONDS = 600.0
REQUEST_TIMEOUT_SECONDS = 30.0
CHUNK_BYTES = 64 * 1024
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac"}


class VerificationError(Exception):
    def __init__(self, code: str, *, http_status: int | None = None):
        super().__init__(code)
        self.code = code
        self.http_status = http_status


def read_release(release: Path) -> tuple[dict, dict]:
    # Lazy import also permits offline tests while the release builder is being
    # developed independently. There is no less strict fallback reader.
    from weekly_release import read_release as validated_read
    return validated_read(release)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _origin_parts(url: str, *, root_only: bool) -> tuple[str, str, int]:
    if not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 for c in url) or "\\" in url:
        raise VerificationError("invalid_origin")
    try:
        parsed = urllib.parse.urlsplit(url)
        port = 443 if parsed.port is None else parsed.port
        host = parsed.hostname
        if (parsed.scheme != "https" or not host or parsed.username is not None or parsed.password is not None
                or not 1 <= port <= 65535 or (root_only and (parsed.path not in {"", "/"} or "?" in url or "#" in url))):
            raise ValueError()
        if ":" in host:
            host = str(ipaddress.IPv6Address(host))
        else:
            host = host.encode("idna").decode("ascii").lower()
            if len(host) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                                     for label in host.split(".")):
                raise ValueError()
        return "https", host, port
    except (ValueError, UnicodeError):
        raise VerificationError("invalid_origin") from None


def _canonical_origin(origin: str) -> str:
    _scheme, host, port = _origin_parts(origin, root_only=True)
    authority = "[" + host + "]" if ":" in host else host
    return "https://" + authority + (f":{port}" if port != 443 else "")


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin: str):
        super().__init__()
        self.origin_parts = _origin_parts(origin, root_only=True)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        try:
            if _origin_parts(target, root_only=False) != self.origin_parts:
                raise VerificationError("redirect_not_allowed")
        except VerificationError:
            raise VerificationError("redirect_not_allowed") from None
        return super().redirect_request(req, fp, code, msg, headers, target)


class _Response:
    def __init__(self, response):
        self._response = response
        self.status = response.status
        self.headers = response.headers
        self.url = response.geturl()

    def iter_bytes(self):
        # read1 yields available data so the verifier can check the overall
        # deadline even when a server continuously trickles response bytes.
        read = getattr(self._response, "read1", self._response.read)
        while True:
            chunk = read(CHUNK_BYTES)
            if not chunk:
                return
            yield chunk

    def close(self):
        self._response.close()


def _default_fetcher(origin: str):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _SameOriginRedirect(origin))

    def fetch(url: str, *, headers: dict, timeout: float):
        request = urllib.request.Request(url, method="GET", headers=headers)
        try:
            return _Response(opener.open(request, timeout=timeout))
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            raise VerificationError("http_error", http_status=status) from None
        except urllib.error.URLError as exc:
            code = "request_timeout" if isinstance(exc.reason, TimeoutError) else "network_error"
            raise VerificationError(code) from None
        except TimeoutError:
            raise VerificationError("request_timeout") from None
        except (OSError, http.client.HTTPException):
            raise VerificationError("network_error") from None
    return fetch


def _header(headers, name: str) -> str | None:
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value)
    return None


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(path: Any) -> str:
    if (not isinstance(path, str) or not path or "\\" in path
            or any(ord(c) < 32 for c in path) or PurePosixPath(path).is_absolute()
            or PurePosixPath(path).as_posix() != path
            or any(part in {"", ".", ".."} for part in path.split("/"))):
        raise VerificationError("invalid_release_path")
    return path


class _Budget:
    def __init__(self):
        self.deadline = time.monotonic() + MAX_TOTAL_SECONDS
        self.downloaded = 0

    def timeout(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise VerificationError("total_timeout")
        if self.downloaded >= MAX_TOTAL_BYTES:
            raise VerificationError("total_byte_limit")
        return min(REQUEST_TIMEOUT_SECONDS, remaining)

    def consume(self, count: int):
        self.downloaded += count
        if self.downloaded > MAX_TOTAL_BYTES:
            raise VerificationError("total_byte_limit")
        if time.monotonic() > self.deadline:
            raise VerificationError("total_timeout")


def _get_bytes(fetcher, origin: str, path: str, budget: _Budget, *, expected_size: int,
               range_end: int | None = None, prefix: bytes | None = None) -> dict:
    headers = {"Accept-Encoding": "identity", "User-Agent": "Tongxing-Release-Verifier/1.0"}
    if range_end is not None:
        headers["Range"] = "bytes=0-1023"
    response = None
    observed: dict[str, Any] = {"receivedBytes": 0}
    try:
        response = fetcher(origin + "/" + urllib.parse.quote(path, safe="/"), headers=headers, timeout=budget.timeout())
        try:
            final_origin = _origin_parts(response.url, root_only=False)
        except VerificationError:
            raise VerificationError("redirect_not_allowed") from None
        if final_origin != _origin_parts(origin, root_only=True):
            raise VerificationError("redirect_not_allowed")
        observed["httpStatus"] = response.status
        if response.status != (206 if range_end is not None else 200):
            raise VerificationError("unexpected_http_status", http_status=response.status)
        encoding = _header(response.headers, "Content-Encoding")
        if encoding and encoding.strip().lower() != "identity":
            raise VerificationError("unexpected_content_encoding")
        response_size = expected_size
        if range_end is not None:
            value = _header(response.headers, "Content-Range") or ""
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", value.strip())
            if match is None or tuple(map(int, match.groups())) != (0, range_end, expected_size):
                raise VerificationError("invalid_content_range")
            observed["contentRange"] = value.strip()
            response_size = range_end + 1
        length = _header(response.headers, "Content-Length")
        if length is not None and (not re.fullmatch(r"\d+", length.strip()) or int(length) != response_size):
            raise VerificationError("content_length_mismatch")
        digest = hashlib.sha256()
        range_bytes = bytearray()
        for chunk in response.iter_bytes():
            if not isinstance(chunk, bytes):
                raise VerificationError("invalid_response_chunk")
            budget.consume(len(chunk))
            observed["receivedBytes"] += len(chunk)
            if observed["receivedBytes"] > response_size:
                raise VerificationError("response_size_exceeded")
            digest.update(chunk)
            if range_end is not None:
                range_bytes.extend(chunk)
        budget.consume(0)
        if observed["receivedBytes"] != response_size:
            raise VerificationError("response_size_mismatch")
        observed["observedSha256"] = digest.hexdigest()
        if prefix is not None and bytes(range_bytes) != prefix:
            raise VerificationError("range_prefix_mismatch")
        return {**observed, "passed": True, "code": "ok"}
    except VerificationError as exc:
        if exc.http_status is not None:
            observed["httpStatus"] = exc.http_status
        return {**observed, "passed": False, "code": exc.code}
    except TimeoutError:
        return {**observed, "passed": False, "code": "request_timeout"}
    except (OSError, http.client.HTTPException):
        return {**observed, "passed": False, "code": "network_error"}
    except Exception:
        return {**observed, "passed": False, "code": "fetch_error"}
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass


def verify_public_release(release: Path, origin: str, *, fetcher=None) -> dict:
    """Return explicit verification evidence; failures never imply success."""
    result = {"schemaVersion": "sermon-weekly-public-verification-v1", "passed": False,
              "origin": None, "buildReportSha256": None, "startedAt": _utc_now(),
              "completedAt": None, "client_smoke": "not_run", "checkedFiles": [],
              "audioRanges": [], "failures": [], "expectedFileCount": 0,
              "checkedFileCount": 0, "totalDownloadedBytes": 0}
    budget = _Budget()
    try:
        origin = _canonical_origin(origin)
        result["origin"] = origin
        release = Path(release)
        report_path = release / "build-report.json"
        before = _file_sha(report_path)
        report, _catalog = read_release(release)
        result["buildReportSha256"] = _file_sha(report_path)
        if before != result["buildReportSha256"]:
            raise VerificationError("local_release_changed")
        expected = {}
        for row in report["files"]:
            path = _safe_path(row["path"])
            if (path in expected or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                    or not isinstance(row["bytes"], int) or isinstance(row["bytes"], bool) or row["bytes"] < 0):
                raise VerificationError("invalid_release_manifest")
            expected[path] = row
        if "weekly.json" not in expected:
            raise VerificationError("missing_weekly_catalog")
        result["expectedFileCount"] = len(expected)
        fetch = fetcher or _default_fetcher(origin)
        for path in ["weekly.json"] + sorted(set(expected) - {"weekly.json"}):
            row = expected[path]
            check = {"path": path, "expectedSha256": row["sha256"], "expectedBytes": row["bytes"],
                     **_get_bytes(fetch, origin, path, budget, expected_size=row["bytes"])}
            if check["passed"] and check["observedSha256"] != row["sha256"]:
                check.update(passed=False, code="sha256_mismatch")
            result["checkedFiles"].append(check)
            if not check["passed"]:
                result["failures"].append({"path": path, "check": "file", "code": check["code"]})
            if check["code"] in {"total_byte_limit", "total_timeout"}:
                break
            if PurePosixPath(path).suffix.lower() in AUDIO_EXTENSIONS:
                if row["bytes"] <= 0:
                    range_check = {"passed": False, "code": "empty_audio"}
                else:
                    local = release / "public" / path
                    if not local.resolve().is_relative_to((release / "public").resolve()):
                        raise VerificationError("invalid_release_path")
                    with local.open("rb") as handle:
                        prefix = handle.read(min(1024, row["bytes"]))
                    range_check = _get_bytes(fetch, origin, path, budget, expected_size=row["bytes"],
                                             range_end=min(1023, row["bytes"] - 1), prefix=prefix)
                    range_check.update(expectedSha256=hashlib.sha256(prefix).hexdigest(),
                                       expectedBytes=len(prefix), expectedTotalBytes=row["bytes"])
                result["audioRanges"].append({"path": path, **range_check})
                if not range_check["passed"]:
                    result["failures"].append({"path": path, "check": "audio_range", "code": range_check["code"]})
                if range_check["code"] in {"total_byte_limit", "total_timeout"}:
                    break
        if _file_sha(report_path) != result["buildReportSha256"]:
            raise VerificationError("local_release_changed")
        result["checkedFileCount"] = len(result["checkedFiles"])
        result["passed"] = not result["failures"] and result["checkedFileCount"] == result["expectedFileCount"]
    except VerificationError as exc:
        result["failures"].append({"check": "verification", "code": exc.code})
    except Exception:
        # Do not serialize exception strings: filesystem paths or server error
        # text may contain private information. The failure remains explicit.
        result["failures"].append({"check": "verification", "code": "local_release_invalid"})
    result["checkedFileCount"] = len(result["checkedFiles"])
    result["totalDownloadedBytes"] = budget.downloaded
    result["completedAt"] = _utc_now()
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists() or args.out.is_symlink():
        parser.error("--out must name a new report file")
    report = verify_public_release(args.release, args.origin)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.out, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"passed": report["passed"], "client_smoke": report["client_smoke"],
                      "checkedFileCount": report["checkedFileCount"]}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
