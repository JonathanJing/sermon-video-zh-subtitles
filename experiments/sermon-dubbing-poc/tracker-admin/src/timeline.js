import { tr, uiLanguage } from './i18n.js';

const SUBSTEP_NAMES = {
  transcribe: ['英文转写', 'English transcription'], align: ['词级对齐', 'Word alignment'],
  freeze: ['英文稿冻结', 'Freeze English text'], anchors: ['时间锚点', 'Time anchors'],
  boundary_check: ['句界与停顿检查', 'Boundary and pause check'],
  group: ['翻译组整体', 'Translation group'], translator: ['初译', 'Initial translation'],
  reviewer: ['独立复核', 'Independent review'], repair: ['修订与重试', 'Repair and retry'],
  coverage: ['覆盖检查', 'Coverage check'], language: ['语言与经文检查', 'Language and scripture check'],
  admission: ['候选准入', 'Candidate admission'], inputs: ['输入物化', 'Materialize inputs'],
  validate: ['身份与策略验证', 'Identity and policy validation'],
  model_load: ['模型加载', 'Model loading'], render_units: ['单元渲染整体', 'Render units, parent span'],
  unit: ['逐单元合成', 'Synthesize units'], assemble: ['音轨组装', 'Assemble track'],
  decode: ['音频解码', 'Decode audio'], hash: ['哈希与收据', 'Hash and receipts'],
  asr: ['回转写筛查', 'Back-transcription screen'], schedule: ['时间排程', 'Schedule'],
  captions: ['字幕 cue', 'Caption cues'], mix: ['完整音轨编码', 'Encode full track'],
  build: ['清单与资产构建', 'Build assets and manifest'], upload: ['资产上传', 'Upload assets'],
  get: ['GET 与哈希', 'GET and hash'], range: ['Range 核验', 'Range verification'],
};
const KINDS = {
  running: ['进行中状态', 'In-progress status'],
  waiting_review: ['待审核状态', 'Awaiting-review status'],
  blocked: ['阻塞状态', 'Blocked status'], measured: ['执行实测', 'Measured execution'],
};
const node = (tag, className = '', value) => {
  const item = document.createElement(tag);
  item.className = className;
  if (value !== undefined) item.textContent = value;
  return item;
};
const name = (code) => SUBSTEP_NAMES[code]?.[uiLanguage() === 'en' ? 1 : 0] || code;
const duration = (seconds) => {
  if (!Number.isFinite(seconds)) return tr('未计时', 'Not measured');
  if (seconds < 60) return `${Math.round(seconds * 10) / 10}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600 * 10) / 10}h`;
  return `${Math.round(seconds / 86400 * 10) / 10}d`;
};
const kindName = (kind) => tr(...(KINDS[kind] || [kind, kind]));
const layer = (id) => Number(id?.[1]);
const hasObservedTime = (row) => row.intervals.length || row.attempts.length
  || row.completedAtSeconds !== null || row.substeps.some((item) => item.attempts.length);

function addSpans(track, spans, range, kind) {
  const width = Math.max(range.end - range.start, 0.1);
  for (const span of spans) {
    const start = Math.max(range.start, span.startSeconds);
    const end = Math.min(range.end, span.endSeconds);
    if (end < start) continue;
    const bar = node('span', `timeline-bar ${kind || span.kind}`);
    bar.style.left = `${Math.max(0, Math.min(100, 100 * (start - range.start) / width))}%`;
    bar.style.width = `${Math.max(0.35, 100 * (end - start) / width)}%`;
    bar.title = `${kindName(kind || span.kind)} · ${duration(span.endSeconds - span.startSeconds)} · +${duration(span.startSeconds)} → +${duration(span.endSeconds)}`;
    track.append(bar);
  }
}

