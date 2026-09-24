/** Opt-in review prototype. Browser controls never write to Firestore or local artifacts. */
import { tr } from './i18n.js';

let stage = 'evidence';
let selectedStep = null;
let decision = null;
let comment = '';
let lastSnapshot = null;
let lastProof = null;

const byId = (id) => document.getElementById(id);
const make = (tag, className, content) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content) node.textContent = content;
  return node;
};
const reviewSteps = (snapshot) => (snapshot.steps || []).filter((step) => step.status === 'waiting_review');

function reset() { stage = 'evidence'; decision = null; comment = ''; }

function evidencePanel(snapshot, candidate) {
  const isAudio = candidate.layer === 3 || candidate.id.startsWith('L3-');
  const panel = make('section', 'bridge-panel');
  panel.append(make('h4', '', tr('审核证据', 'Review evidence')));
  panel.append(make('p', 'bridge-evidence-note', tr(
    '此处展示公开状态能提供的文字。完整审核材料仍在本机私有目录，尚未安全接入 Firebase。',
    'This shows text available in the public status. Full review materials remain in private local storage and are not yet available through Firebase.')));

  const media = make('div', 'bridge-media');
  media.append(make('strong', '', tr('音频／视频回放', 'Audio / video playback')));
  media.append(make('p', '', isAudio ? tr(
    '暂无可播放的审核媒体。正式接入后，此处播放与任务版本绑定的音轨及 1 倍速视频。',
    'No review media is available. The real review will play a version-bound track and 1× video here.') : tr(
    '此文字审核任务没有要求在此播放音频。正式证据应显示源文、候选文字和版本身份。',
    'This text review does not require audio here. Formal evidence should show source text, candidate text, and version identity.')));
  panel.append(media);

  const text = make('details', 'bridge-text-evidence');
  text.open = true;
  text.append(make('summary', '', tr('查看现有文字证据', 'Read available text evidence')));
  const rows = make('dl', 'bridge-facts');
  for (const [key, value] of [
    [tr('页面', 'Page'), snapshot.pageId],
    [tr('检查点', 'Checkpoint'), candidate.id],
    [tr('审核内容', 'Review subject'), isAudio ? tr('目标语言完整音轨的人耳听审与视频同步', 'Full target-language track listening and video synchronization') : (candidate.title || candidate.id)],
    [tr('当前状态', 'Current status'), tr('待人工审核', 'Awaiting human review')],
  ]) {
    const row = make('div', '');
    row.append(make('dt', '', key), make('dd', '', value));
    rows.append(row);
  }
  text.append(rows);
  text.append(make('p', 'bridge-evidence-note', isAudio ? tr(
    '正式音频审核还须核对全文播放、1 倍速视频同步、发音、自然度、完整性、经文、音色身份、同步和 ASR 疑点。这里的状态文字不能替代这些证据。',
    'Formal audio review also requires full playback, 1× video sync, pronunciation, naturalness, completeness, scripture, voice identity, synchronization, and ASR issue decisions. This status text cannot replace that evidence.') : tr(
    '正式文字审核须展示源文、译文、经文版本及逐项问题；这里的状态文字不能替代候选全文。',
    'Formal text review needs source text, translation, scripture version, and issue details. This status text cannot replace the full candidate.')));
  panel.append(text);
  return panel;
}

function decisionPanel(snapshot) {
  const panel = make('section', 'bridge-panel bridge-decision');
  panel.append(make('h4', '', tr('审核决定 · 模拟', 'Review decision · simulation')));
  panel.append(make('p', 'bridge-evidence-note', tr(
    '可试用选择和输入；页面不会保存、发送或授予正式批准。没有完整媒体时，请勿据此作真实同意决定。',
    'Try the choices and comment field. This page does not save, send, or grant formal approval. Do not make a real approval decision without the full media.')));
  const choices = make('div', 'bridge-choice-group');
  for (const [value, zh, en] of [['approve', '同意', 'Approve'], ['reject', '不同意', 'Reject']]) {
    const button = make('button', `bridge-choice ${decision === value ? 'selected' : ''}`, tr(zh, en));
    button.type = 'button';
    button.setAttribute('aria-pressed', String(decision === value));
    button.disabled = stage !== 'evidence';
    button.addEventListener('click', () => { decision = value; render(snapshot); });
    choices.append(button);
  }
  panel.append(choices);

  const label = make('label', 'bridge-comment-label', tr('审核意见', 'Review comment'));
  label.htmlFor = 'bridge-comment';
  const input = make('textarea', 'bridge-comment');
  input.id = 'bridge-comment';
  input.rows = 4;
  input.maxLength = 2000;
  input.placeholder = tr('写明具体问题、时间点或修改建议；不同意时必填。',
    'Describe the issue, timecode, or requested change. Required for rejection.');
  input.value = comment;
  input.disabled = stage !== 'evidence';
  panel.append(label, input);

  const actions = make('div', 'bridge-actions');
  const submit = make('button', 'button primary', tr('模拟提交裁决', 'Simulate decision submission'));
  submit.type = 'button';
  const updateSubmit = () => { submit.disabled = stage !== 'evidence' || !decision || (decision === 'reject' && !comment.trim()); };
  input.addEventListener('input', () => { comment = input.value; updateSubmit(); });
  updateSubmit();
  submit.addEventListener('click', () => { stage = 'queued'; render(snapshot); });
  actions.append(submit);
  if (stage === 'queued') {
    const receive = make('button', 'button', tr('模拟 Mac 领取', 'Simulate Mac receipt'));
    receive.type = 'button';
    receive.addEventListener('click', () => { stage = 'received'; render(snapshot); });
    actions.append(receive);
  }
  const clear = make('button', 'button ghost', tr('重置', 'Reset'));
  clear.type = 'button';
  clear.addEventListener('click', () => { reset(); render(snapshot); });
  actions.append(clear);
  panel.append(actions);
  if (stage !== 'evidence') panel.append(make('p', 'bridge-draft-result', tr(
    `模拟裁决：${decision === 'approve' ? '同意' : '不同意'}。意见：${comment.trim() || '未填写'}。仅保存在当前页面内存。`,
    `Simulated decision: ${decision === 'approve' ? 'approve' : 'reject'}. Comment: ${comment.trim() || 'none'}. Held only in this page's memory.`)));
  return panel;
}

