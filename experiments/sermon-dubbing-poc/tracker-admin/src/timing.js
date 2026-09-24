/** Explain measured coverage without treating completed checkpoints as measured work. */
import { tr } from './i18n.js';

export function timingCoverageNote(coverage = {}, steps = []) {
  const missing = Number.isInteger(coverage?.completedWithoutMeasuredExecutionCount)
    ? coverage.completedWithoutMeasuredExecutionCount
    : (steps || []).filter((step) => step.status === 'complete'
      && step.timing?.measuredExecutionSeconds == null).length;
  const measured = coverage?.measuredStepCount || 0;
  return tr(
    `完成数只表示检查点 · ${measured} 个步骤有实测耗时` +
      (missing ? ` · ${missing} 个已记录步骤缺实测计时` : ''),
    `Recorded count only reflects checkpoints · ${measured} steps have measured execution time` +
      (missing ? ` · ${missing} recorded steps lack measured execution time` : ''));
}

export function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return tr('未知', 'Unknown');
  if (seconds < 1) return tr(`${Math.round(seconds * 1000) / 1000}秒`, `${Math.round(seconds * 1000) / 1000}s`);
  if (seconds < 60) return tr(`${Math.round(seconds * 10) / 10}秒`, `${Math.round(seconds * 10) / 10}s`);
  const whole = Math.floor(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor(whole % 3600 / 60);
  const remaining = whole % 60;
  if (hours) return tr(`${hours}小时${minutes}分${remaining}秒`, `${hours}h ${minutes}m ${remaining}s`);
  if (minutes) return tr(`${minutes}分${remaining}秒`, `${minutes}m ${remaining}s`);
  return tr(`${remaining}秒`, `${remaining}s`);
}

/** Distinguish measured execution from open records and ledger status duration. */
export function stepTimingSummary(step) {
  const timing = step?.timing || {};
  const parts = [];
  if (timing.measuredExecutionSeconds != null) {
    const failures = timing.failedExecutionAttempts || 0;
    const attempts = timing.executionAttempts || 0;
    parts.push(tr(`执行实测累计 ${formatDuration(timing.measuredExecutionSeconds)} · ${timing.executionAttempts || 0} 次${failures ? `，失败 ${failures} 次` : ''}`,
      `Measured execution total ${formatDuration(timing.measuredExecutionSeconds)} · ${attempts} ${attempts === 1 ? 'attempt' : 'attempts'}${failures ? `, ${failures} failed` : ''}`));
  } else if (step?.status === 'complete') {
    parts.push(tr('执行耗时未记录', 'Execution time not recorded'));
  }
  if (timing.openExecution) {
    parts.push(timing.openExecutionElapsedSeconds == null
      ? tr('存在未结束执行记录 · 起点未知', 'Open execution record · Start unknown')
      : tr(`未结束执行计时 ${formatDuration(timing.openExecutionElapsedSeconds)}（截至快照）`,
        `Open execution timer ${formatDuration(timing.openExecutionElapsedSeconds)} (at snapshot)`));
  }
  if (step?.status === 'running' || step?.status === 'waiting_review') {
    const title = step.status === 'running' ? tr('进行中状态持续', 'In-progress status duration')
      : tr('待审状态持续', 'Awaiting-review status duration');
    parts.push(timing.statusElapsedSeconds == null
      ? tr(`${title}：起点未记录`, `${title}: start not recorded`)
      : tr(`${title} ${formatDuration(timing.statusElapsedSeconds)}（截至快照，非执行耗时）`,
        `${title} ${formatDuration(timing.statusElapsedSeconds)} (at snapshot, not execution time)`));
  }
  if (timing.operatorReviewWaitSeconds != null) {
    parts.push(tr(`已结束审核等待累计 ${formatDuration(timing.operatorReviewWaitSeconds)}`,
      `Closed review waits total ${formatDuration(timing.operatorReviewWaitSeconds)}`));
  }
  return parts;
}
