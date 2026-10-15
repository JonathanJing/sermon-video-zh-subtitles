# Run digest 20261014-pr390-compat-catalog-fix

Generated 2026-10-14T17:09:10+00:00. Redacted copies only; source hashes are in manifest.json.

## 结论先行

- 定向兼容发布测试最终 **22/22 通过**；结束状态为 `pass_after_expected-contract-update`，退出码为 0。
- 本轮直接验证了四件事：当前版本和上一版本的兼容来源都会补齐运行时 `pageId` / `audioLocale`，兼容发布准备会写出补齐后的运行时 catalog，同时磁盘上的旧版 v1 release catalog 保持不变。
- 前置失败来自 2 条仍要求“运行时 catalog 与旧 release catalog 逐字节相等”的旧断言；按已审定的新运行时合同更新断言后，同一测试文件全部通过。
- **边界**：本轮只有离线合同／回归测试；生产部署、生产 API 回读和浏览器上传均为 `not_run`，不能据此声称线上或设备验收通过。

## pr390-compat-catalog-fix-tests

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/pr390-compat-catalog-fix-tests`

- outcome `outcome.json`: **pass_after_expected-contract-update** exit 0 (2026-10-14T17:07:00Z → 2026-10-14T17:09:01Z)
- summary `summary.json`: **pass**

Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| python-rollout-before-contract-update | fail | 0.57 |
| python-rollout-after-contract-update | pass | 0.58 |
| python-compile | pass | 0.10 |
| git-diff-check | pass | 0.20 |

Failed stages: `python-rollout-before-contract-update`