export function mount() {
  byId('bridge-mock').hidden = false;
  fetch('./bridge-mock-result.json', { cache: 'no-store' }).then((response) => response.json())
    .then((proof) => {
      if (proof.schemaVersion === 'sermon-tracker-bridge-mock-result-v1'
          && proof.mockOnly === true && proof.cloudState === 'received') {
        lastProof = proof;
        if (lastSnapshot) render(lastSnapshot);
      }
    }).catch(() => {});
}

export function render(snapshot) {
  lastSnapshot = snapshot;
  const available = reviewSteps(snapshot);
  if (!available.some((step) => step.id === selectedStep)) {
    selectedStep = available[0]?.id || null;
    reset();
  }
  const candidate = available.find((step) => step.id === selectedStep);
  const root = byId('bridge-mock-content');
  root.replaceChildren();
  if (!candidate) {
    root.append(make('p', 'bridge-evidence-note', tr('当前页面没有待人工审核的检查点。', 'This page has no checkpoint awaiting human review.')));
    return;
  }

  const selector = make('div', 'bridge-task-selector');
  const label = make('label', '', tr('待审核任务', 'Awaiting review'));
  label.htmlFor = 'bridge-task';
  const select = make('select', '');
  select.id = 'bridge-task';
  for (const step of available) {
    const option = make('option', '', step.id);
    option.value = step.id;
    select.append(option);
  }
  select.value = selectedStep;
  select.addEventListener('change', () => { selectedStep = select.value; reset(); render(snapshot); });
  selector.append(label, select, make('span', 'badge warn', ({
    evidence: tr('查看证据与填写裁决', 'Inspect evidence and draft a decision'),
    queued: tr('模拟：Firebase 已排队', 'Simulated: queued in Firebase'),
    received: tr('模拟：Mac 已写入 JSON', 'Simulated: Mac wrote JSON'),
  })[stage]));
  root.append(selector);

  const path = make('ol', 'bridge-path');
  for (const [index, title] of [
    tr('证据与裁决', 'Evidence and decision'),
    tr('Firebase 指令', 'Firebase command'),
    tr('Mac JSON 收件箱', 'Mac JSON inbox'),
  ].entries()) path.append(make('li', `bridge-path-item ${index <= ['evidence', 'queued', 'received'].indexOf(stage) ? 'active' : ''}`, title));
  root.append(path);

  const columns = make('div', 'bridge-review-grid');
  columns.append(evidencePanel(snapshot, candidate), decisionPanel(snapshot));
  root.append(columns);
  root.append(make('p', 'bridge-disclaimer', tr(
    '所有裁决按钮仅为本浏览器模拟。真实云端→本机测试使用私有 mock_ping 指令；它不能批准内容或启动制作。',
    'All decision buttons are simulated in this browser. The real cloud-to-Mac probe uses a private mock_ping command; it cannot approve content or start production.')));
  if (lastProof) root.append(make('p', 'bridge-proof', tr(
    `最近一次真实链路测试：${lastProof.cloudCreatedAt} 云端排队 → ${lastProof.cloudReceivedAt} 本机收件；云端回执与本地 JSON 的 SHA-256 一致。这是历史测试记录，不代表领取器当前在线。`,
    `Last real transport test: queued ${lastProof.cloudCreatedAt} → Mac receipt ${lastProof.cloudReceivedAt}; cloud receipt matched the local JSON SHA-256. This is a historical test, not current worker presence.`)));
}
