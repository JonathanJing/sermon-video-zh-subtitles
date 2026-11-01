#!/usr/bin/env python3
"""Watch the public Broadcast Message Files Drive folder on Saturday evenings.

    python3 tools/ops/drive_upload_watch.py check        # read the folder once, print JSON
    python3 tools/ops/drive_upload_watch.py test-push    # one test notice to Bark and email
    python3 tools/ops/drive_upload_watch.py install      # copy + LaunchAgent, Sat 18:00
    python3 tools/ops/drive_upload_watch.py status | uninstall
    python3 tools/ops/drive_upload_watch.py run          # what launchd starts

`run` polls the folder page every 60 s from Saturday 18:00 to 22:00 Pacific and
exits. A file is new when its ID has not been seen; the date prefix in its name
is only a label (the 2026-10-24 upload was named Saturday_400pm_Live__1080.mp4).
Files whose earliest Drive timestamp falls before this week's Sunday 00:00 are
recorded silently as the baseline. Pushes go to every Bark key stored in the
login keychain (service org.sermonvideo.drive-upload-watch, accounts bark-iphone
and bark-mac); a macOS notification is shown when the Mac's Bark push did not
arrive. Every non-passive notice also goes out by Gmail SMTP as an independent
backup channel (same keychain service, accounts gmail-user and gmail-app, plus
an optional gmail-to recipient; the sender is the default recipient).
Read-only: no download, no Google sign-in, no production stage.
Standard library only, Python 3.9+, so `install` can run a copy with
/usr/bin/python3 independent of this checkout's branch. See
docs/codex-local-production-runbook.zh.md (Broadcast Message 网盘上传检查).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import datetime as dt
from email.message import EmailMessage
import fcntl
import json
import os
from pathlib import Path
import plistlib
import random
import re
import shutil
import smtplib
import subprocess
import sys
import time
from typing import Callable, Optional
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

FOLDER_ID = "1PsAKaZhYCXsNfzYFkFBTng66N1tPw1sF"
FOLDER_URL = f"https://drive.google.com/drive/folders/{FOLDER_ID}"
TZ = ZoneInfo("America/Los_Angeles")
SATURDAY = 5  # datetime.weekday(); launchd counts Saturday as 6
WINDOW_START = dt.time(18, 0)
WINDOW_END = dt.time(22, 0)
POLL_SECONDS = 60
JITTER_SECONDS = 5
ERROR_THRESHOLD = 3  # consecutive failed reads before one error push
STATE_VERSION = 1
KEEP_WINDOWS_DAYS = 120

LABEL = "org.sermonvideo.drive-upload-watch"
KEYCHAIN_SERVICE = LABEL
BARK_ACCOUNTS = ("bark-iphone", "bark-mac")
MAC_ACCOUNT = "bark-mac"
BARK_URL = "https://api.day.app/push"
BARK_GROUP = "sermon-upload"
EMAIL_ACCOUNTS = ("gmail-user", "gmail-app", "gmail-to")
EMAIL_SUBJECT_PREFIX = "[证道视频监控]"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SUPPORT_DIR = Path.home() / "Library/Application Support" / LABEL
LAUNCH_AGENT = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
SYSTEM_PYTHON = "/usr/bin/python3"

IVD = re.compile(r"window\['_DRIVE_ivd'\] = '(.*?)';", re.S)


def log(message: str) -> None:
    print(f"{dt.datetime.now(TZ):%Y-%m-%d %H:%M:%S} {message}", flush=True)


# ---------------------------------------------------------------- folder page

class ListingError(RuntimeError):
    pass


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime: Optional[str]
    size: Optional[int]
    earliest: Optional[dt.datetime]
    latest: Optional[dt.datetime]

    @property
    def url(self) -> str:
        return f"https://drive.google.com/file/d/{self.id}/view"

    def record(self) -> dict:
        return {"id": self.id, "name": self.name, "mime": self.mime, "sizeBytes": self.size,
                "earliestTimePT": _iso(self.earliest), "latestTimePT": _iso(self.latest), "url": self.url}


def _iso(value: Optional[dt.datetime]) -> Optional[str]:
    return value.isoformat(timespec="seconds") if value else None


def parse_listing(html: str) -> list:
    """Files from the folder page's embedded `_DRIVE_ivd` list (ID, name, MIME, size, two ms stamps)."""
    match = IVD.search(html)
    if not match:
        raise ListingError("folder listing (_DRIVE_ivd) not found; folder may be private or the page format changed")
    raw = re.sub(r"\\x([0-9a-fA-F]{2})", r"\\u00\1", match.group(1)).replace("\\'", "'")
    try:
        data = json.loads(json.loads('"' + raw + '"'))
        entries = data[0] or []
        files = []
        for entry in entries:
            stamps = [t for t in (entry[9], entry[10]) if isinstance(t, (int, float))]
            times = [dt.datetime.fromtimestamp(t / 1000, TZ) for t in stamps]
            files.append(DriveFile(id=entry[0], name=entry[2], mime=entry[3],
                                   size=entry[13] if isinstance(entry[13], int) else None,
                                   earliest=min(times) if times else None,
                                   latest=max(times) if times else None))
    except (ValueError, TypeError, IndexError) as exc:
        raise ListingError(f"folder listing could not be parsed: {exc}") from exc
    return files


