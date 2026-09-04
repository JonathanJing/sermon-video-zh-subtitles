import assert from "node:assert/strict";
import test from "node:test";

import { applyCaptionEvent, createCaptionState } from "../../src/captionState.js";

test("a new ASR final moves only a completed bilingual pair to previous", () => {
  let state = createCaptionState();
  state = applyCaptionEvent(state, {
    type: "asr.final",
    segmentId: "seg-1",
    sourceTextEn: "We walk by faith.",
  });
  state = applyCaptionEvent(state, {
    type: "translation.final",
    segmentId: "seg-1",
    sourceTextEn: "We walk by faith.",
    targetTextZh: "我们凭信心而行。",
  });
  state = applyCaptionEvent(state, {
    type: "asr.final",
    segmentId: "seg-2",
    sourceTextEn: "That changes tomorrow.",
  });

  assert.deepEqual(state.previousFinal, {
    segmentId: "seg-1",
    en: "We walk by faith.",
    zh: "我们凭信心而行。",
  });
  assert.deepEqual(state.active, {
    segmentId: "seg-2",
    en: "That changes tomorrow.",
    zh: "",
    phase: "requesting",
  });
});

test("an unfinished segment never replaces the previous final", () => {
  const previousFinal = { segmentId: "seg-0", en: "Grace leads.", zh: "恩典引领。" };
  const state = applyCaptionEvent({
    previousFinal,
    active: { segmentId: "seg-1", en: "Draft", zh: "草稿", phase: "streaming" },
  }, {
    type: "asr.final",
    segmentId: "seg-2",
    sourceTextEn: "Next sentence.",
  });

  assert.equal(state.previousFinal, previousFinal);
  assert.equal(state.active.zh, "");
});

test("stale translation updates do not overwrite the active segment", () => {
  const state = {
    previousFinal: null,
    active: { segmentId: "seg-2", en: "Current", zh: "当前", phase: "streaming" },
  };
  assert.equal(applyCaptionEvent(state, {
    type: "translation.final",
    segmentId: "seg-1",
    sourceTextEn: "Old",
    targetTextZh: "旧句",
  }), state);
});
