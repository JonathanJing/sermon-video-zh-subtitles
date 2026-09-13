'use strict';
module.exports = (output) => {
  const report = typeof output === 'string' ? JSON.parse(output) : output;
  const valid = report.schemaVersion === 'saturday-quality-comparison-v1'
    && report.humanAcceptance === 'not_evaluated'
    && Array.isArray(report.regressions)
    && report.baseline && report.candidate;
  const pass = valid && report.passed === true;
  return { pass, score: pass ? 1 : 0,
    reason: pass ? 'Offline deterministic checks passed; no human acceptance claimed'
      : 'Offline regression or known baseline issue detected; inspect comparison.json' };
};
