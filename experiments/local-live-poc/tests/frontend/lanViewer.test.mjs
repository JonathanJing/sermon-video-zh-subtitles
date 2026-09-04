import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

async function viewer() {
  const server = await readFile(new URL("../../backend/viewer_server.py", import.meta.url), "utf8");
  const html = server.match(/VIEWER_HTML = """([\s\S]*?)"""/)[1];
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1].replace("__TOKEN__", JSON.stringify("test-viewer-token"));
  const elements = new Map();
  let source;
  const sandbox = {
    document: {
      querySelector(selector) {
        if (!elements.has(selector)) elements.set(selector, { style: {}, classList: { toggle() {} } });
        return elements.get(selector);
      },
    },
    EventSource: class {
      constructor() { source = this; }
    },
    requestAnimationFrame() { return 1; },
    window: { addEventListener() {} },
  };
  vm.runInNewContext(script, sandbox);
  return { elements, deliver: (event) => source.onmessage({ data: JSON.stringify(event) }) };
}

test("LAN viewer clears ended state on same-token stream.ready and resumed snapshots", async () => {
  const { elements, deliver } = await viewer();
  const snapshot = {
    type: "caption.snapshot", sessionActive: false, previousFinal: null,
    active: { segmentId: "old", sourceTextEn: "Faith.", targetTextZh: "信心。", phase: "final" },
  };
  deliver(snapshot);
  assert.equal(elements.get("#status").textContent, "本场已结束");
  deliver({ type: "stream.ready" });
  assert.equal(elements.get("#status").textContent, "字幕连接正常");
  assert.equal(elements.get("#status").className, "ok");
  assert.equal(elements.get("#zh").textContent, "信心。");
  deliver({
    type: "caption.display", segmentId: "new", sourceTextEn: "Hope.", targetTextZh: "盼望。",
    displayKind: "final", phase: "final",
  });
  assert.equal(elements.get("#status").textContent, "字幕连接正常");
  assert.equal(elements.get("#previous-zh").textContent, "信心。");
  assert.equal(elements.get("#zh").textContent, "盼望。");
  deliver({ type: "stream.closed" });
  assert.equal(elements.get("#status").textContent, "本场已结束");
  deliver({ ...snapshot, sessionActive: true });
  assert.equal(elements.get("#status").textContent, "字幕连接正常");
});