def fetch_listing(url: str = FOLDER_URL, timeout: float = 30) -> list:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            html = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        raise ListingError(f"folder page could not be fetched: {exc}") from exc
    return parse_listing(html)


# ---------------------------------------------------------------- window

@dataclass(frozen=True)
class Window:
    day: dt.date  # the Saturday

    @property
    def start(self) -> dt.datetime:
        return dt.datetime.combine(self.day, WINDOW_START, TZ)

    @property
    def end(self) -> dt.datetime:
        return dt.datetime.combine(self.day, WINDOW_END, TZ)

    @property
    def sunday(self) -> dt.date:
        return self.day + dt.timedelta(days=1)

    @property
    def week_start(self) -> dt.datetime:
        """Sunday 00:00 before this Saturday: anything uploaded since then counts as this week's."""
        return dt.datetime.combine(self.day - dt.timedelta(days=6), dt.time(), TZ)

    @property
    def prefix(self) -> str:
        return self.sunday.strftime("%Y%m%d")


def window_on(now: dt.datetime) -> Optional[Window]:
    return Window(now.date()) if now.weekday() == SATURDAY else None


def next_window(now: dt.datetime) -> Window:
    day = now.date() + dt.timedelta(days=(SATURDAY - now.weekday()) % 7)
    window = Window(day)
    return window if now < window.end else Window(day + dt.timedelta(days=7))


# ---------------------------------------------------------------- state

def load_state(path: Path) -> dict:
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("version") != STATE_VERSION:
            raise SystemExit(f"{path}: unsupported state version {state.get('version')!r}")
        return state
    return {"version": STATE_VERSION, "notified": {}, "baseline": {}, "windows": {}}


def save_state(path: Path, state: dict, today: dt.date) -> None:
    cutoff = (today - dt.timedelta(days=KEEP_WINDOWS_DAYS)).isoformat()
    state["windows"] = {day: value for day, value in state["windows"].items() if day >= cutoff}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def append_observation(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- notifications

@dataclass(frozen=True)
class Message:
    title: str
    body: str
    level: str = "active"  # Bark: passive | active | timeSensitive | critical (critical needs the phone's permission)
    url: Optional[str] = None
    sound: Optional[str] = None
    volume: Optional[str] = None  # Bark: 0-10, critical-alert ringtone volume only


def keychain_keys(accounts=BARK_ACCOUNTS) -> dict:
    """Bark device keys from the login keychain; a missing account is left out."""
    keys = {}
    for account in accounts:
        result = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
                                 "-a", account, "-w"], capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            keys[account] = result.stdout.strip()
    return keys


