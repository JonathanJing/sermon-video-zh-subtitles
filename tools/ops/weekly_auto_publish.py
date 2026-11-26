#!/usr/bin/env python3
"""What tools/ops/weekly_auto.py needs to know about a page: its identity, its configuration for
experiments/sentence-first-agent/sfa_publish.py, and how the title table's scripture is written per language.

Nothing here deploys or decides anything. The page configuration is built only from decisions the
reviewer already made on the kickoff page (languages, title format, speaker) and from the title table.
"""
from __future__ import annotations

import re

LOCALES = ("zh-Hans", "ko", "es")
# The title table writes scripture the short Chinese way (启 21:9–21). A page shows the full book name per language.
_SHORT = ("创 出 利 民 申 书 士 得 撒上 撒下 王上 王下 代上 代下 拉 尼 斯 伯 诗 箴 传 歌 赛 耶 哀 结 但 何 珥 摩 俄 拿 弥 鸿 哈 番 该 亚 玛 "
          "太 可 路 约 徒 罗 林前 林后 加 弗 腓 西 帖前 帖后 提前 提后 多 门 来 雅 彼前 彼后 约一 约二 约三 犹 启").split()
_ZH = ("创世记 出埃及记 利未记 民数记 申命记 约书亚记 士师记 路得记 撒母耳记上 撒母耳记下 列王纪上 列王纪下 历代志上 历代志下 以斯拉记 尼希米记 "
       "以斯帖记 约伯记 诗篇 箴言 传道书 雅歌 以赛亚书 耶利米书 耶利米哀歌 以西结书 但以理书 何西阿书 约珥书 阿摩司书 俄巴底亚书 约拿书 弥迦书 "
       "那鸿书 哈巴谷书 西番雅书 哈该书 撒迦利亚书 玛拉基书 马太福音 马可福音 路加福音 约翰福音 使徒行传 罗马书 哥林多前书 哥林多后书 加拉太书 "
       "以弗所书 腓立比书 歌罗西书 帖撒罗尼迦前书 帖撒罗尼迦后书 提摩太前书 提摩太后书 提多书 腓利门书 希伯来书 雅各书 彼得前书 彼得后书 "
       "约翰一书 约翰二书 约翰三书 犹大书 启示录").split()
_KO = ("창세기 출애굽기 레위기 민수기 신명기 여호수아 사사기 룻기 사무엘상 사무엘하 열왕기상 열왕기하 역대상 역대하 에스라 느헤미야 에스더 욥기 시편 잠언 "
       "전도서 아가 이사야 예레미야 예레미야애가 에스겔 다니엘 호세아 요엘 아모스 오바댜 요나 미가 나훔 하박국 스바냐 학개 스가랴 말라기 마태복음 마가복음 "
       "누가복음 요한복음 사도행전 로마서 고린도전서 고린도후서 갈라디아서 에베소서 빌립보서 골로새서 데살로니가전서 데살로니가후서 디모데전서 디모데후서 "
       "디도서 빌레몬서 히브리서 야고보서 베드로전서 베드로후서 요한일서 요한이서 요한삼서 유다서 요한계시록").split()
_ES = ("Génesis|Éxodo|Levítico|Números|Deuteronomio|Josué|Jueces|Rut|1 Samuel|2 Samuel|1 Reyes|2 Reyes|1 Crónicas|2 Crónicas|Esdras|Nehemías|"
       "Ester|Job|Salmos|Proverbios|Eclesiastés|Cantares|Isaías|Jeremías|Lamentaciones|Ezequiel|Daniel|Oseas|Joel|Amós|Abdías|Jonás|Miqueas|"
       "Nahúm|Habacuc|Sofonías|Hageo|Zacarías|Malaquías|Mateo|Marcos|Lucas|Juan|Hechos|Romanos|1 Corintios|2 Corintios|Gálatas|Efesios|"
       "Filipenses|Colosenses|1 Tesalonicenses|2 Tesalonicenses|1 Timoteo|2 Timoteo|Tito|Filemón|Hebreos|Santiago|1 Pedro|2 Pedro|1 Juan|"
       "2 Juan|3 Juan|Judas|Apocalipsis").split("|")
BOOKS = {short: {"zh-Hans": zh, "ko": ko, "es": es} for short, zh, ko, es in zip(_SHORT, _ZH, _KO, _ES, strict=True)}

CATEGORY = {"schemaVersion": "sermon-page-display-category-v1",
            "labels": {"zh-Hans": "周日证道", "en": "Sunday sermon", "ko": "주일 설교", "es": "Sermón del domingo"}}
