'use strict';
const fs = require('node:fs');
const crypto = require('node:crypto');

module.exports = class SavedReportProvider {
  constructor(options) {
    this.config = options.config;
  }
  id() { return 'sermon-local-saved-report-v1'; }
  async callApi() {
    const bytes = fs.readFileSync(this.config.reportPath);
    const hash = crypto.createHash('sha256').update(bytes).digest('hex');
    if (hash !== this.config.reportSha256) throw new Error('Saved comparison report changed');
    const report = JSON.parse(bytes.toString('utf8'));
    return { output: report, cost: 0, tokenUsage: { total: 0, prompt: 0, completion: 0 },
      metadata: { localProviderExecuted: true, reportSha256: hash, networkUsed: false } };
  }
};
