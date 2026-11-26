// apps/review-web/coverage.mjs: the review mode on a track receipt comes from what was played.
import assert from "node:assert/strict";
import test from "node:test";
import { createCoverage, reviewMode } from "../apps/review-web/coverage.mjs";

function play(coverage, from, to, rate = 1, step = 0.25) {
  for (let t = from; t <= to + 1e-9; t += step) coverage.tick(t, rate);
  coverage.stop();
}

test("continuous playback at 1x is credited second by second", () => {
  const coverage = createCoverage(60);
  play(coverage, 0, 29.9);
  const summary = coverage.summary();
  assert.equal(summary.heardSecondsAt1x, 30);
  assert.equal(summary.shareAt1x, 0.5);
  assert.deepEqual(summary.playbackRates, [1]);
});

test("a seek does not credit the part that was skipped", () => {
  const coverage = createCoverage(60);
  play(coverage, 0, 4.9);
  coverage.tick(40, 1);              // jumped without stop(): more than 2 s away, so not listening
  play(coverage, 40, 44.9);
  assert.equal(coverage.summary().heardSecondsAt1x, 10);
  assert.equal(coverage.covers(0, 5), true);
  assert.equal(coverage.covers(5, 40), false);
});

test("faster playback is recorded apart from 1x", () => {
  const coverage = createCoverage(20);
  play(coverage, 0, 19.9, 1.5);
  const summary = coverage.summary();
  assert.equal(summary.heardSecondsAt1x, 0);
  assert.equal(summary.heardSecondsAnySpeed, 20);
  assert.deepEqual(summary.playbackRates, [1.5]);
  assert.equal(coverage.covers(3, 9), true, "a sentence heard at 1.5x still counts as heard");
});

test("a saved snapshot restores only for the same track length", () => {
  const first = createCoverage(30);
  play(first, 0, 9.9);
  const same = createCoverage(30);
  same.restore(first.snapshot());
  assert.equal(same.summary().heardSecondsAt1x, 10);
  const other = createCoverage(31);
  other.restore(first.snapshot());
  assert.equal(other.summary().heardSecondsAt1x, 0);
});

test("review mode is measured, and a declaration is labelled as one", () => {
  const flaggedIds = ["s1", "s2"];
  assert.deepEqual(reviewMode({ shareAt1x: 0.99, flaggedIds, heardIds: [] }),
    { mode: "whole_track", basis: "measured", missingFlagged: ["s1", "s2"] });
  assert.deepEqual(reviewMode({ shareAt1x: 0.4, flaggedIds, heardIds: ["s1", "s2", "s9"] }),
    { mode: "flagged_only", basis: "measured", missingFlagged: [] });
  assert.deepEqual(reviewMode({ shareAt1x: 0.4, flaggedIds, heardIds: ["s1"] }),
    { mode: "partial", basis: "measured", missingFlagged: ["s2"] });
  assert.equal(reviewMode({ shareAt1x: 0.1, flaggedIds, heardIds: [], declaredWholeTrackElsewhere: true }).basis, "declared");
});
