import { tr } from './i18n.js';
import { formatDuration } from './timing.js';
import { sanitizeDag } from './dag-contract.js';
import { snapshotFreshness } from './snapshot-state.js';

const el = (tag, cls = '', text) => { const node = document.createElement(tag); node.className = cls; if (text !== undefined) node.textContent = text; return node; };
const labels = {
  completed:['执行完成','Execution finished'],complete:['计划节点结束','Plan node finished'],failed:['失败','Failed'],cancelled:['已取消','Cancelled'],
  outcome_unknown:['结果未知','Outcome unknown'],unfinished_or_ambiguous:['执行未闭合 · 在线未知','Open execution · Liveness unknown'],pending:['待开始','Pending'],
  running:['运行中','Running'],retrying:['重试中','Retrying'],waiting_review:['等待审核','Awaiting review'],blocked:['阻塞','Blocked'],unknown_outcome:['结果未知','Outcome unknown'],queued:['资源排队','Queued'],unknown:['未知','Unknown'],
  deterministic_program:['确定性程序','Deterministic program'],production_model:['制作模型','Production model'],decision_agent:['决策 Agent','Decision agent'],human:['人工','Human'],external_service:['外部服务','External service'],engineering_codex:['工程 Codex','Engineering Codex'],
  initial_translation:['初译','Initial translation'],independent_review:['独立复核','Independent review'],unit_synthesis:['逐单元合成','Unit synthesis'],audio_validation:['音频校验','Audio validation'],schedule_sync:['排程同步','Schedule sync'],translation:['翻译','Translation'],review:['审核','Review'],asr:['语音识别','ASR'],tts:['语音合成','TTS'],validation:['校验','Validation'],publication:['发布','Publication'],source:['来源准备','Source preparation'],
  real:['真实记录','Real evidence'],synthetic:['合成／模拟记录','Synthetic / mock evidence'],mixed:['真实与模拟混合','Mixed real and synthetic evidence'],
};
const label = (value) => labels[value] ? tr(...labels[value]) : tr('未知', 'Unknown');
const duration = (value) => value == null ? tr('未知', 'Unknown') : formatDuration(value);
const nodeUncertain = (node) => node.kind === 'planned' && (node.unknownOutcome || (node.status === 'complete' && !node.complete));
export const nodeLabel = (node) => node.kind === 'planned' && node.unknownOutcome ? tr('旧尝试结果未解决', 'Previous attempt unresolved') :
  node.kind === 'planned' && node.status === 'complete' && !node.complete ? tr('已报结束 · 门禁未齐', 'Reported finished · Gates unresolved') :
  node.status === 'running' && node.heartbeatStatus !== 'fresh' ? tr('已报运行 · 在线未知', 'Reported running · Liveness unknown') : node.status === 'running' ? tr('最近记录：运行中', 'Last reported running') : label(node.status);
const nodeClass = (node) => nodeUncertain(node) || (node.status === 'running' && node.heartbeatStatus !== 'fresh') ? 'warn' : statusClass(node.status);
const statusClass = (state) => ['completed','complete'].includes(state) ? 'ok' : ['running'].includes(state) ? 'active' : ['failed','blocked'].includes(state) ? 'bad' : 'warn';
const stat = (title, value, detail) => { const node = el('div', 'dag-stat'); node.append(el('span', '', title), el('strong', '', value), el('small', '', detail)); return node; };
let selection = null;
let scope = null;
let view = 'planned';
let previousDag = null;

export function dagRanks(nodes) {
  const ranks = new Map();
  const pending = new Map(nodes.map((node) => [node.id,node]));
  while (pending.size) {
    const ready = [...pending.values()].filter((node) => node.dependsOn.every((id) => ranks.has(id)));
    if (!ready.length) return [];
    for (const node of ready) { ranks.set(node.id, Math.max(-1,...node.dependsOn.map((id) => ranks.get(id))) + 1); pending.delete(node.id); }
  }
  return [...new Set(ranks.values())].sort((a,b) => a-b).map((rank) => nodes.filter((node) => ranks.get(node.id) === rank));
}

const freshProjection = (snapshot, dag) => snapshotFreshness(snapshot.generatedAt).status === 'recent' && snapshotFreshness(dag?.generatedAt).status === 'recent';

function etaText(dag, snapshot) {
  if (dag.eta.status === 'complete') return tr('计划门禁齐备', 'Planned evidence complete');
  if (dag.eta.status !== 'estimated' || !freshProjection(snapshot, dag)) return tr('未知', 'Unknown');
  return `${duration(dag.eta.lowerSeconds)} – ${duration(dag.eta.upperSeconds)}`;
}

