import test from 'node:test';
import assert from 'node:assert/strict';
import { localizeWeek, translateContent } from './content-locales.mjs';

test('presentation localization preserves source transcript, media and approval identity', () => {
  const original = Object.freeze({
    id: 'source-week',
    series: '当生活令人费解',
    sourceLabel: '正式播放版',
    releaseLabel: '正式播放版',
    audioNotice: '整篇中文已审核。字幕随中文音频更新。',
    transcript: Object.freeze([{ en: 'Original English', zh: '中文原文' }]),
    tracks: Object.freeze([{ sha256: 'immutable-hash', cues: [{ text: '中文原文' }] }]),
    humanApproval: Object.freeze({ status: 'pending', note: '待审核' }),
    productionStages: Object.freeze([Object.freeze({ label: '配音检查', detail: '用户已确认审核完成', status: 'pass' })]),
    outline: Object.freeze([Object.freeze({ title: '六、向受苦并同在的君王耶稣祷告', points: Object.freeze(['回应既包括个人祷告，也包括接受愿意一同祷告者的陪伴。']), sourceSliceIndexes: Object.freeze([11, 12]) })]),
  });
  const localized = localizeWeek(original, 'en-US');
  assert.equal(localized.series, 'When Life Doesn’t Make Sense');
  assert.equal(localized.sourceLabel, 'Published edition');
  assert.equal(localized.releaseLabel, original.releaseLabel);
  for (const key of ['transcript', 'tracks', 'humanApproval']) assert.equal(localized[key], original[key]);
  assert.equal(localized.productionStages[0].status, 'pass');
  assert.equal(original.productionStages[0].label, '配音检查');
  assert.equal(localized.productionStages[0].label, 'Dubbing checks');
  assert.equal(localized.outline[0].sourceSliceIndexes, original.outline[0].sourceSliceIndexes);
  assert.deepEqual(localized.contentLocalization.fallbackPaths, []);
  assert.match(localized.contentLocalization.note, /not quotations/);
  assert.match(localized.contentLocalization.note, /not translated back from Chinese/);
});

test('unknown content remains visible with explicit field-level fallback metadata', () => {
  const source = { title: '尚未翻译的新一期', summary: 'Already English', outline: [{ title: '未知标题', points: ['新内容'] }], questions: ['新问题'], productionStages: [{ label: '新标签', detail: '新说明', status: '待确认' }] };
  const localized = localizeWeek(source, 'en');
  assert.equal(localized.title, source.title);
  assert.equal(localized.summary, source.summary);
  assert.deepEqual(localized.contentLocalization.fallbackPaths, ['title', 'questions.0', 'outline.0.title', 'outline.0.points.0', 'productionStages.0.label', 'productionStages.0.detail']);
  assert.equal(localized.productionStages[0].status, '待确认');
});

test('Chinese variants preserve source and unsupported languages do not silently become English', () => {
  const source = { series: '当生活令人费解' };
  for (const locale of ['zh', 'zh-CN', 'zh-TW']) assert.equal(localizeWeek(source, locale), source);
  const localized = localizeWeek(source, 'es-MX');
  assert.equal(localized.series, source.series);
  assert.equal(localized.contentLocalization.kind, 'source-fallback');
  assert.equal(localized.contentLocalization.requestedLocale, 'es-MX');
  assert.deepEqual(localized.contentLocalization.fallbackPaths, ['series']);
  assert.equal(translateContent('配音检查', 'en-US'), 'Dubbing checks');
  assert.equal(translateContent('配音检查', 'zh'), '配音检查');
  assert.equal(translateContent('未知文案', 'en'), '未知文案');
});

test('Korean uses catalog sidecar fields without changing media or approval data', () => {
  const source = {
    id: 'ko-poc', title: '尚未翻译的新一期', series: '当生活令人费解', summary: '中文摘要',
    tracks: [{ sha256: 'fixed' }], humanApproval: { status: 'pending' },
    outline: [{ title: '第一点', points: ['第一段'] }], questions: ['问题一'],
    contentSource: { locale: 'en', status: 'provided_poc', sha256: 'abc123', fields: {
      title: 'New sermon', summary: 'Canonical English summary', outline: [{ title: 'First', points: ['First paragraph'] }], questions: ['First question'],
    } },
    contentLocalizations: { ko: { status: 'draft', sourceLocale: 'en', sourceContentSha256: 'abc123', fields: {
      title: '새 설교', summary: '한국어 요약', outline: [{ title: '첫째', points: ['첫 문단'] }], questions: ['첫 질문'],
    } } },
  };
  const localized = localizeWeek(source, 'ko-KR');
  assert.equal(localized.title, '새 설교');
  assert.equal(localized.series, '삶이 이해되지 않을 때');
  assert.equal(localized.summary, '한국어 요약');
  assert.equal(localized.outline[0].points[0], '첫 문단');
  assert.equal(localized.questions[0], '첫 질문');
  assert.equal(localized.tracks, source.tracks);
  assert.equal(localized.humanApproval, source.humanApproval);
  assert.equal(localized.contentLocalization.kind, 'target-language-sidecar');
  assert.equal(localized.contentLocalization.status, 'draft');
  assert.equal(localized.contentLocalization.sourceContentSha256, 'abc123');
  assert.deepEqual(localized.contentLocalization.fallbackPaths, []);
  assert.match(localized.contentLocalization.note, /POC/);
  const english = localizeWeek(source, 'en');
  assert.equal(english.title, 'New sermon');
  assert.equal(english.summary, 'Canonical English summary');
  assert.equal(english.contentLocalization.kind, 'canonical-source');
});