def post_json(url: str, payload: dict, timeout: float = 15) -> dict:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def local_notify(message: Message) -> bool:
    notifier = shutil.which("terminal-notifier") or next(
        (p for p in ("/opt/homebrew/bin/terminal-notifier", "/usr/local/bin/terminal-notifier") if Path(p).exists()), None)
    if notifier:
        command = [notifier, "-title", message.title, "-message", message.body, "-group", LABEL, "-sound", "Glass"]
        if message.url:
            command += ["-open", message.url]
    else:
        script = f"display notification {json.dumps(message.body)} with title {json.dumps(message.title)} sound name \"Glass\""
        command = ["/usr/bin/osascript", "-e", script]
    return subprocess.run(command, capture_output=True, check=False).returncode == 0


def email_credentials() -> Optional[tuple]:
    """(sender, app password, recipient) from the login keychain, or None when unset."""
    stored = keychain_keys(EMAIL_ACCOUNTS)
    sender, password = stored.get("gmail-user"), stored.get("gmail-app")
    if not sender or not password:
        return None
    return sender, password, stored.get("gmail-to", sender)


def send_email(message: Message, *, credentials: Optional[tuple] = None,
               smtp_factory: Optional[Callable] = None) -> bool:
    """Gmail SMTP backup channel; returns False instead of raising so a mail outage cannot stop the watcher."""
    credentials = credentials or email_credentials()
    if not credentials:
        return False
    sender, password, recipient = credentials
    mail = EmailMessage()
    mail["From"], mail["To"] = sender, recipient
    mail["Subject"] = f"{EMAIL_SUBJECT_PREFIX} {message.title}"
    body = f"{message.body}\n\n{message.url}" if message.url else message.body
    mail.set_content(f"{body}\n\nbark-level={message.level}")
    factory = smtp_factory or smtplib.SMTP_SSL
    try:
        with factory(SMTP_HOST, SMTP_PORT, timeout=15) as client:
            client.login(sender, password)
            client.send_message(mail)
        return True
    except (OSError, smtplib.SMTPException, ValueError) as exc:
        log(f"email push failed: {type(exc).__name__}")  # class name only: no address, no password
        return False


class Notifier:
    def __init__(self, keys: dict, *, bark_url: str = BARK_URL, post: Callable = post_json,
                 local: Callable = local_notify, mail: Optional[Callable] = None,
                 sleep: Callable = time.sleep, attempts: int = 3, push: bool = True):
        self.keys, self.bark_url, self.post, self.local = keys, bark_url, post, local
        self.mail = mail  # None: resolve send_email at send time so tests and patches stay honest
        self.sleep, self.attempts, self.push = sleep, attempts, push

    def send(self, message: Message) -> dict:
        """Push to every key; show a local notification when the Mac's push did not arrive."""
        results = {}
        if not self.push:
            log(f"[no-push] {message.level} {message.title}: {message.body}")
            return {"printed": True}
        for account, key in self.keys.items():
            results[account] = self._push(account, key, message)
        if message.level != "passive":
            results["email"] = self._mail(message)
        if message.level != "passive" and not results.get(MAC_ACCOUNT):
            results["local"] = self.local(message)
        return results

    def _push(self, account: str, key: str, message: Message) -> bool:
        payload = {"device_key": key, "title": message.title, "body": message.body, "group": BARK_GROUP,
                   "level": message.level, "isArchive": "1"}
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

    def _mail(self, message: Message) -> bool:
        mailer = self.mail or send_email
        try:
            return bool(mailer(message))
        except Exception as exc:  # a mail bug must not stop the watcher
            log(f"email push failed: {type(exc).__name__}")
            return False


def delivered(results: dict) -> bool:
    return any(results.values())


# ---------------------------------------------------------------- watcher

def size_text(size: Optional[int]) -> str:
    return f"{size / 1e9:.2f} GB" if size else "大小未知"


