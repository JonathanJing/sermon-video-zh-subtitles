import test from 'node:test';
import assert from 'node:assert/strict';
import { USAGE_ACTIONS } from '../usage-core.mjs';
import { ACTIONS, summarizeUsage, renderUsageHtml } from '../usage-report.mjs';

const FIELD_ACTIONS = {
  seek_undo: '撤销跳转', position_restore: '继续上次收听', position_restart: '从头开始', transcript_current: '定位当前字幕',
  more_open: '展开更多功能', precision_open: '展开精细调整', feedback_section_open: '展开反馈区域',
};

test('private report has a Chinese label for every accepted API action including all legacy actions', () => {
  assert.equal(USAGE_ACTIONS.length, 46);
  assert.equal(new Set(USAGE_ACTIONS).size, USAGE_ACTIONS.length);
  assert.deepEqual(Object.keys(ACTIONS).filter((key) => key !== 'unknown').sort(), [...USAGE_ACTIONS].sort());
  for (const action of USAGE_ACTIONS) assert.match(ACTIONS[action], /[\u3400-\u9fff]/);
});

for (const [action, label] of Object.entries(FIELD_ACTIONS)) {
  test(`private report counts and displays ${action} as ${label}`, () => {
    const at = new Date('2026-09-05T00:00:00.000Z');
    const report = summarizeUsage([{
      schemaVersion: 1, day: '2026-09-04', dailyBrowserKey: 'a'.repeat(64), firstReceivedAt: at,
      totalEvents: 1, droppedEvents: 0,
      events: [{ at, receivedAt: at, sequence: 1, action, panel: 'listen', week: '2026-08-30', trackId: 'full', positionSeconds: 12, speakerId: null }],
    }], { from: '2026-09-04', to: '2026-09-04', now: Date.parse('2026-09-05T00:01:00.000Z') });
    assert.equal(report.sessions[0].events[0].action, action);
    assert.deepEqual(report.actions, [{ key: action, label, events: 1, sessions: 1 }]);
    assert(renderUsageHtml(report).includes(label));
  });
}
