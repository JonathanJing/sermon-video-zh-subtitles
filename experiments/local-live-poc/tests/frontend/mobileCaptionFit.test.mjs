import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

// Exercise the shipped sizing code against constrained boxes and independently
// measured wrapped text. Real browser font/layout geometry is checked separately.
async function fitter(path) {
  const source = await readFile(new URL(path, import.meta.url), "utf8");
  const start = source.indexOf("function fitCaptionPair(");
  const end = source.indexOf("function scheduleFit(", start);
  const sandbox = { getComputedStyle: (element) => ({ ...element.css,
    ...Object.fromEntries(Object.entries(element.style).filter(([, value]) => value !== "")),
  }) };
  vm.runInNewContext(source.slice(start, end), sandbox);
  return { fit: sandbox.fitCaptionPair, source };
}

function pair(width, height, zhSize, enSize, gap) {
  const box = { clientWidth: width, clientHeight: height, hidden: false,
    style: {}, css: { paddingTop: "7px", paddingBottom: "7px", paddingLeft: "0px", paddingRight: "0px" } };
  const paragraph = (size, lineHeight, marginTop) => ({
    textContent: "", style: {}, css: { fontSize: `${size}px`, marginTop: `${marginTop}px` },
    get scrollWidth() { return box.clientWidth; },
    get scrollHeight() {
      if (!this.textContent) return 0;
      const font = parseFloat(this.style.fontSize || this.css.fontSize);
      const units = [...this.textContent].reduce((sum, char) => sum + (char.codePointAt(0) > 255 ? 1 : 0.55), 0);
      return Math.ceil(Math.ceil(units * font / box.clientWidth) * font * lineHeight);
    },
  });
  const zh = paragraph(zhSize, 1.14, 0), en = paragraph(enSize, 1.45, gap);
  return { box, zh, en, usedHeight: () => zh.scrollHeight + en.scrollHeight + parseFloat(en.style.marginTop) + 14 };
}

for (const [name, path] of [
  ["Firebase", "../../firebase/public/viewer.js"],
  ["LAN", "../../backend/viewer_server.py"],
]) {
  test(`${name} fits long bilingual pairs in landscape and portrait without changing either source`, async () => {
    const { fit } = await fitter(path);
    for (const [width, height, zhSize, enSize] of [[742, 150, 70.896, 26], [742, 72, 32, 13], [354, 315, 60, 17]]) {
      const p = pair(width, height, zhSize, enSize, 8);
      p.zh.textContent = "当我们面对明天的挑战时，我们仍然可以凭着信心前行，因为上帝的恩典始终引领我们。";
      p.en.textContent = "When we face the challenges of tomorrow, we can still walk by faith because God's grace continues to lead us.";
      const text = [p.zh.textContent, p.en.textContent];
      fit(p.box, p.zh, p.en);
      assert.ok(p.usedHeight() <= height, `${name}: used ${p.usedHeight()} of ${height}px`);
      assert.ok(parseFloat(p.zh.style.fontSize) > parseFloat(p.en.style.fontSize));
      assert.deepEqual([p.zh.textContent, p.en.textContent], text);
    }
  });

  test(`${name} restores the maximum font after a short caption or more available height`, async () => {
    const { fit } = await fitter(path);
    const p = pair(742, 150, 70.896, 26, 8);
    p.zh.textContent = "我们凭着信心面对明天的挑战，上帝的恩典引领我们继续前行。";
    p.en.textContent = "We face tomorrow's challenges by faith, and God's grace leads us onward.";
    fit(p.box, p.zh, p.en);
    const reduced = parseFloat(p.zh.style.fontSize);
    assert.ok(reduced < 70.896);
    p.box.clientHeight = 450;
    fit(p.box, p.zh, p.en);
    assert.equal(parseFloat(p.zh.style.fontSize), 70.896);
    p.box.clientHeight = 150;
    p.zh.textContent = "恩典。";
    p.en.textContent = "Grace.";
    fit(p.box, p.zh, p.en);
    assert.equal(parseFloat(p.zh.style.fontSize), 70.896);
    fit(p.box, p.zh, p.en, 1.35);
    assert.ok(p.usedHeight() <= p.box.clientHeight, "manual increase must still respect the caption box");
  });
}

test("viewer grids reserve explicit caption rows even when demo and previous are hidden", async () => {
  const css = await readFile(new URL("../../firebase/public/styles.css", import.meta.url), "utf8");
  assert.match(css, /\.viewer-shell \{ height: 100dvh;/);
  assert.match(css, /\.previous \{ grid-row: 2;/);
  assert.match(css, /\.active \{ grid-row: 4;/);
  assert.match(css, /\[hidden\] \{ display: none !important; \}/);
  const { source } = await fitter("../../backend/viewer_server.py");
  assert.match(source, /\.current\{grid-row:3;/);
  assert.doesNotMatch(source, /current\.style\.transform/);
});
