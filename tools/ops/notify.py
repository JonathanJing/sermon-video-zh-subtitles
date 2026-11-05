#!/usr/bin/env python3
"""Bark transport for production progress notifications.

This is the reusable notification side of ``run_status.py``. It knows nothing about
sermon stages: callers pass a title/body/level. Device keys live in the login keychain
under a service separate from the Saturday Drive-upload watcher, so the two notification
streams are auditable apart. Delivery is fail-open for production: a missing key or a
failed push returns a result dict, never raises into a production command.

Default policy (kept in run_status.py, not here):
  passive       informational (run started)
  active        milestone / human review ready
  timeSensitive failure / stalled
  critical      unknown paid outcome, only after the phone grants the permission

Test without sending: ``python3 tools/ops/notify.py test-push --no-push``.
Store keys once (prompts, does not echo):
  security add-generic-password -s org.sermonvideo.production-progress -a bark-iphone -w
  security add-generic-password -s org.sermonvideo.production-progress -a bark-mac -w
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SERVICE = "org.sermonvideo.production-progress"
BARK_URL = "https://api.day.app/push"
GROUP = "sermon-production"
ACCOUNTS = ("bark-iphone", "bark-mac")
MAC_ACCOUNT = "bark-mac"
LEVELS = ("passive", "active", "timeSensitive", "critical")


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
                 attempts: int = 3, push: bool = True):
        self.keys, self.bark_url, self.group = keys, bark_url, group
        self.post, self.local, self.sleep = post, local, sleep
        self.attempts, self.push = attempts, push

    def send(self, message: Message) -> dict:
        """Push to every key; show a local notification when the Mac's push did not arrive."""
        if not self.push:
            log(f"[no-push] {message.level} {message.title}: {message.body}")
            return {"printed": True}
        results: dict[str, bool] = {}
        for account, key in self.keys.items():
            results[account] = self._push(account, key, message)
        if message.level != "passive" and not results.get(MAC_ACCOUNT):
            results["local"] = bool(self.local(message))
        return results

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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    accounts = tuple(args.accounts or ACCOUNTS)
    keys = keychain_keys(accounts, service=args.service)
    if not keys and not args.no_push:
        print(f"no Bark key in the keychain (service {args.service}, accounts {', '.join(accounts)})",
              file=sys.stderr)
        return 1
    notifier = Notifier(keys, bark_url=args.bark_url, group=args.group, push=not args.no_push)
    message = Message(args.title, args.body, args.level, args.url, args.sound, args.volume)
    results = notifier.send(message)
    print(json.dumps({"keys": sorted(keys), "results": results}, ensure_ascii=False))
    if args.no_push:
        return 0
    if not delivered(results):
        print("no channel delivered the notification", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
