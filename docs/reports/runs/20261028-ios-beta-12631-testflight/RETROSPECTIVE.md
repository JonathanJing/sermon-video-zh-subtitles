# 复盘：20261028-ios-beta-12631-testflight

数据见同目录 `INDEX.md`、`manifest.json` 和脱敏的 `release-receipt.json`。本报告记录 iOS 内部 Beta 分发，不表示内容生产或设备验收。

## 结论先行

交付类型：iOS TestFlight 内部 Beta。`1.26.31 (74)` 从提交 `df5a438b4ce04e12886bf138e3ea4b51801c7d67` 归档并导出 IPA；上传、Apple 处理和 Rooted 内部组关联的命令均成功。2026-10-28 21:40:36 UTC 的 Apple 回读为 `VALID / IN_BETA_TESTING`，Rooted 组包含本构建。真机安装、听感和现场同步为 `not_run`。

## 总时间

归档成功记录生成于 21:33:57 UTC，最终 Apple 组关联读回于 21:40:36 UTC，两个收据时间相隔约 6 分 39 秒。归档开始时间、各阶段计算与等待拆分未记录，不能把这段间隔视为完整运行时长，也不能与前一轮比较。

## 各层模型、耗时与速度

| 阶段 | 本轮状态 | 后端及证据 |
|---|---|---|
| L1–L3 内容生产与质检 | `not_run` | 本轮仅打包和分发既有 Dev 内容 |
| L4 iOS Archive | 成功 | Xcode `TongxingBeta / BetaRelease`；本地 `release-record.json` 与归档日志哈希见收据 |
| L4 IPA 导出 | 成功 | `xcodebuild -exportArchive`；IPA SHA-256 见收据 |
| L4 TestFlight | 成功 | 上传、处理等待、Rooted 关联各自退出码为 0；Apple 回读见收据 |

模型推理、token、音频速度和费用不适用于本轮。构建阶段的计算时间未分项记录。

## 错误

本次归档、导出、上传、等待和内部分发的记录均为成功。此前普通 `Release` 模拟器构建因缺少受 SHA-256 约束的本地手册资源而停止，见独立报告 `20261028-ios-release-local-guide-required`；该失败不属于本次 `BetaRelease` 分发命令。

## 可以改进的地方

本次 Beta IPA 未内置 `weekly-guides.json`，手册展示依赖 Dev 远端内容。下一轮若需离线手册验收，应在归档前核对经批准的本地资源、固定哈希及实际 IPA 内容；本轮不以空资源推断远端手册不可用。负责人：下一轮 iOS 发布执行者。

## 实际覆盖范围

复用已提交的 iOS 修复源码；执行 Beta 归档、IPA 导出、TestFlight 上传、Apple 处理等待及 Rooted 内部组关联。未执行 L1–L3 生产、正式 App Store 提交、真机安装、音频听感或现场字幕同步。

## 遗留状态

`1.26.31 (74)` 已占用。私有 Archive、IPA、上传命令收据和 Apple 快照保留在本机忽略目录；无本轮已知未结束任务。本 Beta IPA 不含本地手册后备资源。

## 外部可见的变化

Apple 的 `1.26.31 (74)` 处于 `VALID / IN_BETA_TESTING`，Rooted 内部组关联已读回。Dev 内容站未由本轮修改。设备与场地验收仍为 `not_run`。
