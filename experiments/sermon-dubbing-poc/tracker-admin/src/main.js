import { renderSnapshot, showConnection, showEmpty } from './view.js';

const byId = (id) => document.getElementById(id);
let runs = [];
let selectedId = null;

function selectRun(pageId) {
  selectedId = pageId;
  const selected = runs.find((run) => run.pageId === pageId);
  if (!selected) return showEmpty('暂无制作记录', '状态发布器尚未写入本周页面。');
  try { renderSnapshot(selected); }
  catch { showEmpty('状态格式不兼容', '请检查状态发布器与页面版本。'); }
}

function renderRunList() {
  const select = byId('week-select');
  const previous = selectedId;
  select.replaceChildren(...runs.map((run) => {
    const option = document.createElement('option');
    option.value = run.pageId;
    option.textContent = `${run.serviceDate || '未登记日期'} · ${run.pageId}`;
    return option;
  }));
  const next = runs.some((run) => run.pageId === previous) ? previous : runs[0]?.pageId;
  if (next) { select.value = next; selectRun(next); }
  else showEmpty('暂无制作记录', '状态发布器尚未写入本周页面。');
}

async function start() {
  byId('week-select').addEventListener('change', (event) => selectRun(event.target.value));
  if (new URLSearchParams(location.search).get('local') === '1') {
    const response = await fetch('./local-preview.json', { cache: 'no-store' });
    if (!response.ok) throw new Error('local preview snapshot unavailable');
    runs = [await response.json()];
    showConnection('本地快照 · 非实时', 'warn');
    renderRunList();
    return;
  }
  if (new URLSearchParams(location.search).get('demo') === '1') {
    const { demoSnapshot } = await import('./demo.js');
    runs = [demoSnapshot];
    showConnection('演示数据', 'warn');
    renderRunList();
    return;
  }
  const response = await fetch('/tracker-config.json', { cache: 'no-store' });
  if (!response.ok) {
    showConnection('未配置', 'warn');
    showEmpty('Firebase 尚未配置', '创建 tracker-config.json 并构建状态页；此文件只能包含公开 Web App 配置。');
    return;
  }
  const config = await response.json();
  if (!config.projectId || !config.apiKey || !config.appId || !config.databaseId
      || Object.values(config).some((value) => typeof value === 'string' && value.startsWith('REPLACE_'))) {
    showConnection('配置无效', 'bad');
    showEmpty('Firebase 配置不完整', '请填写 Web App 的公开配置和独立 Firestore 数据库 ID。');
    return;
  }
  const [{ initializeApp }, { collection, getFirestore, limit, onSnapshot, orderBy, query }] =
    await Promise.all([import('firebase/app'), import('firebase/firestore')]);
  const app = initializeApp({ apiKey: config.apiKey, projectId: config.projectId, appId: config.appId });
  const db = getFirestore(app, config.databaseId);
  showConnection('实时连接中', 'active');
  const recent = query(collection(db, 'sermonTrackerRuns'), orderBy('updatedAt', 'desc'), limit(32));
  onSnapshot(recent, (result) => {
    runs = result.docs.map((doc) => doc.data().snapshot)
      .filter((item) => item && item.schemaVersion === 'sermon-public-tracker-snapshot-v1');
    showConnection('实时同步', 'ok');
    renderRunList();
  }, () => {
    showConnection('读取失败', 'bad');
    showEmpty('状态库无法读取', '请检查网络和 Firestore 只读规则。');
  });
}

start().catch(() => {
  showConnection('初始化失败', 'bad');
  showEmpty('状态页无法启动', '请检查构建文件与 Firebase Web App 配置。');
});
