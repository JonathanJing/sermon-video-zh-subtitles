#!/usr/bin/env python3
"""Bounded Claude Code CLI (Opus) tasks of the sentence-first route.

    opus_tasks.py brief     --run RUN --episode EPISODE.json --out BRIEF.json
    opus_tasks.py translate --run RUN --locale L --episode EPISODE.json --brief BRIEF.json [--parts 4]
    opus_tasks.py audit     --run RUN --locale L --episode EPISODE.json --brief BRIEF.json [--apply]
    opus_tasks.py rewrite   --run RUN --locale L --mode colloquial|condense --select estimate|measured
    opus_tasks.py repair    --run RUN --locale L --issues ISSUES.json --episode EPISODE.json --brief BRIEF.json [--apply]

Every task is one or more `claude -p <prompt> --model opus --permission-mode acceptEdits` calls
(the stack in docs/sentence-first-model-stack.zh.md). A call gets one input file and writes one
output file; this script, not the model, checks the output: the ids, the order, the language,
empty targets, numbers that changed. A part that fails the check is dispatched once more and
then reported; nothing is retried without limit.

  brief      reads the English sentences and the shared terminology table and lists the names,
             terms and Bible books of this episode with their rendering per language, so the
             parallel translators agree with each other.
  translate  one sentence in, one sentence out, natural spoken wording (translate_parts.py splits
             and merges; this dispatches the parts).
  audit      an independent fidelity review of the merged translation. With --apply, high and
             medium findings become revisions in review.json and low ones become notes: the
             reviewer sees every one of them flagged on the track review page.
  rewrite    for a dubbed track that cannot keep up with the video. `colloquial` rewrites the
             selected sentences the way the preacher would say them aloud, same content;
             `condense` shortens what still does not fit, removing only repetition, filler and
             restatement. The order is fixed: colloquial first, condense only if that was not
             enough (user decision 2026-11-25; DeepSeek is not used for this).

  repair     for the sentences a track reviewer sent back. The reviewer's tags and note go to the
             model with the English, the current wording and what the voice actually read; it
             returns either a new wording or "render again" for a sentence whose text is right.
             With --apply the new wordings become revisions in review.json. The reviewer hears
             every one of them again; nothing here approves anything.

The episode file carries the facts a prompt needs: speaker, series and title per language, the
English title. The prompts and conventions are the week-11 ones with the episode-specific lists
replaced by the brief.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXP = Path(__file__).resolve().parent
TERMINOLOGY = ROOT / "docs" / "series-terminology.zh.md"
ESTABLISHED = EXP / "established-terms.json"            # renderings already used on published pages
MODEL = "opus"
DIGITS = re.compile(r"\d+")

LOCALES = {
    "zh-Hans": {
        "label": "简体中文（zh-Hans）", "language": "中文",
        "rules": ("这是主日证道（单人讲道），不是对谈。讲员是 {speaker}，面向会众口播。语气是自然、可朗读的中文口语，"
                  "不要书面化，不要补出英文没有的主语，不要用「弟兄姊妹」等英文没有的称呼加添。\n"
                  "系列名：{series}；讲员只说书卷名时译书卷名，不要说成系列全名。本篇标题：{englishTitle} = {title}。\n"
                  "经文引句用和合本措辞；和合本与英文原意有出入时以英文为准。\n"
                  "本篇的术语、人名和书卷名（必须照用）：\n{terms}\n"
                  "- 数字保留阿拉伯数字，TTS 读法后续统一处理；不要写成汉字数字。\n"
                  "- 英文是 ASR 转写，可能有口语碎片：照原意译成自然短句，不要补写成完整论述。")},
    "ko": {
        "label": "한국어（ko）", "language": "韩语",
        "rules": ("이것은 주일 설교(한 사람의 설교)입니다. 설교자는 {speaker}이고 회중에게 말합니다. "
                  "설교 낭독이므로 「~습니다/~ㅂ니다」체의 자연스러운 구어체로 옮기고, 영어에 없는 주어나 호칭을 더하지 마세요.\n"
                  "시리즈명: {series}. 화자가 성경 책 이름만 말하면 책 이름으로 옮깁니다. 이번 제목: {englishTitle} = {title}.\n"
                  "성경 인용은 개역개정 표현으로 하고, 개역개정과 영어 원문의 뜻이 다르면 영어를 따릅니다.\n"
                  "이번 설교의 용어·인명·성경 책 이름(반드시 그대로 사용):\n{terms}\n"
                  "- 숫자는 아라비아 숫자로 두고, 읽기는 TTS 단계에서 따로 처리합니다.\n"
                  "- 영어 원문은 ASR이므로 구어 조각이 있습니다. 원래 뜻대로 짧고 자연스럽게 옮기고, 완전한 문장으로 보태지 마세요.")},
    "es": {
        "label": "español（es）", "language": "西班牙语",
        "rules": ("Es un sermón dominical (una sola persona), no una conversación. Predica {speaker} ante la congregación. "
                  "Español oral, natural para doblaje; trato de «ustedes»; no añadas sujetos ni vocativos que el inglés no dice.\n"
                  "Serie: {series}. Cuando solo nombra el libro bíblico, traduce el nombre del libro. Título de este mensaje: {englishTitle} = {title}.\n"
                  "Las citas bíblicas usan el texto de Reina-Valera 1960; si difiere del sentido del inglés, sigue el inglés.\n"
                  "Términos, nombres y libros de este mensaje (úsalos tal cual):\n{terms}\n"
                  "- Conserva los números en cifras árabes; la lectura para TTS se resuelve después.\n"
                  "- El inglés es una transcripción ASR y trae fragmentos orales: tradúcelos como frases cortas naturales, sin completarlos.")},
}

BRIEF_PROMPT = """\
你在为一篇英文证道的三语翻译准备「本篇用词约定」，只做这一件事。

