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