function evidenceAgeText(dag) {
  const { status } = snapshotFreshness(dag.freshness.sourceObservedAt);
  return tr(`日志证据：${status === 'recent' ? '最近记录' : status === 'stale' ? '旧记录' : '时间未知'} · 投影完整性：${dag.quality.status} · 节点 ID 仅在本快照内有效`, `Log evidence: ${status} · Projection integrity: ${dag.quality.status} · Node IDs are snapshot-local`);
}

export function renderDag(snapshot) {
  const host = document.getElementById('dag-panel');
  const dag = sanitizeDag(snapshot.dag);
  const openDetails = new Set([...host.querySelectorAll('details[open]')].map((n) => n.className));
  const focusInside = host.contains(document.activeElement);
  const focusId = focusInside ? document.activeElement.id : null;
  if (scope !== snapshot.pageId) { scope = snapshot.pageId; selection = null; view = 'planned'; }
  if (previousDag !== snapshot.dag) { selection = null; previousDag = snapshot.dag; }
  host.replaceChildren();
  if (!dag) {
    host.append(el('p', 'dag-empty', tr('这份快照尚未接入执行 DAG。下方检查点保留原有账本状态；模型、依赖和剩余时间不会由百分比补造。', 'This snapshot has no execution DAG. The checkpoint ledger remains below; models, dependencies and remaining time are not inferred from its percentage.')));
    return;
  }
  const modes = el('div', 'dag-mode');
  modes.append(el('span', `badge ${dag.evidenceMode === 'real' ? '' : 'warn'}`, label(dag.evidenceMode)),
    el('span', 'muted', tr('只读投影 · 不授予内容批准或发布资格', 'Read-only projection · No content or release authority')));
  const metrics = el('div', 'dag-stats');
  const counts = dag.progress?.counts;
  metrics.append(stat(tr('已处理 / 冻结计划', 'Processed / frozen plan'), counts ? `${counts.processed ?? '?'} / ${counts.total ?? '?'}` : tr('未接入计划', 'Plan not connected'),
    dag.progress?.plannedProcessedPercent == null ? tr('覆盖不足，百分比未知', 'Insufficient coverage; percentage unknown') : `${dag.progress.plannedProcessedPercent}% · ${tr('处理不等于通过', 'Processed does not mean passed')}`),
    stat(tr('剩余 DAG 估计区间', 'Remaining DAG estimate'), etaText(dag,snapshot), tr(`${dag.eta.sampleCount ?? 0} 个可比样本 · ${dag.eta.confidence === 'medium' ? '中等' : dag.eta.confidence === 'low' ? '低' : '未知'}置信度`, `${dag.eta.sampleCount ?? 0} comparable samples · ${dag.eta.confidence} confidence`)),
    stat(tr('已记录墙钟时间', 'Recorded wall time'), duration(dag.summary.endToEndWallSeconds), tr('并行叶节点耗时不相加为总耗时', 'Parallel leaf durations are not wall time')));
  metrics.children[1].querySelector('strong').id = 'dag-eta-value';
  const detail = el('details','dag-estimate-detail');
  detail.append(el('summary','',tr('估计依据与数据覆盖', 'Estimate basis and data coverage')));
  detail.append(el('p','',tr('按已冻结依赖和资源容量估计；人工等待、未知结果、过期心跳或缺历史样本时降级为未知。区间不包括未来重试、新返工或未记录排队，不承诺交付时刻。', 'Estimated from frozen dependencies and resource capacity. Human waits, unknown outcomes, stale heartbeats or missing history make ETA unknown. The interval excludes future retries, new rework and unrecorded queues; it is not a delivery promise.')),
    el('p','',`${tr('实测完成叶节点小计', 'Completed leaf subtotal')}: ${duration(dag.summary.measuredSpanSeconds)} · ${tr('已记录关键路径', 'Recorded critical path')}: ${duration(dag.criticalPath.activeSeconds)}`),
    el('p','',`${tr('未闭合执行', 'Open executions')}: ${dag.summary.unfinishedSpanCount ?? '?'} · ${tr('损坏日志行', 'Damaged log rows')}: ${dag.quality.damagedRowCount ?? '?'} · ${tr('未展示节点', 'Omitted nodes')}: ${dag.quality.omittedNodeCount ?? '?'}`));
  if (dag.eta.reasonCodes.length) detail.append(el('p','dag-reasons', `${tr('未知／降级原因代码', 'Unknown / degraded reason codes')}: ${dag.eta.reasonCodes.join(' · ')}`));
  host.append(modes, metrics, detail);
  const evidence = el('p','dag-empty',evidenceAgeText(dag));
  evidence.id = 'dag-evidence-age';
  host.append(evidence);
  const toolbar = el('div','dag-toolbar');
  const chooser = el('div','dag-tabs'); chooser.setAttribute('role','group'); chooser.setAttribute('aria-label',tr('DAG 数据视图','DAG data view'));
  for (const mode of ['planned','observed']) {
    const button = el('button','',mode === 'planned' ? tr('冻结计划与状态','Frozen plan & state') : tr('已观测执行 DAG','Observed execution DAG'));
    button.type = 'button'; button.setAttribute('aria-pressed',String(view === mode));
    button.addEventListener('click',() => { view = mode; selection = null; renderDag(snapshot); host.querySelector(`button[aria-pressed="true"]`)?.focus(); });
    chooser.append(button);
  }
  toolbar.append(chooser,el('small','muted',tr('选择节点查看模型、计时、依赖与输入输出', 'Select a node for model, timing, dependencies and I/O'))); host.append(toolbar);
  const nodes = view === 'planned' ? dag.progress?.nodes || [] : dag.nodes;
  if (!nodes.length) { host.append(el('p','dag-empty',view === 'planned' ? tr('尚无绑定本轮的冻结计划与状态收据。已观测视图只显示真实写入的执行记录。', 'No frozen plan and receipts bound to this run. The observed view shows only recorded executions.') : tr('尚无可展示的执行记录。', 'No execution records available.'))); }
  else {
    if (!nodes.some((node) => node.id === selection)) selection = nodes.find((node) => ['running','blocked','retrying','unknown_outcome','unfinished_or_ambiguous'].includes(node.status))?.id || nodes[0].id;
    const layout = el('div','dag-layout');
    const graph = el('div','dag-graph'); graph.setAttribute('aria-label',tr('按依赖顺序排列的 DAG 节点','DAG nodes in dependency order'));
    for (const [index, rank] of dagRanks(nodes).entries()) {
      const column = el('section','dag-rank'); column.append(el('h4','',tr(`依赖层 ${index+1}`, `Dependency level ${index+1}`)));
      for (const node of rank) {
        const button = el('button',`dag-node ${nodeClass(node)}`); button.type='button'; button.dataset.runState = node.status; button.dataset.heartbeat = node.heartbeatStatus; button.setAttribute('aria-pressed',String(node.id === selection)); button.setAttribute('aria-controls','dag-node-detail');
        button.append(el('strong','',`${node.id} · ${label(node.code)}`),el('span','dag-node-state',nodeLabel(node)),el('small','',`${node.layer ? `L${node.layer}` : tr('层未知','Layer unknown')} · ${node.locale === 'unknown' ? tr('语言未知','Locale unknown') : node.locale}`),el('small','',node.dependsOn.length ? `← ${node.dependsOn.join(', ')}` : node.dependencyStatus === 'recorded' ? tr('已记录为根节点', 'Recorded root node') : tr('依赖证据未知', 'Dependency evidence unknown')));
        button.addEventListener('click',() => { selection=node.id; renderDag(snapshot); host.querySelector(`#dag-node-detail`)?.focus({preventScroll:true}); }); column.append(button);
      }
      graph.append(column);
    }
    const node = nodes.find((n) => n.id === selection);
    const panel = el('section','dag-node-detail'); panel.id='dag-node-detail'; panel.tabIndex=-1; panel.setAttribute('aria-labelledby','dag-node-title');
    const title = el('h4','',`${node.id} · ${label(node.code)}`);title.id='dag-node-title'; const statusBadge = el('span',`badge ${nodeClass(node)}`,nodeLabel(node));statusBadge.id='dag-node-status';statusBadge.dataset.runState=node.status;statusBadge.dataset.heartbeat=node.heartbeatStatus;panel.append(title,statusBadge);
    const facts=el('dl','dag-facts');
    const values = [
      [tr('执行角色','Executor role'),label(node.executorType)], [tr('执行器心跳','Executor heartbeat'),({fresh:tr('有新鲜收据','Fresh receipt'),stale:tr('过期','Stale'),unknown:tr('未知','Unknown'),not_applicable:tr('不适用','Not applicable')})[node.heartbeatStatus]], [view === 'planned' ? tr('计划配置模型','Planned model') : tr('已观测模型','Observed model'),node.modelCodes.join(' · ') || tr('未记录／未公开','Not recorded / not public')],
      [tr('逻辑层 / 语言','Logical layer / locale'),`${node.layer ? `L${node.layer}` : '—'} / ${node.locale}`],
      [tr('累计重试','Retries'),node.retryCount == null ? tr('身份不足，未知','Insufficient identity; unknown') : String(node.retryCount)],
      [tr('本次实测执行','Measured attempt'),duration(node.timing.elapsedSeconds)],
      [tr('进行中实测计时','Measured active elapsed'),duration(node.timing.activeElapsedSeconds)],
      [tr('输入产物 / 输出产物','Input / output artifacts'),`${node.io.inputArtifactCount ?? '?'} / ${node.io.outputArtifactCount ?? '?'}`],
      [tr('未解析依赖','Unresolved dependencies'),String(node.unresolvedDependencyCount)],
    ];
    for (const [name,value] of values) { const pair=el('div');pair.append(el('dt','',name),el('dd','',value));if (name === tr('执行器心跳','Executor heartbeat')) { pair.lastChild.id='dag-heartbeat';pair.lastChild.dataset.heartbeat=node.heartbeatStatus; } facts.append(pair); } panel.append(facts);
    if (node.dependsOn.length) { const links=el('div','dag-dependencies'); links.append(el('span','',tr('上游节点：','Upstream: '))); for (const dep of node.dependsOn) { const link=el('button','',dep);link.type='button';link.addEventListener('click',()=>{selection=dep;renderDag(snapshot);host.querySelector('#dag-node-detail')?.focus({preventScroll:true});});links.append(link); } panel.append(links); }
    panel.append(el('p','hint',tr('输入输出只展示已绑定的公开数量；原始路径、内容、哈希和私有日志不在公开页面提供下载。缺失证据保持未知。', 'I/O shows bound public counts only. Raw paths, content, hashes and private logs are not downloadable from this public page. Missing evidence stays unknown.')));
    if (view === 'planned') {
      const evidence=el('div','dag-evidence');
      for (const [key,name] of [['executionSucceeded',tr('执行通过','Execution passed')],['contentReviewPassed',tr('机器复核','Machine review')],['realHumanApproved',tr('真实人审','Real human review')],['simulatedHumanApproved',tr('模拟人审','Simulated review')],['admitted',tr('准入','Admission')]]) evidence.append(el('span','',`${name}: ${!node.requiredEvidence.includes(key) ? tr('非本节点必需门禁','Not required for this node') : node.evidence[key] === true ? tr('有证据','Evidenced') : node.evidence[key] === false ? tr('未有通过证据','No passing evidence') : tr('未知','Unknown')}`));
      panel.append(evidence);
    }
    layout.append(graph,panel);host.append(layout);
    refreshDagEstimate(snapshot);
  }
  const log=el('details','dag-log-contract');log.append(el('summary','',tr('统一日志格式与安全边界','Unified log format and safety boundary')),
    el('p','',tr('规范格式：sermon-workflow-accounting-v3 / sermon-accounting-log-contract-v1。事件按 run、workflow、span、attempt、sequence 关联；重试追加新尝试，容器不重复计入叶节点耗时。', 'Canonical format: sermon-workflow-accounting-v3 / sermon-accounting-log-contract-v1. Events correlate run, workflow, span, attempt and sequence; retries append attempts, and containers do not double-count leaf duration.')),
    el('p','',tr('此视图是允许字段的投影，不是原始日志；连接成功、执行结束、机器复核、人工批准与发布验收各自独立。', 'This view is an allowlisted projection, not raw logs. Connection, execution, machine review, human approval and release acceptance remain independent.')),el('p','',`${tr('事件 / 规范格式 / 旧格式', 'Events / canonical profile / legacy')}: ${dag.logs.eventCount ?? '?'} / ${dag.logs.profileEventCount ?? '?'} / ${dag.logs.legacyEventCount ?? '?'}`));host.append(log);
  for (const detail of host.querySelectorAll('details')) detail.open = openDetails.has(detail.className);
  if (focusInside) {
    const target = focusId ? document.getElementById(focusId) : host.querySelector('.dag-tabs button[aria-pressed="true"]');
    target?.focus({preventScroll:true});
  }
}

export function refreshDagEstimate(snapshot) {
  const target = document.getElementById('dag-eta-value');
  const dag = target ? sanitizeDag(snapshot.dag) : null;
  if (dag) {
    target.textContent = etaText(dag, snapshot);
    const evidence = document.getElementById('dag-evidence-age');
    if (evidence) evidence.textContent = evidenceAgeText(dag);
  }
  if (!freshProjection(snapshot, dag)) {
    for (const element of document.querySelectorAll('[data-run-state="running"]')) {
      element.classList.remove('active'); element.classList.add('warn');
      const text = element.querySelector('.dag-node-state') || element;
      text.textContent = tr('已报运行 · 快照已过期', 'Reported running · Snapshot stale');
    }
    const heartbeat = document.getElementById('dag-heartbeat');
    if (heartbeat?.dataset.heartbeat === 'fresh') heartbeat.textContent = tr('旧快照中的心跳；当前未知', 'Heartbeat in old snapshot; current state unknown');
  }
}
