#!/usr/bin/env python3
"""Bark and email transport for production progress notifications.

This is the reusable notification side of ``run_status.py`` and ``production_notices.py``.
It knows nothing about sermon stages: callers pass a title/body/level. Device keys live in
the login keychain under a service separate from the Saturday Drive-upload watcher, so the
two notification streams are auditable apart. Delivery is fail-open for production: a missing
key or a failed push returns a result dict, never raises into a production command.

Email is the independent backup channel, as in the Drive watcher: every notice that is not
``passive`` also goes out by Gmail SMTP when the keychain holds ``gmail-user`` (sender) and
``gmail-app`` (app password) under the same service; ``gmail-to`` overrides the recipient.
An email cannot break through silent or focus mode; it is a record and a second path.

Default policy (kept in run_status.py, not here):
  passive       informational (run started)
  active        milestone / human review ready
  timeSensitive failure / stalled
  critical      unknown paid outcome, only after the phone grants the permission

Test without sending: ``python3 tools/ops/notify.py test-push --no-push``.
Store keys once (prompts, does not echo):
  security add-generic-password -s org.sermonvideo.production-progress -a bark-iphone -w
  security add-generic-password -s org.sermonvideo.production-progress -a bark-mac -w
  security add-generic-password -s org.sermonvideo.production-progress -a bark-mbp14 -w
  security add-generic-password -s org.sermonvideo.production-progress -a gmail-user -w
  security add-generic-password -s org.sermonvideo.production-progress -a gmail-app -w
"""
from __future__ import annotations

import argparse
import json
import shutil
import smtplib
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Callable

SERVICE = "org.sermonvideo.production-progress"
BARK_URL = "https://api.day.app/push"
GROUP = "sermon-production"
ACCOUNTS = ("bark-iphone", "bark-mac", "bark-mbp14")   # bark-mac is this Mac; bark-mbp14 is the second Mac (added 2026-11-25)
MAC_ACCOUNT = "bark-mac"
LEVELS = ("passive", "active", "timeSensitive", "critical")
EMAIL_ACCOUNTS = ("gmail-user", "gmail-app", "gmail-to")
EMAIL_FALLBACK_SERVICE = "org.sermonvideo.drive-upload-watch"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


