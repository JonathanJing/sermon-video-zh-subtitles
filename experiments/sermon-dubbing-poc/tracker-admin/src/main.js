import { renderSnapshot, showConnection, showEmpty } from './view.js';
import { setUiLanguage, translateStatic, tr } from './i18n.js';

const byId = (id) => document.getElementById(id);
let runs = [];
let selectedId = null;
let connectionState = ['正在连接', 'Connecting', 'neutral'];
let emptyState = null;
let refreshMode = 'cloud';

function connection(chinese, english, status = 'neutral') {
  connectionState = [chinese, english, status];
  showConnection(tr(chinese, english), status);
}

function empty(chineseTitle, englishTitle, chineseDetail, englishDetail) {
  emptyState = [chineseTitle, englishTitle, chineseDetail, englishDetail];
  showEmpty(tr(chineseTitle, englishTitle), tr(chineseDetail, englishDetail));
}

function refreshNote() {
  const notes = {
    local: ['本地静态快照：浏览器刷新只重读文件；需先重新生成 JSON',
      'Static local snapshot: browser reload only rereads the file; regenerate the JSON first'],
    demo: ['合成演示数据；不检查本地或云端产物',
      'Synthetic demo data; no local or cloud artifacts are checked'],
    cloud: ['Firestore 实时订阅；新状态依赖本地发布器写入',
      'Live Firestore subscription; new status requires a local publisher write'],
  };
  byId('refresh-note').textContent = tr(...notes[refreshMode]);
}

function selectRun(pageId) {
  selectedId = pageId;
  const selected = runs.find((run) => run.pageId === pageId);
  if (!selected) return empty('暂无制作记录', 'No production record',
    '状态发布器尚未写入本周页面。', 'The publisher has not written this page yet.');
  try { renderSnapshot(selected); emptyState = null; }
  catch { empty('状态格式不兼容', 'Incompatible status format',
    '请检查状态发布器与页面版本。', 'Check the publisher and page versions.'); }
}

function renderRunList() {
  const select = byId('week-select');
  const previous = selectedId;
  select.replaceChildren(...runs.map((run) => {
    const option = document.createElement('option');
    option.value = run.pageId;
    option.textContent = `${run.serviceDate || tr('未登记日期', 'Date not recorded')} · ${run.pageId}`;
    return option;
  }));
  const next = runs.some((run) => run.pageId === previous) ? previous : runs[0]?.pageId;
  if (next) { select.value = next; selectRun(next); }
  else empty('暂无制作记录', 'No production record',
    '状态发布器尚未写入本周页面。', 'The publisher has not written this page yet.');
}

async function start() {
  translateStatic();
  connection(...connectionState);
  refreshNote();
  for (const code of ['zh', 'en']) {
    byId(`language-${code}`).addEventListener('click', () => {
      setUiLanguage(code);
      connection(...connectionState);
      refreshNote();
      if (runs.length) renderRunList();
      else if (emptyState) showEmpty(tr(emptyState[0], emptyState[1]), tr(emptyState[2], emptyState[3]));
    });
  }
  byId('week-select').addEventListener('change', (event) => selectRun(event.target.value));
  if (new URLSearchParams(location.search).get('local') === '1') {
    refreshMode = 'local';
    refreshNote();
    const response = await fetch('./local-preview.json', { cache: 'no-store' });
    if (!response.ok) throw new Error('local preview snapshot unavailable');
    runs = [await response.json()];
    connection('本地快照 · 非实时', 'Local snapshot · Not live', 'warn');
    renderRunList();
    return;
  }
  if (new URLSearchParams(location.search).get('demo') === '1') {
    refreshMode = 'demo';
    refreshNote();
    const { demoSnapshot } = await import('./demo.js');
    runs = [demoSnapshot];
    connection('演示数据', 'Demo data', 'warn');
    renderRunList();
    return;
  }
  const response = await fetch('/tracker-config.json', { cache: 'no-store' });
  if (!response.ok) {
    connection('未配置', 'Not configured', 'warn');
    empty('Firebase 尚未配置', 'Firebase not configured',
      '创建 tracker-config.json 并构建状态页；此文件只能包含公开 Web App 配置。',
      'Create tracker-config.json and build the page. This file must contain public Web App settings only.');
    return;
  }
  const config = await response.json();
  if (!config.projectId || !config.apiKey || !config.appId || !config.databaseId
      || Object.values(config).some((value) => typeof value === 'string' && value.startsWith('REPLACE_'))) {
    connection('配置无效', 'Invalid configuration', 'bad');
    empty('Firebase 配置不完整', 'Incomplete Firebase configuration',
      '请填写 Web App 的公开配置和独立 Firestore 数据库 ID。',
      'Provide public Web App settings and the dedicated Firestore database ID.');
    return;
  }
  const [{ initializeApp }, { collection, getFirestore, limit, onSnapshot, orderBy, query }] =
    await Promise.all([import('firebase/app'), import('firebase/firestore')]);
  const app = initializeApp({ apiKey: config.apiKey, projectId: config.projectId, appId: config.appId });
  const db = getFirestore(app, config.databaseId);
  connection('实时连接中', 'Connecting live', 'active');
  const recent = query(collection(db, 'sermonTrackerRuns'), orderBy('updatedAt', 'desc'), limit(32));
  onSnapshot(recent, (result) => {
    runs = result.docs.map((doc) => doc.data().snapshot)
      .filter((item) => item && item.schemaVersion === 'sermon-public-tracker-snapshot-v1');
    connection('实时同步', 'Live sync', 'ok');
    renderRunList();
  }, () => {
    connection('读取失败', 'Read failed', 'bad');
    empty('状态库无法读取', 'Cannot read status database',
      '请检查网络和 Firestore 只读规则。', 'Check the network and Firestore read-only rules.');
  });
}

start().catch(() => {
  connection('初始化失败', 'Initialization failed', 'bad');
  empty('状态页无法启动', 'Status page could not start',
    '请检查构建文件与 Firebase Web App 配置。', 'Check the build files and Firebase Web App settings.');
});
