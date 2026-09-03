#!/usr/bin/env python3
"""Serve a loopback-only UI for hash-bound sermon parallel-corpus review."""

from __future__ import annotations

import argparse
from collections import Counter
import fcntl
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
import re
import secrets
import sys
import threading
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse
import webbrowser


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import build_sermon_parallel_corpus_poc as corpus  # noqa: E402
from scripts import build_sermon_parallel_quality_catalog as quality  # noqa: E402
from scripts import export_sermon_parallel_review_bundle as review_export  # noqa: E402


HISTORY_SCHEMA_VERSION = "sermon-parallel-human-decision-history-v1"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
MAX_REQUEST_BYTES = 2 * 1024 * 1024


class DecisionConflict(RuntimeError):
    """Raised when a browser tries to replace a decision it did not load."""


class BoundaryNotApproved(RuntimeError):
    """Raised when content review is attempted before boundary approval."""


class ReviewStore:
    def __init__(
        self,
        *,
        review_root: Path,
        decisions_path: Path,
        history_root: Path,
    ) -> None:
        self.review_root = review_root.resolve()
        self.decisions_path = decisions_path.resolve()
        self.history_root = history_root.resolve()
        self._lock = threading.RLock()
        review_path = self.review_root / "review-items.all.jsonl"
        self.items = corpus.read_jsonl(review_path)
        self.item_by_id: dict[str, dict[str, Any]] = {}
        for item in self.items:
            review_export.validate_review_item(item)
            item_id = str(item["reviewItemId"])
            if item_id in self.item_by_id:
                raise RuntimeError(f"Duplicate review item ID: {item_id}")
            self.item_by_id[item_id] = item
        self.order = [str(item["reviewItemId"]) for item in self.items]
        self._load_decisions()

    def _load_decisions(self) -> dict[str, dict[str, Any]]:
        rows = (
            corpus.read_jsonl(self.decisions_path)
            if self.decisions_path.exists()
            else []
        )
        result: dict[str, dict[str, Any]] = {}
        for decision in rows:
            item_id = str(decision.get("reviewItemId") or "")
            if not item_id or item_id in result:
                raise RuntimeError("Decisions contain a blank or duplicate review item ID")
            item = self.item_by_id.get(item_id)
            if item is None:
                raise RuntimeError(f"Decision references unknown review item: {item_id}")
            quality.validate_human_decision(item, decision)
            result[item_id] = decision
        self.decisions = result
        return result

    def summary(self) -> dict[str, Any]:
        with self._lock:
            self._load_decisions()
            priorities = Counter(str(item["priority"]) for item in self.items)
            statuses = Counter(
                str(decision["status"]) for decision in self.decisions.values()
            )
            unapproved_boundaries = sum(
                1
                for item in self.items
                if not (
                    item["boundary"].get("approvedByHuman") is True
                    and item["boundary"].get("status")
                    == "approved_human_boundary"
                )
            )
            return {
                "schemaVersion": "sermon-parallel-review-ui-summary-v1",
                "status": (
                    "content_review_ready"
                    if unapproved_boundaries == 0
                    else "boundary_approval_required"
                ),
                "total": len(self.items),
                "completed": len(self.decisions),
                "remaining": len(self.items) - len(self.decisions),
                "byPriority": dict(sorted(priorities.items())),
                "byDecisionStatus": dict(sorted(statuses.items())),
                "unapprovedBoundaryItems": unapproved_boundaries,
                "trainingEligibility": "blocked",
            }

    def list_items(
        self, *, priority: str | None = None, state: str = "all"
    ) -> list[dict[str, Any]]:
        if priority not in {None, "high", "normal"}:
            raise ValueError("priority must be high, normal, or omitted")
        if state not in {"all", "pending", "completed"}:
            raise ValueError("state must be all, pending, or completed")
        with self._lock:
            self._load_decisions()
            rows: list[dict[str, Any]] = []
            for item_id in self.order:
                item = self.item_by_id[item_id]
                decision = self.decisions.get(item_id)
                if priority and item["priority"] != priority:
                    continue
                if state == "pending" and decision is not None:
                    continue
                if state == "completed" and decision is None:
                    continue
                rows.append(
                    {
                        "reviewItemId": item_id,
                        "sermonId": item["sermonId"],
                        "priority": item["priority"],
                        "issues": item["issues"],
                        "startMs": item["source"]["startMs"],
                        "endMs": item["source"]["endMs"],
                        "decisionStatus": (
                            decision["status"] if decision is not None else "pending"
                        ),
                        "englishPreview": str(item["source"]["english"])[:180],
                        "chinesePreview": str(item["candidate"]["chinese"])[:120],
                    }
                )
            return rows

    def get_item(self, item_id: str) -> dict[str, Any]:
        with self._lock:
            self._load_decisions()
            item = self.item_by_id.get(item_id)
            if item is None:
                raise KeyError(item_id)
            decision = self.decisions.get(item_id)
            start_seconds = max(0, int(item["source"]["startMs"]) // 1000 - 4)
            video_id = str(item["sermonId"])
            youtube_url = None
            youtube_embed_url = None
            if VIDEO_ID_RE.fullmatch(video_id):
                youtube_url = (
                    f"https://www.youtube.com/watch?v={video_id}&t={start_seconds}s"
                )
                youtube_embed_url = (
                    f"https://www.youtube-nocookie.com/embed/{video_id}"
                    f"?start={start_seconds}"
                )
            return {
                "item": item,
                "decision": decision or review_export.decision_template(item),
                "decisionSha256": (
                    corpus.stable_json_sha256(decision)
                    if decision is not None
                    else None
                ),
                "youtubeUrl": youtube_url,
                "youtubeEmbedUrl": youtube_embed_url,
            }

    def save_decision(
        self,
        *,
        item_id: str,
        submitted: dict[str, Any],
        expected_decision_sha256: str | None,
    ) -> dict[str, Any]:
        with self._lock:
            self.decisions_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.decisions_path.with_suffix(
                self.decisions_path.suffix + ".lock"
            )
            with lock_path.open("a+", encoding="utf-8") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                try:
                    return self._save_decision_locked(
                        item_id=item_id,
                        submitted=submitted,
                        expected_decision_sha256=expected_decision_sha256,
                    )
                finally:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _save_decision_locked(
        self,
        *,
        item_id: str,
        submitted: dict[str, Any],
        expected_decision_sha256: str | None,
    ) -> dict[str, Any]:
        item = self.item_by_id.get(item_id)
        if item is None:
            raise KeyError(item_id)
        if not (
            item["boundary"].get("approvedByHuman") is True
            and item["boundary"].get("status") == "approved_human_boundary"
        ):
            raise BoundaryNotApproved(
                f"{item_id}: approve and regenerate sermon boundaries before content review"
            )
        self._load_decisions()
        existing = self.decisions.get(item_id)
        existing_sha = (
            corpus.stable_json_sha256(existing) if existing is not None else None
        )
        normalized_expected = str(expected_decision_sha256 or "") or None
        if normalized_expected != existing_sha:
            raise DecisionConflict(
                f"{item_id}: decision changed after this browser loaded it"
            )
        decision = {
            "schemaVersion": quality.DECISION_SCHEMA_VERSION,
            "reviewItemId": item_id,
            "reviewPayloadSha256": item["reviewPayloadSha256"],
            "status": submitted.get("status"),
            "reviewer": submitted.get("reviewer"),
            "reviewerRole": submitted.get("reviewerRole"),
            "reviewedAt": corpus.utc_now(),
            "audioChecked": submitted.get("audioChecked"),
            "englishDecision": submitted.get("englishDecision"),
            "approvedEnglish": submitted.get("approvedEnglish"),
            "chineseDecision": submitted.get("chineseDecision"),
            "approvedChinese": submitted.get("approvedChinese"),
            "scriptureChecked": submitted.get("scriptureChecked"),
            "properNounsChecked": submitted.get("properNounsChecked"),
            "numbersChecked": submitted.get("numbersChecked"),
            "materialErrorTypes": submitted.get("materialErrorTypes"),
            "adjudicationComplete": submitted.get("adjudicationComplete"),
            "notes": submitted.get("notes"),
        }
        quality.validate_human_decision(item, decision)
        decision_sha = corpus.stable_json_sha256(decision)
        action = "created" if existing is None else "replaced"
        history = {
            "schemaVersion": HISTORY_SCHEMA_VERSION,
            "savedAt": corpus.utc_now(),
            "action": action,
            "reviewItemId": item_id,
            "reviewPayloadSha256": item["reviewPayloadSha256"],
            "priorDecisionSha256": existing_sha,
            "decisionSha256": decision_sha,
            "decision": decision,
        }
        safe_item_id = re.sub(r"[^A-Za-z0-9_.-]", "_", item_id)
        history_path = (
            self.history_root
            / safe_item_id
            / f"{history['savedAt'].replace(':', '-')}-{decision_sha}.json"
        )
        corpus.write_json(history_path, history)
        merged = dict(self.decisions)
        merged[item_id] = decision
        ordered = [merged[value] for value in self.order if value in merged]
        corpus.write_jsonl(self.decisions_path, ordered)
        self.decisions = merged
        return {
            "decision": decision,
            "decisionSha256": decision_sha,
            "historyReceipt": corpus.display_path(history_path),
            "summary": self.summary(),
        }


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>证道中英语料人工审核</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; color: #16211b; background: #f4f5f1; }
    header { position: sticky; top: 0; z-index: 2; padding: 12px 18px; background: #173d2a; color: white; display: flex; gap: 18px; align-items: center; flex-wrap: wrap; }
    header h1 { margin: 0; font-size: 18px; }
    header .progress { font-variant-numeric: tabular-nums; }
    .layout { display: grid; grid-template-columns: minmax(260px, 330px) minmax(0, 1fr); min-height: calc(100vh - 58px); }
    aside { border-right: 1px solid #cfd5ce; background: white; overflow: auto; max-height: calc(100vh - 58px); }
    .filters { padding: 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; border-bottom: 1px solid #e1e4df; }
    select, input, textarea, button { font: inherit; }
    select, input[type=text], textarea { width: 100%; border: 1px solid #b5bdb6; border-radius: 7px; padding: 8px; background: white; }
    textarea { min-height: 130px; resize: vertical; line-height: 1.45; }
    #items { list-style: none; margin: 0; padding: 0; }
    #items button { width: 100%; border: 0; border-bottom: 1px solid #eceeeb; background: white; text-align: left; padding: 11px 12px; cursor: pointer; }
    #items button:hover, #items button.active { background: #edf5ef; }
    .item-title { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; font-weight: 650; }
    .preview { margin-top: 5px; font-size: 12px; color: #5a645d; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .badge { display: inline-block; border-radius: 999px; padding: 2px 7px; font-size: 11px; background: #e7ece8; }
    .badge.high { background: #ffe1d8; color: #7f2412; }
    main { padding: 20px; max-width: 1240px; width: 100%; margin: 0 auto; }
    .empty { padding: 60px 20px; text-align: center; color: #657069; }
    .panel { background: white; border: 1px solid #d8ddd7; border-radius: 12px; padding: 16px; margin-bottom: 14px; }
    .meta { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .warning { padding: 10px 12px; border-radius: 8px; background: #fff0cf; color: #684900; margin: 10px 0; }
    iframe { width: 100%; aspect-ratio: 16 / 9; border: 0; border-radius: 9px; background: #111; }
    .columns { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    label { display: block; margin: 8px 0 5px; font-size: 13px; font-weight: 650; }
    .checks { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 14px; }
    .checks label { font-weight: 450; margin: 0; }
    .risk-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px 12px; }
    .risk-grid label { font-weight: 450; margin: 0; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #f6f7f5; padding: 10px; border-radius: 8px; }
    .actions { display: flex; justify-content: space-between; gap: 10px; align-items: center; }
    .primary { border: 0; border-radius: 8px; background: #176b43; color: white; padding: 10px 16px; cursor: pointer; }
    .primary:disabled { opacity: .45; cursor: not-allowed; }
    .secondary { border: 1px solid #aeb7af; border-radius: 8px; background: white; padding: 9px 12px; cursor: pointer; }
    #message { min-height: 22px; color: #176b43; }
    @media (max-width: 820px) {
      .layout { grid-template-columns: 1fr; }
      aside { max-height: 36vh; border-right: 0; border-bottom: 1px solid #cfd5ce; }
      .columns, .risk-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>证道中英语料人工审核</h1>
    <span id="progress" class="progress">载入中…</span>
    <span id="mode"></span>
  </header>
  <div class="layout">
    <aside>
      <div class="filters">
        <select id="priority"><option value="">全部优先级</option><option value="high">high</option><option value="normal">normal</option></select>
        <select id="state"><option value="pending">待审核</option><option value="completed">已决定</option><option value="all">全部</option></select>
      </div>
      <ul id="items"></ul>
    </aside>
    <main><div id="content" class="empty">请选择一条审核项。</div></main>
  </div>
  <script nonce="__NONCE__">
    const READ_ONLY = __READ_ONLY__;
    const ERROR_TYPES = ["source_asr","boundary","omission","unsupported_addition","meaning","negation","number","scripture","proper_noun","theology_term","readability","other"];
    let rows = [];
    let current = null;

    async function api(path, options = {}) {
      const response = await fetch(path, {credentials: "same-origin", ...options});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      return data;
    }
    function node(tag, text, className) {
      const value = document.createElement(tag);
      if (text !== undefined && text !== null) value.textContent = text;
      if (className) value.className = className;
      return value;
    }
    function checked(id) { return document.getElementById(id).checked; }
    function value(id) { return document.getElementById(id).value; }
    function setChecked(id, state) { document.getElementById(id).checked = Boolean(state); }

    async function refresh(keepSelection = true) {
      const priority = value("priority");
      const state = value("state");
      const query = new URLSearchParams({state});
      if (priority) query.set("priority", priority);
      const [summary, list] = await Promise.all([api("/api/summary"), api(`/api/items?${query}`)]);
      document.getElementById("progress").textContent = `${summary.completed}/${summary.total} 已决定；${summary.remaining} 待审核`;
      document.getElementById("mode").textContent = READ_ONLY ? "只读模式" : (summary.status === "content_review_ready" ? "可写模式" : "边界未批准");
      rows = list.items;
      renderList();
      if (keepSelection && current && rows.some(row => row.reviewItemId === current.item.reviewItemId)) {
        await selectItem(current.item.reviewItemId);
      }
    }
    function renderList() {
      const list = document.getElementById("items");
      list.replaceChildren();
      for (const row of rows) {
        const button = node("button");
        if (current && current.item.reviewItemId === row.reviewItemId) button.classList.add("active");
        const title = node("div", null, "item-title");
        title.append(node("span", row.reviewItemId));
        title.append(node("span", row.priority, `badge ${row.priority}`));
        button.append(title, node("div", `${row.decisionStatus} · ${row.englishPreview}`, "preview"));
        button.addEventListener("click", () => selectItem(row.reviewItemId));
        list.append(button);
      }
    }
    function addTextList(parent, values) {
      const list = node("ul");
      for (const text of values || []) list.append(node("li", String(text)));
      parent.append(list);
    }
    async function selectItem(id) {
      current = await api(`/api/items/${encodeURIComponent(id)}`);
      renderList();
      renderCurrent();
    }
    function renderCurrent() {
      const host = document.getElementById("content");
      host.replaceChildren();
      const item = current.item;
      const decision = current.decision;
      const top = node("section", null, "panel");
      const heading = node("h2", item.reviewItemId);
      const meta = node("div", null, "meta");
      meta.append(node("span", item.priority, `badge ${item.priority}`));
      meta.append(node("span", `${item.source.startMs}–${item.source.endMs} ms`));
      meta.append(node("span", `边界：${item.boundary.status}`));
      top.append(heading, meta);
      if (!item.boundary.approvedByHuman) top.append(node("div", "边界尚未人工批准：本包只能检查，不能提交内容决定。", "warning"));
      const issueTitle = node("strong", "风险标记：");
      top.append(issueTitle);
      addTextList(top, item.issues);
      host.append(top);

      const audio = node("section", null, "panel");
      audio.append(node("h3", "源音频"));
      if (current.youtubeEmbedUrl) {
        const frame = node("iframe");
        frame.src = current.youtubeEmbedUrl;
        frame.title = `${item.reviewItemId} 源音频`;
        frame.allow = "encrypted-media; picture-in-picture";
        frame.referrerPolicy = "no-referrer";
        audio.append(frame);
        const link = node("a", "在 YouTube 时间点打开");
        link.href = current.youtubeUrl;
        link.target = "_blank";
        link.rel = "noreferrer noopener";
        audio.append(link);
      } else audio.append(node("p", "无法构造源音频链接。"));
      host.append(audio);

      const textPanel = node("section", null, "panel columns");
      const enBox = node("div");
      enBox.append(node("label", "批准后的英文"));
      const enDecision = node("select"); enDecision.id = "englishDecision";
      for (const optionValue of ["keep","corrected","reject"]) { const option = node("option", optionValue); option.value = optionValue; enDecision.append(option); }
      enDecision.value = ["keep","corrected","reject"].includes(decision.englishDecision) ? decision.englishDecision : "keep";
      const en = node("textarea"); en.id = "approvedEnglish"; en.value = decision.approvedEnglish || item.source.english;
      en.addEventListener("input", () => { enDecision.value = en.value === item.source.english ? "keep" : "corrected"; });
      enBox.append(enDecision, en);
      const zhBox = node("div");
      zhBox.append(node("label", "批准后的中文"));
      const zhDecision = node("select"); zhDecision.id = "chineseDecision";
      for (const optionValue of ["keep","corrected","reject"]) { const option = node("option", optionValue); option.value = optionValue; zhDecision.append(option); }
      zhDecision.value = ["keep","corrected","reject"].includes(decision.chineseDecision) ? decision.chineseDecision : "keep";
      const zh = node("textarea"); zh.id = "approvedChinese"; zh.value = decision.approvedChinese || item.candidate.chinese;
      zh.addEventListener("input", () => { zhDecision.value = zh.value === item.candidate.chinese ? "keep" : "corrected"; });
      zhBox.append(zhDecision, zh);
      textPanel.append(enBox, zhBox);
      host.append(textPanel);

      const evidence = node("section", null, "panel columns");
      const scripture = node("div"); scripture.append(node("h3", "经文对齐"), node("pre", JSON.stringify(item.candidate.scriptureAlignments, null, 2)));
      const names = node("div"); names.append(node("h3", "专名与模型备注"), node("pre", JSON.stringify({properNouns: item.candidate.properNouns, modelNotes: item.candidate.modelNotes}, null, 2)));
      evidence.append(scripture, names); host.append(evidence);

      const form = node("section", null, "panel");
      const reviewerColumns = node("div", null, "columns");
      const reviewerBox = node("div"); reviewerBox.append(node("label", "审核者"));
      const reviewer = node("input"); reviewer.type = "text"; reviewer.id = "reviewer"; reviewer.value = decision.reviewer || localStorage.getItem("sermonReviewer") || ""; reviewerBox.append(reviewer);
      const roleBox = node("div"); roleBox.append(node("label", "审核角色"));
      const role = node("input"); role.type = "text"; role.id = "reviewerRole"; role.value = decision.reviewerRole || localStorage.getItem("sermonReviewerRole") || "bilingual_reviewer"; roleBox.append(role);
      reviewerColumns.append(reviewerBox, roleBox); form.append(reviewerColumns);
      form.append(node("label", "最终决定"));
      const status = node("select"); status.id = "decisionStatus";
      for (const [optionValue, label] of [["","请选择"],["approved","批准"],["changes_required","需要修订"],["rejected","拒绝"]]) { const option = node("option", label); option.value = optionValue; status.append(option); }
      status.value = decision.status === "pending_human_input" ? "" : decision.status;
      form.append(status);
      const checks = node("div", null, "checks");
      for (const [id, label] of [["audioChecked","已听源音频"],["scriptureChecked","已核对经文"],["properNounsChecked","已核对专名"],["numbersChecked","已核对数字"],["adjudicationComplete","裁决已完成"]]) {
        const wrapper = node("label"); const box = node("input"); box.type = "checkbox"; box.id = id; box.checked = Boolean(decision[id]); wrapper.append(box, document.createTextNode(` ${label}`)); checks.append(wrapper);
      }
      form.append(node("h3", "候选中的 material error 类型"), checks);
      const risks = node("div", null, "risk-grid");
      for (const errorType of ERROR_TYPES) { const wrapper = node("label"); const box = node("input"); box.type = "checkbox"; box.dataset.errorType = errorType; box.checked = (decision.materialErrorTypes || []).includes(errorType); wrapper.append(box, document.createTextNode(` ${errorType}`)); risks.append(wrapper); }
      form.append(risks, node("label", "审核备注"));
      const notes = node("textarea"); notes.id = "notes"; notes.value = decision.notes || ""; notes.style.minHeight = "80px"; form.append(notes);
      const actions = node("div", null, "actions");
      const message = node("span", "", null); message.id = "message";
      const save = node("button", READ_ONLY ? "只读模式" : "保存最终决定", "primary"); save.disabled = READ_ONLY || !item.boundary.approvedByHuman; save.addEventListener("click", saveDecision);
      actions.append(message, save); form.append(actions); host.append(form);
    }
    async function saveDecision() {
      const status = value("decisionStatus");
      if (!status) { document.getElementById("message").textContent = "请选择最终决定。"; return; }
      if (status === "approved" && !window.confirm("确认已听源音频并完成全部核对，保存为人工批准？")) return;
      const reviewer = value("reviewer").trim(); const reviewerRole = value("reviewerRole").trim();
      localStorage.setItem("sermonReviewer", reviewer); localStorage.setItem("sermonReviewerRole", reviewerRole);
      const materialErrorTypes = [...document.querySelectorAll("[data-error-type]:checked")].map(element => element.dataset.errorType);
      const body = {
        expectedDecisionSha256: current.decisionSha256,
        status, reviewer, reviewerRole,
        audioChecked: checked("audioChecked"),
        englishDecision: value("englishDecision"), approvedEnglish: value("approvedEnglish"),
        chineseDecision: value("chineseDecision"), approvedChinese: value("approvedChinese"),
        scriptureChecked: checked("scriptureChecked"), properNounsChecked: checked("properNounsChecked"), numbersChecked: checked("numbersChecked"),
        materialErrorTypes, adjudicationComplete: checked("adjudicationComplete"), notes: value("notes")
      };
      const message = document.getElementById("message"); message.textContent = "保存中…";
      try {
        const result = await api(`/api/items/${encodeURIComponent(current.item.reviewItemId)}/decision`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
        message.textContent = `已保存；receipt ${result.historyReceipt}`;
        current = await api(`/api/items/${encodeURIComponent(current.item.reviewItemId)}`);
        await refresh(true);
      } catch (error) { message.textContent = error.message; }
    }
    document.getElementById("priority").addEventListener("change", () => refresh(false));
    document.getElementById("state").addEventListener("change", () => refresh(false));
    refresh(false).catch(error => { document.getElementById("content").textContent = error.message; });
  </script>
</body>
</html>
"""


def render_html(*, read_only: bool, nonce: str) -> str:
    return HTML_TEMPLATE.replace("__NONCE__", nonce).replace(
        "__READ_ONLY__", "true" if read_only else "false"
    )


def make_handler(
    *, store: ReviewStore, token: str, read_only: bool
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "SermonReview/1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def allowed_host(self) -> bool:
            port = int(self.server.server_address[1])
            return self.headers.get("Host", "") in {
                f"127.0.0.1:{port}",
                f"localhost:{port}",
            }

        def has_session(self) -> bool:
            raw = self.headers.get("Cookie", "")
            jar = cookies.SimpleCookie()
            try:
                jar.load(raw)
            except cookies.CookieError:
                return False
            morsel = jar.get("sermon_review_session")
            return morsel is not None and hmac.compare_digest(morsel.value, token)

        def send_common_headers(self, *, content_type: str, length: int) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")

        def send_json(self, status: int, value: Any) -> None:
            payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_common_headers(
                content_type="application/json; charset=utf-8", length=len(payload)
            )
            self.end_headers()
            self.wfile.write(payload)

        def send_error_json(self, status: int, message: str) -> None:
            self.send_json(status, {"error": message})

        def authenticated_api(self) -> bool:
            if not self.allowed_host():
                self.send_error_json(421, "unexpected Host header")
                return False
            if not self.has_session():
                self.send_error_json(401, "review session cookie required")
                return False
            return True

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self.send_json(200, {"status": "ok", "readOnly": read_only})
                return
            if not self.allowed_host():
                self.send_error_json(421, "unexpected Host header")
                return
            if parsed.path == "/" and parse_qs(parsed.query).get("token") == [token]:
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header(
                    "Set-Cookie",
                    f"sermon_review_session={token}; Path=/; HttpOnly; SameSite=Strict",
                )
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if parsed.path == "/":
                if not self.has_session():
                    self.send_error_json(401, "open the one-time review URL again")
                    return
                nonce = secrets.token_urlsafe(18)
                payload = render_html(read_only=read_only, nonce=nonce).encode("utf-8")
                self.send_response(200)
                self.send_common_headers(
                    content_type="text/html; charset=utf-8", length=len(payload)
                )
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'none'; "
                    f"script-src 'nonce-{nonce}'; "
                    "style-src 'unsafe-inline'; connect-src 'self'; "
                    "frame-src https://www.youtube-nocookie.com; "
                    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
                )
                self.end_headers()
                self.wfile.write(payload)
                return
            if not parsed.path.startswith("/api/") or not self.authenticated_api():
                if parsed.path.startswith("/api/"):
                    return
                self.send_error_json(404, "not found")
                return
            try:
                if parsed.path == "/api/summary":
                    self.send_json(200, store.summary())
                    return
                if parsed.path == "/api/items":
                    query = parse_qs(parsed.query)
                    priority = query.get("priority", [None])[0] or None
                    state = query.get("state", ["all"])[0]
                    self.send_json(
                        200,
                        {"items": store.list_items(priority=priority, state=state)},
                    )
                    return
                prefix = "/api/items/"
                if parsed.path.startswith(prefix):
                    item_id = unquote(parsed.path[len(prefix) :])
                    if "/" in item_id or not item_id:
                        raise KeyError(item_id)
                    self.send_json(200, store.get_item(item_id))
                    return
                self.send_error_json(404, "not found")
            except KeyError:
                self.send_error_json(404, "unknown review item")
            except ValueError as exc:
                self.send_error_json(400, str(exc))

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if not self.authenticated_api():
                return
            if read_only:
                self.send_error_json(403, "server is in read-only mode")
                return
            origin = self.headers.get("Origin")
            port = int(self.server.server_address[1])
            if origin and origin not in {
                f"http://127.0.0.1:{port}",
                f"http://localhost:{port}",
            }:
                self.send_error_json(403, "cross-origin write rejected")
                return
            match = re.fullmatch(r"/api/items/([^/]+)/decision", parsed.path)
            if not match:
                self.send_error_json(404, "not found")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error_json(400, "invalid Content-Length")
                return
            if length <= 0 or length > MAX_REQUEST_BYTES:
                self.send_error_json(413, "request body is empty or too large")
                return
            try:
                submitted = json.loads(self.rfile.read(length))
                if not isinstance(submitted, dict):
                    raise ValueError("request JSON must be an object")
                item_id = unquote(match.group(1))
                expected = submitted.pop("expectedDecisionSha256", None)
                result = store.save_decision(
                    item_id=item_id,
                    submitted=submitted,
                    expected_decision_sha256=expected,
                )
            except json.JSONDecodeError:
                self.send_error_json(400, "invalid JSON")
            except KeyError:
                self.send_error_json(404, "unknown review item")
            except DecisionConflict as exc:
                self.send_error_json(409, str(exc))
            except BoundaryNotApproved as exc:
                self.send_error_json(409, str(exc))
            except (TypeError, ValueError) as exc:
                self.send_error_json(400, str(exc))
            else:
                self.send_json(200, result)

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--review-root",
        type=Path,
        default=Path("data/derived/sermon-parallel-review-poc-v1"),
    )
    parser.add_argument(
        "--decisions",
        type=Path,
        default=Path(
            "data/derived/sermon-parallel-review-poc-v1/human-decisions.jsonl"
        ),
    )
    parser.add_argument(
        "--history-root",
        type=Path,
        default=Path(
            "data/derived/sermon-parallel-review-poc-v1/decision-history"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(
            "data/reports/sermon-parallel-review-poc-v1/review-tool-check.json"
        ),
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    args.review_root = corpus.resolve_path(args.review_root)
    args.decisions = corpus.resolve_path(args.decisions)
    args.history_root = corpus.resolve_path(args.history_root)
    args.report = corpus.resolve_path(args.report)
    return args


def main() -> int:
    args = parse_args()
    store = ReviewStore(
        review_root=args.review_root,
        decisions_path=args.decisions,
        history_root=args.history_root,
    )
    summary = store.summary()
    if args.check:
        report = {
            **summary,
            "toolStatus": "review_tool_ready",
            "writeReady": summary["unapprovedBoundaryItems"] == 0,
            "decisionsPath": corpus.display_path(args.decisions),
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
            "generatedAt": corpus.utc_now(),
        }
        corpus.write_json(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not args.read_only and summary["unapprovedBoundaryItems"]:
        raise SystemExit(
            "Writable content review is blocked: approve sermon-only boundaries, "
            "regenerate the POC, and export a fresh review bundle first. "
            "Use --read-only to inspect the current bundle."
        )
    token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(store=store, token=token, read_only=args.read_only),
    )
    port = int(server.server_address[1])
    url = f"http://127.0.0.1:{port}/?token={quote(token)}"
    print(
        json.dumps(
            {
                "status": "serving",
                "url": url,
                "readOnly": args.read_only,
                "summary": summary,
                "bind": f"127.0.0.1:{port}",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