# The wording the published Sunday pages carry (pages/revelation-*.json). "已人工审核" is true of a page built
# here only because sfa_publish.py refuses a verdict that is not an approved human one.
FIXED_META = {
    "zh-Hans": {"badge": "周日证道 · AI 合成配音 · 已人工审核", "source": "英文来源 / English source",
                "note": "AI 合成配音，与原视频同步。本项目与 Mariners Church 无隶属关系。"},
    "ko": {"badge": "주일 설교 · AI 합성 음성 · 검토 완료", "source": "영어 원본 / English source",
           "note": "AI 합성 음성 더빙으로 원본 영상과 동기화됩니다. 이 프로젝트는 Mariners Church와 관련이 없습니다."},
    "es": {"badge": "Sermón del domingo · Voz sintetizada por IA · Revisado", "source": "Fuente en inglés / English source",
           "note": "Doblaje con voz sintetizada por IA, sincronizado con el video original. Este proyecto no está afiliado con Mariners Church."},
}
INDEPENDENT_NOTE = {"zh-Hans": "AI 合成配音，独立音轨，不与原视频同步。本项目与 Mariners Church 无隶属关系。",
                    "ko": "AI 합성 음성 더빙으로 원본 영상과 동기화되지 않는 독립 음성입니다. 이 프로젝트는 Mariners Church와 관련이 없습니다.",
                    "es": "Doblaje con voz sintetizada por IA, pista independiente no sincronizada con el video original. Este proyecto no está afiliado con Mariners Church."}


class PageError(ValueError):
    """Something a page needs is not known; the message says what a person has to supply."""


def scripture_names(short: str | None) -> dict:
    """`启 21:9–21` as each language writes it. Chinese keeps the en dash, Korean and Spanish use a hyphen."""
    match = re.fullmatch(r"\s*(\S+?)\s+(\d.*?)\s*", short or "")
    if not match or match.group(1) not in BOOKS:
        raise PageError(f"标题表里的经文「{short or ''}」认不出书卷，页面的经文一栏写不出来")
    book, rest = BOOKS[match.group(1)], match.group(2)
    return {"zh-Hans": f"{book['zh-Hans']} {rest}", "ko": f"{book['ko']} {rest.replace('–', '-')}", "es": f"{book['es']} {rest.replace('–', '-')}"}


def page_id(series_key: str | None, english_title: str, sunday: str) -> str:
    """`revelation-jesus-will-return-20261122`: the first word of the series key, the English title, the Sunday."""
    words = re.findall(r"[a-z0-9]+", (english_title or "").lower())
    if not words or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", sunday or ""):
        raise PageError("页面编号要有英文讲题和主日日期")
    prefix = re.findall(r"[a-z0-9]+", (series_key or "sermon").lower())[0]
    return "-".join([prefix, *words])[:70].rstrip("-") + "-" + sunday.replace("-", "")


def title_section(table_text: str, english_title: str) -> dict | None:
    """The series (key and Chinese name) whose table lists this English title."""
    current = None
    for line in table_text.splitlines():
        heading = re.match(r"##\s+(.+?)（`([a-z0-9][a-z0-9-]*)`）\s*$", line.strip())
        if heading:
            current = {"zhName": heading.group(1).strip(), "key": heading.group(2)}
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if current and line.strip().startswith("|") and len(cells) == 8 and cells[0].isdigit() and cells[2].lower() == (english_title or "").lower():
            return {**current, "week": int(cells[0]), "scripture": cells[3]}
    return None


