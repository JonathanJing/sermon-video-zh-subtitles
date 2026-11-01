// dsh-production-progress — browser half.
//
// Plain lazy-CJS bundle using the same handoff shape as the shipped UI
// packages. React is a platform-seeded module; no build step is required.
//
// The dock row is intentionally small: one line for the current stage and a
// click-to-expand panel for stages/attention. It polls the host route; it does
// not touch Python, the filesystem, or any gate.
window.__ModuleLoader__.load({
  id: 'dsh-production-progress',
  factory: (require) => {
    const React = require('react')
    const h = React.createElement
    const ROUTE = '/production-progress/status'
    const POLL_MS = 4000

    const LOCALE_LABEL = { 'zh-Hans': '中文', ko: '한국어', es: 'Español' }
    const STATE_LABEL = {
      planned: '计划中', active: '进行中', attention_required: '需处理', completed: '完成',
    }
    const STAGE_STATE = {
      running: '进行中', waiting: '等待', failed: '失败', succeeded: '完成',
      skipped: '跳过', pending: '待开始',
    }
    const TONE = {
      ok: '#4ca66a', active: '#4aa3df', attention: '#e0a23a', bad: '#d9534f', dim: '#8a8a8a',
    }

    function parseTime(value) {
      const parsed = Date.parse(value)
      return Number.isFinite(parsed) ? parsed : null
    }

    function ageSeconds(value, now) {
      const parsed = parseTime(value)
      return parsed === null ? null : Math.max(0, (now - parsed) / 1000)
    }

    function formatAge(seconds) {
      if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—'
      if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`
      if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
      if (seconds < 86400) return `${Math.floor(seconds / 3600)}h${Math.floor((seconds % 3600) / 60)}m`
      return `${Math.floor(seconds / 86400)}d`
    }

    function localeOf(id) {
      const match = /(zh-Hans|ko|es)$/.exec(id || '')
      return match ? match[1] : ''
    }

    function localeLabel(locale) {
      return LOCALE_LABEL[locale] || locale || ''
    }

    function stageLabel(id) {
      if (!id) return '等待中'
      const locale = localeOf(id)
      const suffix = locale ? ` · ${localeLabel(locale)}` : ''
      if (id.startsWith('l1.start')) return 'L1 开工'
      if (id.startsWith('l1.preflight')) return 'L1 前置检查'
      if (id.startsWith('l1.english')) return 'L1 英文表'
      if (id.startsWith('l1.speakers')) return 'L1 讲员映射'
      if (id.startsWith('l2.translate')) return `L2 翻译${suffix}`
      if (id.startsWith('l2.audit')) return `L2 审计${suffix}`
      if (id.startsWith('l2.consistency')) return 'L2 一致性'
      if (id.startsWith('l3.speech')) return `L3 口播${suffix}`
      if (id.startsWith('l3.tts')) return `L3 配音${suffix}`
      if (id.startsWith('l3.finish')) return 'L3 收尾'
      if (id.startsWith('l3.lag-loop')) return `L3 落后回环${suffix}`
      if (id.startsWith('l3.review')) return `待审听${suffix}`
      if (id.startsWith('l4.study')) return 'L4 学习内容'
      if (id.startsWith('l4.publish')) return 'L4 发布'
      return id
    }

    function stateLabel(state) {
      return STATE_LABEL[state] || state || '未知'
    }

    function stageTone(stage) {
      if (stage.state === 'failed' || stage.stalled) return TONE.bad
      if (stage.state === 'waiting') return TONE.attention
      if (stage.state === 'running') return TONE.active
      if (stage.state === 'succeeded' || stage.state === 'skipped') return TONE.ok
      return TONE.dim
    }

    function progressText(stage) {
      const progress = stage.progress
      if (!progress || (progress.done === null && progress.total === null)) return ''
      if (progress.total === null || progress.total === undefined) return `${progress.done ?? '?'}`
      return `${progress.done ?? 0}/${progress.total}`
    }

    function progressPercent(stage) {
      const progress = stage.progress
      if (!progress || !progress.total || progress.done === null || progress.done === undefined) return null
      return Math.max(0, Math.min(100, Math.round((progress.done / progress.total) * 100)))
    }

    function heartbeatText(stage, now) {
      if (stage.state !== 'running') return ''
      const age = ageSeconds(stage.heartbeatAt || stage.startedAt, now)
      return age === null ? '' : `心跳 ${formatAge(age)}`
    }

    function attentionTone(severity) {
      if (severity === 'critical') return TONE.bad
      if (severity === 'timeSensitive') return TONE.attention
      if (severity === 'attention') return TONE.attention
      return TONE.dim
    }

    function pickRun(runs) {
      if (!Array.isArray(runs) || runs.length === 0) return null
      const rank = { attention_required: 0, active: 1, planned: 2, completed: 3 }
      return [...runs].sort((a, b) => {
        const order = (rank[a.state] ?? 9) - (rank[b.state] ?? 9)
        if (order !== 0) return order
        return String(b.generatedAt || '').localeCompare(String(a.generatedAt || ''))
      })[0]
    }

    function useStatus() {
      const [value, setValue] = React.useState({ data: null, error: null })
      React.useEffect(() => {
        let stopped = false
        let timer = null
        const load = async () => {
          try {
            const response = await fetch(ROUTE, { cache: 'no-store' })
            if (!response.ok) throw new Error(`HTTP ${response.status}`)
            const data = await response.json()
            if (!stopped) setValue({ data, error: null })
          } catch (error) {
            if (!stopped) setValue(prev => ({ data: prev.data, error: String(error?.message || error) }))
          } finally {
            if (!stopped) timer = setTimeout(load, POLL_MS)
          }
        }
        load()
        return () => {
          stopped = true
          if (timer !== null) clearTimeout(timer)
        }
      }, [])
      return value
    }

    function useNow() {
      const [now, setNow] = React.useState(() => Date.now())
      React.useEffect(() => {
        const timer = setInterval(() => setNow(Date.now()), 1000)
        return () => clearInterval(timer)
      }, [])
      return now
    }

    function StageLine({ stage }) {
      const tone = stageTone(stage)
      const progress = progressText(stage)
      const percent = progressPercent(stage)
      const now = Date.now()
      const waiting = stage.state === 'waiting'
        ? `等 ${formatAge(ageSeconds(stage.waitingSince, now))}`
        : ''
      const stall = stage.stalled ? `停滞 ${formatAge(stage.stalledSeconds ?? 0)}` : ''
      const retry = stage.attempt > 1 ? `↻${stage.attempt}` : ''
      const evidence = stage.evidenceLevel || ''
      const detail = [progress, heartbeatText(stage, now), waiting, stall, evidence, retry]
        .filter(Boolean).join(' · ')
      return h('div', {
        style: {
          display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, padding: '2px 0',
          opacity: stage.state === 'succeeded' ? 0.62 : 1,
        },
      },
        h('span', { style: { width: 6, height: 6, borderRadius: '50%', background: tone, flex: '0 0 auto' } }),
        h('span', {
          style: {
            minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            color: stage.state === 'failed' ? TONE.bad : 'inherit',
          },
        }, stageLabel(stage.id)),
        h('span', { style: { marginLeft: 'auto', opacity: 0.65, flex: '0 0 auto' } },
          STAGE_STATE[stage.state] || stage.state),
        detail ? h('span', {
          style: { fontVariantNumeric: 'tabular-nums', opacity: 0.65, flex: '0 0 auto' },
        }, detail) : null,
        percent !== null ? h('span', {
          style: { width: 26, height: 3, borderRadius: 2, background: 'rgba(127,127,127,.25)', flex: '0 0 auto' },
        }, h('span', {
          style: { display: 'block', width: `${percent}%`, height: '100%', borderRadius: 2, background: tone },
        })) : null,
      )
    }

    function Dock() {
      const { data } = useStatus()
      const now = useNow()
      const [open, setOpen] = React.useState(false)
      const runs = Array.isArray(data?.runs) ? data.runs : []
      const run = pickRun(runs)
      if (!run) return null
      if (run.state === 'completed' && (ageSeconds(run.generatedAt, now) ?? 0) > 6 * 3600) return null

      const active = run.stages.find(stage => stage.id === run.activeStage)
        || run.stages.find(stage => stage.state === 'failed')
        || run.stages.find(stage => stage.state === 'waiting')
        || run.stages.find(stage => stage.state === 'running')
        || null
      // External waits are severity=info; the stage table still shows them,
      // but they must not turn into a warning badge in the dock.
      const attentionItems = run.attention.filter(item => item.severity !== 'info')
      const attention = attentionItems[0] || null
      const attentionCount = attentionItems.length
      const stale = run.freshness?.state === 'stale'
      const tone = run.stalled ? TONE.bad
        : run.state === 'attention_required' ? TONE.attention
        : run.state === 'completed' ? TONE.ok
        : stale ? TONE.attention
        : TONE.active
      const progress = active ? progressText(active) : ''
      const waiting = active?.state === 'waiting'
        ? `等 ${formatAge(ageSeconds(active.waitingSince, now))}`
        : ''
      const stalled = active?.stalled
        ? `停滞 ${formatAge(active.stalledSeconds ?? 0)}`
        : ''
      const heartbeat = active ? heartbeatText(active, now) : ''

      const row = h('button', {
        type: 'button',
        onClick: () => setOpen(value => !value),
        title: run.title,
        'aria-expanded': open,
        style: {
          display: 'flex', alignItems: 'center', gap: 6, width: '100%', minWidth: 0,
          padding: '2px 0', border: 0, background: 'transparent', cursor: 'pointer',
          color: 'var(--dsh-text-secondary, #8a8a8a)', font: 'inherit', fontSize: 12,
          textAlign: 'left',
        },
      },
        h('span', {
          style: {
            width: 7, height: 7, borderRadius: '50%', background: tone, flex: '0 0 auto',
            boxShadow: `0 0 0 3px ${tone}22`,
          },
        }),
        h('span', { style: { color: 'var(--dsh-text-primary, #e6e6e6)', fontWeight: 600 } }, '生产'),
        h('span', { style: { opacity: 0.35 } }, '·'),
        h('span', { style: { flex: '0 0 auto' } }, localeLabel(run.locale) || '—'),
        h('span', { style: { opacity: 0.35 } }, '·'),
        h('span', {
          style: {
            color: 'var(--dsh-text-primary, #e6e6e6)', fontWeight: 600,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0,
          },
        }, active ? stageLabel(active.id) : stateLabel(run.state)),
        progress ? h('span', {
          style: { fontVariantNumeric: 'tabular-nums', flex: '0 0 auto' },
        }, progress) : null,
        waiting ? h('span', { style: { color: TONE.attention, flex: '0 0 auto' } }, waiting) : null,
        stalled ? h('span', { style: { color: TONE.bad, flex: '0 0 auto' } }, stalled) : null,
        heartbeat && !waiting && !stalled ? h('span', {
          style: { fontVariantNumeric: 'tabular-nums', opacity: 0.6, flex: '0 0 auto' },
        }, heartbeat) : null,
        attentionCount > 0 ? h('span', {
          style: { color: attentionTone(attention?.severity), flex: '0 0 auto' },
        }, `⚠ ${attentionCount}`) : null,
        run.state === 'completed' ? h('span', {
          style: { color: TONE.ok, flex: '0 0 auto' },
        }, '✓ 完成') : null,
        h('span', { style: { marginLeft: 'auto', opacity: 0.45, fontSize: 10, flex: '0 0 auto' } },
          open ? '▾' : '▸'),
      )

      if (!open) return h('div', { style: { width: '100%' } }, row)

      const panel = h('div', {
        style: {
          marginTop: 6, padding: '8px 10px', border: '1px solid var(--dsh-border, rgba(127,127,127,.22))',
          borderRadius: 8, background: 'var(--dsh-surface-2, rgba(127,127,127,.08))',
          fontSize: 11.5, lineHeight: 1.45, maxHeight: 300, overflowY: 'auto',
        },
      },
        h('div', {
          style: { display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 6, minWidth: 0 },
        },
          h('span', {
            style: {
              color: 'var(--dsh-text-primary, #e6e6e6)', fontWeight: 600,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            },
          }, run.title),
          h('span', { style: { marginLeft: 'auto', opacity: 0.55, flex: '0 0 auto' } },
            `${run.runId} · ${stateLabel(run.state)}`),
        ),
        attention ? h('div', {
          style: {
            display: 'flex', gap: 6, alignItems: 'baseline', padding: '4px 0',
            color: attentionTone(attention.severity),
          },
        },
          h('span', { style: { flex: '0 0 auto' } }, `⚠ ${attention.kind}`),
          h('span', {
            style: {
              minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              color: 'var(--dsh-text-secondary, #8a8a8a)',
            },
          }, attention.message || attention.waitingOn || stageLabel(attention.stage)),
        ) : null,
        run.stages.slice(0, 12).map(stage => h(StageLine, { key: stage.id, stage })),
        run.stages.length > 12 ? h('div', { style: { opacity: 0.55, padding: '2px 0' } },
          `+${run.stages.length - 12} 个阶段`) : null,
        run.required?.missing?.length ? h('div', {
          style: { marginTop: 5, color: TONE.attention, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
        }, `缺步骤：${run.required.missing.slice(0, 4).map(stageLabel).join('、')}`) : null,
        h('div', { style: { marginTop: 6, opacity: 0.55, display: 'flex', gap: 6 } },
          h('span', null, `快照 ${formatAge(ageSeconds(run.generatedAt, now))} 前`),
          stale ? h('span', { style: { color: TONE.attention } }, '· 可能过期') : null,
        ),
      )
      return h('div', { style: { width: '100%' } }, row, panel)
    }

    const inject = ['slots']

    function apply(ctx) {
      ctx.slots.inject('conversation.input.dock', () => ctx.slots.register({
        name: 'conversation.input.dock',
        id: 'production-progress',
        order: 16,
        registrant: 'dsh-production-progress',
      }, Dock))
    }

    return { apply, inject, Dock }
  },
})
