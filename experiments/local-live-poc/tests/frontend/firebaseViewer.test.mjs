import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const viewerHtml = new URL("../../firebase/public/index.html", import.meta.url);

test("public viewer initializes the provisioned non-default RTDB instance", async () => {
  const html = await readFile(viewerHtml, "utf8");
  assert.match(html, /https:\/\/ai-for-god-caption-dev\.firebaseio\.com/);
  assert.doesNotMatch(html, /\/__\/firebase\/init\.js/);
});

test("public viewer identifies the Sunday sermon and carries the PDF-aligned disclaimer", async () => {
  const html = await readFile(viewerHtml, "utf8");
  assert.match(html, /主日证道 · 中文字幕/);
  assert.match(html, /独立个人非官方项目/);
  assert.match(html, /无隶属、授权或背书关系/);
  assert.match(html, /AI 辅助英文听写和中文翻译/);
  assert.match(html, /教会官方资料及讲员原始英文为准/);
  assert.doesNotMatch(html, /<h1>现场中文字幕<\/h1>/);
});