def page_config(*, production: str, environment: str, kickoff: dict, section: dict, series: dict, speaker: str, sunday: str,
                source_url: str, window_end: float, sentences: int, reviewer: str, basis: str) -> dict:
    """The page configuration sfa_publish.py reads. Paths are relative to the checkout, as that driver expects."""
    locales = [locale for locale in LOCALES if locale in kickoff["decisions"]["locales"]]
    titles, english = kickoff["title"]["titles"], kickoff["title"].get("english")
    missing = [locale for locale in locales if not (titles.get(locale) or "").strip() or not (series.get(locale) or "").strip()]
    if missing or not english:
        raise PageError(f"页面缺标题或系列名：{'、'.join(missing) or '英文讲题'}。先在标题表登记这一周")
    scripture = scripture_names(section.get("scripture"))
    series_first = kickoff["title"].get("format") == "series_dot_title"
    shown = {locale: f"{series[locale]} · {titles[locale]}" if series_first else titles[locale] for locale in locales}
    synced = kickoff["decisions"]["sync"] == "synced"
    runs = "artifacts/sentence-first-agent"
    suffix = {"zh-Hans": "zh", "ko": "ko", "es": "es"}
    check = {"englishTitle": english, "seriesKey": section["key"], "mode": "table"}
    if not series_first:                                    # the table's rule is "series · title": showing the title alone is the reviewer's decision
        check.update(mode="approved_exception", publishedTitles=shown, approvedBy=reviewer,
                     reason=f"开工确认页选择主标题只显示本篇讲题（决定 {kickoff['decisionId']}）；三语讲题取自标题表第 {section['week']} 周")
    return {
        "schemaVersion": "sentence-first-page-config-v1", "pageId": page_id(section["key"], english, sunday), "environment": environment,
        "locales": locales, "defaultTargetLocale": locales[0], "runsRoot": runs,
        "runs": {locale: f"{production}-{suffix[locale]}" for locale in locales},
        "source": {"url": source_url, "date": sunday, "window": {"start": 0.0, "end": window_end},
                   "englishSource": f"{runs}/{production}-source/layer1/english-source.json"},
        "sentences": sentences, "speakers": speaker, "category": CATEGORY, "title": shown[locales[0]],
        "meta": {locale: {"title": shown[locale], "series": series[locale], "scripture": scripture[locale], **FIXED_META[locale],
                          **({} if synced else {"note": INDEPENDENT_NOTE[locale]})} for locale in locales},
        "verdict": f"{runs}/{production}-review/human-review-verdict.json",
        "candidate": {"schemaVersion": "sentence-first-episode-candidate-v1", "translationBasis": {"default": "{locale}: " + basis}},
        "audioPackage": {"schemaVersion": "sentence-first-episode-audio-package-v1", "voices": "from-speakers",
                         "synchronization": ("unit audio placed on the English source start times (gap 0.05 s); sync gate max lag <= 8 s" if synced
                                             else "independent track at natural speech rate; not synchronized with the source video")},
        "releasePackageId": "{pageId}-{locale}-{environment}-v1",
        "verify": {"schemaVersion": "sentence-first-episode-http-verification-v1"},
        "englishReference": {"mode": "full"}, "summary": {"includeEnvironment": True}, "baseline": {"allowDefaultLocaleDrift": True},
        "mediaType": "podcast", "titleCheck": check,
    }


# ---------------------------------------------------------------- the driver's Layer 4 stages

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "experiments" / "sentence-first-agent"
PUBLISH_STAGES = ("l4.config", "l4.preflight", "l4.assets", "l4.fingerprint", "l4.stage1", "gate.publish", "wait.publish",
                  "l4.deploy1", "l4.verify", "l4.stage2", "l4.deploy2", "l4.readback", "l4.gate", "gate.confirm", "wait.confirm")
ENVIRONMENT = {"production_page": "production", "dev_review": "dev"}
# What the kickoff page lists (weekly_auto.DELIVERABLES, by number) and where each one stands in this driver.
NOT_AUTOMATED = {6: "研读手册条目还没有接到自动流程，发布后按 runbook 10.7 手工补",
                 7: "统计目录还没有接到自动流程，发布后按 runbook 10.7 手工补（补之前本页的赞踩和收听统计不可用）"}
