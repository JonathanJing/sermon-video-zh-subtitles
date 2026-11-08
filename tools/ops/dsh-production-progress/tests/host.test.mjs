import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { apply, buildPayload, handleStatus, ROUTE, resolveStatusRoot } from '../lib/index.js'

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'dsh-progress-'))
  const run = join(root, 'run-zh')
  await mkdir(join(run, 'status'), { recursive: true })
  await writeFile(join(root, '.status-index.json'), JSON.stringify({
    schemaVersion: 'sentence-first-status-index-v1',
    productions: {
      sermon: {
        productionId: 'sermon',
        title: 'Proverbs 3',
        active: true,
        updatedAt: '2026-11-01T12:00:00+00:00',
        runs: { 'zh-Hans': 'run-zh' },
      },
    },
  }))
  await writeFile(join(run, 'status', 'status.json'), JSON.stringify({
    schemaVersion: 'sentence-first-run-status-v1',
    runId: 'run-zh',
    locale: 'zh-Hans',
    generatedAt: '2026-11-01T12:00:02+00:00',
    startedAt: '2026-11-01T11:59:00+00:00',
    runState: 'attention_required',
    stalled: false,
    freshness: { ageSeconds: 2, state: 'fresh' },
    decisions: { form: 'full', sync: true, publish: true, locales: ['zh-Hans'], title: 'Proverbs 3' },
    stages: [
      { id: 'l2.translate.zh-Hans', state: 'succeeded', progress: { unit: 'rows', done: 100, total: 100 } },
      { id: 'l3.tts.zh-Hans', state: 'running', heartbeatAt: '2026-11-01T12:00:00+00:00', progress: { unit: 'sentences', done: 12, total: 42 }, etaAt: '2026-11-01T12:10:00+00:00', etaSource: 'observed', sessionId: 'session-test-1' },
      { id: 'l3.finish', state: 'failed', errorClass: 'infra', errorMessage: 'ssh timeout' },
      { id: 'l4.publish', state: 'pending' },
    ],
    attention: [{
      kind: 'failed', severity: 'timeSensitive', stage: 'l3.finish', since: '2026-11-01T12:00:01+00:00',
      ageSeconds: 1, message: 'ssh timeout', actionUrl: 'http://127.0.0.1:8765/review-player.html',
      sessionId: 'session-test-1',
    }],
    required: { missing: ['l3.lag-loop.zh-Hans'] },
  }))
  return { root, run }
}

test('buildPayload merges the index and compacts the snapshot', async () => {
  const { root, run } = await fixture()
  const payload = await buildPayload(root, { now: new Date('2026-11-01T12:00:03+00:00') })
  assert.equal(payload.ok, true)
  assert.equal(payload.runs.length, 1)
  const [entry] = payload.runs
  assert.equal(entry.runId, 'run-zh')
  assert.equal(entry.locale, 'zh-Hans')
  assert.equal(entry.title, 'Proverbs 3')
  assert.equal(entry.activeStage, 'l3.finish')
  assert.equal(entry.stages.some(stage => stage.id === 'l4.publish'), false)
  assert.equal(entry.stages.find(stage => stage.id === 'l3.tts.zh-Hans').progress.done, 12)
  assert.equal(entry.stages.find(stage => stage.id === 'l3.tts.zh-Hans').etaAt, '2026-11-01T12:10:00+00:00')
  assert.equal(entry.stages.find(stage => stage.id === 'l3.tts.zh-Hans').etaSource, 'observed')
  assert.equal(entry.stages.find(stage => stage.id === 'l3.tts.zh-Hans').sessionId, 'session-test-1')
  assert.equal(entry.attention[0].severity, 'timeSensitive')
  assert.equal(entry.attention[0].actionUrl, undefined)
  assert.equal(entry.attention[0].sessionId, 'session-test-1')
  assert.deepEqual(entry.required.missing, ['l3.lag-loop.zh-Hans'])
  assert.equal(payload.activeRun, 'run-zh')
  assert.equal(entry.decisions.publish, true)
  assert.ok(run.endsWith('run-zh'))
})

test('buildPayload falls back to a directory scan without an index', async () => {
  const root = await mkdtemp(join(tmpdir(), 'dsh-progress-scan-'))
  const run = join(root, 'run-ko')
  await mkdir(join(run, 'status'), { recursive: true })
  await writeFile(join(run, 'status', 'status.json'), JSON.stringify({
    runId: 'run-ko', locale: 'ko', runState: 'active', generatedAt: '2026-11-01T12:00:00+00:00',
    stages: [{ id: 'l1.start', state: 'running' }], attention: [], required: { missing: [] },
  }))
  const payload = await buildPayload(root)
  assert.equal(payload.ok, true)
  assert.equal(payload.runs[0].runId, 'run-ko')
  assert.equal(payload.runs[0].title, 'ko 生产')
})

test('buildPayload reports a missing root without throwing', async () => {
  const root = join(tmpdir(), 'dsh-progress-does-not-exist')
  const payload = await buildPayload(root)
  assert.equal(payload.ok, false)
  assert.deepEqual(payload.runs, [])
})

test('apply registers the exact status route', () => {
  const routes = []
  const ctx = {
    effect(fn) { return fn() },
    webServer: { register(route) { routes.push(route); return () => {} } },
  }
  apply(ctx, { statusRoot: '/tmp' })
  assert.equal(routes.length, 1)
  assert.equal(routes[0].path, ROUTE)
  assert.equal(routes[0].kind, 'exact')
})

test('handleStatus serves JSON for GET and rejects other methods', async () => {
  const { root } = await fixture()
  const headers = {}
  let body = ''
  const res = {
    statusCode: 0,
    setHeader(name, value) { headers[name] = value },
    end(value = '') { body = value },
  }
  await handleStatus({ method: 'GET' }, res, root)
  assert.equal(res.statusCode, 200)
  assert.match(headers['Content-Type'], /application\/json/)
  assert.equal(JSON.parse(body).runs[0].runId, 'run-zh')

  const res405 = { statusCode: 0, setHeader() {}, end() {} }
  await handleStatus({ method: 'POST' }, res405, root)
  assert.equal(res405.statusCode, 405)
})

test('resolveStatusRoot prefers an explicit config over the default', () => {
  assert.equal(resolveStatusRoot({ statusRoot: '/tmp' }), '/tmp')
})
