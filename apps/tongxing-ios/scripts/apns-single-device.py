#!/usr/bin/env python3
"""Explicit, Beta-only single-device APNs test. Never logs credentials or tokens."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
import urllib.request
import uuid

class TestValidationError(ValueError):
    pass


class OutcomeUnknownError(RuntimeError):
    pass


BUNDLE = "com.jonathanjing.tongxing.beta"
ORIGIN = "https://ai-for-god-sermon-audio-dev.web.app"


def private_file(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise TestValidationError("Private input must be an owner-only file (chmod 600)")
    return path


def device_receipt(path):
    item = json.loads(private_file(path).read_text())
    if item.get("schemaVersion") != "tongxing-beta-apns-device-v1" or item.get("bundleID") != BUNDLE:
        raise TestValidationError("Only a Tongxing Beta device receipt is accepted")
    if item.get("environment") not in ("sandbox", "production"):
        raise TestValidationError("The signed APNs environment is required")
    token = item.get("deviceToken", "")
    # APNs tokens are variable length. Reject malformed hex, not a fixed size.
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-fA-F]+", token) or len(token) % 2:
        raise TestValidationError("Invalid device token")
    if item.get("locale") not in ("zh-Hans", "en", "ko", "es", "vi"):
        raise TestValidationError("Unsupported subscription language")
    return item


def fetch_json(url, limit=2_000_000):
    with urllib.request.urlopen(url, timeout=30) as response:
        if response.url != url:
            raise TestValidationError("Content redirects are not accepted")
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise TestValidationError("Content exceeds size limit")
    return json.loads(raw), raw


def notice_payload(catalog, page_id, locale):
    if catalog.get("schemaVersion") not in ("sermon-multilingual-catalog-v3", "sermon-multilingual-catalog-v4"):
        raise TestValidationError("A published dual-script catalog is required")
    page_id = page_id or catalog.get("defaultPageId") or catalog.get("defaultPageID")
    pages = [p for p in catalog["pages"] if p.get("id") == page_id]
    if len(pages) != 1:
        raise TestValidationError("Expected one current page")
    page = pages[0]
    if page.get("simulationOnly") or page.get("diagnosticOnly"):
        raise TestValidationError("Simulated or diagnostic pages cannot be sent")
    target = page.get("targets", {}).get(locale)
    if not target or target.get("contentStatus") not in ("human_reviewed", "machine_checked") or target.get("simulationOnly") or target.get("diagnosticOnly"):
        raise TestValidationError("Page has no subscribed language")
    digest = target.get("releasePackageJsonSha256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise TestValidationError("Published release hash is required")
    notice = {"schemaVersion": "tongxing-beta-notification-v1", "environment": "beta-dev",
              "pageID": page_id, "locale": locale, "releaseSHA256": digest}
    titles = {"zh-Hans": "[Beta 远程测试] 本周证道", "ko": "[Beta 테스트] 이번 주 설교",
              "es": "[Prueba Beta] Sermón de esta semana", "en": "[Beta remote test] This week’s sermon",
              "vi": "[Thử nghiệm Beta] Bài giảng tuần này"}
    return {"aps": {"alert": {"title": titles[locale], "body": page.get("date", "")}, "sound": "default"},
            "tongxing": notice}, target


def provider_token(key_path, key_id, team_id):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    key = serialization.load_pem_private_key(private_file(key_path).read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise TestValidationError("APNs requires a P-256 private key")
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=")
    message = encode({"alg": "ES256", "kid": key_id}) + b"." + encode({"iss": team_id, "iat": int(time.time())})
    r, s = decode_dss_signature(key.sign(message, ec.ECDSA(hashes.SHA256())))
    signature = base64.urlsafe_b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).rstrip(b"=")
    return (message + b"." + signature).decode()


def send(device, payload, jwt, output_dir):
    host = "api.sandbox.push.apple.com" if device["environment"] == "sandbox" else "api.push.apple.com"
    request_id = str(uuid.uuid4())
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    # No token/JWT in process arguments, receipt, or stdout. curl receives a private stdin config.
    def quoted(value):
        if any(c in value for c in ("\r", "\n", "\x00")):
            raise TestValidationError("Invalid HTTP value")
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    with tempfile.TemporaryDirectory(prefix="tongxing-apns-") as temporary:
        body = Path(temporary) / "payload.json"
        body.write_text(json.dumps(payload, ensure_ascii=False))
        os.chmod(body, 0o600)
        response = Path(temporary) / "response.json"
        config = "\n".join([
            "http2", "silent", "request = POST", "connect-timeout = 15", "max-time = 30",
            "url = " + quoted(f"https://{host}/3/device/{device['deviceToken']}"),
            "header = " + quoted("authorization: bearer " + jwt),
            "header = " + quoted("apns-topic: " + BUNDLE),
            "header = " + quoted("apns-push-type: alert"), "header = " + quoted("apns-priority: 10"),
            "header = " + quoted("apns-expiration: 0"), "header = " + quoted("apns-id: " + request_id),
            "data-binary = " + quoted("@" + str(body)), "output = " + quoted(str(response)),
            'write-out = "%{http_code}"', ""])
        destination = output_dir / (request_id + ".json")
        intent = {"schemaVersion": "tongxing-apns-single-device-attempt-v1", "apnsID": request_id,
                  "bundleID": BUNDLE, "environment": device["environment"], "phase": "request_outcome_unknown",
                  "notice": payload["tongxing"], "timestamp": int(time.time())}
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(json.dumps(intent, indent=2) + "\n")
            file.flush(); os.fsync(file.fileno())
        try:
            result = subprocess.run(["/usr/bin/curl", "-q", "--config", "-"], input=config, text=True, capture_output=True)
        except Exception:
            raise OutcomeUnknownError("Request outcome unknown; inspect the private attempt receipt and device before any new send") from None
        try:
            reason = None
            if response.is_file() and response.stat().st_size:
                try:
                    reason = json.loads(response.read_text()).get("reason")
                except (ValueError, AttributeError):
                    reason = "unparseable_response"
            http_status = int(result.stdout) if result.stdout.isdigit() else 0
            receipt = {"schemaVersion": "tongxing-apns-single-device-attempt-v1", "apnsID": request_id,
                       "bundleID": BUNDLE, "environment": device["environment"], "httpStatus": http_status,
                       "reason": reason, "curlExitCode": result.returncode, "timestamp": int(time.time()),
                       "notice": payload["tongxing"], "apnsAccepted": http_status == 200 and result.returncode == 0,
                       "deviceDisplayed": "not_run", "contentOpened": "not_run", "posterVerified": "not_run"}
            receipt["phase"] = "response_observed" if http_status else "request_outcome_unknown"
            try:
                temporary_receipt = None
                try:
                    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output_dir, prefix=".receipt-", delete=False) as file:
                        temporary_receipt = Path(file.name)
                        file.write(json.dumps(receipt, indent=2) + "\n")
                        file.flush(); os.fsync(file.fileno())
                    os.replace(temporary_receipt, destination)
                finally:
                    if temporary_receipt is not None:
                        temporary_receipt.unlink(missing_ok=True)
            except Exception:
                raise OutcomeUnknownError("Request outcome unknown; the initial private attempt receipt remains; do not resend automatically") from None
            print(json.dumps({"httpStatus": http_status, "reason": reason, "receipt": str(destination)}))
            return receipt["apnsAccepted"]
        except OutcomeUnknownError:
            raise
        except Exception:
            raise OutcomeUnknownError("Request outcome unknown; inspect the private attempt receipt and device before any new send") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--device", required=True, help="Owner-only exported Beta device receipt")
    parser.add_argument("--page-id")
    parser.add_argument("--output-dir", default="artifacts/tongxing-ios/apns-tests")
    parser.add_argument("--execute", action="store_true", help="Send exactly one request; no automatic retries")
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"[A-Z0-9]{10}", args.key_id) or not re.fullmatch(r"[A-Z0-9]{10}", args.team_id):
            raise TestValidationError("Invalid key/team identifier")
        device = device_receipt(args.device)
        catalog, _ = fetch_json(ORIGIN + "/multilingual-v3.json")
        payload, target = notice_payload(catalog, args.page_id, device["locale"])
        release_url = target.get("releasePackageUrl", "")
        if not isinstance(release_url, str) or not release_url.startswith("/releases-v2/") or ".." in release_url or "?" in release_url:
            raise TestValidationError("Only same-origin published releases are accepted")
        release, raw = fetch_json(ORIGIN + release_url)
        if hashlib.sha256(raw).hexdigest() != payload["tongxing"]["releaseSHA256"]:
            raise TestValidationError("Current release hash does not match")
        if release.get("status") != "published_http_verified" or release.get("httpVerification", {}).get("status") != "pass" or release.get("pageId") != payload["tongxing"]["pageID"] or release.get("targetLocale") != device["locale"]:
            raise TestValidationError("Page release must be HTTP verified")
        jwt = provider_token(args.key_file, args.key_id, args.team_id)
        if not args.execute:
            print(json.dumps({"dryRun": True, "environment": device["environment"], "notice": payload["tongxing"]}))
            return 0
        return 0 if send(device, payload, jwt, args.output_dir) else 1
    except OutcomeUnknownError as error:
        print(str(error))
        return 1
    except Exception as error:
        # Third-party exceptions may contain secrets; retain only our validation messages.
        print("Test not sent: " + (str(error) if type(error) is TestValidationError else type(error).__name__))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
