/** Explain measured coverage without treating completed checkpoints as measured work. */
export function timingCoverageNote(coverage = {}, steps = []) {
  const missing = Number.isInteger(coverage?.completedWithoutMeasuredExecutionCount)
    ? coverage.completedWithoutMeasuredExecutionCount
    : (steps || []).filter((step) => step.status === 'complete'
      && step.timing?.measuredExecutionSeconds == null).length;
  const measured = coverage?.measuredStepCount || 0;
  return `完成数只表示检查点 · ${measured} 个步骤有实测耗时` +
    (missing ? ` · ${missing} 个已记录步骤缺实测计时` : '');
}

export function measuredDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '未测得';
  if (seconds < 1) return `${Math.max(0.001, Math.round(seconds * 1000) / 1000)}秒`;
  if (seconds < 60) return `${Math.round(seconds * 10) / 10}秒`;
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}分${whole % 60}秒`;
}