只读这三个文件，不要修改它们：
- 英文句表：{sentences}（每行一个 JSON，字段 `english` 是讲员的话，英文是 ASR 转写稿）
- 已发布页面用过的写法：{established}（`terms` 里的每一行是一个英文词和它的三语写法；这篇里出现了就必须照用，一个字都不要改）
- 共享术语表：{terminology}（本系列已经定下的译名，必须沿用）

本篇：讲员 {speaker}；英文标题 {englishTitle}；系列 {seriesAll}。

通读英文句表，列出**在这篇里确实出现**的三类词，并给出简体中文、韩语、西班牙语的写法：
1. names：人名、地名、机构名、品牌名。
2. terms：神学和教会用语、这篇反复出现的关键词。
3. books：提到的圣经书卷名，以及出现过的经文出处（书卷加章节）。
写法的依据依次是：已发布页面用过的写法；共享术语表；各语言通行的圣经译本（和合本、개역개정、Reina-Valera 1960）；通行译名。没有通行译名的人名、品牌保留英文原文。不要列没有出现的词，不要编造经文。

写入 {output}，内容是一个 JSON 对象，结构恰好是：
{{"names": [{{"english": "...", "zh-Hans": "...", "ko": "...", "es": "..."}}],
  "terms": [{{"english": "...", "zh-Hans": "...", "ko": "...", "es": "..."}}],
  "books": [{{"english": "...", "zh-Hans": "...", "ko": "...", "es": "..."}}]}}
只写这一个文件；最后只回复一行：done <条目总数>。
"""

TRANSLATE_PROMPT = """\
你是一位资深的证道译者，只做一件事：把英文证道逐句译成{label}。

输入文件：{input}
每行是一个 JSON：{{"id","english","before","after"}}。
- `english` 是要翻译的这一句（英文是 ASR 转写稿）。
- `before`（前 3 句）和 `after`（后 2 句）只是语境参考，**不要翻译它们**，也不要借用它们的内容。

翻译要求：
1. 完整覆盖本句的所有含义，不增译、不漏译、不改写讲员的论点。
2. 一句英文对应一句译文，不合并、不拆分、不重复。数字、经文出处、人名、系列名按英文原文和下面的约定。
3. 口语自然、可直接朗读配音，像讲员当场说出来的话；否定、条件、时态、比较级要准确。
4. {rules}

自检（必须做）：全部写完后，再从头通读一次译文，逐句对照英文检查：漏译、增译、否定词、数字、人名、经文出处、意思偏移。有问题就改那一句的译文，并在 `reviewNote` 里写 "revised: <原因>"；没有问题的写 "pass"。

输出：写入 {output}，每行一个 JSON，字段恰好是 {{"id","locale","target","reviewNote"}}，id 与输入一一对应、顺序一致，locale 固定为 "{locale}"。
只写这个输出文件，不要写别的文件，不要修改输入文件；最后只回复一行：done <行数>。
"""

AUDIT_PROMPT = """\
你是一位独立的证道译文审校者，只做一件事：逐句对照英文，找出{label}译文里的**保真问题**。

上下文：讲员 {speaker}，系列 {series}，英文标题 {englishTitle}。英文是 ASR 转写稿，句表已经过人工审核。你的任务是独立复核译文本身，不要重译整个风格。

只读这两个文件，不要修改它们：
- 英文原文：{sentences}
- 现有译文（冻结副本）：{translations}

逐句检查（id 一一对应）：
1. 漏译：英文里的信息在译文里没有。
2. 增译：译文里出现英文没有的信息。
3. 否定、条件、时态是否准确。
4. 数字、经文出处（书卷、章、节）、人名、系列名是否正确。
5. 意思偏移：译文换个说法但意思变了，或把讲员的话当成别人的话。
6. 本篇约定的用词是否照用：
{terms}

