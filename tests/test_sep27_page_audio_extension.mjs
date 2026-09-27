import test from "node:test";
import assert from "node:assert/strict";
import {
  audioAvailabilityMessage, dubOutputFromVideo,
  validateAudioExtension, validateSpokenCaptions
} from "../firebase/dev/public/sep27-page-audio-extension.mjs";

const page = { pageId: "2026-09-27-weekend-sermon-drive-530",
  sourceSha256: "1".repeat(64), duration: 1891.677333 };
const row = {
  displayCandidateJsonSha256: "2".repeat(64), displayContentSha256: "3".repeat(64),
  spokenCandidateJsonSha256: "4".repeat(64), audioPackageJsonSha256: "5".repeat(64),
  audioHumanReviewReceiptJsonSha256: "6".repeat(64),
  machineScreeningReceiptJsonSha256: "7".repeat(64),
  audio: { path: "/media/track.mp3", sha256: "8".repeat(64) },
  captions: { path: "/captions/spoken.json", sha256: "9".repeat(64) },
  durationSeconds: page.duration, spokenCueCount: 1
};
const manifest = {
  schemaVersion: "sermon-full-video-audio-extension-v1",
  pageId: page.pageId,
  englishSourcePackageJsonSha256: "a".repeat(64),
  sourceMediaSha256: page.sourceSha256,
  pageDataSha256: "fa071d1b7678eeaad7c5ae4c1539d2b6f8b908322b2e12283881b0be304362f3",
  status: "three_locale_audio_human_reviewed_candidate",
  locales: { "zh-Hans": row, ko: row, es: row }
};

test("separate full display and spoken identities validate", () => {
  assert.equal(validateAudioExtension(manifest, page), manifest);
  assert.notEqual(row.displayCandidateJsonSha256, row.spokenCandidateJsonSha256);
});

test("missing locale or cross-origin audio is rejected", () => {
  const missing = structuredClone(manifest);
  delete missing.locales.es;
  assert.throws(() => validateAudioExtension(missing, page));
  const external = structuredClone(manifest);
  external.locales.ko.audio.path = "//other.example/track.mp3";
  assert.throws(() => validateAudioExtension(external, page));
});

test("spoken captions have their own timed text contract", () => {
  const captions = { cues: [{ textGroupId: "g1", text: "短口播", start: 0.4, end: 1.2 }] };
  assert.equal(validateSpokenCaptions(captions, 1, page.duration), captions.cues);
  assert.throws(() => validateSpokenCaptions(captions, 2, page.duration));
  captions.cues[0].end = page.duration + 1;
  assert.throws(() => validateSpokenCaptions(captions, 1, page.duration));
});

test("loading and failed tracks have distinct user-visible status", () => {
  assert.equal(audioAvailabilityMessage("loading"), "配音加载中…");
  assert.equal(audioAvailabilityMessage("ready"), "配音已就绪");
  assert.match(audioAvailabilityMessage("unavailable"), /配音暂不可用/);
  assert.equal(audioAvailabilityMessage(""), "");
});

test("dub output follows video volume and the user's mute intent", () => {
  assert.deepEqual(dubOutputFromVideo(0.35, false), { volume: 0.35, muted: false });
  assert.deepEqual(dubOutputFromVideo(0.8, true), { volume: 0.8, muted: true });
  assert.deepEqual(dubOutputFromVideo(0, false), { volume: 0, muted: false });
  assert.throws(() => dubOutputFromVideo(1.1, false));
});
