#!/usr/bin/env python3
"""Drive the weekly sermon from a new Drive file to an approved English table (Layer 1).

    weekly_auto.py pending                         what launchd runs: start new triggers, move productions on
    weekly_auto.py start --trigger FILE [--rehearsal]
    weekly_auto.py run --production NAME [--retry] move one production on (apply decisions first)
    weekly_auto.py status [--production NAME]
    weekly_auto.py reconcile --production NAME --outcome charged|not_charged
    weekly_auto.py rebuild-english --production NAME [--fixes FILE]
    weekly_auto.py agents print|install|uninstall|status
    weekly_auto.py url

What runs by itself, from the trigger the Drive watcher writes (tools/ops/drive_upload_watch.py):
download and hash the file, cut the audio, transcribe (paid, inside the weekly cap), build the
sentence table, and open two review steps: the kickoff decisions and the English table. Then it
waits. A decision from the review page (tools/ops/review_gate_server.py) is checked against the
files once more; only then are the kickoff record, the revised sentence table, the English
source package and its receipt written. Translation, dubbing and publishing are not driven
from here yet: after the English table the run continues by the runbook
(experiments/sentence-first-agent/AGENTS.md).

Rules it keeps:
  - Every step is skipped when its output is already there; a stopped run resumes.
  - A failed step is not retried by the timer. `run --retry` retries it once, by a person.
  - Before a paid request the weekly ledger reserves its cost; over the cap nothing is sent.
    A paid step that ends without a clear result stops all paid work until `reconcile`.
  - A rehearsal writes the same files but approves nothing (humanApproval false, not eligible
    for translation) and says "演练" in every notice.

The standing authorizations (source folder, weekly cap, page decisions) are in
config/weekly-sermon-auto.json. This Mac's own settings (where the artifacts live, the review
port and address) are in ~/Library/Application Support/org.sermonvideo.weekly-auto/local.json.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import notify  # noqa: E402
import production_notices as notices  # noqa: E402
import review_gates  # noqa: E402
from review_gate_server import tailnet_name  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "experiments" / "sentence-first-agent"
CONFIG = ROOT / "config" / "weekly-sermon-auto.json"
SUPPORT = Path.home() / "Library" / "Application Support" / "org.sermonvideo.weekly-auto"
TRIGGERS = Path.home() / "Library" / "Application Support" / "org.sermonvideo.drive-upload-watch" / "triggers"
LABEL_REVIEW = "org.sermonvideo.weekly-auto.review"
LABEL_DRIVER = "org.sermonvideo.weekly-auto.driver"
AGENT_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
TZ = notices.TZ
STAGES = ("source.accept", "source.download", "source.derive", "gate.decisions", "l1.prompt", "l1.transcribe",
          "l1.anchor", "l1.rows", "gate.english", "wait.review", "handoff")
DELIVERABLES = ("页面 + 三语 assets（page/content/audio/captions）", "release 包", "目录（multilingual-v5/v4/v3）",
                "英文对照 /english-reference/<pageId>.json", "现场对齐（sidecar + 每语指纹索引）", "研读手册条目", "统计目录")
MAX_NOTICE_ATTEMPTS = 6
NEXT_AFTER_ENGLISH = "翻译和配音（还没有自动化，按 runbook 从 sfa.py start 继续）"


class StageError(Exception):
    """A stage stopped. `message` is what the person reads; `fields` fill the notice for `event`."""

    def __init__(self, error_class: str, message: str, *, event: str = "stage.failed", **fields):
        super().__init__(message)
        self.error_class, self.message, self.event, self.fields = error_class, message, event, fields


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def json_sha(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def clock_text(seconds: float) -> str:
    return f"{int(seconds // 60)} 分 {int(seconds % 60)} 秒"


# ---------------------------------------------------------------- weekly budget ledger

class Budget:
    """One file per ISO week: what paid work was reserved, what it cost, what is still unknown."""

    def __init__(self, work_root: Path, cap_usd: float, when: dt.date):
        year, week, _ = when.isocalendar()
        self.path = work_root / review_gates.ROOT_NAME / "budget" / f"openai-{year}-W{week:02d}.json"
        self.cap = float(cap_usd)

    def _load(self) -> dict:
        return read_json(self.path, {"schemaVersion": "weekly-auto-budget-v1", "capUsd": self.cap, "entries": []})

    def committed(self, ledger: dict | None = None) -> float:
        entries = (ledger or self._load())["entries"]
        return round(sum(e["actualUsd"] if e["state"] == "settled" else e["reservedUsd"] for e in entries
                         if e["state"] in ("settled", "reserved", "unknown")), 4)

    def unknown(self) -> list[dict]:
        return [e for e in self._load()["entries"] if e["state"] in ("reserved", "unknown")]

    def reserve(self, production: str, stage: str, usd: float) -> str:
        ledger = self._load()
        spent = self.committed(ledger)
        if spent + usd > self.cap + 1e-9:
            raise StageError("budget", "超过每周预算上限", event="budget.blocked",
                             spent=f"{spent:.2f}", reserve=f"{usd:.2f}", cap=f"{self.cap:g}")
        entry_id = f"{production}:{stage}:{len(ledger['entries']) + 1}"
        ledger["entries"].append({"id": entry_id, "production": production, "stage": stage, "state": "reserved",
                                  "reservedUsd": round(usd, 4), "actualUsd": None, "at": review_gates.now_iso()})
        review_gates.write_json(self.path, ledger)
        return entry_id

    def close(self, entry_id: str, state: str, actual_usd: float | None = None) -> None:
        ledger = self._load()
        for entry in ledger["entries"]:
            if entry["id"] == entry_id:
                entry.update(state=state, actualUsd=None if actual_usd is None else round(actual_usd, 4), closedAt=review_gates.now_iso())
        review_gates.write_json(self.path, ledger)


# ---------------------------------------------------------------- the driver

class Driver:
    def __init__(self, work_root: Path, *, config_path: Path = CONFIG, push: bool = True, local: dict | None = None,
                 run=subprocess.run, opener=urllib.request.urlopen, notifier=None, python: str | None = None,
                 sleep=time.sleep):
        self.work_root = Path(work_root).resolve()
        self.config_path = Path(config_path)
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.local = local if local is not None else read_json(SUPPORT / "local.json", {})
        self.store = review_gates.Store(self.work_root)
        self.run_command, self.opener, self.push, self.sleep = run, opener, push, sleep
        self.python = python or self.local.get("python") or sys.executable
        self._notifier = notifier

    # ---- small helpers
    def log(self, production: str, event: str, **fields) -> None:
        path = self.store.production_dir(production) / "events.ndjson"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": review_gates.now_iso(), "event": event, **fields}, ensure_ascii=False) + "\n")

    def save(self, record: dict) -> None:
        self.store.write_production(record)

    def worker(self, record: dict, stage: str, detail: str, state: str = "在线") -> None:
        record["worker"] = {"lastSeenAt": review_gates.now_iso(), "state": state, "stage": stage, "detail": detail}
        self.save(record)

    def source_run(self, record: dict) -> Path:
        return self.work_root / record["sourceRun"]

    def step(self, record: dict, name: str, command: list[str], *, cwd: Path | None = None) -> str:
        """Run one child step from the code checkout; a non-zero exit is a failed stage."""
        self.log(record["production"], "step.started", step=name)
        done = self.run_command(command, cwd=str(cwd or ROOT), capture_output=True, text=True, check=False,
                                env={**os.environ, "PATH": f"{AGENT_PATH}:{os.environ.get('PATH', '')}"})
        self.log(record["production"], "step.finished", step=name, exit=done.returncode)
        if done.returncode != 0:
            tail = (done.stderr or done.stdout or "").strip().splitlines()[-1:] or [""]
            raise StageError("process", f"{name} 退出码 {done.returncode}：{tail[0][:160]}", stageName=name)
        return done.stdout

    def review_base(self) -> str | None:
        if self.local.get("reviewBaseUrl"):
            return str(self.local["reviewBaseUrl"]).rstrip("/")
        name = tailnet_name()
        return f"https://{name}:{self.local.get('port', self.config['review']['port'])}" if name else None

    def page_url(self, record: dict, kind: str | None = None, gate_id: str | None = None) -> str | None:
        base = self.review_base()
        if not base:
            return None
        if kind is None:
            return f"{base}/index.html?production={record['production']}"
        return f"{base}/{notices.GATES[kind]['page']}?production={record['production']}&gate={gate_id}"

    def notifier(self):
        if self._notifier is None:
            self._notifier = (notify.Notifier(notify.keychain_keys(), mail=notify.configured_mail()) if self.push
                              else notify.Notifier({}, push=False))
        return self._notifier

    def notice(self, record: dict, event: str, *, kind: str | None = None, gate_id: str | None = None,
               locale: str | None = None, once: str | None = None, **fields) -> None:
        """Send one catalog notice, once per key. A notice never fails the production."""
        try:
            built = notices.build(event, production=record["production"], kind=kind, locale=locale,
                                  url=self.page_url(record, kind, gate_id), rehearsal=bool(record.get("rehearsal")), **fields)
            key = once or built["key"]
            if key in record.setdefault("notices", {}):
                return
            if built["linkMissing"]:
                built["body"] += " 审核页地址暂时拿不到，请在生产机上查看。"
            self.deliver(record, key, built, 1)
        except Exception as exc:  # noqa: BLE001
            self.log(record["production"], "notice.failed", noticeEvent=event, error=type(exc).__name__)

    def deliver(self, record: dict, key: str, built: dict, attempt: int) -> None:
        """Send; a notice no channel took stays in the outbox and is tried again on the next run."""
        results = self.notifier().send(notices.to_message(built))
        delivered = notify.delivered(results) or bool(results.get("printed"))
        record["notices"][key] = {"at": review_gates.now_iso(), "event": built["event"], "level": built["level"], "delivered": delivered,
                                  "channels": sorted(name for name, ok in results.items() if ok), "attempts": attempt}
        outbox = record.setdefault("outbox", {})
        if delivered or attempt >= MAX_NOTICE_ATTEMPTS:
            outbox.pop(key, None)
        else:
            outbox[key] = {**{name: built[name] for name in ("event", "level", "title", "body", "url")}, "attempts": attempt}
        self.log(record["production"], "notice", key=key, level=built["level"], delivered=delivered,
                 channels=record["notices"][key]["channels"], attempt=attempt)

    def flush_outbox(self, record: dict) -> None:
        for key, item in list(record.get("outbox", {}).items()):
            try:
                self.deliver(record, key, item, item["attempts"] + 1)
            except Exception as exc:  # noqa: BLE001
                self.log(record["production"], "notice.failed", noticeEvent=item.get("event"), error=type(exc).__name__)

    # ---- starting
    def start(self, trigger: dict, *, rehearsal: bool = False, production: str | None = None) -> dict:
        file = trigger["file"]
        saturday = dt.date.fromisoformat(trigger["window"])
        name = production or (f"rehearsal-{dt.datetime.now(TZ):%Y%m%d-%H%M}" if rehearsal else f"{saturday:%Y%m%d}-sermon")
        folder = self.store.production_dir(name)
        if (folder / "production.json").is_file():
            return self.store.production(name)
        record = {"schemaVersion": "weekly-auto-production-v1", "production": name, "rehearsal": rehearsal,
                  "saturday": saturday.isoformat(), "sunday": trigger["sunday"], "createdAt": review_gates.now_iso(),
                  "trigger": trigger, "sourceRun": str(Path("artifacts") / "sentence-first-agent" / f"{name}-source"),
                  "episode": {"sunday": trigger["sunday"], "title": None, "speaker": None},
                  "source": {"fileId": file["id"], "name": file["name"], "sizeBytes": file.get("sizeBytes"),
                             "mime": file.get("mime"), "url": file.get("url"), "folderUrl": trigger.get("folderUrl"),
                             "uploadedAt": file.get("latestTimePT")},
                  "stages": {}, "notices": {}, "reminders": {}, "state": "running", "worker": {}}
        self.save(record)
        self.log(name, "production.created", fileId=file["id"], rehearsal=rehearsal)
        return record

    # ---- stages
    def stage_source_accept(self, record: dict) -> str:
        source, rules = record["source"], self.config["source"]
        if record["trigger"].get("folderId") != rules["folderId"]:
            raise StageError("source", "不在授权的来源文件夹里", event="source.rejected", fileName=source["name"],
                             reason="不在授权的来源文件夹里")
        if not any(str(source.get("mime") or "").startswith(prefix) for prefix in rules["acceptMimePrefixes"]):
            raise StageError("source", "不是视频文件", event="source.rejected", fileName=source["name"], reason="不是视频文件")
        if source.get("sizeBytes") and source["sizeBytes"] < rules["minBytes"]:
            raise StageError("source", "文件太小", event="source.rejected", fileName=source["name"],
                             reason=f"只有 {source['sizeBytes'] / 1e6:.0f} MB，不像一场证道")
        self.notice(record, "production.started", sunday=record["sunday"], fileName=source["name"],
                    sizeGb=f"{(source.get('sizeBytes') or 0) / 1e9:.2f}", eta="转写完成后（通常 15–20 分钟）")
        return "done"

    def download(self, record: dict, target: Path) -> None:
        """Public Drive file by id, resumable; an HTML answer means Drive refused the file."""
        source = record["source"]
        url = f"https://drive.usercontent.google.com/download?id={source['fileId']}&export=download&confirm=t"
        part = target.with_name(target.name + ".part")
        expected = source.get("sizeBytes")
        last_error = "没有开始"
        for attempt in range(1, 4):
            have = part.stat().st_size if part.exists() else 0
            if expected and have >= expected:
                break
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **({"Range": f"bytes={have}-"} if have else {})})
            try:
                with self.opener(request, timeout=120) as response:
                    if str(response.headers.get("Content-Type", "")).startswith("text/html"):
                        raise StageError("download", "Drive 返回了网页而不是文件", event="source.download_failed",
                                         fileName=source["name"], reason="Drive 返回了网页而不是文件（可能超过下载配额或已取消公开）", attempts=attempt)
                    resumed = getattr(response, "status", 200) == 206
                    with part.open("ab" if resumed else "wb") as handle:
                        written = have if resumed else 0
                        mark = written
                        for block in iter(lambda: response.read(1 << 20), b""):
                            handle.write(block)
                            written += len(block)
                            if written - mark >= 100 * (1 << 20):
                                mark = written
                                self.worker(record, "下载", f"{written / 1e6:.0f} MB" + (f" / {expected / 1e6:.0f} MB" if expected else ""))
                if not expected or part.stat().st_size >= expected:
                    break
                last_error = f"只下到 {part.stat().st_size} / {expected} 字节"
            except (urllib.error.URLError, OSError) as exc:
                last_error = f"{type(exc).__name__}"
                self.sleep(min(30, 5 * attempt))
        size = part.stat().st_size if part.exists() else 0
        if not size or (expected and size != expected):
            raise StageError("download", last_error, event="source.download_failed", fileName=source["name"],
                             reason=f"{last_error}；大小 {size}，应为 {expected}", attempts=3)
        os.replace(part, target)

    def stage_source_download(self, record: dict) -> str:
        folder = self.source_run(record) / "source"
        folder.mkdir(parents=True, exist_ok=True)
        media = folder / "episode.mp4"
        identity = folder / "source.json"
        if not identity.is_file():
            if not media.is_file():
                self.worker(record, "下载", record["source"]["name"])
                self.download(record, media)
            self.worker(record, "核对文件", "计算哈希和时长")
            probe = self.step(record, "ffprobe", ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(media)])
            review_gates.write_json(identity, {
                "schemaVersion": "weekly-auto-source-v1", "fileId": record["source"]["fileId"], "name": record["source"]["name"],
                "url": record["source"].get("url"), "folderUrl": self.config["source"]["folderUrl"],
                "sizeBytes": media.stat().st_size, "sha256": sha256_file(media), "durationSeconds": float(probe.strip()),
                "attribution": self.config["source"]["attribution"], "downloadedAt": review_gates.now_iso(),
                "authorization": self.config["authorizations"]["sourceAutoStart"]})
        record["source"].update({k: v for k, v in read_json(identity).items() if k in ("sha256", "durationSeconds", "sizeBytes")})
        return "done"

    def stage_source_derive(self, record: dict) -> str:
        folder = self.source_run(record) / "source"
        media, wav, mp3 = folder / "episode.mp4", folder / "source.wav", folder / "sermon-upload.mp3"
        if not wav.is_file():
            self.worker(record, "切音频", "16 kHz 单声道")
            self.step(record, "ffmpeg wav", ["ffmpeg", "-v", "error", "-y", "-i", str(media), "-vn", "-ac", "1", "-ar", "16000",
                                             "-c:a", "pcm_s16le", str(wav) + ".tmp.wav"])
            os.replace(str(wav) + ".tmp.wav", wav)
        if not mp3.is_file():
            limits = self.config["transcription"]
            duration = record["source"]["durationSeconds"]
            rate = next((k for k in limits["uploadBitratesKbps"] if k * 125 * duration <= limits["uploadMaxBytes"]), None)
            if rate is None:
                raise StageError("source", f"{clock_text(duration)} 的音频放不进一次上传", stageName="切音频")
            self.step(record, "ffmpeg mp3", ["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-ac", "1", "-b:a", f"{rate}k", str(mp3) + ".tmp.mp3"])
            os.replace(str(mp3) + ".tmp.mp3", mp3)
        return "done"

    def title_row(self, sunday: str) -> dict | None:
        table = ROOT / self.config["defaults"]["titleTable"]
        series = None
        for line in table.read_text(encoding="utf-8").splitlines():
            heading = re.match(r"##\s+(.+?)（`", line)
            if heading:
                series = heading.group(1).strip()
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if line.startswith("|") and len(cells) >= 8 and cells[1].startswith(sunday) and cells[0].isdigit():
                return {"week": int(cells[0]), "english": cells[2], "scripture": cells[3], "speaker": cells[4],
                        "titles": {"zh-Hans": cells[5], "ko": cells[6], "es": cells[7]}, "series": series}
        return None

    def speaker_options(self) -> list[dict]:
        registry = json.loads((ROOT / "config" / "speaker-voice-registry.json").read_text(encoding="utf-8"))
        folders = [Path.home() / "tts-runtime", self.work_root / "artifacts" / "model-routing" / "macbook-tts"]
        present = [path.name.removeprefix("checkpoint-") for folder in folders if folder.is_dir() for path in folder.glob("checkpoint-*")]
        options = []
        for speaker in registry["speakers"]:
            if speaker["authorization"]["status"] != "authorized" or "multilingual_dubbing" not in speaker["authorization"]["purposes"]:
                continue
            sha = speaker["checkpoint"]["checkpointSha256"]
            options.append({"value": speaker["speakerId"], "label": speaker["displayName"],
                            "locales": [c["targetLocale"] for c in speaker["localeCapabilities"] if c.get("status") == "human_reviewed"],
                            "checkpointReady": any(prefix and sha.startswith(prefix) for prefix in present)})
        return options

    def stage_gate_decisions(self, record: dict) -> str:
        source, defaults = record["source"], self.config["defaults"]
        row = self.title_row(record["sunday"])
        speakers = self.speaker_options()
        named = next((o["value"] for o in speakers if row and o["label"] == row["speaker"]), None)
        speaker_id = named or defaults["speakerId"]
        assets = self.source_run(record) / "review" / "decisions"
        (assets / "window").mkdir(parents=True, exist_ok=True)
        wav, duration = self.source_run(record) / "source" / "source.wav", source["durationSeconds"]
        for name, start in (("head", 0.0), ("tail", max(0.0, duration - 15.0))):
            clip = assets / "window" / f"{name}.mp3"
            if not clip.is_file():
                self.step(record, f"ffmpeg {name}", ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-t", "15", "-i", str(wav),
                                                    "-ac", "1", "-b:a", "64k", str(clip)])
        minutes = round(duration * 1.28 / 60)
        data = {
            "source": {"fileName": source["name"], "sizeBytes": source["sizeBytes"], "durationSeconds": duration,
                       "uploadedAt": source.get("uploadedAt"), "sha256": source["sha256"], "fileUrl": source.get("url"),
                       "attribution": self.config["source"]["attribution"],
                       "authorization": f"默认配置里的来源自动开工授权（{self.config['authorizations']['sourceAutoStart']['grantedAt']} 用户决定）"},
            "choices": [
                {"key": "form", "label": "形态", "multi": False, "value": defaults["form"],
                 "options": [{"value": "full", "label": "整期"}, {"value": "clip", "label": "10 分钟片段", "help": "片段目前不能自动处理，选它会停下来等人工。"}]},
                {"key": "locales", "label": "语言", "multi": True, "value": defaults["locales"],
                 "options": [{"value": code, "label": notices.LOCALE_NAMES.get(code, code)} for code in ("zh-Hans", "ko", "es")]},
                {"key": "sync", "label": "同步", "multi": False, "value": "synced" if defaults["sync"] else "independent", "options": [
                    {"value": "synced", "label": "跟视频同步", "help": "每句放在英文的时间点上。放不下时先去静音，再逐句加速到 1.15 倍以内，最后才做最小删字。"},
                    {"value": "independent", "label": "独立音轨", "help": "自然语速，不精简；配音比原片长，不跟画面。"}]},
                {"key": "publish", "label": "发布", "multi": False, "value": defaults["publish"], "options": [
                    {"value": "production_page", "label": "正式页", "help": "以 human_reviewed 发布，要你听完每条整轨并审译文。"},
                    {"value": "dev_review", "label": "只出 Dev 审核"}, {"value": "none", "label": "不出页面"}]},
                {"key": "speakerId", "label": "讲员", "multi": False, "value": speaker_id, "options": speakers,
                 "evidence": (f"标题表这一周登记的讲员是 {row['speaker']}。" if named else "标题表没有登记这一周的讲员，先按默认值；请听开头 15 秒确认。")}],
            "title": {"basis": "title_table" if row else "missing", "week": row["week"] if row else None,
                      "english": row["english"] if row else None, "scripture": row["scripture"] if row else None,
                      "series": {"zh-Hans": row["series"]} if row and row["series"] else {}, "format": "title_only",
                      "titles": row["titles"] if row else {}},
            "window": {"start": 0.0, "end": duration, "mediaDuration": duration, "head": "window/head.mp3", "tail": "window/tail.mp3"},
            "deliverables": [{"n": n + 1, "label": label, "deliver": True, "reason": None} for n, label in enumerate(DELIVERABLES)],
            "plan": [{"label": "英文表", "when": "转写和拆句完成后", "effort": "审 10–20 分钟"},
                     {"label": "每种语言的整轨", "when": "英文表批准后逐条配好", "effort": f"每条整轨约 {minutes} 分钟，只跟标记约 {max(10, minutes // 2)} 分钟"},
                     {"label": "发布授权", "when": "三条音轨都有结论之后", "effort": "约 5 分钟"},
                     {"label": "发布后确认", "when": "发布之后", "effort": "约 10 分钟"}]}
        summary = "整期 · 三语 · 同步 · 正式页" + ("" if row else " · 标题表里没有这一周")
        self.store.open_gate(record["production"], gate_id="l0.decisions", kind="decisions", title="开工确认", summary=summary,
                             bindings={"sourceMediaSha256": source["sha256"], "defaultsConfigSha256": sha256_file(self.config_path)},
                             data=data, assets_root=assets)
        record["episode"].update(title=(row or {}).get("titles", {}).get("zh-Hans"),
                                 speaker=next((o["label"] for o in speakers if o["value"] == speaker_id), speaker_id))
        self.notice(record, "gate.opened", kind="decisions", gate_id="l0.decisions",
                    summary="默认值已填好：" + summary + ("，需要你填讲题" if not row else ""))
        return "done"

    def stage_l1_prompt(self, record: dict) -> str:
        layer1 = self.source_run(record) / "layer1"
        layer1.mkdir(parents=True, exist_ok=True)
        row = self.title_row(record["sunday"])
        prompt = self.config["transcription"]["basePrompt"]
        if row:
            prompt += f' Episode: "{row["english"]}".'
        (layer1 / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")
        return "done"

    def budget(self, record: dict) -> Budget:
        return Budget(self.work_root, self.config["budget"]["weeklyCapUsd"], dt.date.fromisoformat(record["saturday"]))

    def stage_l1_transcribe(self, record: dict) -> str:
        layer1 = self.source_run(record) / "layer1"
        outputs = [layer1 / name for name in ("raw-whisper.json", "words.json", "gpt-4o-chunks.json", "raw-gpt-4o-transcribe.txt")]
        if all(path.is_file() for path in outputs):
            return "done"
        budget, limits = self.budget(record), self.config["transcription"]
        if budget.unknown():
            raise StageError("unknown_outcome", "之前有一次付费请求结果未知，先对账", event="paid.unknown_outcome", stageName="英文转写")
        minutes = record["source"]["durationSeconds"] / 60
        rates = limits["estimatedUsdPerAudioMinute"]
        usage_path = layer1 / "transcribe-usage.json"
        before = read_json(usage_path, {"models": {}})["models"]
        cost = lambda usage: sum(rates.get(model, 0.0) * row["audioSeconds"] / 60 for model, row in usage.items())
        estimate = minutes * (rates[limits["timingModel"]] + rates[limits["textModel"]] * limits["textMaxAttempts"])
        entry = budget.reserve(record["production"], "l1.transcribe", estimate)
        self.worker(record, "英文转写", f"{clock_text(record['source']['durationSeconds'])} 的音频，两遍")
        env_file = Path(self.local.get("envFile") or self.work_root / ".env.openai")
        command = [self.python, str(ROOT / "tools" / "ops" / "run_with_openai_environment.py"), "--environment", limits["environment"],
                   "--env-file", str(env_file), "--",
                   self.python, str(EXP / "l1_transcribe.py"), "--audio", str(self.source_run(record) / "source" / "sermon-upload.mp3"),
                   "--out", str(layer1), "--prompt-file", str(layer1 / "prompt.txt"), "--timing-model", limits["timingModel"],
                   "--text-model", limits["textModel"], "--chunk-seconds", str(limits["chunkSeconds"]), "--max-attempts", str(limits["textMaxAttempts"])]
        try:
            self.step(record, "英文转写", command, cwd=self.work_root)
        except StageError as exc:
            budget.close(entry, "unknown")
            raise StageError("unknown_outcome", exc.message, event="paid.unknown_outcome", stageName="英文转写") from exc
        budget.close(entry, "settled", cost(read_json(usage_path, {"models": {}})["models"]) - cost(before))
        if not all(path.is_file() for path in outputs):
            raise StageError("process", "转写结束了但缺少输出文件", stageName="英文转写")
        return "done"

    def build_candidate(self, record: dict) -> dict:
        run, source = self.source_run(record), record["source"]
        layer1, candidate = run / "layer1", run / "layer1" / "candidate"
        command = [self.python, str(EXP / "l1_anchor.py"), "build", "--raw", str(layer1 / "raw-whisper.json"),
                   "--media-sha256", source["sha256"], "--media-duration", repr(source["durationSeconds"]), "--out", str(candidate),
                   "--source-url", self.config["source"]["folderUrl"], "--date", record["sunday"],
                   "--speaker-source", "single speaker; identity confirmed by the reviewer on the kickoff page; no diarization pass",
                   "--text-chunks", str(layer1 / "gpt-4o-chunks.json")]
        if (layer1 / "english-fixes.json").is_file():
            command += ["--fixes", str(layer1 / "english-fixes.json")]
        return json.loads(self.step(record, "拆句", command).strip().splitlines()[-1])

    def stage_l1_anchor(self, record: dict) -> str:
        if not (self.source_run(record) / "layer1" / "candidate" / "anchor-manifest.json").is_file():
            self.worker(record, "拆句", "按词时间切成句子")
            self.build_candidate(record)
        return "done"

    def stage_l1_rows(self, record: dict) -> str:
        run = self.source_run(record)
        candidate, out = run / "layer1" / "candidate", run / "review" / "english"
        self.worker(record, "准备英文审核页", "切每句的原声")
        command = [self.python, str(EXP / "l1_review_rows.py"), "--manifest", str(candidate / "anchor-manifest.json"),
                   "--audio", str(run / "source" / "source.wav"), "--out", str(out), "--file-name", record["source"]["name"],
                   "--crosscheck", str(candidate / "english-crosscheck.json"), "--fixes-applied", str(candidate / "english-fixes-applied.json")]
        self.step(record, "英文审核数据", command)
        return "done"

    def stage_gate_english(self, record: dict) -> str:
        run = self.source_run(record)
        manifest = read_json(run / "layer1" / "candidate" / "anchor-manifest.json")
        data = read_json(run / "review" / "english" / "rows.json")
        flagged = sum(1 for row in data["rows"] if row["flags"])
        gate = self.store.open_gate(record["production"], gate_id="l1.english-review", kind="english", title="英文表批准",
                                    bindings={"anchorManifestJsonSha256": json_sha(manifest), "sourceMediaSha256": record["source"]["sha256"]},
                                    data=data, assets_root=run / "review" / "english", summary=f"{len(data['rows'])} 句 · {flagged} 句有标记")
        self.notice(record, "gate.opened", kind="english", gate_id="l1.english-review", revision=gate["revision"],
                    units=len(data["rows"]), flagged=flagged, minutes=max(10, min(30, round(flagged * 0.3))))
        self.worker(record, "等你审核", "开工确认和英文表", state="等待")
        return "done"

    def stage_wait_review(self, record: dict) -> str:
        states = {gate["gateId"]: gate for gate in self.store.gates(record["production"])}
        waiting = [gate for gate in states.values() if gate["state"] != "applied"]
        if not waiting:
            return "done"
        now = dt.datetime.now(dt.timezone.utc)
        for gate in waiting:
            if gate["state"] != "open" or not gate.get("openedAt"):
                continue
            opened = dt.datetime.fromisoformat(gate["openedAt"])
            sent = record.setdefault("reminders", {}).get(gate["gateId"], 0)
            if notices.reminder_due(gate["kind"], opened, now, sent):
                waited = int((now - opened).total_seconds() // 60)
                self.notice(record, "gate.reminder", kind=gate["kind"], gate_id=gate["gateId"], once=f"reminder:{gate['gateId']}:{gate['revision']}",
                            waited=f"{waited} 分钟" if waited < 120 else f"{waited // 60} 小时")
                record["reminders"][gate["gateId"]] = sent + 1
        reworking = [gate["title"] for gate in waiting if gate["state"] in ("changes_requested", "stale")]
        self.worker(record, "等修改后重出" if reworking and len(reworking) == len(waiting) else "等你审核",
                    "、".join(gate["title"] for gate in waiting), state="等待")
        return "waiting"

    def stage_handoff(self, record: dict) -> str:
        run = self.source_run(record)
        package = read_json(run / "layer1" / "english-source.json")
        kickoff = read_json(self.store.production_dir(record["production"]) / "kickoff.json")
        if not package or not kickoff:
            raise StageError("process", "审核已通过但缺少开工记录或英文包", stageName="交接")
        locales = kickoff["decisions"]["locales"]
        review_gates.write_json(self.store.production_dir(record["production"]) / "next-step.json", {
            "schemaVersion": "weekly-auto-next-step-v1", "rehearsal": bool(record.get("rehearsal")),
            "note": "Layer 1 完成。翻译、配音和发布还没有自动化，按 runbook 继续。" if not record.get("rehearsal") else "演练结束。这些文件没有人工批准，不能用于翻译或发布。",
            "englishSource": str((run / "layer1" / "english-source.json").relative_to(self.work_root)),
            "anchorManifest": str((run / "layer1" / "anchor-manifest.json").relative_to(self.work_root)),
            "media": str((run / "source" / "episode.mp4").relative_to(self.work_root)),
            "kickoff": kickoff["decisions"], "title": kickoff["title"],
            "sfaStart": {"locales": locales, "units": f"0:{len(package['units']) - 1}", "windowStart": 0.0,
                         "sync": kickoff["decisions"]["sync"] == "synced", "publish": kickoff["decisions"]["publish"] == "production_page"}})
        record["state"] = "rehearsal_complete" if record.get("rehearsal") else "layer1_ready"
        self.worker(record, "Layer 1 完成", "演练结束" if record.get("rehearsal") else "等待按 runbook 继续翻译", state="空闲")
        return "done"

    # ---- decisions
    def apply_decisions(self, record: dict) -> None:
        for item in self.store.pending(record["production"]):
            decision, gate_id = item["decision"], item["decision"]["gateId"]
            kind = decision["kind"]
            done = lambda outcome, **kw: self.store.record_outcome(record["production"], gate_id, item["decisionId"], outcome, **kw)
            try:
                if kind not in ("decisions", "english"):
                    raise StageError("unsupported", "这一步还没有接到自动流程")
                if decision["verdict"] == "changes_requested":
                    done("applied")
                    edits = (decision["payload"].get("edits") or {}) if kind == "english" else {}
                    count = sum(len(edits.get(name) or []) for name in ("replace", "mergeWithPrevious", "drop")) or 1
                    self.notice(record, "decision.changes_requested", kind=kind, gate_id=gate_id, once=f"changes:{item['decisionId']}", count=count)
                    continue
                receipt, following = (self.apply_kickoff if kind == "decisions" else self.apply_english)(record, item)
                done("applied", receipt_sha256=receipt, next_stage=following)
                self.notice(record, "decision.applied", kind=kind, gate_id=gate_id, once=f"applied:{item['decisionId']}", verdict="批准",
                            reviewer=item["reviewer"].get("name") or item["reviewer"]["login"], next=following)
            except StageError as exc:
                if exc.error_class == "stale":
                    done("rejected_stale", message=exc.message)
                    self.notice(record, "decision.rejected_stale", kind=kind, gate_id=gate_id, once=f"stale:{item['decisionId']}")
                else:
                    done("failed", message=exc.message)
                    self.notice(record, "decision.failed", kind=kind, gate_id=gate_id, once=f"failed:{item['decisionId']}", reason=exc.message)
            self.log(record["production"], "decision.handled", decisionId=item["decisionId"], gate=gate_id,
                     outcome=self.store.outcome(record["production"], gate_id, item["decisionId"])["outcome"])

    def apply_kickoff(self, record: dict, item: dict) -> tuple[str, str]:
        decision, source = item["decision"], record["source"]
        if decision["bindings"] != {"sourceMediaSha256": source["sha256"], "defaultsConfigSha256": sha256_file(self.config_path)}:
            raise StageError("stale", "来源文件或默认配置在提交后变了")
        payload = decision["payload"]
        chosen, window = payload["decisions"], payload["window"]
        if chosen.get("form") != "full":
            raise StageError("unsupported", "片段形态还不能自动处理，请在生产机上按 runbook 手工开工")
        if abs(window["start"]) > 0.01 or abs(window["end"] - source["durationSeconds"]) > 0.01:
            raise StageError("unsupported", "目前只能自动处理整段媒体的窗口；改了起止就要在生产机上手工处理")
        speaker = next((o for o in self.speaker_options() if o["value"] == chosen.get("speakerId")), None)
        if not speaker or any(locale not in speaker["locales"] for locale in chosen["locales"]) or not speaker["checkpointReady"]:
            raise StageError("unsupported", "所选讲员缺语言能力或声音文件没有就位")
        path = self.store.production_dir(record["production"]) / "kickoff.json"
        review_gates.write_json(path, {
            "schemaVersion": "weekly-auto-kickoff-v1", "production": record["production"], "humanApproval": not record.get("rehearsal"),
            "rehearsal": bool(record.get("rehearsal")), "decisions": chosen, "title": payload["title"], "window": window,
            "deliverables": payload["deliverables"], "changedFromDefaults": payload.get("changedFromDefaults", []),
            "sourceMediaSha256": source["sha256"], "decidedBy": item["reviewer"], "decidedAt": item["receivedAt"],
            "decisionId": item["decisionId"], "authority": self.config["authorizations"]["pageDecisions"]})
        record["episode"].update(speaker=speaker["label"], title=payload["title"]["titles"].get("zh-Hans") or record["episode"].get("title"))
        return sha256_file(path), "英文表批准"

    def apply_english(self, record: dict, item: dict) -> tuple[str, str]:
        run, decision = self.source_run(record), item["decision"]
        layer1, candidate = run / "layer1", run / "layer1" / "candidate"
        manifest = read_json(candidate / "anchor-manifest.json")
        if decision["bindings"] != {"anchorManifestJsonSha256": json_sha(manifest), "sourceMediaSha256": record["source"]["sha256"]}:
            raise StageError("stale", "句表在提交后变了")
        folder = self.store.gate_dir(record["production"], decision["gateId"])
        edits_path = folder / f"edits-{item['decisionId']}.json"
        review_gates.write_json(edits_path, decision["payload"].get("edits") or {})
        record_path = folder / "decisions" / f"{item['decisionId']}.json"
        try:
            self.step(record, "应用修改", [self.python, str(EXP / "l1_anchor.py"), "revise", "--candidate", str(candidate / "anchor-manifest.json"),
                                       "--edits", str(edits_path), "--out", str(layer1)])
            command = [self.python, str(EXP / "l1_english_source.py"), "--anchor", str(layer1 / "anchor-manifest.json"),
                       "--words", str(layer1 / "words.json"), "--raw-text", str(layer1 / "raw-gpt-4o-transcribe.txt"),
                       "--upload", str(run / "source" / "sermon-upload.mp3"), "--media", str(run / "source" / "episode.mp4"),
                       "--review-csv", str(layer1 / "english-review.csv"), "--decision", str(record_path),
                       "--authority", "config/weekly-sermon-auto.json#authorizations.pageDecisions",
                       "--root", str(self.work_root), "--out", str(layer1 / "english-source.json"),
                       "--timing-model", self.config["transcription"]["timingModel"], "--text-model", self.config["transcription"]["textModel"]]
            summary = json.loads(self.step(record, "英文来源包", command + (["--rehearsal"] if record.get("rehearsal") else [])).strip().splitlines()[-1])
        except StageError as exc:
            raise StageError("process", exc.message) from exc
        return summary["receiptSha256"], NEXT_AFTER_ENGLISH if not record.get("rehearsal") else "演练到此结束"

    # ---- the loop
    def advance(self, production: str, *, retry: bool = False) -> dict:
        folder = self.store.production_dir(production)
        with open(folder / "driver.lock", "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return self.store.production(production)          # another run of the driver has it
            record = self.store.production(production)
            self.flush_outbox(record)
            self.apply_decisions(record)
            for stage in STAGES:
                state = record["stages"].get(stage, {})
                if state.get("state") == "done":
                    continue
                if state.get("state") == "failed" and not retry:
                    break
                retry = False                                       # a retry covers the one failed stage
                record["stages"][stage] = {"state": "running", "startedAt": review_gates.now_iso()}
                self.save(record)
                try:
                    result = getattr(self, "stage_" + stage.replace(".", "_").replace("-", "_"))(record)
                except StageError as exc:
                    record["stages"][stage] = {"state": "failed", "at": review_gates.now_iso(), "errorClass": exc.error_class, "message": exc.message}
                    record["state"] = "blocked"
                    self.worker(record, stage, exc.message, state="停下了")
                    fields = {"stageName": stage, "errorClass": exc.error_class, "message": exc.message, **exc.fields}
                    fields = {name: value for name, value in fields.items() if "{" + name + "}" in "".join(filter(None, notices.EVENTS[exc.event][3:5]))}
                    self.notice(record, exc.event, once=f"{exc.event}:{stage}:{record['stages'][stage]['at']}", **fields)
                    break
                record["stages"][stage] = {"state": "done" if result == "done" else "waiting", "at": review_gates.now_iso()}
                if record.get("state") == "blocked":
                    record["state"] = "running"
                self.save(record)
                self.log(production, "stage", stage=stage, result=result)
                if result != "done":
                    break
            self.save(record)
            return record


# ---------------------------------------------------------------- commands

def load_trigger(args) -> dict:
    if args.trigger:
        return json.loads(Path(args.trigger).read_text(encoding="utf-8"))
    raise SystemExit("start needs --trigger")


def status_of(record: dict) -> dict:
    return {"production": record["production"], "state": record.get("state"), "rehearsal": record.get("rehearsal"),
            "worker": record.get("worker"), "stages": {name: state.get("state") for name, state in record.get("stages", {}).items()},
            "failed": {name: state.get("message") for name, state in record.get("stages", {}).items() if state.get("state") == "failed"}}


def cmd_pending(driver: Driver, args) -> int:
    known = {driver.store.production(name)["trigger"]["file"]["id"]: name for name in driver.store.productions()}
    triggers = sorted(Path(args.triggers).glob("*.json")) if Path(args.triggers).is_dir() else []
    for path in triggers:
        trigger = json.loads(path.read_text(encoding="utf-8"))
        if trigger.get("schemaVersion") == "sermon-drive-upload-trigger-v1" and trigger["file"]["id"] not in known:
            record = driver.start(trigger)
            known[trigger["file"]["id"]] = record["production"]
    for name in driver.store.productions():
        record = driver.store.production(name)
        if record.get("state") in ("running", "blocked"):
            print(json.dumps(status_of(driver.advance(name)), ensure_ascii=False))
    return 0


def agent_plists(work_root: Path, port: int, python: str, allow_host: str | None = None) -> dict[str, dict]:
    common = {"RunAtLoad": True, "EnvironmentVariables": {"PATH": AGENT_PATH}, "WorkingDirectory": str(ROOT)}
    here = Path(__file__).resolve().parent
    return {
        LABEL_REVIEW: {**common, "Label": LABEL_REVIEW, "KeepAlive": True,
                       "ProgramArguments": [python, str(here / "review_gate_server.py"), "serve", "--work-root", str(work_root), "--port", str(port),
                                            *(["--allow-host", allow_host] if allow_host else [])],
                       "StandardOutPath": str(SUPPORT / "review.log"), "StandardErrorPath": str(SUPPORT / "review.log")},
        LABEL_DRIVER: {**common, "Label": LABEL_DRIVER, "WatchPaths": [str(TRIGGERS)], "StartInterval": 300,
                       "ProgramArguments": ["/usr/bin/caffeinate", "-i", python, str(here / "weekly_auto.py"), "--work-root", str(work_root), "pending"],
                       "StandardOutPath": str(SUPPORT / "driver.log"), "StandardErrorPath": str(SUPPORT / "driver.log")},
    }


def cmd_agents(driver: Driver, args) -> int:
    port = args.port or driver.local.get("port") or driver.config["review"]["port"]
    # The tailnet name is read here, by the person installing, and written into this Mac's own files:
    # a LaunchAgent cannot always ask Tailscale for it at start.
    host = tailnet_name() or driver.local.get("reviewHost")
    plists = agent_plists(driver.work_root, port, driver.python, host)
    domain = f"gui/{os.getuid()}"
    launch = lambda *a: subprocess.run(["/bin/launchctl", *a], capture_output=True, text=True, check=False)
    folder = Path.home() / "Library" / "LaunchAgents"
    if args.action == "print":
        print(json.dumps(plists, ensure_ascii=False, indent=1))
    elif args.action == "install":
        SUPPORT.mkdir(parents=True, exist_ok=True)
        TRIGGERS.mkdir(parents=True, exist_ok=True)
        driver.local = {**driver.local, "workRoot": str(driver.work_root), "port": port, "python": driver.python,
                        **({"reviewHost": host, "reviewBaseUrl": f"https://{host}:{port}"} if host else {})}
        review_gates.write_json(SUPPORT / "local.json", driver.local)
        for label, plist in plists.items():
            path = folder / f"{label}.plist"
            path.write_bytes(plistlib.dumps(plist))
            launch("bootout", f"{domain}/{label}")
            result = launch("bootstrap", domain, str(path))
            if result.returncode != 0:
                print(result.stderr.strip(), file=sys.stderr)
                return 1
        print(json.dumps({"installed": sorted(plists), "port": port, "workRoot": str(driver.work_root), "reviewUrl": driver.review_base(),
                          "tailscaleServe": f"tailscale serve --bg --https={port} http://127.0.0.1:{port}"}, ensure_ascii=False, indent=1))
    elif args.action == "uninstall":
        for label in plists:
            launch("bootout", f"{domain}/{label}")
            (folder / f"{label}.plist").unlink(missing_ok=True)
        print(json.dumps({"removed": sorted(plists)}))
    else:
        out = {}
        for label in plists:
            text = launch("print", f"{domain}/{label}").stdout
            state = re.search(r"^\s*state = (.+)$", text, re.M)
            out[label] = {"loaded": bool(text), "state": state.group(1) if state else None}
        print(json.dumps({"agents": out, "local": driver.local, "reviewUrl": driver.review_base()}, ensure_ascii=False, indent=1))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--work-root", type=Path, help="the checkout whose artifacts/ holds the productions (default: local.json, else this checkout)")
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--no-push", action="store_true", help="print notices instead of sending them")
    commands = parser.add_subparsers(dest="command", required=True)
    pending = commands.add_parser("pending", help="start new triggers and move every unfinished production on")
    pending.add_argument("--triggers", type=Path, default=TRIGGERS)
    start = commands.add_parser("start", help="start a production from one trigger file")
    start.add_argument("--trigger", type=Path)
    start.add_argument("--rehearsal", action="store_true", help="write everything, approve nothing")
    start.add_argument("--production")
    start.add_argument("--no-run", action="store_true")
    run = commands.add_parser("run", help="move one production on")
    run.add_argument("--production", required=True)
    run.add_argument("--retry", action="store_true", help="retry the stage that failed, once")
    apply = commands.add_parser("apply", help="apply stored decisions, then move on (what the review service calls)")
    apply.add_argument("--production", required=True)
    status = commands.add_parser("status")
    status.add_argument("--production")
    reconcile = commands.add_parser("reconcile", help="settle a paid request whose result was unknown")
    reconcile.add_argument("--production", required=True)
    reconcile.add_argument("--outcome", choices=("charged", "not_charged"), required=True)
    rebuild = commands.add_parser("rebuild-english", help="rebuild the sentence table (with machine fixes) and reopen its review")
    rebuild.add_argument("--production", required=True)
    rebuild.add_argument("--fixes", type=Path, help="machine fixes: global / text / merge / drop")
    agents = commands.add_parser("agents", help="the two LaunchAgents: review service and driver")
    agents.add_argument("action", choices=("print", "install", "uninstall", "status"))
    agents.add_argument("--port", type=int)
    commands.add_parser("url", help="print the address of the review pages")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    local = read_json(SUPPORT / "local.json", {})
    driver = Driver(args.work_root or local.get("workRoot") or ROOT, config_path=args.config, push=not args.no_push, local=local)
    if args.command == "pending":
        return cmd_pending(driver, args)
    if args.command == "agents":
        return cmd_agents(driver, args)
    if args.command == "url":
        print(driver.review_base() or "")
        return 0 if driver.review_base() else 1
    if args.command == "status":
        names = [args.production] if args.production else driver.store.productions()
        print(json.dumps([status_of(driver.store.production(name)) for name in names], ensure_ascii=False, indent=1))
        return 0
    if args.command == "start":
        record = driver.start(load_trigger(args), rehearsal=args.rehearsal, production=args.production)
        if not args.no_run:
            record = driver.advance(record["production"])
    elif args.command in ("run", "apply"):
        record = driver.advance(args.production, retry=getattr(args, "retry", False))
    elif args.command == "reconcile":
        record = driver.store.production(args.production)
        budget = driver.budget(record)
        for entry in budget.unknown():
            if entry["production"] == args.production:
                budget.close(entry["id"], "settled" if args.outcome == "charged" else "released",
                             entry["reservedUsd"] if args.outcome == "charged" else None)
        driver.log(args.production, "budget.reconciled", outcome=args.outcome)
    else:  # rebuild-english
        record = driver.store.production(args.production)
        layer1 = driver.source_run(record) / "layer1"
        if args.fixes:
            shutil.copyfile(args.fixes, layer1 / "english-fixes.json")
        shutil.rmtree(layer1 / "candidate", ignore_errors=True)
        for stage in ("l1.anchor", "l1.rows", "gate.english", "wait.review", "handoff"):
            record["stages"].pop(stage, None)
        driver.save(record)
        record = driver.advance(args.production)
    print(json.dumps(status_of(record), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