class Watcher:
    def __init__(self, *, state_path: Path, notifier: Notifier, fetch: Callable = fetch_listing,
                 clock: Callable = lambda: dt.datetime.now(TZ), sleep: Callable = time.sleep,
                 poll_seconds: float = POLL_SECONDS, jitter_seconds: float = JITTER_SECONDS):
        self.state_path, self.notifier, self.fetch = state_path, notifier, fetch
        self.clock, self.sleep = clock, sleep
        self.poll_seconds, self.jitter_seconds = poll_seconds, jitter_seconds
        self.observations = state_path.with_name("observations.ndjson")
        self.state = load_state(state_path)
        self.failures = 0
        self.last_names: list = []

    def slot(self, window: Window) -> dict:
        return self.state["windows"].setdefault(window.day.isoformat(), {
            "startSent": False, "baselineDone": False, "found": [], "summarySent": False,
            "errorSent": False, "recoverySent": False})

    def save(self) -> None:
        save_state(self.state_path, self.state, self.clock().date())

    def run(self) -> int:
        now = self.clock()
        window = window_on(now)
        if window is None or now < window.start:
            log(f"outside the window; next {next_window(now).start:%Y-%m-%d %H:%M %Z}")
            return 0
        slot = self.slot(window)
        if now >= window.end:
            if slot["summarySent"]:
                log("window already closed and summarised")
                return 0
            log("started after the window closed: one catch-up read, then the summary")
            self.poll(window)
        else:
            self.start(window, slot)
            while True:
                started = time.monotonic()
                self.poll(window)
                interval = self.poll_seconds + random.uniform(0, self.jitter_seconds)
                remaining = (window.end - self.clock()).total_seconds()
                if remaining <= 0:
                    break
                self.sleep(max(1.0, min(interval - (time.monotonic() - started), remaining)))
                if self.clock() >= window.end:
                    break
        self.summarise(window, slot)
        return 0

    def start(self, window: Window, slot: dict) -> None:
        if slot["startSent"]:
            return
        accounts = ", ".join(a.replace("bark-", "") for a in self.notifier.keys) or "无"
        missing = [a for a in BARK_ACCOUNTS if a not in self.notifier.keys]
        body = (f"{WINDOW_START:%H:%M}–{WINDOW_END:%H:%M} 每 {self.poll_seconds:.0f}s 查一次 Broadcast Message Files"
                f" · Bark: {accounts}")
        if missing:
            body += f" · 缺少 {', '.join(missing)}"
        results = self.notifier.send(Message("开始监控证道视频上传", body, level="active" if missing else "passive"))
        slot["startSent"] = delivered(results)
        self.save()

    def poll(self, window: Window) -> list:
        slot = self.slot(window)
        try:
            files = self.fetch()
        except ListingError as exc:
            self.failures += 1
            log(f"read failed ({self.failures} in a row): {exc}")
            if self.failures >= ERROR_THRESHOLD and not slot["errorSent"]:
                results = self.notifier.send(Message("证道视频检查失败", f"连续 {self.failures} 次读不到文件夹：{exc}",
                                                     level="timeSensitive"))
                slot["errorSent"] = delivered(results)
                self.save()
            return []
        if slot["errorSent"] and not slot["recoverySent"] and self.failures:
            slot["recoverySent"] = delivered(self.notifier.send(
                Message("证道视频检查已恢复", "文件夹又能读取了", level="passive")))
        self.failures = 0
        self.last_names = [f.name for f in files]
        now = self.clock()
        new = []
        for item in files:
            if item.id in self.state["notified"] or item.id in self.state["baseline"]:
                continue
            fresh = item.earliest >= window.week_start if item.earliest else slot["baselineDone"]
            if fresh:
                new.append(item)
            else:
                self.state["baseline"][item.id] = {**item.record(), "recordedPT": _iso(now)}
        slot["baselineDone"] = True
        for item in new:
            results = self.notifier.send(self.found_message(item, window))
            if not delivered(results):
                log(f"no channel delivered the notice for {item.name}; retrying next poll")
                continue
            record = {**item.record(), "firstSeenPT": _iso(now), "window": window.day.isoformat()}
            self.state["notified"][item.id] = record
            slot["found"].append(item.id)
            append_observation(self.observations, {"event": "found", **record, "delivery": results})
            log(f"new file {item.name} ({size_text(item.size)}) notified: {results}")
        self.save()
        return new

    def found_message(self, item: DriveFile, window: Window) -> Message:
        stamp = f"{item.earliest:%H:%M} PT" if item.earliest else "时间未知"
        if item.earliest and item.earliest.date() != window.day:
            stamp = f"{item.earliest:%m-%d %H:%M} PT"
        label = f"名称含 {window.prefix}" if window.prefix in item.name else f"名称不含 {window.prefix}"
        body = f"{item.name} · {size_text(item.size)} · {stamp} · {label}"
        if item.earliest and item.earliest < window.start:
            body += " · 窗口前已上传"
        return Message("证道视频已上传", body, level="critical", url=item.url, sound="bell", volume="0")

    def summarise(self, window: Window, slot: dict) -> None:
        if slot["summarySent"]:
            return
        if not slot["found"]:
            listing = "、".join(self.last_names) if self.last_names else "（未读到或为空）"
            results = self.notifier.send(Message(
                "本周未见新证道视频",
                f"{WINDOW_START:%H:%M}–{WINDOW_END:%H:%M} 未见新文件。文件夹现有：{listing}"))
            slot["summarySent"] = delivered(results)
        else:
            slot["summarySent"] = True
        append_observation(self.observations, {"event": "window_closed", "window": window.day.isoformat(),
                                               "found": slot["found"], "closedPT": _iso(self.clock())})
        self.save()


