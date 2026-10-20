#!/usr/bin/env node
/** Dev-only Firestore -> local JSON transport probe. Never applies a review. */
import { randomUUID, createHash } from 'node:crypto';
import { mkdir, open, readFile, rename, rm } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { applicationDefault, initializeApp } from 'firebase-admin/app';
import { getFirestore } from 'firebase-admin/firestore';

const PROJECT = 'ai-for-god-sermon-audio-dev';
const DATABASE = 'sermon-tracker';
const COLLECTION = 'trackerBridgeMockCommands';
const SCHEMA = 'sermon-tracker-bridge-mock-v1';

function options(argv) {
  const [action, ...rest] = argv;
  if (!['send', 'receive', 'inspect'].includes(action)) throw new Error('use send, receive, or inspect');
  const result = { action };
  for (let i = 0; i < rest.length; i += 2) {
    const flag = rest[i];
    if (!['--page-id', '--step-id', '--inbox', '--id', '--timeout-seconds'].includes(flag) || !rest[i + 1]) {
      throw new Error(`invalid option: ${flag}`);
    }
    result[flag.slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = rest[i + 1];
  }
  if (action !== 'inspect' && (!result.pageId || !/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,100}$/.test(result.pageId))) {
    throw new Error('valid --page-id required');
  }
  if (action === 'send' && (!result.stepId || !/^L[1-4]-\d\d(?:@[a-zA-Z-]+)?$/.test(result.stepId))) {
    throw new Error('valid --step-id required');
  }
  if (action === 'receive' && !result.inbox) throw new Error('--inbox required');
  if (action === 'inspect' && !/^[0-9a-f-]{36}$/.test(result.id || '')) throw new Error('valid --id required');
  result.timeoutSeconds = Number(result.timeoutSeconds || 45);
  if (!Number.isInteger(result.timeoutSeconds) || result.timeoutSeconds < 5 || result.timeoutSeconds > 300) {
    throw new Error('timeout must be 5–300 seconds');
  }
  return result;
}

function database() {
  const app = initializeApp({ credential: applicationDefault(), projectId: PROJECT });
  return getFirestore(app, DATABASE);
}

function validate(command, id, pageId) {
  if (command.schemaVersion !== SCHEMA || command.action !== 'mock_ping' || command.mockOnly !== true
      || command.commandId !== id || command.pageId !== pageId
      || !/^L[1-4]-\d\d(?:@[a-zA-Z-]+)?$/.test(command.stepId || '')) {
    throw new Error('invalid mock command');
  }
}

async function writeInbox(path, payload) {
  const contents = `${JSON.stringify(payload, null, 2)}\n`;
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  try {
    const prior = JSON.parse(await readFile(path, 'utf8'));
    if (prior.commandId !== payload.commandId || prior.pageId !== payload.pageId || prior.action !== payload.action) {
      throw new Error('existing inbox file does not match command');
    }
    return createHash('sha256').update(await readFile(path)).digest('hex');
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  const temporary = `${path}.${randomUUID()}.tmp`;
  let file;
  try {
    file = await open(temporary, 'wx', 0o600);
    await file.writeFile(contents);
    await file.sync();
    await file.close();
    file = null;
    await rename(temporary, path);
  } finally {
    if (file) await file.close();
    await rm(temporary, { force: true });
  }
  return createHash('sha256').update(contents).digest('hex');
}

async function claim(db, ref, pageId, workerId) {
  const claimId = randomUUID();
  const result = await db.runTransaction(async (tx) => {
    const snapshot = await tx.get(ref);
    if (!snapshot.exists) return null;
    const command = snapshot.data();
    if (command.pageId !== pageId || command.schemaVersion !== SCHEMA) return null;
    const expired = command.state === 'claimed' && command.leaseUntil?.toMillis() <= Date.now();
    if (command.state !== 'queued' && !expired) return null;
    validate(command, ref.id, pageId);
    tx.update(ref, { state: 'claimed', claimId, workerId, leaseUntil: new Date(Date.now() + 60000) });
    return command;
  });
  return result ? { command: result, claimId } : null;
}

async function receive(db, args) {
  const workerId = randomUUID();
  const inbox = resolve(args.inbox);
  let finished = false;
  let working = false;
  let done;
  let failed;
  const completion = new Promise((resolveDone, rejectDone) => { done = resolveDone; failed = rejectDone; });
  const query = db.collection(COLLECTION).where('state', 'in', ['queued', 'claimed']);
  async function reconcile() {
    if (finished || working) return;
    working = true;
    try {
      const snapshot = await query.get();
      for (const item of snapshot.docs) {
        if (item.data().pageId !== args.pageId) continue;
        const claimed = await claim(db, item.ref, args.pageId, workerId);
        if (!claimed) continue;
        const { command, claimId } = claimed;
        const payload = {
          schemaVersion: SCHEMA, commandId: item.id, pageId: command.pageId,
          stepId: command.stepId, action: 'mock_ping', mockOnly: true,
          state: 'received', receivedAt: new Date().toISOString(),
        };
        const file = resolve(inbox, `${item.id}.json`);
        const sha256 = await writeInbox(file, payload);
        await db.runTransaction(async (tx) => {
          const current = await tx.get(item.ref);
          if (current.data()?.claimId !== claimId || current.data()?.state !== 'claimed') {
            throw new Error('claim changed before acknowledgment');
          }
          tx.update(item.ref, { state: 'received', receivedAt: new Date(), localJsonSha256: sha256 });
        });
        finished = true;
        done({ commandId: item.id, state: 'received', file, localJsonSha256: sha256 });
        return;
      }
    } catch (error) { finished = true; failed(error); }
    finally { working = false; }
  }
  const unsubscribe = query.onSnapshot(() => { void reconcile(); }, (error) => { finished = true; failed(error); });
  const interval = setInterval(() => { void reconcile(); }, 15000);
  const timeout = setTimeout(() => { finished = true; failed(new Error('receive timed out')); }, args.timeoutSeconds * 1000);
  try { await reconcile(); return await completion; }
  finally { unsubscribe(); clearInterval(interval); clearTimeout(timeout); }
}

async function main() {
  const args = options(process.argv.slice(2));
  const db = database();
  if (args.action === 'send') {
    const commandId = randomUUID();
    await db.collection(COLLECTION).doc(commandId).create({
      schemaVersion: SCHEMA, commandId, pageId: args.pageId, stepId: args.stepId,
      action: 'mock_ping', mockOnly: true, state: 'queued', createdAt: new Date(),
    });
    console.log(JSON.stringify({ commandId, state: 'queued', mockOnly: true }));
  } else if (args.action === 'inspect') {
    const snapshot = await db.collection(COLLECTION).doc(args.id).get();
    if (!snapshot.exists) throw new Error('command not found');
    const command = snapshot.data();
    console.log(JSON.stringify({ commandId: args.id, state: command.state,
      mockOnly: command.mockOnly, localJsonSha256: command.localJsonSha256 || null }));
  } else {
    console.log(JSON.stringify(await receive(db, args)));
  }
}

main().catch((error) => { console.error(error.message); process.exitCode = 1; });