只把**确实有问题**的句子写进 {output}，每行一个 JSON：
{{"id":"s0123","issue":"漏译/增译/否定/数字/人名/经文/偏移 + 一句说明","suggestedTarget":"你建议改成什么（保持原语气与长度，不要重写整句风格）","severity":"high|medium|low"}}
没有问题的句子不要写；一个问题都没有时写一个空文件。宁可少报也不要编；不确定的把 severity 写 low。
只写这一个文件，不要改输入文件，不要输出解释；最后只回复一行：done <问题数>。
"""

REWRITE_PROMPT = {
    "colloquial": """\
你在为一篇证道的{label}配音稿做口语化，只做这一件事。配音要跟着原视频走，下面这些句子念出来比英文原声长。

输入文件：{input}
每行是一个 JSON：{{"id","english","target","sourceSeconds","dubSeconds","before","after"}}。
- `target` 是现在的译文；`sourceSeconds` 是英文原声的时长，`dubSeconds` 是现在配音的时长（估算或实测）。
- `before`、`after` 是前后句的译文，只作语境，不要改它们。

把 `target` 改写成讲员当场会说出来的自然口语：
1. 意思和信息一句不少：论点、否定、条件、数字、人名、经文出处都要在。
2. 用更顺口、更短的说法：去掉书面腔、绕口的定语和不必要的虚词；同一个意思选更短的词。
3. 不要为了短而删内容，不要合并或拆分句子，不要动数字的写法（保留阿拉伯数字）。
4. 改不出更顺口的说法就不要改。

输出：写入 {output}，每行一个 JSON，字段恰好是 {{"id","target","note"}}，只写确实改了的句子；`note` 用几个字说明改了什么。
只写这个输出文件；最后只回复一行：done <行数>。
""",
    "condense": """\
你在为一篇证道的{label}配音稿做精简，只做这一件事。这些句子已经口语化过，念出来仍然比英文原声长，配音跟不上原视频。

输入文件：{input}
每行是一个 JSON：{{"id","english","target","sourceSeconds","dubSeconds","before","after"}}。
- `target` 是现在的译文；`sourceSeconds` 是英文原声的时长，`dubSeconds` 是现在配音的时长。目标是念出来不超过 `sourceSeconds`。
- `before`、`after` 是前后句的译文，只作语境，不要改它们。

把 `target` 缩短到能在 `sourceSeconds` 内念完：
1. 只能删这三样：重复的话、填充词和语气词、同一个意思的换句话说。
2. 不能删：论点、否定、条件、数字、人名、经文出处。删了就不是这句话了。
3. 留下的必须是一句完整、自然、可以直接念的话，不能是残句。
4. 保留阿拉伯数字的写法。实在缩不到目标长度，就缩到不丢内容的最短。

输出：写入 {output}，每行一个 JSON，字段恰好是 {{"id","target","note"}}，只写确实改了的句子；`note` 写删了什么。
只写这个输出文件；最后只回复一行：done <行数>。
""",
}

ISSUE_TAGS = {"translation": "译文", "reading": "读音", "facts": "数字／人名／经文", "audio": "音质", "sync": "不同步", "other": "其他"}

REPAIR_PROMPT = """\
你在修改一篇证道的{label}配音稿里被听审人退回的句子，只做这一件事。听审人听过整条配音，标出了有问题的句子。

上下文：讲员 {speaker}，系列 {series}，英文标题 {englishTitle}。

输入文件：{input}
每行是一个 JSON：{{"id","english","target","spoken","before","after","tags","note"}}。
- `english` 是英文原句（ASR 转写稿）；`target` 是现在的译文；`spoken` 是配音实际念的文字（数字等已换成读法，可能和译文不同）。
- `before`、`after` 是前后句的译文，只作语境，不要改它们。
- `tags` 是听审人选的问题类型；`note` 是听审人写的话，可能直接给了改法。

逐句处理：
1. 听审人写了改成什么，就照他写的改，不要再自行润色；只有明显的笔误才顺一下。
2. 听审人只说了哪里不对，就只改那一处，其余的字保持原样。
3. 问题只在声音上（音质、不同步，或读音问题而文字没有错）、文字不用改的：`action` 写 "rerender"，`target` 原样抄回。读音问题如果换一个写法能让机器读对（多音字换同义词、缩写展开），可以改字，`action` 写 "retranslate"。
4. 不加英文里没有的内容；数字、人名、经文出处要和英文一致，保留阿拉伯数字的写法；本篇约定的用词照用：
{terms}
5. 配音要跟上原视频：改后的句子不要比原来长很多。
6. 看不懂听审人要什么的句子，不要猜：`action` 写 "unclear"，`target` 原样抄回，`note` 写你哪里不明白。

