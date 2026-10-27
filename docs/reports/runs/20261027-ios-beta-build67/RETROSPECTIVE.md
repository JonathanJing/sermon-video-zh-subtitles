# 复盘：20261027-ios-beta-build67

## 结论先行

交付类型为 Beta 测试分发。Build 67 已上传，Apple 状态为 `VALID` 并列入 Rooted；Agent 只读确认实体 iPhone 安装了 Build 67。用户报告关闭 App 后从聊天点击 Dev 测试链接，正确进入“耶稣审判并保守”页面。版本回读与用户的行为反馈是两条不同证据，详见 [INDEX.md](INDEX.md) 和 [summary.json](20261027-ios-beta-build67/summary.json)。

## 总时间

本轮没有完整开始、结束及等待分类记录，无法准确计算端到端墙钟时间。上传后 16:05:29 UTC 的早期快照尚未列出该构建，16:08:07 UTC 后续回读已列出。

## 各阶段

| 阶段 | 状态 | 证据 |
|---|---|---|
| L1–L3 内容生产 | `not_run` | 本轮为 iOS Beta 分发 |
| 源码与 Archive | 成功 | commit、Archive manifest 哈希见摘要；独立基线不含后续研读界面工作 |
| IPA 导出 | 成功 | IPA SHA-256 见摘要 |
| TestFlight 上传 | exit 0 | 上传回执与 IPA 身份见摘要 |
| Apple 状态 | `VALID`、`IN_BETA_TESTING`，Rooted 包含 Build 67 | 2026-10-27 16:08:07 UTC 快照 |
| 真机安装 | 安装 `1.26.25 (67)` | Agent 只读设备查询，2026-10-27 约 16:31 UTC |
| 真机链接目标页 | 用户报告成功 | 关闭 App 后从聊天点击 Dev 测试链接，进入“耶稣审判并保守”；未独立采集设备事件 |
| 场地验收 | `not_run` | 未执行 |

模型调用与音频生产不属于本轮范围。

## 错误与等待

上传后的早期快照尚未列出 Build 67，后续查询已确认；不能把短暂未列出当作上传失败。此前 Build 65 的设备反馈与本轮 Build 67 的用户反馈分别记录。

## 可以改进的地方

继续分开记录归档、上传、Apple 处理、设备安装版本和用户看到的最终页面；其他启动状态、链接和设备按实际需要分别验证。

## 实际覆盖范围

本轮覆盖冻结源码的归档、导出、上传和 Apple 处理状态回读，以及一台 iPhone 的安装版本回读和一次用户报告的链接场景。Simulator 测试及旧代码对照另见 [对应草稿报告 PR #1414](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1414)。

## 遗留状态

其他设备、链接、语言和启动状态尚未证明通过；原始日志和二进制留在本机忽略目录。

## 外部可见的变化

Build 67 已出现在 Apple 内部测试组 Rooted 且状态为 `VALID`。用户报告的链接落页结果不证明正式 App 发布、Build 67 音频播放或场地验收。
