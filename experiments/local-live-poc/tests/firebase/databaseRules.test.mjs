import assert from "node:assert/strict";
import { after, before, beforeEach, test } from "node:test";
import { readFile } from "node:fs/promises";

import {
  assertFails,
  assertSucceeds,
  initializeTestEnvironment,
} from "@firebase/rules-unit-testing";
import { get, ref, set } from "firebase/database";

const projectId = "demo-ai-for-god-caption-dev";
const rulesPath = new URL("../../firebase/database.rules.json", import.meta.url);
let testEnvironment;

function captionSnapshot(overrides = {}) {
  const now = Date.now();
  return {
    schemaVersion: 1,
    status: "live",
    sequence: 1,
    previousFinal: null,
    active: {
      segmentId: "seg-1",
      sourceTextEn: "We walk by faith.",
      targetTextZh: "我们凭信心而行。",
      phase: "final",
    },
    publishedAt: now,
    expiresAt: now + 60 * 60 * 1000,
    ...overrides,
  };
}

async function seed(path, value) {
  await testEnvironment.withSecurityRulesDisabled(async (context) => {
    await set(ref(context.database(), path), value);
  });
}

before(async () => {
  testEnvironment = await initializeTestEnvironment({
    projectId,
    database: {
      host: "127.0.0.1",
      port: 9000,
      rules: await readFile(rulesPath, "utf8"),
    },
  });
});

beforeEach(async () => {
  await testEnvironment.clearDatabase();
});

after(async () => {
  await testEnvironment.cleanup();
});

test("anonymous viewer can read one live unexpired session", async () => {
  const token = "valid_token_1234567890123456";
  await seed(`sessions/${token}`, captionSnapshot());
  const snapshot = await assertSucceeds(
    get(ref(testEnvironment.unauthenticatedContext().database(), `sessions/${token}`)),
  );
  assert.equal(snapshot.val().active.targetTextZh, "我们凭信心而行。");
});

test("anonymous viewer cannot read the database root or an expired session", async () => {
  const token = "expired_token_12345678901234";
  await seed(`sessions/${token}`, captionSnapshot({ expiresAt: Date.now() - 1 }));
  const database = testEnvironment.unauthenticatedContext().database();
  await assertFails(get(ref(database)));
  await assertFails(get(ref(database, `sessions/${token}`)));
});

test("anonymous viewer cannot write captions", async () => {
  await assertFails(set(
    ref(testEnvironment.unauthenticatedContext().database(), "sessions/anonymous_token_1234567890"),
    captionSnapshot(),
  ));
});

test("publisher claim can write a valid caption snapshot", async () => {
  const database = testEnvironment.authenticatedContext("publisher", {
    captionPublisher: true,
  }).database();
  await assertSucceeds(set(
    ref(database, "sessions/publisher_token_1234567890"),
    captionSnapshot(),
  ));
});

test("rules reject unknown fields and sequence rollback", async () => {
  const token = "publisher_token_rollback_12345";
  const database = testEnvironment.authenticatedContext("publisher", {
    captionPublisher: true,
  }).database();
  await assertFails(set(
    ref(database, `sessions/${token}`),
    captionSnapshot({ unexpected: "blocked" }),
  ));
  await seed(`sessions/${token}`, captionSnapshot({ sequence: 3 }));
  await assertFails(set(
    ref(database, `sessions/${token}`),
    captionSnapshot({ sequence: 2 }),
  ));
});