输出：写入 {output}，每行一个 JSON，字段恰好是 {{"id","action","target","note"}}，输入里的每个 id 恰好一行、顺序一致；`action` 是 "retranslate"、"rerender"、"unclear" 之一；`note` 用一句话说明改了什么。
只写这个输出文件；最后只回复一行：done <行数>。
"""


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run_claude(prompt: str, *, timeout: int = 3600, model: str = MODEL) -> dict:
    """One CLI call from the checkout root. The CLI writes its own output file; we read the last reply line."""
    binary = os.environ.get("SFA_CLAUDE_BIN", "claude")
    started = time.time()
    try:
        done = subprocess.run([binary, "-p", prompt, "--model", model, "--permission-mode", "acceptEdits"],
                              capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
        code, out, err = done.returncode, done.stdout or "", done.stderr or ""
    except subprocess.TimeoutExpired:
        code, out, err = 124, "", "timeout"
    except OSError as exc:
        code, out, err = 127, "", type(exc).__name__
    return {"exit": code, "seconds": round(time.time() - started, 1), "tail": out.strip()[-160:], "stderr": err.strip()[-300:]}


def episode_facts(episode: dict, locale: str | None = None) -> dict:
    titles, series = episode.get("titles") or {}, episode.get("series") or {}
    facts = {"speaker": episode.get("speaker") or "the preacher", "englishTitle": episode.get("englishTitle") or "(untitled)",
             "seriesAll": " / ".join(value for value in series.values() if value) or "（未登记）"}
    if locale:
        facts.update(title=titles.get(locale) or facts["englishTitle"], series=series.get(locale) or series.get("zh-Hans") or "（未登记）")
    return facts


def terms_text(brief: dict, locale: str) -> str:
    lines = []
    for group, heading in (("books", "书卷与出处"), ("terms", "术语"), ("names", "人名与机构")):
        pairs = [f"{item['english']} = {item[locale]}" for item in brief.get(group, []) if item.get(locale)]
        if pairs:
            lines.append(f"- {heading}：" + "；".join(pairs))
    return "\n".join(lines) or "- （本篇没有额外约定，按共享术语表和通行译名）"


def effective_targets(run: Path) -> dict[str, str]:
    targets = {row["id"]: row["target"] for row in load_jsonl(run / "translations.jsonl")}
    review = json.loads((run / "review.json").read_text(encoding="utf-8")) if (run / "review.json").exists() else {}
    for unit, revision in (review.get("revisions") or {}).items():
        if unit in targets and revision.get("target"):
            targets[unit] = revision["target"]
    return targets


# ---------------------------------------------------------------- brief

def validate_brief(value) -> list[str]:
    problems = []
    if not isinstance(value, dict):
        return ["not an object"]
    for group in ("names", "terms", "books"):
        rows = value.get(group)
        if not isinstance(rows, list):
            problems.append(f"{group} is not a list")
            continue
        for row in rows:
            if not isinstance(row, dict) or not all(isinstance(row.get(key), str) and row.get(key).strip() for key in ("english", *LOCALES)):
                problems.append(f"{group}: a row lacks english or a language")
                break
    return problems


def cmd_brief(args) -> int:
    episode = json.loads(args.episode.read_text(encoding="utf-8"))
    attempts = []
    for attempt in (1, 2):
        args.out.unlink(missing_ok=True)
        prompt = BRIEF_PROMPT.format(sentences=args.run / "sentences.jsonl", terminology=TERMINOLOGY, established=ESTABLISHED,
                                     output=args.out, **episode_facts(episode))
        result = run_claude(prompt, timeout=args.timeout)
        try:
            value = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else None
            problems = validate_brief(value) if value is not None else ["no output file"]
        except ValueError:
            problems = ["output is not JSON"]
        attempts.append({**result, "attempt": attempt, "problems": problems})
        if result["exit"] == 0 and not problems:
            value["schemaVersion"] = "sentence-first-episode-brief-v1"
            value["terminologySha256"] = hashlib.sha256(TERMINOLOGY.read_bytes()).hexdigest()
            value["establishedTermsSha256"] = hashlib.sha256(ESTABLISHED.read_bytes()).hexdigest()
            used = {row["english"].lower(): row for row in json.loads(ESTABLISHED.read_text(encoding="utf-8"))["terms"]}
            # A published rendering wins over what the model wrote this time: put it back and say so.
            corrected = []
            for group in ("names", "terms", "books"):
                for row in value[group]:
                    known = used.get(row["english"].lower())
                    for locale in LOCALES if known else ():
                        if row[locale] != known[locale]:
                            corrected.append({"english": row["english"], "locale": locale, "was": row[locale], "now": known[locale]})
                            row[locale] = known[locale]
            value["correctedToEstablished"] = corrected
            write_json(args.out, value)
            print(json.dumps({"brief": str(args.out), "names": len(value["names"]), "terms": len(value["terms"]),
                              "books": len(value["books"]), "attempts": attempt}, ensure_ascii=False))
            return 0
    print(json.dumps({"brief": None, "attempts": attempts}, ensure_ascii=False))
    return 1


# ---------------------------------------------------------------- translate

def check_part(run: Path, part: int, locale: str) -> list[str]:
    source = load_jsonl(run / "translate" / f"input-{part}.jsonl")
    out = run / "translate" / f"output-{part}.jsonl"
    if not out.exists():
        return ["no output file"]
    try:
        rows = load_jsonl(out)
    except ValueError:
        return ["output is not JSONL"]
    if [row.get("id") for row in rows] != [row["id"] for row in source]:
        return [f"ids differ from the input ({len(rows)} rows for {len(source)})"]
    problems = []
    if any(row.get("locale") != locale for row in rows):
        problems.append("wrong locale")
    if any(not str(row.get("target") or "").strip() for row in rows):
        problems.append("empty target")
    return problems


def cmd_translate(args) -> int:
    episode = json.loads(args.episode.read_text(encoding="utf-8"))
    brief = json.loads(args.brief.read_text(encoding="utf-8")) if args.brief and args.brief.exists() else {}
    spec = LOCALES[args.locale]
    rules = spec["rules"].format(terms=terms_text(brief, args.locale), **episode_facts(episode, args.locale))
    parts = sorted(int(path.stem.split("-")[1]) for path in (args.run / "translate").glob("input-*.jsonl"))
    if not parts:
        raise SystemExit("no translate/input-<k>.jsonl: run translate_parts.py split first")

    def dispatch(part: int, attempt: int) -> dict:
        base = args.run / "translate"
        (base / f"output-{part}.jsonl").unlink(missing_ok=True)
        prompt = TRANSLATE_PROMPT.format(label=spec["label"], rules=rules, locale=args.locale,
                                         input=base / f"input-{part}.jsonl", output=base / f"output-{part}.jsonl")
        result = run_claude(prompt, timeout=args.timeout)
        return {"locale": args.locale, "part": part, "attempt": attempt, **result, "problems": check_part(args.run, part, args.locale)}

    results = []
    pending = [part for part in parts if args.force or check_part(args.run, part, args.locale)]
    for attempt in (1, 2):                                  # one more dispatch for the parts that failed the check, then stop
        if not pending:
            break
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            batch = list(pool.map(lambda part: dispatch(part, attempt), pending))
        results.extend(batch)
        for row in batch:
            print(json.dumps(row, ensure_ascii=False), flush=True)
        pending = [row["part"] for row in batch if row["exit"] != 0 or row["problems"]]
    write_json(args.run / "translate-dispatch.json", results)
    print(json.dumps({"locale": args.locale, "parts": len(parts), "dispatched": len(results), "bad": pending}, ensure_ascii=False))
    return 0 if not pending else 1


# ---------------------------------------------------------------- audit

def cmd_audit(args) -> int:
    episode = json.loads(args.episode.read_text(encoding="utf-8"))
    brief = json.loads(args.brief.read_text(encoding="utf-8")) if args.brief and args.brief.exists() else {}
    spec = LOCALES[args.locale]
    folder = args.run / "audit"
    folder.mkdir(exist_ok=True)
    frozen, out = folder / "translations.audit.jsonl", folder / f"audit-{args.locale}.jsonl"
    record_path = folder / f"audit-{args.locale}.dispatch.json"
    ids = {row["id"] for row in load_jsonl(args.run / "sentences.jsonl")}
    if not record_path.exists() or args.force:
        shutil.copyfile(args.run / "translations.jsonl", frozen)
        attempts = []
        for attempt in (1, 2):
            out.unlink(missing_ok=True)
            prompt = AUDIT_PROMPT.format(label=spec["label"], sentences=args.run / "sentences.jsonl", translations=frozen, output=out,
                                         terms=terms_text(brief, args.locale), **episode_facts(episode, args.locale))
            result = run_claude(prompt, timeout=args.timeout)
            problems = []
            try:
                rows = load_jsonl(out) if out.exists() else None
            except ValueError:
                rows, problems = None, ["output is not JSONL"]
            if rows is None and not problems and not re.search(r"done\s+0\b", result["tail"]):
                problems = ["no output file and the reply does not say done 0"]
            if rows and any(row.get("id") not in ids or row.get("severity") not in ("high", "medium", "low") for row in rows):
                problems.append("a row has an unknown id or severity")
            attempts.append({**result, "attempt": attempt, "problems": problems})
            if result["exit"] == 0 and not problems:
                break
        if attempts[-1]["exit"] != 0 or attempts[-1]["problems"]:
            print(json.dumps({"locale": args.locale, "audit": "failed", "attempts": attempts}, ensure_ascii=False))
            return 1
        if not out.exists():
            out.write_text("", encoding="utf-8")
        write_json(record_path, {"locale": args.locale, "frozenSha256": hashlib.sha256(frozen.read_bytes()).hexdigest(), "attempts": attempts})
    findings = load_jsonl(out)
    summary = {"locale": args.locale, "findings": len(findings),
               "bySeverity": {level: sum(1 for row in findings if row["severity"] == level) for level in ("high", "medium", "low")}}
    if args.apply:
        review_path = args.run / "review.json"
        review = json.loads(review_path.read_text(encoding="utf-8"))
        current = effective_targets(args.run)
        revisions, notes = review.setdefault("revisions", {}), review.setdefault("notes", {})
        adopted = []
        for row in findings:
            suggestion = str(row.get("suggestedTarget") or "").strip()
            if row["severity"] in ("high", "medium") and suggestion and suggestion != current.get(row["id"]):
                revisions[row["id"]] = {"target": suggestion, "note": f"audit {row['severity']}: {row.get('issue', '')}"}
                adopted.append(row["id"])
            else:
                notes[row["id"]] = f"audit {row['severity']}: {row.get('issue', '')}"
        write_json(review_path, review)
        write_json(folder / f"audit-{args.locale}.applied.json", {"adoptedAsRevisions": adopted, "notedOnly": sorted(set(r["id"] for r in findings) - set(adopted))})
        summary.update(adopted=len(adopted), noted=len(findings) - len(adopted))
    print(json.dumps(summary, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- rewrite (sync)

def select_rows(run: Path, how: str, *, margin: float = 0.3, limit: int = 160) -> list[dict]:
    """Sentences whose dub is longer than its English slot, worst first, at most `limit`.

    estimate: from speech.jsonl before any rendering (estimatedSeconds against budgetSeconds).
    measured: from schedule.json after merging (dubSeconds against sourceSeconds, or lag above 1 s).
    """
    sentences = load_jsonl(run / "sentences.jsonl")
    targets = effective_targets(run)
    if how == "estimate":
        timing = {row["id"]: (float(row.get("budgetSeconds") or 0), float(row.get("estimatedSeconds") or 0), 0.0)
                  for row in load_jsonl(run / "speech.jsonl")}
    else:
        schedule = json.loads((run / "schedule.json").read_text(encoding="utf-8"))["sentences"]
        timing = {row["id"]: (float(row.get("sourceSeconds") or 0), float(row.get("dubSeconds") or 0), float(row.get("lagSeconds") or 0))
                  for row in schedule}
    order = [row["id"] for row in sentences]
    english = {row["id"]: row["english"] for row in sentences}
    picked = []
    for index, unit in enumerate(order):
        slot, dub, lag = timing.get(unit, (0.0, 0.0, 0.0))
        if slot <= 0 or (dub - slot <= margin and lag <= 1.0):
            continue
        picked.append({"id": unit, "english": english[unit], "target": targets[unit], "sourceSeconds": round(slot, 2),
                       "dubSeconds": round(dub, 2), "before": targets.get(order[index - 1]) if index else None,
                       "after": targets.get(order[index + 1]) if index + 1 < len(order) else None,
                       "_over": dub - slot + max(0.0, lag)})
    picked.sort(key=lambda row: row["_over"], reverse=True)
    keep = {row["id"] for row in picked[:limit]}
    return [{k: v for k, v in row.items() if k != "_over"} for row in picked if row["id"] in keep]


def check_rewrite(mode: str, before: dict, row: dict) -> str | None:
    """Why a rewritten sentence is refused, or None when it may be used."""
    target = str(row.get("target") or "").strip()
    if not target:
        return "empty"
    if sorted(DIGITS.findall(target)) != sorted(DIGITS.findall(before["target"])):
        return "numbers changed"
    if mode == "condense" and len(target) > len(before["target"]):
        return "longer than before"
    if mode == "colloquial" and len(target) > len(before["target"]) * 1.05 + 1:
        return "longer than before"
    if mode == "condense" and len(target) < len(before["target"]) * 0.45:
        return "cut by more than half"
    return None


def cmd_rewrite(args) -> int:
    spec = LOCALES[args.locale]
    folder = args.run / "sync"
    folder.mkdir(exist_ok=True)
    selected = select_rows(args.run, args.select, margin=args.margin, limit=args.limit)
    selected.sort(key=lambda row: row["id"])
    tag = f"{args.mode}-{args.select}"
    report = {"schemaVersion": "sentence-first-sync-rewrite-v1", "locale": args.locale, "mode": args.mode, "select": args.select,
              "selected": len(selected), "accepted": [], "rejected": [], "unchanged": 0, "attempts": []}
    if selected:
        chunks = [selected[i:i + args.chunk] for i in range(0, len(selected), args.chunk)]
        by_id = {row["id"]: row for row in selected}

        def dispatch(index: int) -> dict:
            source, out = folder / f"{tag}-input-{index + 1}.jsonl", folder / f"{tag}-output-{index + 1}.jsonl"
            source.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in chunks[index]), encoding="utf-8")
            out.unlink(missing_ok=True)
            result = run_claude(REWRITE_PROMPT[args.mode].format(label=spec["label"], input=source, output=out), timeout=args.timeout)
            try:
                rows = load_jsonl(out) if out.exists() else []
            except ValueError:
                rows, result = [], {**result, "exit": result["exit"] or 65}
            return {"chunk": index + 1, **result, "rows": rows}

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(dispatch, range(len(chunks))))
        review_path = args.run / "review.json"
        review = json.loads(review_path.read_text(encoding="utf-8"))
        revisions = review.setdefault("revisions", {})
        for result in results:
            report["attempts"].append({key: result[key] for key in ("chunk", "exit", "seconds", "tail", "stderr")})
            for row in result["rows"]:
                before = by_id.get(row.get("id"))
                if before is None:
                    report["rejected"].append({"id": row.get("id"), "why": "not in the selection"})
                    continue
                why = check_rewrite(args.mode, before, row)
                if why:
                    report["rejected"].append({"id": row["id"], "why": why})
                elif row["target"].strip() == before["target"]:
                    report["unchanged"] += 1
                else:
                    earlier = (revisions.get(row["id"]) or {}).get("note")
                    note = f"sync {args.mode}: {str(row.get('note') or '').strip()[:80]}"
                    revisions[row["id"]] = {"target": row["target"].strip(), "note": f"{earlier}; {note}" if earlier else note}
                    report["accepted"].append(row["id"])
        write_json(review_path, review)
        if any(result["exit"] != 0 for result in results) and not report["accepted"]:
            write_json(folder / f"{tag}-report.json", report)
            print(json.dumps({key: report[key] if key not in ("accepted", "rejected") else len(report[key]) for key in report}, ensure_ascii=False))
            return 1
    write_json(folder / f"{tag}-report.json", report)
    print(json.dumps({"locale": args.locale, "mode": args.mode, "select": args.select, "selected": report["selected"],
                      "accepted": len(report["accepted"]), "rejected": len(report["rejected"]), "unchanged": report["unchanged"]}, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- repair (track review)

def check_repair(before: dict, row: dict) -> str | None:
    """Why a returned sentence is refused, or None when it may be used."""
    target, action = str(row.get("target") or "").strip(), row.get("action")
    if action not in ("retranslate", "rerender", "unclear"):
        return "unknown action"
    if not target:
        return "empty"
    if action != "retranslate" and target != before["target"]:
        return "wording changed without saying so"
    if action == "retranslate" and target == before["target"]:
        return "says retranslate but the wording is the same"
    if len(target) > len(before["target"]) * 1.6 + 10:
        return "much longer than before"
    return None


def cmd_repair(args) -> int:
    """The reviewer's marked sentences, one model call (a second one for rows that fail the check)."""
    episode = json.loads(args.episode.read_text(encoding="utf-8"))
    brief = json.loads(args.brief.read_text(encoding="utf-8")) if args.brief and args.brief.exists() else {}
    spec = LOCALES[args.locale]
    request = json.loads(args.issues.read_text(encoding="utf-8"))
    tag = args.issues.stem.replace("issues-", "")
    folder = args.run / "repair"
    folder.mkdir(exist_ok=True)
    sentences = load_jsonl(args.run / "sentences.jsonl")
    order = [row["id"] for row in sentences]
    english = {row["id"]: row["english"] for row in sentences}
    targets = effective_targets(args.run)
    spoken = {row["id"]: row.get("spokenText") for row in load_jsonl(args.run / "speech.jsonl")}
    unknown = sorted(set(request["rows"]) - set(order))
    if unknown or not request["rows"]:
        print(json.dumps({"locale": args.locale, "repair": "failed", "why": f"unknown ids {unknown}" if unknown else "no sentences"}, ensure_ascii=False))
        return 1
    rows = []
    for unit in sorted(request["rows"], key=order.index):
        index, mark = order.index(unit), request["rows"][unit]
        rows.append({"id": unit, "english": english[unit], "target": targets[unit], "spoken": spoken.get(unit),
                     "before": targets.get(order[index - 1]) if index else None,
                     "after": targets.get(order[index + 1]) if index + 1 < len(order) else None,
                     "tags": [ISSUE_TAGS.get(name, name) for name in mark.get("tags") or []], "note": str(mark.get("note") or "").strip()})
    by_id = {row["id"]: row for row in rows}
    report_path = folder / f"repair-{tag}-report.json"
    accepted, attempts, pending = {}, [], rows
    for attempt in (1, 2):                                  # one more call for the rows that failed the check, then stop
        source, out = folder / f"repair-{tag}-input-{attempt}.jsonl", folder / f"repair-{tag}-output-{attempt}.jsonl"
        source.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in pending), encoding="utf-8")
        out.unlink(missing_ok=True)
        result = run_claude(REPAIR_PROMPT.format(label=spec["label"], input=source, output=out, terms=terms_text(brief, args.locale),
                                                 **episode_facts(episode, args.locale)), timeout=args.timeout)
        try:
            returned = load_jsonl(out) if out.exists() else []
        except ValueError:
            returned = []
        refused = {}
        for row in returned:
            before = by_id.get(row.get("id"))
            if before is None or row["id"] in accepted:
                continue
            why = check_repair(before, row)
            if why:
                refused[row["id"]] = why
            else:
                accepted[row["id"]] = {"action": row["action"], "target": str(row["target"]).strip(), "note": str(row.get("note") or "").strip()[:160]}
        pending = [row for row in pending if row["id"] not in accepted]
        attempts.append({**result, "attempt": attempt, "refused": refused, "missing": [row["id"] for row in pending if row["id"] not in refused]})
        if not pending:
            break
    report = {"schemaVersion": "sentence-first-review-repair-v1", "locale": args.locale, "round": tag,
              "decisionId": request.get("decisionId"), "issues": len(rows), "attempts": attempts,
              "rows": [{"id": unit, "tags": by_id[unit]["tags"], "reviewerNote": by_id[unit]["note"], "before": by_id[unit]["target"],
                        **accepted.get(unit, {"action": "failed", "target": by_id[unit]["target"], "note": "no usable answer"})} for unit in by_id]}
    summary = {"locale": args.locale, "issues": len(rows),
               **{name: [row["id"] for row in report["rows"] if row["action"] == name] for name in ("retranslate", "rerender", "unclear", "failed")}}
    if summary["failed"]:                                   # nothing is applied from a round that did not answer every sentence
        write_json(report_path, report)
        print(json.dumps({**summary, "repair": "failed"}, ensure_ascii=False))
        return 1
    if args.apply and summary["retranslate"]:
        review_path = args.run / "review.json"
        review = json.loads(review_path.read_text(encoding="utf-8"))
        revisions = review.setdefault("revisions", {})
        for row in report["rows"]:
            if row["action"] != "retranslate":
                continue
            earlier = (revisions.get(row["id"]) or {}).get("note")
            note = f"review fix {tag}: {row['reviewerNote'][:80] or '、'.join(row['tags']) or row['note'][:80]}"
            revisions[row["id"]] = {"target": row["target"], "note": f"{earlier}; {note}" if earlier else note}
        write_json(review_path, review)
        report["applied"] = True
    write_json(report_path, report)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    brief = commands.add_parser("brief", help="names, terms and Bible books of this episode per language")
    brief.add_argument("--run", type=Path, required=True)
    brief.add_argument("--episode", type=Path, required=True)
    brief.add_argument("--out", type=Path, required=True)
    brief.add_argument("--timeout", type=int, default=1800)
    for name in ("translate", "audit"):
        command = commands.add_parser(name)
        command.add_argument("--run", type=Path, required=True)
        command.add_argument("--locale", choices=sorted(LOCALES), required=True)
        command.add_argument("--episode", type=Path, required=True)
        command.add_argument("--brief", type=Path)
        command.add_argument("--timeout", type=int, default=5400 if name == "translate" else 3600)
        command.add_argument("--force", action="store_true", help="dispatch again even when the output passes the check")
        if name == "translate":
            command.add_argument("--workers", type=int, default=4)
        else:
            command.add_argument("--apply", action="store_true", help="write the findings into review.json")
    rewrite = commands.add_parser("rewrite", help="colloquial rewrite or condensing for sentences that do not fit their slot")
    rewrite.add_argument("--run", type=Path, required=True)
    rewrite.add_argument("--locale", choices=sorted(LOCALES), required=True)
    rewrite.add_argument("--mode", choices=("colloquial", "condense"), required=True)
    rewrite.add_argument("--select", choices=("estimate", "measured"), required=True)
    rewrite.add_argument("--margin", type=float, default=0.3, help="seconds a dub may exceed its slot before it is selected")
    rewrite.add_argument("--limit", type=int, default=160)
    rewrite.add_argument("--chunk", type=int, default=60)
    rewrite.add_argument("--workers", type=int, default=3)
    rewrite.add_argument("--timeout", type=int, default=3600)
    repair = commands.add_parser("repair", help="the sentences a track reviewer sent back: a new wording, or render again")
    repair.add_argument("--run", type=Path, required=True)
    repair.add_argument("--locale", choices=sorted(LOCALES), required=True)
    repair.add_argument("--issues", type=Path, required=True, help='{"rows": {"s0012": {"tags": [...], "note": "..."}}}; the file name gives the round')
    repair.add_argument("--episode", type=Path, required=True)
    repair.add_argument("--brief", type=Path)
    repair.add_argument("--apply", action="store_true", help="write the new wordings into review.json")
    repair.add_argument("--timeout", type=int, default=1800)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return {"brief": cmd_brief, "translate": cmd_translate, "audit": cmd_audit, "rewrite": cmd_rewrite, "repair": cmd_repair}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
