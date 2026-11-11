import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('client bundle registers the production-progress sidebar tab', async () => {
  const source = await readFile(new URL('../lib/client.js', import.meta.url), 'utf8')
  let handoff = null
  const window = {
    __ModuleLoader__: {
      load(value) { handoff = value },
    },
  }
  // eslint-disable-next-line no-new-func
  const execute = new Function('window', source)
  execute(window)
  assert.ok(handoff)
  assert.equal(handoff.id, 'dsh-production-progress')

  const fakeReact = {
    createElement() {},
    useState() {},
    useEffect() {},
  }
  const exports = handoff.factory(spec => {
    if (spec === 'react') return fakeReact
    throw new Error(`unexpected require ${spec}`)
  })
  assert.deepEqual(exports.inject, ['slots', 'sessions'])
  assert.equal(typeof exports.apply, 'function')
  assert.equal(typeof exports.ProgressView, 'function')
  assert.equal(typeof exports.orderedRuns, 'function')
  assert.equal(exports.stageLabel('l3.tts.john_thomas.zh-Hans'), 'L3 配音 · 中文')
  assert.equal(exports.stageLabel('l3.tts.john_thomas.zh-Hans', false), 'L3 配音')
  const nowIso = new Date().toISOString()
  assert.match(exports.etaText({ state: 'running', etaAt: nowIso }), /^预计 /)
  assert.match(exports.etaText({ state: 'running', etaSeconds: 60 }, nowIso), /^预计 /)
  assert.match(exports.etaText({ state: 'waiting', waitingSince: nowIso, expectedMinutes: '20-80' }, nowIso), /^预计 /)
  assert.match(exports.etaText({ state: 'succeeded', finishedAt: nowIso }), /^完成 /)
  assert.equal(exports.etaText({ state: 'pending' }), '')
  assert.equal(exports.reviewSessionId({ attention: [{ kind: 'human_review', sessionId: 's1' }], stages: [] }), 's1')
  assert.equal(exports.reviewSessionId({ attention: [], stages: [{ state: 'waiting', sessionId: 's2' }] }), 's2')
  assert.equal(exports.reviewSessionId({ attention: [], stages: [] }), null)
  const ordered = exports.orderedRuns([
    { runId: 'done', state: 'completed', generatedAt: '2026-11-09T00:00:00Z' },
    { runId: 'live', state: 'active', generatedAt: '2026-11-09T01:00:00Z' },
    { runId: 'bad', state: 'attention_required', generatedAt: '2026-11-09T02:00:00Z' },
  ])
  assert.deepEqual(ordered.map(run => run.runId), ['bad', 'live', 'done'])

  const previousStorage = globalThis.localStorage
  try {
    globalThis.localStorage = {
      getItem() { return JSON.stringify(['run-a', '', 3, 'run-b']) },
      setItem() {},
    }
    assert.deepEqual(exports.readDismissedRuns(), ['run-a', 'run-b'])
  } finally {
    if (previousStorage === undefined) delete globalThis.localStorage
    else globalThis.localStorage = previousStorage
  }

  let injectedService = null
  let sidebarScope = null
  let tabOptions = null
  const slotRequests = []
  const registrations = []
  const ctx = {
    inject(names, callback) {
      injectedService = names
      callback(sidebarScope = {
        sidebarRightTabs: {
          register(options) { tabOptions = options; return () => {} },
        },
        slots: {
          inject(name, factory) { slotRequests.push(name); factory(); return () => {} },
          register(options, component) {
            registrations.push({ options, component })
            return () => {}
          },
        },
      })
      return () => {}
    },
  }
  exports.apply(ctx)
  assert.deepEqual(injectedService, ['sidebarRightTabs'])
  assert.ok(sidebarScope)
  assert.equal(tabOptions.id, 'production-progress')
  assert.equal(tabOptions.kind, 'production-progress')
  assert.equal(tabOptions.title(), '进度')
  assert.deepEqual(slotRequests, ['sidebar.right.pane.tab', 'sidebar.right.pane.tab.title'])
  assert.equal(registrations[0].options.key, 'production-progress')
  assert.equal(typeof registrations[0].component, 'function')
  assert.equal(registrations[1].options.key, 'production-progress')
  assert.equal(typeof registrations[1].component, 'function')
  assert.ok(!slotRequests.includes('conversation.input.dock'))
})