function axisRange(rows, fullDuration, focused) {
  if (!focused) return { start: 0, end: Math.max(fullDuration, 1) };
  const values = rows.flatMap((row) => [
    ...row.intervals.flatMap((span) => [span.startSeconds, span.endSeconds]),
    ...row.attempts.flatMap((span) => [span.startSeconds, span.endSeconds]),
    ...row.substeps.flatMap((child) => child.attempts.flatMap((span) => [span.startSeconds, span.endSeconds])),
    row.completedAtSeconds,
  ]).filter(Number.isFinite);
  if (!values.length) return { start: 0, end: Math.max(fullDuration, 1) };
  const start = Math.min(...values);
  const end = Math.max(...values);
  return { start, end: Math.max(start + 1, end) };
}

function addRankings(container, rows, stepName) {
  const sets = [
    { title: tr('最长状态区间', 'Longest status intervals'),
      entries: rows.flatMap((row) => row.intervals.map((span) => ({ row, span }))) },
    { title: tr('最长执行实测', 'Longest measured executions'),
      entries: rows.flatMap((row) => [
        ...row.attempts.map((span) => ({ row, span })),
        ...row.substeps.flatMap((child) => child.attempts.map((span) => ({ row, span, child }))),
      ]) },
  ];
  const wrapper = node('div', 'timeline-rankings');
  for (const set of sets) {
    const box = node('div', 'timeline-ranking');
    box.append(node('h4', '', set.title));
    const entries = set.entries.sort((a, b) =>
      (b.span.endSeconds - b.span.startSeconds) - (a.span.endSeconds - a.span.startSeconds)).slice(0, 3);
    if (!entries.length) box.append(node('p', 'muted', tr('尚无实测记录', 'No measured records')));
    else {
      const list = node('ol');
      for (const { row, span, child } of entries) {
        list.append(node('li', '', `${row.id}${child ? ` / ${name(child.code)}` : ` · ${stepName(row)}`} · ${kindName(span.kind)} · ${duration(span.endSeconds - span.startSeconds)}`));
      }
      box.append(list);
    }
    wrapper.append(box);
  }
  container.append(wrapper);
}

