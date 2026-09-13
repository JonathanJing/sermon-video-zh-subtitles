import test from 'node:test';
import assert from 'node:assert/strict';
import { waitForGatewayRestart } from '../../src/runtimeRestart.js';
const service = 'local-live-caption-gateway';
function clock() {
  let time = 0;
  return { now: () => time, sleep: async (ms) => { time += ms; } };
}
test('waits for a different process even when the model is degraded', async () => {
  const replies = [
    { service, runtimeInstanceId: 'old', status: 'ready' },
    { service, runtimeInstanceId: 'new', status: 'degraded' },
  ];
  let calls = 0;
  const health = await waitForGatewayRestart('old', { ...clock(), getHealth: async () => replies[calls++] });
  assert.equal(calls, 2);
  assert.equal(health.status, 'degraded');
});
test('survives connection failures and startup longer than 30 seconds', async () => {
  let calls = 0;
  const health = await waitForGatewayRestart('old', { ...clock(), getHealth: async (timeout) => {
    assert.ok(timeout <= 2000);
    if (++calls < 70) throw new Error('offline');
    return { service, runtimeInstanceId: 'new' };
  } });
  assert.equal(health.runtimeInstanceId, 'new');
});
test('does not report success when the old process stays up', async () => {
  await assert.rejects(waitForGatewayRestart('old', { ...clock(), timeoutMs: 1500,
    getHealth: async () => ({ service, runtimeInstanceId: 'old', status: 'ready' }),
  }), /重新连接/);
});
test('legacy restart acknowledgement accepts a newly versioned backend', async () => {
  const result = await waitForGatewayRestart(undefined, { ...clock(),
    getHealth: async () => ({ service, runtimeInstanceId: 'new', status: 'degraded' }),
  });
  assert.equal(result.runtimeInstanceId, 'new');
});
