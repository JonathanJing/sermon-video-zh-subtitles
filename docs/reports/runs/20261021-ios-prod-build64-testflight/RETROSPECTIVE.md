# 复盘：20261021-ios-prod-build64-testflight

## 结论先行

正式 App 1.26.21（64）TestFlight 上传命令退出 0；Apple 处理结果读回 `VALID / IN_BETA_TESTING`，Rooted 内测组关系及测试说明读回。脱敏 outcome.json 记录构建身份。本报告只确认 Apple 分发状态，不代表真机接收或 App Store 审核。

## 总时间

上传从 2026-10-22 05:06:17 至 05:07:26 UTC，约 69 秒。Apple 处理及内测组更新单独等待；无付费模型调用。

## 各层模型、耗时与速度

L1–L3 未执行。L4 使用 Fastlane/App Store Connect 上传并读回，无模型、token 或推理费用。

## 错误

本候选上传无报错。构建 62、63 因后续隐私披露修正而被构建 64 取代，未重复上传相同 IPA。

## 可以改进的地方

将 App Store Connect 的隐私披露一致性列入归档前检查，可减少版本递增和 Apple 处理等待；由 iOS 发行维护者在 PR #1301 跟进。

## 实际覆盖范围

仅覆盖 L4 的 TestFlight 上传、Apple 构建处理、Rooted 组归属与测试说明。真机订阅、单设备 APNs、退出订阅、音频听感和正式审核尚未执行。

## 遗留状态

Apple 构建 62、63 保留为历史候选。构建 64 待真机验收；本地 IPA 和原始日志位于忽略目录。

## 外部可见的变化

Rooted 内测员可获得正式 App 1.26.21（64）。App Store 版本仍为准备提交状态，没有进入审核或上架。