export function renderTimeline(snapshot, stepName) {
  const container = document.getElementById('timeline');
  const timeline = snapshot?.timeline;
  if (timeline?.schemaVersion !== 'sermon-tracker-relative-timeline-v1' || !Array.isArray(timeline.rows)) {
    container.replaceChildren(node('p', 'timeline-empty', tr(
      '这份快照尚无时间线数据。用新版快照生成器从本周账本重新发布后显示。',
      'No timeline data in this snapshot. Rebuild and publish it from this week’s ledger.')));
    return;
  }
  const rows = timeline.rows;
  const summary = node('div', 'timeline-summary');
  summary.append(node('strong', '', tr('计时覆盖', 'Timing coverage')),
    node('span', '', tr(
      `${timeline.coverage?.measuredSteps || 0}/${rows.length} 步骤实测 · ${timeline.coverage?.measuredSubsteps || 0}/${timeline.coverage?.plannedSubsteps || 0} 细分实测`,
      `${timeline.coverage?.measuredSteps || 0}/${rows.length} measured steps · ${timeline.coverage?.measuredSubsteps || 0}/${timeline.coverage?.plannedSubsteps || 0} measured substeps`)),
    node('span', 'muted', tr(`观察跨度 ${duration(timeline.durationSeconds)}`, `Observed span ${duration(timeline.durationSeconds)}`)));
  const note = node('p', 'timeline-note', tr(
    '横轴从首次有记录的事件起算；状态持续不等于程序耗时。圆点只表示完成记录；没有起止记录的细分项显示“未计时”。重叠的父子跨度不可相加。',
    'The axis begins at the first recorded event. Status duration is not execution time. A dot marks completion only; substeps without start and end are unmeasured. Overlapping parent and child spans cannot be summed.'));
  const toolbar = node('div', 'timeline-toolbar');
  const filter = node('select');
  filter.setAttribute('aria-label', tr('筛选时间线层次', 'Filter timeline layer'));
  for (const [value, title] of [['all', tr('全部层', 'All layers')], ...[1, 2, 3, 4].map((item) => [String(item), `Layer ${item}`])]) {
    const option = node('option', '', title);
    option.value = value;
    filter.append(option);
  }
  const previous = container.querySelector('select')?.value;
  filter.value = ['all', '1', '2', '3', '4'].includes(previous) ? previous : 'all';
  const legend = node('div', 'timeline-legend');
  for (const kind of ['measured', 'running', 'waiting_review', 'blocked']) {
    const item = node('span', '', kindName(kind));
    item.prepend(node('i', kind));
    legend.append(item);
  }
  toolbar.append(filter, legend);
  const axis = node('div', 'timeline-axis');
  const chart = node('div', 'timeline-chart');
  filter.addEventListener('change', draw);
  container.replaceChildren(summary, note, toolbar, axis, chart);
  addRankings(container, rows, stepName);
  draw();

  function draw() {
    const selected = filter.value;
    const visible = selected === 'all' ? rows : rows.filter((row) => layer(row.id) === Number(selected));
    const range = axisRange(visible, timeline.durationSeconds, selected !== 'all');
    axis.replaceChildren(node('span', '', `+${duration(range.start)}`),
      node('span', '', `+${duration((range.start + range.end) / 2)}`),
      node('span', '', `+${duration(range.end)}`));
    const plotted = visible;
    chart.replaceChildren();
    if (!plotted.length) {
      chart.append(node('p', 'timeline-empty', tr('此层尚无带时间的记录。', 'No timed records in this layer.')));
      return;
    }
    for (const row of plotted) {
      const details = node('details', 'timeline-row');
      const head = node('summary', 'timeline-row-head');
      const title = node('span', 'timeline-row-title', `${row.id} · ${stepName(row)}${hasObservedTime(row) ? '' : tr(' · 未计时', ' · unmeasured')}`);
      const track = node('span', 'timeline-track');
      addSpans(track, row.intervals, range);
      addSpans(track, row.attempts, range);
      if (row.completedAtSeconds !== null && row.completedAtSeconds >= range.start && row.completedAtSeconds <= range.end) {
        const marker = node('span', 'timeline-complete');
        marker.style.left = `${100 * (row.completedAtSeconds - range.start) / (range.end - range.start)}%`;
        marker.title = tr('完成记录；不代表执行时长', 'Completion event; not execution duration');
        track.append(marker);
      }
      head.append(title, track);
      details.append(head);
      const body = node('div', 'timeline-detail');
      const measured = row.attempts.reduce((sum, span) => sum + span.endSeconds - span.startSeconds, 0);
      body.append(node('p', 'muted', tr(
        `执行跨度 ${row.attempts.length} 条，合计 ${row.attempts.length ? duration(measured) : '未计时'}；状态跨度 ${row.intervals.length} 条。`,
        `${row.attempts.length} execution spans, total ${row.attempts.length ? duration(measured) : 'unmeasured'}; ${row.intervals.length} status intervals.`)));
      for (const child of row.substeps) {
        const childRow = node('div', 'timeline-child');
        const dependency = child.dependsOn.length ? tr(` · 依赖 ${child.dependsOn.map(name).join('、')}`, ` · depends on ${child.dependsOn.map(name).join(', ')}`) : '';
        childRow.append(node('span', '', `${name(child.code)}${dependency}`),
          node('span', child.observedCount ? 'timeline-observed' : 'muted', child.observedCount
            ? tr(`${child.observedCount} 条实测 · 最长 ${duration(child.longestSeconds)}`, `${child.observedCount} measured · longest ${duration(child.longestSeconds)}`)
            : tr('未计时', 'Not measured')));
        if (child.attempts.length) {
          const childTrack = node('span', 'timeline-track timeline-child-track');
          addSpans(childTrack, child.attempts, range);
          childRow.append(childTrack);
        }
        body.append(childRow);
      }
      details.append(body);
      chart.append(details);
    }
  }
}
