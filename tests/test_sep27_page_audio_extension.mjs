import test from "node:test";
import assert from "node:assert/strict";
import {
  audioAvailabilityMessage, bindDubPlayback, dubOutputFromVideo,
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

test("dub pauses during video buffering and resumes only while active and playing", async () => {
  const video = new EventTarget();
  video.readyState = 4;
  video.paused = false;
  let active = true;
  let plays = 0;
  let pauses = 0;
  let failures = 0;
  const audio = {
    play: async () => { plays += 1; },
    pause: () => { pauses += 1; }
  };
  bindDubPlayback(video, audio, () => active, () => { failures += 1; });
  video.dispatchEvent(new Event("play"));
  assert.equal(plays, 1);
  video.dispatchEvent(new Event("waiting"));
  assert.equal(pauses, 1);
  video.dispatchEvent(new Event("play"));
  assert.equal(plays, 1, "a play event does not override the buffering pause");
  video.dispatchEvent(new Event("playing"));
  assert.equal(plays, 2);
  video.dispatchEvent(new Event("stalled"));
  assert.equal(pauses, 2);
  active = false;
  video.dispatchEvent(new Event("playing"));
  assert.equal(plays, 2, "English original never starts a dub");
  active = true;
  video.paused = true;
  video.dispatchEvent(new Event("pause"));
  video.dispatchEvent(new Event("playing"));
  assert.equal(plays, 2, "an explicit user pause remains paused");
  video.paused = false;
  video.dispatchEvent(new Event("playing"));
  assert.equal(plays, 3);
  assert.equal(failures, 0);
});

test("a play rejection after buffering does not discard the selected dub", async () => {
  const video = new EventTarget();
  video.readyState = 4;
  video.paused = false;
  let rejectPlay;
  let failures = 0;
  const audio = {
    play: () => new Promise((_, reject) => { rejectPlay = reject; }),
    pause: () => {}
  };
  const playback = bindDubPlayback(video, audio, () => true,
    () => { failures += 1; });
  const pending = playback.play();
  video.dispatchEvent(new Event("waiting"));
  rejectPlay(new Error("play interrupted by pause"));
  await pending;
  assert.equal(failures, 0);
});