@dataclass(frozen=True)
class Message:
    title: str
    body: str
    level: str = "active"
    url: str | None = None
    sound: str | None = None
    volume: str | None = None  # Bark: 0-10, critical-alert ringtone volume only

    def __post_init__(self) -> None:
        if self.level not in LEVELS:
            raise ValueError(f"Bark level must be one of {', '.join(LEVELS)}")


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def keychain_keys(accounts: tuple[str, ...] = ACCOUNTS, *, service: str = SERVICE,
                  run: Callable = subprocess.run) -> dict[str, str]:
    """Bark device keys from the login keychain; a missing account is left out."""
    keys: dict[str, str] = {}
    for account in accounts:
        result = run(["/usr/bin/security", "find-generic-password", "-s", service,
                      "-a", account, "-w"], capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            keys[account] = result.stdout.strip()
    return keys


def post_json(url: str, payload: dict, timeout: float = 15) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def email_credentials(*, service: str = SERVICE, run: Callable = subprocess.run) -> tuple[str, str, str] | None:
    """(sender, app password, recipient) from the login keychain, or None when email is not set up.

    The Gmail accounts are looked up under `service` first and then under the Drive watcher's
    service: it is the same mailbox, and the app password is already stored there on a Mac that
    runs the watcher. Bark device keys are not shared this way."""
    for name in dict.fromkeys((service, EMAIL_FALLBACK_SERVICE)):
        stored = keychain_keys(EMAIL_ACCOUNTS, service=name, run=run)
        sender, password = stored.get("gmail-user"), stored.get("gmail-app")
        if sender and password:
            return sender, password, stored.get("gmail-to", sender)
    return None


def send_email(message: Message, *, credentials: tuple[str, str, str] | None = None,
               smtp_factory: Callable | None = None, service: str = SERVICE) -> bool:
    """Gmail SMTP backup channel. Returns False instead of raising: mail must not stop production."""
    credentials = credentials or email_credentials(service=service)
    if not credentials:
        return False
    sender, password, recipient = credentials
    mail = EmailMessage()
    mail["From"], mail["To"] = sender, recipient
    mail["Subject"] = message.title
    if message.level in ("timeSensitive", "critical"):
        # Outlook and Apple Mail flag these; Gmail decides "Important" on its own.
        mail["Importance"] = "high"
        mail["X-Priority"] = "1 (Highest)"
    body = f"{message.body}\n\n{message.url}" if message.url else message.body
    mail.set_content(f"{body}\n\nbark-level={message.level}")
    factory = smtp_factory or smtplib.SMTP_SSL
    try:
        with factory(SMTP_HOST, SMTP_PORT, timeout=15) as client:
            client.login(sender, password)
            client.send_message(mail)
        return True
    except (OSError, smtplib.SMTPException, ValueError) as exc:
        log(f"email failed: {type(exc).__name__}")  # class name only: no address, no password
        return False


def local_notify(message: Message, *, group: str = GROUP) -> bool:
    """macOS fallback when the Mac's Bark push did not arrive."""
    notifier = shutil.which("terminal-notifier") or next(
        (path for path in ("/opt/homebrew/bin/terminal-notifier", "/usr/local/bin/terminal-notifier")
         if Path(path).exists()), None)
    if notifier:
        command = [notifier, "-title", message.title, "-message", message.body,
                   "-group", group, "-sound", "Glass"]
        if message.url:
            command += ["-open", message.url]
    else:
        script = (f"display notification {json.dumps(message.body)} with title "
                  f"{json.dumps(message.title)} sound name \"Glass\"")
        command = ["/usr/bin/osascript", "-e", script]
    try:
        return subprocess.run(command, capture_output=True, check=False).returncode == 0
    except OSError as exc:
        log(f"local notification failed: {type(exc).__name__}")
        return False


class Notifier:
    def __init__(self, keys: dict[str, str], *, bark_url: str = BARK_URL,
                 group: str = GROUP, post: Callable = post_json,
                 local: Callable = local_notify, sleep: Callable = time.sleep,
                 attempts: int = 3, push: bool = True, mail: Callable | None = None):
        self.keys, self.bark_url, self.group = keys, bark_url, group
        self.post, self.local, self.sleep = post, local, sleep
        self.attempts, self.push = attempts, push
        self.mail = mail  # None: no email channel (the caller passes send_email when it is configured)

    def send(self, message: Message) -> dict:
        """Push to every key, email what is not passive, and fall back to a local notification."""
        if not self.push:
            log(f"[no-push] {message.level} {message.title}: {message.body}")
            return {"printed": True}
        results: dict[str, bool] = {}
        for account, key in self.keys.items():
            results[account] = self._push(account, key, message)
        if self.mail is not None and message.level != "passive":
            results["email"] = self._mail(message)
        if message.level != "passive" and not results.get(MAC_ACCOUNT):
            results["local"] = bool(self.local(message))
        return results

    def _mail(self, message: Message) -> bool:
        try:
            return bool(self.mail(message))
        except Exception as exc:  # noqa: BLE001 - a mail bug must not stop production
            log(f"email failed: {type(exc).__name__}")
            return False

    def _push(self, account: str, key: str, message: Message) -> bool:
        payload = {"device_key": key, "title": message.title, "body": message.body,
                   "group": self.group, "level": message.level, "isArchive": "1"}
        if message.url:
            payload["url"] = message.url
        if message.sound:
            payload["sound"] = message.sound
        if message.volume is not None:
            payload["volume"] = message.volume
        for attempt in range(1, self.attempts + 1):
            try:
                reply = self.post(self.bark_url, payload)
                if reply.get("code") == 200:
                    return True
                reason = f"code {reply.get('code')}: {reply.get('message')}"
            except (urllib.error.URLError, OSError, ValueError) as exc:
                reason = str(exc)
            log(f"Bark push to {account} failed (attempt {attempt}/{self.attempts}): {reason}")
            if attempt < self.attempts:
                self.sleep(2 ** attempt)
        return False


def delivered(results: dict) -> bool:
    return any(bool(value) for key, value in results.items() if key != "printed")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("test-push", "send"):
        command = commands.add_parser(name)
        if name == "test-push":
            command.add_argument("--title", default="[同行] 测试通知")
            command.add_argument("--body", default="production progress notification test")
        else:
            command.add_argument("--title", required=True)
            command.add_argument("--body", required=True)
        command.add_argument("--level", choices=LEVELS, default="active")
        command.add_argument("--url")
        command.add_argument("--sound")
        command.add_argument("--volume")
        command.add_argument("--service", default=SERVICE)
        command.add_argument("--group", default=GROUP)
        command.add_argument("--bark-url", default=BARK_URL)
        command.add_argument("--account", action="append", dest="accounts")
        command.add_argument("--no-push", action="store_true")
        command.add_argument("--no-email", action="store_true", help="skip the email channel even when it is set up")
    return parser


def configured_mail(service: str = SERVICE) -> Callable | None:
    """send_email bound to this service when the keychain has the Gmail accounts, else None."""
    credentials = email_credentials(service=service)
    if not credentials:
        return None
    return lambda message: send_email(message, credentials=credentials)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    accounts = tuple(args.accounts or ACCOUNTS)
    keys = keychain_keys(accounts, service=args.service)
    mail = None if (args.no_email or args.no_push) else configured_mail(args.service)
    if not keys and mail is None and not args.no_push:
        print(f"no Bark key and no email in the keychain (service {args.service}, accounts {', '.join(accounts)})",
              file=sys.stderr)
        return 1
    notifier = Notifier(keys, bark_url=args.bark_url, group=args.group, push=not args.no_push, mail=mail)
    message = Message(args.title, args.body, args.level, args.url, args.sound, args.volume)
    results = notifier.send(message)
    print(json.dumps({"keys": sorted(keys), "emailConfigured": mail is not None, "results": results}, ensure_ascii=False))
    if args.no_push:
        return 0
    if not delivered(results):
        print("no channel delivered the notification", file=sys.stderr)
        return 1
    if args.command == "test-push" and mail is not None and message.level != "passive" and results.get("email") is not True:
        print("email is set up but the test message was not accepted", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
