import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const template = readFileSync(new URL("../firebase/production-overlay/legacy-query-router.js", import.meta.url), "utf8");
const script = template.replace("__LEGACY_WEEK_IDS__", JSON.stringify(["old-week"]));

function redirectedUrl(pathname, search) {
  let redirected;
  vm.runInNewContext(script, {
    Set, URLSearchParams,
    location: { pathname, search, hash: "", replace: url => { redirected = url; } }
  });
  return redirected;
}

test("old poster links open the preserved Chinese reader", () => {
  assert.equal(redirectedUrl("/", "?week=old-week"),
    "/legacy-reader.html?week=old-week");
});

test("new multilingual poster links remain in the formal reader", () => {
  assert.equal(redirectedUrl("/", "?week=new-four-layer-week"), undefined);
  assert.equal(redirectedUrl("/pages/new-four-layer-week/ko", "?week=old-week"), undefined);
});