# ---------------------------------------------------------------- launchd

def plist_for(script: Path, support: Path) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": ["/usr/bin/caffeinate", "-i", SYSTEM_PYTHON, "-I", str(script), "run"],
        "StartCalendarInterval": {"Weekday": 6, "Hour": WINDOW_START.hour, "Minute": WINDOW_START.minute},
        "RunAtLoad": True,
        "StandardOutPath": str(support / "watch.log"),
        "StandardErrorPath": str(support / "watch.log"),
    }


def launchctl(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/launchctl", *arguments], capture_output=True, text=True, check=False)


def cmd_install(args) -> int:
    support = args.support_dir
    support.mkdir(parents=True, exist_ok=True)
    script = support / "drive_upload_watch.py"
    plist = plistlib.dumps(plist_for(script, support)).decode("utf-8")
    if args.print:
        print(plist)
        return 0
    shutil.copy2(Path(__file__).resolve(), script)
    LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENT.write_text(plist, encoding="utf-8")
    domain = f"gui/{os.getuid()}"
    launchctl("bootout", f"{domain}/{LABEL}")
    result = launchctl("bootstrap", domain, str(LAUNCH_AGENT))
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        return 1
    print(json.dumps({"installed": str(LAUNCH_AGENT), "script": str(script), "log": str(support / "watch.log"),
                      "barkAccounts": sorted(keychain_keys()), "emailConfigured": email_credentials() is not None,
                      "nextWindow": next_window(dt.datetime.now(TZ)).start.isoformat()}, indent=2))
    return 0


def cmd_uninstall(args) -> int:
    launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    if LAUNCH_AGENT.exists():
        LAUNCH_AGENT.unlink()
    print(json.dumps({"removed": str(LAUNCH_AGENT), "keptState": str(args.support_dir)}, indent=2))
    return 0


def cmd_status(args) -> int:
    loaded = launchctl("print", f"gui/{os.getuid()}/{LABEL}")
    state = re.search(r"^\s*state = (.+)$", loaded.stdout, re.M)
    last_exit = re.search(r"^\s*last exit code = (.+)$", loaded.stdout, re.M)
    log_path = args.support_dir / "watch.log"
    tail = log_path.read_text(encoding="utf-8").splitlines()[-5:] if log_path.exists() else []
    print(json.dumps({
        "launchAgent": str(LAUNCH_AGENT) if LAUNCH_AGENT.exists() else None,
        "loaded": loaded.returncode == 0,
        "jobState": state.group(1) if state else None,
        "lastExit": last_exit.group(1) if last_exit else None,
        "installedCopyMatchesThisFile": _same_file(args.support_dir / "drive_upload_watch.py", Path(__file__)),
        "barkAccounts": sorted(keychain_keys()),
        "emailConfigured": email_credentials() is not None,
        "nextWindow": next_window(dt.datetime.now(TZ)).start.isoformat(),
        "logTail": tail,
    }, ensure_ascii=False, indent=2))
    return 0


def _same_file(a: Path, b: Path) -> Optional[bool]:
    return a.read_bytes() == b.resolve().read_bytes() if a.exists() else None


# ---------------------------------------------------------------- commands

def cmd_check(args) -> int:
    now = dt.datetime.now(TZ)
    out = {"checkedAtPT": _iso(now), "folder": FOLDER_URL, "nextWindow": next_window(now).start.isoformat(),
           "barkAccounts": sorted(keychain_keys())}
    try:
        out["files"] = [f.record() for f in fetch_listing()]
    except ListingError as exc:
        print(json.dumps({**out, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_test_push(args) -> int:
    keys = keychain_keys()
    if not keys:
        print(f"no Bark key in the keychain (service {KEYCHAIN_SERVICE}, accounts {', '.join(BARK_ACCOUNTS)})",
              file=sys.stderr)
    email_ready = email_credentials() is not None
    if not email_ready:
        print(f"email channel not configured (service {KEYCHAIN_SERVICE}, accounts gmail-user and gmail-app)",
              file=sys.stderr)
    critical = getattr(args, "critical", False)
    test_message = Message("证道视频监控测试", f"测试推送 · {dt.datetime.now(TZ):%m-%d %H:%M} PT",
                           level="critical" if critical else "active", url=FOLDER_URL,
                           volume="0" if critical else None)
    results = Notifier(keys).send(test_message)
    print(json.dumps(results, indent=2))
    ok = bool(keys) and all(results.get(a) for a in keys)
    if email_ready:
        ok = ok and results.get("email") is True
    return 0 if ok else 1


def simulated_clock(start: dt.datetime) -> Callable:
    origin = time.monotonic()
    return lambda: start + dt.timedelta(seconds=time.monotonic() - origin)


def cmd_run(args) -> int:
    args.state.parent.mkdir(parents=True, exist_ok=True)
    with open(args.state.with_name("watch.lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("another watcher holds the lock; exiting")
            return 0
        clock = simulated_clock(dt.datetime.fromisoformat(args.now).replace(tzinfo=TZ)) if args.now else (
            lambda: dt.datetime.now(TZ))
        notifier = Notifier(keychain_keys(), push=not args.no_push)
        return Watcher(state_path=args.state, notifier=notifier, clock=clock,
                       poll_seconds=args.interval).run()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--support-dir", type=Path, default=SUPPORT_DIR, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="poll during the Saturday window, then exit")
    run.add_argument("--state", type=Path, default=SUPPORT_DIR / "state.json")
    run.add_argument("--interval", type=float, default=POLL_SECONDS, help="seconds between reads")
    run.add_argument("--now", help="pretend the run starts at this Pacific time (ISO), e.g. 2026-10-31T19:30")
    run.add_argument("--no-push", action="store_true", help="print notices instead of sending them")
    commands.add_parser("check", help="read the folder once and print JSON (no state, no notice)")
    test_push = commands.add_parser("test-push", help="send one test notice to every Bark key and the email channel")
    test_push.add_argument("--critical", action="store_true",
                           help="send the found-upload shape: critical level with volume=0 (silent)")
    install = commands.add_parser("install", help="copy this file and load the Saturday LaunchAgent")
    install.add_argument("--print", action="store_true", help="print the plist only")
    commands.add_parser("uninstall", help="unload and remove the LaunchAgent (state is kept)")
    commands.add_parser("status", help="LaunchAgent state, Bark accounts, next window, log tail")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {"run": cmd_run, "check": cmd_check, "test-push": cmd_test_push, "install": cmd_install,
                "uninstall": cmd_uninstall, "status": cmd_status}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
