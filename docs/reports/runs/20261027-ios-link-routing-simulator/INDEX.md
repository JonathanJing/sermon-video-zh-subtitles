# Run digest 20261027-ios-link-routing-simulator

Generated 2026-10-27T15:54:32+00:00. Redacted copies only; source hashes are in manifest.json.

## 20261027-ios-link-routing-simulator

Source: `~/.codex/worktrees/ios-universal-link-routing/sermon-video-zh-subtitles/artifacts/run-report-inputs/20261027-ios-link-routing-simulator`

- summary `summary.json`: **simulator_passed_negative_control_reproduced_device_fix_not_validated**

## 结果与边界

- `TongxingBeta` / `BetaDebug` Simulator 构建成功。较早修复版本定向测试 10 项通过，加入刷新和用户选择保护后的版本 12 项通过。
- 负向对照使用 `origin/dev` 原 AppModel 和本轮测试文件：冷启动测试执行 1 项、失败 1 项，实际为默认页而非目标页，按预期复现原问题。
- 测试时源码尚未提交。后期修复的 AppModel 和测试文件哈希、各运行身份与日志哈希见 [summary.json](20261027-ios-link-routing-simulator/summary.json)；不可将结果归属为后续某个提交的测试。
- 用户报告 Build 65 冷启动落到默认页，温启动成功。Simulator 模型测试不能代替真机 Universal Link 投递；修复尚待新 Beta 真机验证。