EVIDENCE = {1: "资产目录 + 逐文件 HTTP 核对 SHA", 2: "资产目录里的 release 模板，第二次部署时定稿", 3: "第二份快照 + 回读线上目录",
            4: "随第二次部署上线 + 回读", 5: "/alignment/<pageId>.json + 门禁 --require-alignment",
            6: "candidate 快照 + 门禁 --require-guide", 7: "函数更新时间 + 三语 /api/session 200"}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _read(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    temporary.replace(path)


class PublishStages:
    """Mixed into weekly_auto.Driver. The page goes out in two deployments, both listed on the publish
    authorization page and neither made before the reviewer has authorized them there:

      1. the page, transcript, captions and audio of each language;
      2. the releases, the shared catalogs, the English reference and the live-audio alignment.

    Everything before the first deployment only writes local files. A deployment is never made twice:
    a snapshot that already has a deployment attempt is left for a person to reconcile."""

    Error: type                                              # weekly_auto.StageError, set on the Driver

    # ---- where things are
    def publish_dir(self, record: dict) -> Path:
        return self.work_root / "artifacts" / "sentence-first-agent" / f"{record['production']}-publish"

    def page(self, record: dict) -> dict:
        return _read(self.publish_dir(record) / "page-config.json")

    def delivers(self, record: dict, n: int) -> bool:
        chosen = {item["n"]: item for item in self.kickoff(record).get("deliverables") or []}
        return n not in NOT_AUTOMATED and bool((chosen.get(n) or {"deliver": True}).get("deliver"))

    def aligns(self, record: dict) -> bool:
        """Live-audio alignment needs a dub on the source clock and a window that starts at zero (both are what this driver makes)."""
        return self.delivers(record, 5) and self.synced(record)

    def sfa_publish(self, record: dict, name: str, *args, env: dict | None = None) -> dict:
        out = self.step(record, name, [self.python, EXP / "sfa_publish.py", "--config", self.publish_dir(record) / "page-config.json", *args],
                        cwd=self.work_root, env=env)
        return json.loads(out.strip().splitlines()[-1])

    def intent(self, record: dict, **changes) -> dict:
        path = self.publish_dir(record) / "publish-intent.json"
        value = {**(_read(path) or {}), **changes}
        _write(path, value)
        return value

    # ---- before anything is deployed
    def stage_l4_config(self, record: dict) -> str:
        folder = self.publish_dir(record)
        if (folder / "page-config.json").is_file():
            return "done"
        kickoff = self.kickoff(record)
        table = (ROOT / self.config["defaults"]["titleTable"]).read_text(encoding="utf-8")
        section = title_section(table, kickoff["title"].get("english") or "")
        if section is None:
            raise self.Error("unsupported", "标题表里找不到这一篇的英文讲题，页面的系列名和经文写不出来；先在标题表登记这一周", stageName="页面配置")
        package = _read(self.source_run(record) / "layer1" / "english-source.json")
        decided = kickoff.get("decidedBy") or {}
        try:
            config = page_config(
                production=record["production"], environment=ENVIRONMENT[kickoff["decisions"]["publish"]], kickoff=kickoff, section=section,
                series=self.series_names(section["zhName"]), speaker=self.speaker(record)["name"], sunday=record["sunday"],
                source_url=package["source"]["sourceUrl"], window_end=package["source"]["approvedWindow"]["end"], sentences=len(package["units"]),
                reviewer=f"{decided.get('name') or decided.get('login')} (review page, {kickoff['decidedAt']})",
                basis="Claude Code CLI Opus translation with an independent Opus audit; wording changes the track reviewer asked for are in review.json")
        except PageError as exc:
            raise self.Error("unsupported", str(exc), stageName="页面配置") from exc
        _write(folder / "page-config.json", config)
        self.intent(record, schemaVersion="weekly-auto-publish-intent-v1", id=f"{record['production']}-publish-1", pageId=config["pageId"],
                    environment=config["environment"], production=record["production"],
                    deliverables=self.deliverables(record), preparedBy="tools/ops/weekly_auto.py")
        record.setdefault("page", {}).update(pageId=config["pageId"], environment=config["environment"])
        return "done"

    def deliverables(self, record: dict) -> list[dict]:
        chosen = {item["n"]: item for item in self.kickoff(record).get("deliverables") or []}
        rows = []
        for n, label in enumerate(self.DELIVERABLE_LABELS, start=1):
            asked = (chosen.get(n) or {"deliver": True, "reason": None})
            reason = None if self.delivers(record, n) else (NOT_AUTOMATED.get(n) if asked.get("deliver") else asked.get("reason") or "开工确认时选了本轮不交付")
            if n == 5 and asked.get("deliver") and not self.synced(record):
                reason = "独立音轨不跟原视频的时间走，做不了现场对齐"
            rows.append({"n": n, "label": label, "deliver": reason is None, "state": "ready", "evidence": EVIDENCE[n], "reason": reason})
        return rows

    def stage_l4_preflight(self, record: dict) -> str:
        folder = self.publish_dir(record)
        self.worker(record, "发布预检", "页面身份、英文包批准、听审收据、标题")
        self.sfa_publish(record, "页面配置核对", "validate")
        _write(folder / "preflight.json", self.sfa_publish(record, "发布预检", "preflight"))
        return "done"

    def stage_l4_assets(self, record: dict) -> str:
        folder = self.publish_dir(record)
        if (folder / "assets.json").is_file():
            return "done"
        shutil.rmtree(folder / "assets", ignore_errors=True)     # nothing is deployed yet: a half-written directory is simply made again
        self.worker(record, "页面资产", "每种语言的页面、文稿、字幕、MP3 和 release 模板")
        with self.heartbeat(record, "页面资产", lambda: "生成中"):
            _write(folder / "assets.json", self.sfa_publish(record, "页面资产", "assets", "--out", folder / "assets"))
        return "done"

    def stage_l4_fingerprint(self, record: dict) -> str:
        """The source landmarks once, then one index per language bound to the MP3 that will be published."""
        if not self.aligns(record):
            return "done"
        folder, page = self.publish_dir(record) / "alignment", self.page(record)
        folder.mkdir(parents=True, exist_ok=True)
        package = _read(self.source_run(record) / "layer1" / "english-source.json")
        media, media_sha = self.work_root / package["source"]["media"]["file"], package["source"]["media"]["sha256"]
        tool = ["node", ROOT / "packages" / "fingerprint" / "bin" / "build_fingerprint_index.mjs"]
        window = ["--source-sha", media_sha, "--start", "0", "--end", repr(float(page["source"]["window"]["end"]))]

        def made(receipt: Path, output: Path, name: str, *args) -> dict:
            """The tool refuses an existing output; its own stdout line is kept as the receipt of a finished one."""
            done = _read(receipt)
            if done and output.is_file() and _sha(output) == done["sha256"]:
                return done
            output.unlink(missing_ok=True)
            done = json.loads(self.step(record, name, [*tool, *args, *window, "--out", output], cwd=self.work_root).strip().splitlines()[-1])
            _write(receipt, done)
            return done

        self.worker(record, "现场对齐指纹", "原视频的声音指纹")
        source = made(folder / "source-landmarks.receipt.json", folder / "source-landmarks.json", "原声指纹", "--mode", "precompute", "--source", media)
        for locale in page["locales"]:
            made(folder / f"index-{locale}.receipt.json", folder / f"index-{locale}.json", f"指纹绑定 {locale}", "--mode", "bind",
                 "--precomputed", folder / "source-landmarks.json", "--precomputed-sha", source["sha256"],
                 "--track", self.publish_dir(record) / "assets" / "public" / "media" / page["pageId"] / f"{locale}.mp3", "--page-id", page["pageId"])
        return "done"

    def stage_l4_stage1(self, record: dict) -> str:
        folder = self.publish_dir(record)
        if (folder / "stage1.json").is_file():
            return "done"
        for name in ("baseline", "stage1"):
            shutil.rmtree(folder / name, ignore_errors=True)
        self.worker(record, "第一份快照", "取线上现状，叠上本页的资产")
        with self.heartbeat(record, "第一份快照", lambda: "取线上现状并核对"):
            self.sfa_publish(record, "线上现状", "baseline", "--out", folder / "baseline")
            staged = self.sfa_publish(record, "第一份快照", "stage1", "--baseline", folder / "baseline", "--assets", folder / "assets", "--out", folder / "stage1")
            check = self.sfa_publish(record, "部署前核对 1", "publish-check", "--snapshot", folder / "stage1", "--assets", folder / "assets", "--baseline", folder / "baseline")
        _write(folder / "stage1.json", {"staged": staged, "publishCheck": check, "sealSha256": _sha(folder / "stage1" / "seal-report.json")})
        return "done"

    # ---- the authorization
    def publish_bindings(self, record: dict) -> dict:
        folder, page = self.publish_dir(record), self.page(record)
        verdict = self.work_root / page["verdict"]
        return {"publishIntentId": _read(folder / "publish-intent.json")["id"], "stage1SealSha256": _sha(folder / "stage1" / "seal-report.json"),
                **{f"release.{locale}": _sha(folder / "assets" / "releases" / f"{locale}.json") for locale in page["locales"]},
                "humanReviewVerdictSha256": _sha(verdict)}

    def planned_deployments(self, record: dict) -> list[dict]:
        page = self.page(record)
        pid, count = page["pageId"], len(page["locales"])
        second = [f"{count} 种语言的 release", "multilingual-v5/v4/v3 目录", f"/english-reference/{pid}.json"]
        if self.aligns(record):
            second += [f"/alignment/{pid}.json", f"{count} 个声音指纹索引"]
        return [
            {"n": 1, "label": "页面与各语言资产", "changes": [f"/pages/{pid}/…", f"/content/{pid}/…", f"/captions/{pid}/…", f"{count} 种语言的 MP3"],
             "touchesOtherPages": False, "otherPagesNote": None, "verify": "逐文件 HTTP 核对 SHA，MP3 支持按范围请求"},
            {"n": 2, "label": "release、目录、英文对照" + ("、现场对齐" if self.aligns(record) else ""), "changes": second, "touchesOtherPages": True,
             "otherPagesNote": "目录是所有页面共用的：这次把本页加进目录，默认打开的页面按规则取日期最新的一篇证道。其他页面自己的条目不变，生成快照时由机器逐页核对。",
             "verify": "回读线上目录、release 和英文对照，再过发布完整性门禁"}]

    def stage_gate_publish(self, record: dict) -> str:
        folder, page = self.publish_dir(record), self.page(record)
        preflight, intent = _read(folder / "preflight.json"), _read(folder / "publish-intent.json")
        reviews = {locale: _read(self.store.production_dir(record["production"]) / "reviews" / f"{locale}.json") for locale in page["locales"]}
        mode = {"whole_track": "整轨", "flagged_only": "只听标记", "partial": "不完整"}
        names = self.LOCALE_NAMES
        title = preflight["titleCheck"]
        data = {
            "intent": {"id": intent["id"], "pageId": page["pageId"], "environment": page["environment"], "origin": preflight["origin"],
                       "kindLabel": "首次发布", "preparedAt": self.now()},
            "page": {"date": page["source"]["date"], "speaker": page["speakers"], "reviewLabel": "AI 合成配音 · 已人工审核（human_reviewed）",
                     "titleCheck": {"mode": title["mode"], "ok": True,
                                    "detail": "三语标题与标题表一致" if title["mode"] == "table" else "主标题只显示本篇讲题（开工确认时的选择）；三语讲题与标题表一致"},
                     "locales": [{"locale": locale, "category": page["category"]["labels"].get(locale), **{key: page["meta"][locale][key] for key in ("title", "series", "scripture", "badge", "note")},
                                  "url": f"{preflight['origin']}/pages/{page['pageId']}/{locale}/index.html"} for locale in page["locales"]]},
            "preconditions": [
                {"key": "english", "label": "英文来源包已人工批准", "ok": True, "detail": "机器核对：发布预检读了英文包和它的批准收据"},
                {"key": "reviews", "label": "各语言听审收据为通过，音轨哈希与当前文件一致", "ok": True,
                 "detail": "机器核对：" + "、".join(f"{names.get(locale, locale)}{mode.get(reviews[locale]['reviewMode'], reviews[locale]['reviewMode'])}" for locale in page["locales"])},
                {"key": "study", "label": "学习内容", "ok": None, "detail": "本轮页面不带大纲与默想"},
                {"key": "preflight", "label": "发布预检通过", "ok": True, "detail": "机器核对：标题、开工决定、各语言的预检记录"
                 + (f"；提示 {len(preflight['warnings'])} 条" if preflight.get("warnings") else "")},
                {"key": "publishCheck", "label": "第一次部署前的哈希核对通过", "ok": True, "detail": "机器核对：快照里的资产与 release 模板一致，目录里还没有本页"},
                {"key": "devGate", "label": "候选快照先在 dev 过门禁", "ok": None, "detail": "没有做：上线后在目标站点过发布完整性门禁，不过就停下并通知"},
                {"key": "concurrency", "label": "同一页面没有其他代理在改", "ok": None, "detail": "没有机器核对；线上现状在取快照之后如果变了，部署会被拒绝"}],
            "deliverables": intent["deliverables"],
            "deployments": self.planned_deployments(record),
            "afterPublish": ["回读线上文件，再过发布完整性门禁；不过就停下并通知你", "推送「发布后确认」请你在手机上看",
                             "导出运行报告（公开仍是单独一步）"]
                            + [f"{row['n']}. {row['label']}：{row['reason']}" for row in intent["deliverables"] if row["n"] in NOT_AUTOMATED]}
        gate = self.store.open_gate(record["production"], gate_id="l4.publish.authorization", kind="publish", title="发布授权",
                                    bindings=self.publish_bindings(record), data=data,
                                    summary=f"{page['pageId']} · {page['environment']} · {len(data['deployments'])} 次部署")
        self.notice(record, "gate.opened", kind="publish", gate_id="l4.publish.authorization", revision=gate["revision"],
                    pageId=page["pageId"], deployments=len(data["deployments"]))
        return "done"

    def stage_wait_publish(self, record: dict) -> str:
        return self.wait_for(record, ["l4.publish.authorization"])

    def apply_publish(self, record: dict, item: dict) -> tuple[str, str]:
        decision, folder = item["decision"], self.publish_dir(record)
        if decision["bindings"] != self.publish_bindings(record):
            raise self.Error("stale", "准备好的快照、release 或听审结论在提交后变了")
        planned = [row["n"] for row in self.planned_deployments(record)]
        payload = decision["payload"]
        if sorted(payload.get("authorizedDeployments") or []) != planned or payload.get("pageId") != self.page(record)["pageId"]:
            raise self.Error("unsupported", "授权里列的部署和准备好的不一致")
        path = self.store.production_dir(record["production"]) / "publish-authorization.json"
        _write(path, {"schemaVersion": "weekly-auto-publish-authorization-v1", "intentId": payload["intentId"], "pageId": payload["pageId"],
                      "environment": payload["environment"], "authorizedDeployments": planned, "bindings": decision["bindings"],
                      "humanApproval": True, "decisionId": item["decisionId"], "authorizedBy": item["reviewer"], "authorizedAt": item["receivedAt"],
                      "authority": self.config["authorizations"]["pageDecisions"]})
        self.intent(record, authorization={"decisionId": item["decisionId"], "by": item["reviewer"], "at": item["receivedAt"], "deployments": planned})
        return _sha(path), "部署"

    # ---- the two deployments
    def deploy(self, record: dict, n: int, snapshot: Path) -> str:
        """One guarded deployment. It needs the reviewer's authorization for this number and for these files,
        and it is never repeated: an attempt that did not end as deployed is for a person to reconcile."""
        name, folder = f"第 {n} 次部署", self.publish_dir(record)
        granted = _read(self.store.production_dir(record["production"]) / "publish-authorization.json")
        if not granted or n not in granted["authorizedDeployments"] or granted["bindings"] != self.publish_bindings(record):
            raise self.Error("authorization", "没有覆盖这次部署的授权，或授权之后文件变了", stageName=name)
        attempt = _read(snapshot / "deployment-attempt-v2.json")
        if attempt and attempt.get("status") == "deployed":
            return "done"
        if attempt:
            raise self.Error("unknown_outcome", f"上一次尝试的结果是 {attempt.get('status')}：先核对线上版本，不要重试", stageName=name)
        self.worker(record, name, "带保护的发布：线上现状与取快照时不同就拒绝")
        with self.heartbeat(record, name, lambda: "上传并切换版本"):
            result = self.sfa_publish(record, name, "publish", "--snapshot", snapshot)
        deployments = (_read(folder / "publish-intent.json") or {}).get("deployments") or {}
        self.intent(record, deployments={**deployments, str(n): {**result, "snapshot": snapshot.name, "at": self.now()}})
        return "done"

    def stage_l4_deploy1(self, record: dict) -> str:
        return self.deploy(record, 1, self.publish_dir(record) / "stage1")

    def stage_l4_verify(self, record: dict) -> str:
        folder = self.publish_dir(record)
        self.worker(record, "核对线上资产", "逐文件取回并比对 SHA")
        self.sfa_publish(record, "核对线上资产", "verify", "--assets", folder / "assets", "--out", folder / "http-verification.json")
        return "done"

    def stage_l4_stage2(self, record: dict) -> str:
        folder, page = self.publish_dir(record), self.page(record)
        if (folder / "stage2.json").is_file():
            return "done"
        if (folder / "stage2" / "deployment-attempt-v2.json").is_file():
            raise self.Error("unknown_outcome", "第二份快照已经有过部署尝试：先核对线上版本", stageName="第二份快照")
        shutil.rmtree(folder / "stage2", ignore_errors=True)
        self.worker(record, "第二份快照", "release、目录、英文对照" + ("、现场对齐" if self.aligns(record) else ""))
        with self.heartbeat(record, "第二份快照", lambda: "生成并核对"):
            staged = self.sfa_publish(record, "第二份快照", "stage2", "--stage1", folder / "stage1", "--assets", folder / "assets",
                                      "--evidence", folder / "http-verification.json", "--out", folder / "stage2", "--with-english")
            if self.aligns(record):
                public = folder / "stage2" / "public"
                indexes = [part for locale in page["locales"] for part in ("--index", f"{locale}={folder / 'alignment' / f'index-{locale}.json'}")]
                self.step(record, "对齐清单", [self.python, ROOT / "tools" / "ops" / "build_alignment_sidecar.py", "--public", public,
                                             "--page-id", page["pageId"], *indexes, "--write"], cwd=self.work_root)
                self.step(record, "目录绑定对齐", [self.python, ROOT / "tools" / "ops" / "run.py", "delivery.published_alignment_catalog",
                                               "--public", public, "--page-id", page["pageId"]], cwd=self.work_root)
                # the seal lists every file and the catalog hashes: it is made again after the catalogs changed, not before
                self.step(record, "重新封存快照", [self.python, ROOT / "tools" / "ops" / "reseal_snapshot.py", "--snapshot", folder / "stage2"], cwd=self.work_root)
            check = self.sfa_publish(record, "部署前核对 2", "publish-check", "--snapshot", folder / "stage2", "--baseline", folder / "baseline",
                                     "--require-english-reference")
        _write(folder / "stage2.json", {"staged": staged, "publishCheck": check, "sealSha256": _sha(folder / "stage2" / "seal-report.json")})
        return "done"

    def stage_l4_deploy2(self, record: dict) -> str:
        return self.deploy(record, 2, self.publish_dir(record) / "stage2")

    def stage_l4_readback(self, record: dict) -> str:
        folder, page = self.publish_dir(record), self.page(record)
        self.worker(record, "回读线上", "目录、release、英文对照")
        # a passed readback also exports the run report and the reading PDF to the private stores: production pages only
        quiet = None if page["environment"] == "production" else {"SFA_RUN_REPORT": "0", "SFA_READING_PDF": "0"}
        _write(folder / "readback.json", self.sfa_publish(record, "回读线上", "readback", "--stage2", folder / "stage2", env=quiet))
        return "done"

    def stage_l4_gate(self, record: dict) -> str:
        folder, page = self.publish_dir(record), self.page(record)
        origin = _read(folder / "preflight.json")["origin"]
        command = [self.python, ROOT / "tools" / "ops" / "sfa_publish_gate.py", "--page-id", page["pageId"], "--origin", origin,
                   "--json-out", folder / "publish-gate.json", *(["--require-alignment"] if self.aligns(record) else [])]
        self.worker(record, "发布完整性门禁", "目录、release、资产、英文对照" + ("、对齐" if self.aligns(record) else ""))
        try:
            self.step(record, "发布完整性门禁", command, cwd=self.work_root)
        except self.Error as exc:
            report = _read(folder / "publish-gate.json") or {}         # absent when the gate itself broke (network, a missing file)
            failed = report.get("failed") or [check.get("check") for check in report.get("checks") or [] if check.get("required") and not check.get("ok")]
            raise self.Error("gate", f"发布完整性门禁没过：{'、'.join(failed[:6]) or exc.message}", event="publish.gate_failed",
                             pageId=page["pageId"], failed=len(failed) or 1, stageName="发布完整性门禁") from exc
        report = _read(folder / "publish-gate.json")
        if not report or report.get("status") != "pass":       # exit 0 without a passing report is not a pass
            raise self.Error("gate", "发布完整性门禁没有留下通过的结果文件", event="publish.gate_failed", pageId=page["pageId"], failed=1, stageName="发布完整性门禁")
        self.intent(record, gate={"path": "publish-gate.json", "sha256": _sha(folder / "publish-gate.json"), "status": report["status"],
                                  "checks": len(report.get("checks") or []), "at": self.now()})
        return "done"

    # ---- after it is live
    def stage_gate_confirm(self, record: dict) -> str:
        folder, page = self.publish_dir(record), self.page(record)
        intent, origin = _read(folder / "publish-intent.json"), _read(folder / "preflight.json")["origin"]
        last = intent["deployments"][str(max(int(n) for n in intent["deployments"]))]
        data = {"pageId": page["pageId"],
                "published": {"deployedAt": last["at"], "gate": "机器核对：通过（目录、release、资产、英文对照" + ("、对齐" if self.aligns(record) else "") + "）",
                              "smoke": "没有做浏览器冒烟；回读和门禁只核对文件"},
                "locales": [{"locale": locale, "url": f"{origin}/pages/{page['pageId']}/{locale}/index.html", "appUrl": None} for locale in page["locales"]],
                "items": [{"key": "plays", "label": "音频能播放", "required": True}, {"key": "captions", "label": "字幕跟着音频走", "required": True},
                          {"key": "english", "label": "英文对照显示", "required": False}, {"key": "app", "label": "App 里能看到本页", "required": False}],
                "notDelivered": [f"{row['n']}. {row['label']}：{row['reason']}" for row in intent["deliverables"] if not row["deliver"]]}
        gate = self.store.open_gate(record["production"], gate_id="l4.device-confirm", kind="confirm", title="发布后确认",
                                    bindings={"publishIntentId": intent["id"], "publishGateJsonSha256": _sha(folder / "publish-gate.json")}, data=data,
                                    summary=f"{page['pageId']} 已上线，请在手机上确认")
        self.notice(record, "gate.opened", kind="confirm", gate_id="l4.device-confirm", revision=gate["revision"], pageId=page["pageId"])
        return "done"

    def stage_wait_confirm(self, record: dict) -> str:
        return self.wait_for(record, ["l4.device-confirm"])

    def apply_confirm(self, record: dict, item: dict) -> tuple[str, str]:
        decision, folder = item["decision"], self.publish_dir(record)
        intent = _read(folder / "publish-intent.json")
        if decision["bindings"] != {"publishIntentId": intent["id"], "publishGateJsonSha256": _sha(folder / "publish-gate.json")}:
            raise self.Error("stale", "发布门禁的结果在提交后变了")
        path = self.store.production_dir(record["production"]) / "device-confirmation.json"
        _write(path, {"schemaVersion": "weekly-auto-device-confirmation-v1", "pageId": self.page(record)["pageId"], "intentId": intent["id"],
                      "humanApproval": True, "checks": decision.get("checks") or {}, "items": decision["payload"], "note": decision.get("note"),
                      "decisionId": item["decisionId"], "confirmedBy": item["reviewer"], "confirmedAt": item["receivedAt"],
                      "authority": self.config["authorizations"]["pageDecisions"],
                      "scope": "这位审核人在自己的设备上看过页面；不是现场验收，也不是 App 商店版本的验收"})
        self.intent(record, confirmation={"decisionId": item["decisionId"], "by": item["reviewer"], "at": item["receivedAt"]})
        return _sha(path), "完成"
