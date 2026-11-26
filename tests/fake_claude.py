#!/usr/bin/env python3
"""Stands in for the Claude Code CLI in tests: reads the paths a prompt names and writes the output file.

What it writes is steered by FAKE_CLAUDE_MODE (ok, drop_row, no_output, fail) so the caller's checks
and its single re-dispatch can be exercised. Every call is appended to FAKE_CLAUDE_LOG.
"""
import json
import os
from pathlib import Path
import re
import sys

prompt = sys.argv[sys.argv.index("-p") + 1]
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
log = os.environ.get("FAKE_CLAUDE_LOG")
out = Path(re.search(r"写[入进] (\S+?)[，,。\s]", prompt).group(1))
if "本篇用词约定" in prompt:
    kind = "brief"
elif "保真问题" in prompt:
    kind = "audit"
elif "做口语化" in prompt:
    kind = "colloquial"
elif "做精简" in prompt:
    kind = "condense"
else:
    kind = "translate"
calls = 0
if log:
    lines = Path(log).read_text().splitlines() if Path(log).exists() else []
    calls = sum(1 for line in lines if json.loads(line)["out"] == str(out))
    with open(log, "a") as handle:
        handle.write(json.dumps({"kind": kind, "out": str(out), "argv": [a for a in sys.argv[1:] if a != prompt]}) + "\n")
if mode == "fail" or (mode == "fail_once" and calls == 0):
    print("boom", file=sys.stderr)
    sys.exit(1)
if mode == "no_output":
    print("done 0")
    sys.exit(0)
rows = lambda path: [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
if kind == "brief":
    out.write_text(json.dumps({
        "names": [{"english": "Eric", "zh-Hans": "艾瑞克" if mode == "brief_differs" else "埃里克", "ko": "에릭", "es": "Eric"}],
        "terms": [{"english": "the city", "zh-Hans": "那城", "ko": "그 성", "es": "la ciudad"}],
        "books": [{"english": "chapter 21", "zh-Hans": "第 21 章", "ko": "21장", "es": "capítulo 21"}]}, ensure_ascii=False))
    print("done 3")
elif kind == "translate":
    source = rows(re.search(r"输入文件：(\S+)", prompt).group(1))
    locale = re.search(r'locale 固定为 "([^"]+)"', prompt).group(1)
    if mode == "drop_row" or (mode == "drop_row_once" and calls == 0):
        source = source[:-1]
    out.write_text("".join(json.dumps({"id": r["id"], "locale": locale, "target": f"[{locale}] {r['english']}", "reviewNote": "pass"},
                                      ensure_ascii=False) + "\n" for r in source), encoding="utf-8")
    print(f"done {len(source)}")
elif kind == "audit":
    sentences = rows(re.search(r"英文原文：(\S+)", prompt).group(1))
    findings = [{"id": sentences[1]["id"], "issue": "数字：漏了章节", "suggestedTarget": "AUDITED " + sentences[1]["english"], "severity": "high"},
                {"id": sentences[2]["id"], "issue": "偏移：不确定", "suggestedTarget": "", "severity": "low"}]
    out.write_text("".join(json.dumps(f, ensure_ascii=False) + "\n" for f in findings), encoding="utf-8")
    print("done 2")
else:
    source = rows(re.search(r"输入文件：(\S+)", prompt).group(1))
    result = []
    for index, row in enumerate(source):
        words = row["target"].split()
        if kind == "condense":
            target = " ".join(words[: max(3, len(words) * 2 // 3)])
        else:
            target = row["target"].replace("everyone, and ", "")
        if mode == "break_numbers" and index == 0:
            target = target + " 99"
        if target != row["target"]:
            result.append({"id": row["id"], "target": target, "note": kind})
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in result), encoding="utf-8")
    print(f"done {len(result)}")
