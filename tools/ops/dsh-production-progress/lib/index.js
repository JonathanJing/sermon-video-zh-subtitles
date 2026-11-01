/**
 * dsh-production-progress — host half.
 *
 * Serves the compact production snapshot consumed by the client dock. The
 * sentence-first producer keeps `status/status.json` fresh on every event
 * (run_status.py refreshes after a write), so this is a read-only view: no
 * Python child process, no writes, no gates.
 *
 * Data source:
 *   <statusRoot>/.status-index.json
 *   <statusRoot>/<run>/status/status.json
 *
 * Missing files are normal (no run yet); the route answers `{ ok: true, runs: [] }`
 * and the dock renders nothing.
 */
import { existsSync } from 'node:fs'
import { readFile, readdir } from 'node:fs/promises'
import { homedir } from 'node:os'
import { isAbsolute, join, resolve } from 'node:path'

export const name = 'dsh-production-progress'
export const inject = ['webServer']
export const ROUTE = '/production-progress/status'

const HOME_STATUS_ROOT = join(
  homedir(),
  'SynologyDrive', 'GitHub', 'Active', 'sermon-video-zh-subtitles',
  'artifacts', 'sentence-first-agent',
)
const SEVERITY_RANK = { critical: 0, timeSensitive: 1, attention: 2, info: 3 }
const STATE_RANK = { attention_required: 0, active: 1, planned: 2, completed: 3 }

/** Resolve the status root from config, env, the personal checkout, then cwd. */
export function resolveStatusRoot(config = {}) {
  const candidates = [
    config.statusRoot,
    process.env.SFA_STATUS_ROOT,
    HOME_STATUS_ROOT,
    join(process.cwd(), 'artifacts', 'sentence-first-agent'),
  ]
  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim() !== '' && existsSync(candidate)) {
      return resolve(candidate)
    }
  }
  return resolve(candidates[2])
}

async function readJson(path) {
  try {
    return JSON.parse(await readFile(path, 'utf8'))
  } catch {
    return null
  }
}

function iso(value) {
  return typeof value === 'string' && value !== '' ? value : null
}

function trimText(value, max = 240) {
  if (typeof value !== 'string') return null
  const compact = value.replace(/\s+/g, ' ').trim()
  if (compact === '') return null
  return compact.length > max ? `${compact.slice(0, max - 1)}…` : compact
}

function compactStage(stage) {
  return {
    id: stage.id,
    phase: stage.phase ?? null,
    lane: stage.lane ?? null,
    state: stage.state ?? 'pending',
    attempt: stage.attempt ?? 0,
    startedAt: iso(stage.startedAt),
    finishedAt: iso(stage.finishedAt),
    waitingSince: iso(stage.waitingSince),
    waitingOn: trimText(stage.waitingOn, 120),
    expectedMinutes: stage.expectedMinutes ?? null,
    progress: stage.progress && typeof stage.progress === 'object'
      ? {
          unit: stage.progress.unit ?? 'units',
          done: stage.progress.done ?? null,
          total: stage.progress.total ?? null,
        }
      : null,
    heartbeatAt: iso(stage.heartbeatAt),
    heartbeatExpectedSeconds: stage.heartbeatExpectedSeconds ?? null,
    stalled: Boolean(stage.stalled),
    stalledSeconds: stage.stalledSeconds ?? null,
    etaSeconds: stage.etaSeconds ?? null,
    etaAt: iso(stage.etaAt),
    etaSource: stage.etaSource ?? null,
    evidenceLevel: stage.evidenceLevel ?? null,
    errorClass: stage.errorClass ?? null,
    errorMessage: trimText(stage.errorMessage),
    resume: trimText(stage.resume, 160),
    source: stage.source ?? null,
  }
}

function compactAttention(item) {
  return {
    kind: item.kind ?? 'unknown',
    severity: item.severity ?? 'info',
    stage: item.stage ?? null,
    since: iso(item.since),
    ageSeconds: item.ageSeconds ?? null,
    message: trimText(item.message),
    waitingOn: trimText(item.waitingOn, 120),
    expectedMinutes: item.expectedMinutes ?? null,
    errorClass: item.errorClass ?? null,
  }
}

