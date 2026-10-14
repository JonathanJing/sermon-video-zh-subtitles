# Run digest 20261014-pr390-review-fix

Generated 2026-10-14T17:02:18+00:00. Redacted copies only; source hashes are in manifest.json.

## 结论先行

- 高置信结论：在正确测试入口下，Node 定向测试 27/27、Python 定向测试 22/22 通过，最终状态为 `pass_after_entrypoint_retry`、退出码 0。
- 证据边界：首次仓库根 Python 入口因测试本地模块导入路径失败；报告只绑定提交 `ace03ce8ba8c2ebf015795162393f4f631e39b46`，生产部署、浏览器、真机和场地均未运行。
- 处置建议：复盘已按八项补齐；同步最新 `dev` 并确认检查保持绿色后再转 Ready／合并报告 PR。

## pr390-review-fix-tests

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/pr390-review-fix-tests`

- outcome `outcome.json`: **pass_after_entrypoint_retry** exit 0 (2026-10-14T17:01:00Z → 2026-10-14T17:02:07Z)
- summary `summary.json`: **pass**

Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| node-targeted-tests | pass | 2.79 |
| python-root-entrypoint | fail | 0.11 |
| python-test-directory-retry | pass | 0.51 |
| git-diff-check | pass | 0.20 |

Failed stages: `python-root-entrypoint`
