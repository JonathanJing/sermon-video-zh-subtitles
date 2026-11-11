// dsh-production-progress — browser half.
//
// Plain lazy-CJS bundle using the same handoff shape as the shipped UI
// packages. React is a platform-seeded module; no build step is required.
//
// The right-sidebar tab shows one card per run with a stage table and attention.
// It polls the host route; it does not touch Python, the filesystem, or any gate.
// Closing a card only persists that run id in localStorage; the tab stays.
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

    const DISMISS_KEY = 'dsh-production-progress.dismissed-runs.v1'

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

    function formatClock(value) {
      const parsed = parseTime(value)
      if (parsed === null) return ''
      const stamp = new Date(parsed)
      const now = new Date()
      const time = stamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
      return stamp.toDateString() === now.toDateString()
        ? time
        : `${stamp.getMonth() + 1}/${stamp.getDate()} ${time}`
    }

    function expectedMaxMinutes(value) {
      const numbers = String(value || '').match(/\d+/g)
      return numbers ? Math.max(...numbers.map(Number)) : null
    }

    function stageEtaAt(stage, snapshotAt) {
      if (!stage) return null
      if (stage.etaAt) return stage.etaAt
      const base = parseTime(snapshotAt)
      if (base === null) return null
      if (stage.state === 'running' && stage.etaSeconds !== null && stage.etaSeconds !== undefined) {
        return new Date(base + Number(stage.etaSeconds) * 1000).toISOString()
      }
      if (stage.state === 'waiting') {
        const since = parseTime(stage.waitingSince) ?? base
        const minutes = expectedMaxMinutes(stage.expectedMinutes)
        return minutes === null ? null : new Date(since + minutes * 60000).toISOString()
      }
      return null
    }

    function etaText(stage, snapshotAt) {
      if (!stage) return ''
      if (stage.state === 'running' || stage.state === 'waiting') {
        const clock = formatClock(stageEtaAt(stage, snapshotAt))
        return clock ? `预计 ${clock}` : '预计 —'
      }
      if (stage.state === 'succeeded' || stage.state === 'skipped') {
        const clock = formatClock(stage.finishedAt)
        return clock ? `完成 ${clock}` : ''
      }
      if (stage.state === 'failed') {
        const clock = formatClock(stage.finishedAt)
        return clock ? `失败 ${clock}` : ''
      }
      return ''
    }

    function localeOf(id) {
      const match = /(zh-Hans|ko|es)$/.exec(id || '')
      return match ? match[1] : ''
    }

    function localeLabel(locale) {
      return LOCALE_LABEL[locale] || locale || ''
    }

    function stageLabel(id, includeLocale = true) {
      if (!id) return '等待中'
      const locale = localeOf(id)
      const suffix = includeLocale && locale ? ` · ${localeLabel(locale)}` : ''
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

    function StageLine({ stage, snapshotAt }) {
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
      const detail = [etaText(stage, snapshotAt), progress, heartbeatText(stage, now), waiting, stall, evidence, retry]
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

    function orderedRuns(runs) {
      if (!Array.isArray(runs)) return []
      const rank = { attention_required: 0, active: 1, planned: 2, completed: 3 }
      return [...runs].sort((a, b) => {
        const order = (rank[a.state] ?? 9) - (rank[b.state] ?? 9)
        if (order !== 0) return order
        return String(b.generatedAt || '').localeCompare(String(a.generatedAt || ''))
      })
    }

    function readDismissedRuns() {
      try {
        if (typeof localStorage === 'undefined') return []
        const raw = localStorage.getItem(DISMISS_KEY)
        if (!raw) return []
        const parsed = JSON.parse(raw)
        return Array.isArray(parsed)
          ? parsed.filter(runId => typeof runId === 'string' && runId !== '')
          : []
      } catch (error) {
        return []
      }
    }

    function saveDismissedRuns(runIds) {
      try {
        if (typeof localStorage !== 'undefined') {
          localStorage.setItem(DISMISS_KEY, JSON.stringify(runIds))
        }
      } catch (error) {
        // Private mode / a locked-down webview must not break the tab.
      }
    }

    function useDismissedRuns() {
      const [runIds, setRunIds] = React.useState(readDismissedRuns)
      React.useEffect(() => { saveDismissedRuns(runIds) }, [runIds])
      return {
        ids: runIds,
        has: runId => runIds.includes(runId),
        dismiss: runId => setRunIds(prev => prev.includes(runId) ? prev : [...prev, runId]),
        restoreAll: () => setRunIds([]),
      }
    }

    function RunCard({ run, now, openSession, onDismiss, defaultOpen }) {
      const [open, setOpen] = React.useState(Boolean(defaultOpen))
      const active = run.stages.find(stage => stage.id === run.activeStage)
        || run.stages.find(stage => stage.state === 'failed')
        || run.stages.find(stage => stage.state === 'waiting')
        || run.stages.find(stage => stage.state === 'running')
        || null
      // severity=info is an external wait; keep it in the stage table but do
      // not turn it into a warning on the row.
      const attentionItems = run.attention.filter(item => item.severity !== 'info')
      const reviewSession = reviewSessionId(run)
      const canOpenReview = Boolean(reviewSession && typeof openSession === 'function')
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
      const activeEta = active && (active.state === 'running' || active.state === 'waiting')
        ? etaText(active, run.generatedAt)
        : ''

      const summary = [
        localeLabel(run.locale) || '—',
        active ? stageLabel(active.id, false) : stateLabel(run.state),
        progress,
        waiting,
        stalled,
        heartbeat && !waiting && !stalled ? heartbeat : '',
        activeEta,
      ].filter(Boolean)

      const row = h('button', {
        type: 'button',
        onClick: () => setOpen(value => !value),
        title: run.title,
        'aria-expanded': open,
        style: {
          flex: '1 1 auto', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 3,
          padding: 0, border: 0, background: 'transparent', cursor: 'pointer',
          color: 'inherit', font: 'inherit', textAlign: 'left',
        },
      },
        h('span', {
          style: { display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, width: '100%' },
        },
          h('span', {
            style: {
              width: 7, height: 7, borderRadius: '50%', background: tone, flex: '0 0 auto',
              boxShadow: `0 0 0 3px ${tone}22`,
            },
          }),
          h('span', {
            style: {
              color: 'var(--dsh-text-primary, #e6e6e6)', fontWeight: 600,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0,
            },
          }, run.title || run.runId),
          h('span', {
            style: { color: tone, flex: '0 0 auto', fontSize: 11, fontWeight: 600 },
          }, stateLabel(run.state)),
          h('span', { style: { marginLeft: 'auto', opacity: 0.45, fontSize: 10, flex: '0 0 auto' } },
            open ? '▾' : '▸'),
        ),
        h('span', {
          style: {
            display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, width: '100%',
            color: 'var(--dsh-text-secondary, #8a8a8a)', fontSize: 11.5,
          },
        },
          summary.map(value => h('span', {
            key: value,
            style: {
              flex: '0 0 auto', fontVariantNumeric: 'tabular-nums',
              color: value === waiting || value === stalled ? TONE.attention : 'inherit',
            },
          }, value)),
          attentionItems.length > 0 ? h('span', {
            style: { color: attentionTone(attentionItems[0]?.severity), flex: '0 0 auto' },
          }, `⚠ ${attentionItems.length}`) : null,
          run.state === 'completed' ? h('span', { style: { color: TONE.ok, flex: '0 0 auto' } }, '✓ 完成') : null,
        ),
      )

      const head = h('div', {
        style: { display: 'flex', alignItems: 'flex-start', gap: 6, width: '100%', minWidth: 0 },
      },
        row,
        canOpenReview ? h('button', {
          type: 'button',
          title: '打开待审听对话',
          onClick: () => openSession(reviewSession),
          style: {
            flex: '0 0 auto', border: '1px solid var(--dsh-border, rgba(127,127,127,.28))',
            background: 'transparent', color: 'var(--dsh-accent, #4aa3df)',
            borderRadius: 999, padding: '1px 7px', font: 'inherit', fontSize: 10.5,
            cursor: 'pointer', whiteSpace: 'nowrap',
          },
        }, '打开对话 ↗') : null,
        h('button', {
          type: 'button',
          title: '关闭这一行（tab 保留）',
          'aria-label': '关闭进度行',
          onClick: () => onDismiss(run.runId),
          style: {
            flex: '0 0 auto', border: 0, background: 'transparent',
            color: 'var(--dsh-text-secondary, #8a8a8a)', cursor: 'pointer',
            fontSize: 15, lineHeight: 1, padding: '0 2px', opacity: 0.62,
          },
        }, '×'),
      )

      const panel = h('div', {
        style: {
          marginTop: 8, padding: '8px 9px', border: '1px solid var(--dsh-border, rgba(127,127,127,.2))',
          borderRadius: 8, background: 'var(--dsh-surface-2, rgba(127,127,127,.07))',
          fontSize: 11.2, lineHeight: 1.45, maxHeight: 380, overflowY: 'auto',
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
          }, run.runId),
          h('span', { style: { marginLeft: 'auto', opacity: 0.55, flex: '0 0 auto' } },
            stale ? '快照可能过期' : stateLabel(run.state)),
        ),
        attentionItems.length > 0 ? h('div', { style: { marginBottom: 5 } },
          attentionItems.map(item => h('div', {
            key: `${item.kind}:${item.stage || ''}:${item.since || ''}`,
            style: {
              display: 'flex', gap: 6, alignItems: 'baseline', padding: '2px 0',
              color: attentionTone(item.severity),
            },
          },
            h('span', { style: { flex: '0 0 auto' } }, `⚠ ${item.kind}`),
            h('span', {
              style: {
                minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                color: 'var(--dsh-text-secondary, #8a8a8a)',
              },
            }, item.message || item.waitingOn || stageLabel(item.stage)),
          ))) : null,
        run.stages.map(stage => h(StageLine, { key: stage.id, stage, snapshotAt: run.generatedAt })),
        run.required?.missing?.length ? h('div', {
          style: { marginTop: 5, color: TONE.attention, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
        }, `缺步骤：${run.required.missing.slice(0, 4).map(stageLabel).join('、')}`) : null,
        h('div', { style: { marginTop: 6, opacity: 0.55, display: 'flex', gap: 6 } },
          h('span', null, `快照 ${formatAge(ageSeconds(run.generatedAt, now))} 前`),
          stale ? h('span', { style: { color: TONE.attention } }, '· 可能过期') : null,
        ),
      )

      return h('section', {
        style: {
          border: '1px solid var(--dsh-border, rgba(127,127,127,.2))',
          borderRadius: 10, padding: '9px 10px', marginBottom: 9,
          background: 'var(--dsh-surface-1, rgba(127,127,127,.04))', minWidth: 0,
        },
      }, head, open ? panel : null)
    }

    function ProgressView({ openSession }) {
      const { data, error } = useStatus()
      const now = useNow()
      const dismissed = useDismissedRuns()
      const runs = orderedRuns(data?.runs)
      const visible = runs.filter(run => !dismissed.has(run.runId))
      const dismissedCount = runs.filter(run => dismissed.has(run.runId)).length
      const generatedAt = data?.generatedAt

      return h('div', {
        style: {
          width: '100%', height: '100%', overflowY: 'auto', boxSizing: 'border-box',
          padding: '14px 12px 28px', color: 'var(--dsh-text-primary, #e6e6e6)',
        },
      },
        h('div', {
          style: { display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap', marginBottom: 4 },
        },
          h('div', { style: { fontSize: 16, fontWeight: 650 } }, '生产进度'),
          generatedAt ? h('span', {
            style: { fontSize: 10.5, opacity: 0.55, fontVariantNumeric: 'tabular-nums' },
          }, `更新 ${formatAge(ageSeconds(generatedAt, now))} 前`) : null,
          error ? h('span', { style: { fontSize: 10.5, color: TONE.attention } }, `读取失败：${error}`) : null,
        ),
        h('div', { style: { fontSize: 10.5, opacity: 0.52, lineHeight: 1.45, marginBottom: 10 } },
          '关闭只隐藏这一行，tab 会保留；新 run 会出现。'),
        !data ? h('div', { style: { opacity: 0.55, fontSize: 12, padding: '16px 0' } }, '读取中…')
          : runs.length === 0 ? h('div', { style: { opacity: 0.55, fontSize: 12, padding: '16px 0' } }, '暂无生产 run')
          : visible.length === 0 ? h('div', {
            style: {
              border: '1px dashed var(--dsh-border, rgba(127,127,127,.28))', borderRadius: 10,
              padding: '16px 12px', fontSize: 12, opacity: 0.75,
            },
          },
            h('div', null, `已关闭 ${dismissedCount} 条进度`),
            h('button', {
              type: 'button',
              onClick: dismissed.restoreAll,
              style: {
                marginTop: 8, border: '1px solid var(--dsh-border, rgba(127,127,127,.28))',
                background: 'transparent', color: 'var(--dsh-accent, #4aa3df)',
                borderRadius: 6, padding: '3px 9px', font: 'inherit', fontSize: 11, cursor: 'pointer',
              },
            }, '恢复显示'),
          ) : visible.map((run, index) => h(RunCard, {
            key: run.runId,
            run,
            now,
            openSession,
            onDismiss: dismissed.dismiss,
            defaultOpen: index === 0,
          })),
        dismissedCount > 0 && visible.length > 0 ? h('div', {
          style: { marginTop: 12, fontSize: 10.5, opacity: 0.55, display: 'flex', gap: 8, alignItems: 'center' },
        },
          h('span', null, `已关闭 ${dismissedCount} 条`),
          h('button', {
            type: 'button',
            onClick: dismissed.restoreAll,
            style: {
              border: 0, background: 'transparent', color: 'var(--dsh-accent, #4aa3df)',
              padding: 0, font: 'inherit', fontSize: 10.5, cursor: 'pointer',
            },
          }, '恢复显示'),
        ) : null,
      )
    }

    const inject = ['slots', 'sessions']

    function reviewSessionId(run) {
      const human = (run.attention || []).find(item => item.kind === 'human_review' && item.sessionId)
      if (human) return human.sessionId
      const waiting = (run.stages || []).find(stage => stage.state === 'waiting' && stage.sessionId)
      return waiting ? waiting.sessionId : null
    }

    function openSession(ctx, sessionId) {
      if (!sessionId) return false
      try {
        if (ctx.sessions && typeof ctx.sessions.open === 'function') {
          ctx.sessions.open(sessionId)
          return true
        }
        const workspace = typeof ctx.get === 'function' ? ctx.get('uiWorkspace') : null
        if (workspace && typeof workspace.openSession === 'function') {
          workspace.openSession(sessionId)
          return true
        }
      } catch (error) {
        // Navigation is best-effort; never break the dock.
      }
      return false
    }

    const TAB_ID = 'production-progress'
    const TAB_TITLE = '进度'

    function apply(ctx) {
      const open = id => openSession(ctx, id)
      return ctx.inject(['sidebarRightTabs'], scope => {
        const tabs = scope.sidebarRightTabs
        if (!tabs || typeof tabs.register !== 'function') return
        const disposers = []
        const track = value => { if (typeof value === 'function') disposers.push(value) }
        try {
          track(tabs.register({
            id: TAB_ID,
            kind: TAB_ID,
            title: () => TAB_TITLE,
          }))
          track(scope.slots.inject('sidebar.right.pane.tab', () => scope.slots.register({
            name: 'sidebar.right.pane.tab',
            key: TAB_ID,
          }, props => h(ProgressView, { ...props, openSession: open }))))
          track(scope.slots.inject('sidebar.right.pane.tab.title', () => scope.slots.register({
            name: 'sidebar.right.pane.tab.title',
            key: TAB_ID,
          }, () => h('span', { style: { fontWeight: 600 } }, TAB_TITLE))))
        } catch (error) {
          for (const dispose of disposers.splice(0)) dispose()
          return
        }
        return () => { for (const dispose of disposers.splice(0)) dispose() }
      })
    }

    return { apply, inject, ProgressView, stageLabel, etaText, formatClock, reviewSessionId, orderedRuns, readDismissedRuns }
  },
})