function compactRun(snapshot, ref) {
  const allStages = Array.isArray(snapshot.stages) ? snapshot.stages : []
  const stages = allStages.filter(stage => stage.state !== 'pending').map(compactStage)
  const attention = (Array.isArray(snapshot.attention) ? snapshot.attention : [])
    .map(compactAttention)
    .sort((a, b) => (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9))
  const decisions = snapshot.decisions && typeof snapshot.decisions === 'object' ? snapshot.decisions : {}
  const activeStage = stages.find(stage => stage.state === 'failed')
    ?? stages.find(stage => stage.state === 'waiting')
    ?? stages.find(stage => stage.state === 'running')
    ?? stages.find(stage => stage.id === snapshot.activeStage)
    ?? null
  const locale = snapshot.locale ?? ref.locale ?? null
  return {
    runId: snapshot.runId ?? ref.runDir.split('/').pop(),
    productionId: ref.productionId ?? snapshot.productionId ?? null,
    locale,
    title: trimText(decisions.title, 160) ?? trimText(ref.entry?.title, 160) ?? (locale ? `${locale} 生产` : '生产'),
    state: snapshot.runState ?? 'planned',
    generatedAt: iso(snapshot.generatedAt),
    startedAt: iso(snapshot.startedAt),
    stalled: Boolean(snapshot.stalled),
    freshness: {
      ageSeconds: snapshot.freshness?.ageSeconds ?? null,
      state: snapshot.freshness?.state ?? 'unknown',
    },
    decisions: {
      form: decisions.form ?? null,
      sync: decisions.sync ?? null,
      publish: decisions.publish ?? null,
      locales: Array.isArray(decisions.locales) ? decisions.locales : null,
    },
    stages,
    attention,
    required: {
      missing: Array.isArray(snapshot.required?.missing) ? snapshot.required.missing : [],
    },
    stageCount: allStages.length,
    activeStage: activeStage?.id ?? null,
  }
}

async function collectRunRefs(root) {
  const refs = new Map()
  const index = await readJson(join(root, '.status-index.json'))
  const productions = index?.productions
  if (productions && typeof productions === 'object') {
    for (const [productionId, entry] of Object.entries(productions)) {
      for (const [locale, raw] of Object.entries(entry?.runs ?? {})) {
        if (typeof raw !== 'string' || raw === '') continue
        const runDir = isAbsolute(raw) ? raw : resolve(root, raw)
        refs.set(runDir, {
          runDir,
          productionId,
          locale: locale === 'default' ? null : locale,
          entry,
        })
      }
    }
  }
  if (refs.size === 0) {
    const entries = await readdir(root, { withFileTypes: true }).catch(() => [])
    for (const entry of entries) {
      if (!entry.isDirectory() || entry.name.startsWith('.')) continue
      refs.set(resolve(root, entry.name), {
        runDir: resolve(root, entry.name),
        productionId: entry.name,
        locale: null,
        entry: null,
      })
    }
  }
  return [...refs.values()]
}

/** Build the JSON payload served to the dock (exported for tests). */
export async function buildPayload(root = resolveStatusRoot(), { now = new Date() } = {}) {
  const base = resolve(root)
  if (!existsSync(base)) {
    return { ok: false, error: 'status root not found', generatedAt: now.toISOString(), runs: [] }
  }
  const runs = []
  for (const ref of await collectRunRefs(base)) {
    const snapshot = await readJson(join(ref.runDir, 'status', 'status.json'))
    if (!snapshot || typeof snapshot !== 'object') continue
    runs.push(compactRun(snapshot, ref))
  }
  runs.sort((a, b) => {
    const rank = (STATE_RANK[a.state] ?? 9) - (STATE_RANK[b.state] ?? 9)
    if (rank !== 0) return rank
    return String(b.generatedAt ?? '').localeCompare(String(a.generatedAt ?? ''))
  })
  const activeRun = runs.find(run => run.state === 'active' || run.state === 'attention_required')
    ?? runs[0]
    ?? null
  return {
    ok: true,
    generatedAt: now.toISOString(),
    activeRun: activeRun?.runId ?? null,
    runs,
  }
}

/** Exact-path HTTP handler; owns the full response lifecycle. */
export async function handleStatus(req, res, root) {
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.statusCode = 405
    res.setHeader('Allow', 'GET, HEAD')
    res.end()
    return
  }
  let payload
  try {
    payload = await buildPayload(root)
  } catch {
    payload = { ok: false, error: 'status unavailable', runs: [] }
  }
  res.statusCode = 200
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.setHeader('Cache-Control', 'no-store')
  const body = JSON.stringify(payload)
  if (req.method === 'HEAD') {
    res.end()
    return
  }
  res.end(body)
}

/** Cordis plugin body: register the status route. */
export function apply(ctx, config = {}) {
  const root = resolveStatusRoot(config)
  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: ROUTE,
    handler: (req, res) => handleStatus(req, res, root),
  }))
}
