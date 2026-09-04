import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const viewerHtml = new URL("../../firebase/public/index.html", import.meta.url);

test("public viewer initializes the provisioned non-default RTDB instance", async () => {
  const html = await readFile(viewerHtml, "utf8");
  assert.match(html, /https:\/\/ai-for-god-caption-dev\.firebaseio\.com/);
  assert.doesNotMatch(html, /\/__\/firebase\/init\.js/);
});

test("public viewer identifies the Sunday sermon and carries an AI disclaimer", async () => {
  const html = await readFile(viewerHtml, "utf8");
  assert.match(html, /主日证道 · 中文字幕/);
  assert.match(html, /AI 实时生成，仅供辅助理解/);
  assert.match(html, /可能存在遗漏或误译/);
  assert.doesNotMatch(html, /<h1>现场中文字幕<\/h1>/);
});
