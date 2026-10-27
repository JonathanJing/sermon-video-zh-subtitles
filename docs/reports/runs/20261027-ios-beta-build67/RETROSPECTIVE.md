# 复盘：20261027-ios-beta-build67

## 结论先行

交付类型为 Beta 测试分发。Build 67 归档、导出和上传成功，Apple 回读状态为 `VALID`，并列入 Rooted；真机安装和冷启动路由验证尚待执行。汇总及证据哈希见 [INDEX.md](INDEX.md) 和 [summary.json](20261027-ios-beta-build67/summary.json)。

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
| Build 67 真机安装及冷启动路由 | `not_run`／待反馈 | 最后一次设备读回仍是 Build 65 |
| 场地验收 | `not_run` | 未执行 |

模型调用与音频生产不属于本轮范围。

## 错误与等待

上传后的早期快照尚未列出 Build 67，后续查询已确认；不能把短暂未列出当作上传失败，也不能用上传成功替代设备验证。Build 67 的真机安装与冷启动结果仍待用户反馈。

## 可以改进的地方

继续分开记录归档、上传、Apple 处理和设备最终页面；设备验证应确认安装的是 Build 67，并分别检查冷启动打开应用与落到正确页面。

## 实际覆盖范围

本轮覆盖冻结源码的归档、导出、上传和 Apple 处理状态回读，不包括真机目标页验收。Simulator 测试及旧代码对照另见 [对应草稿报告 PR #1414](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1414)。

## 遗留状态

Build 67 的真机验证待完成；最后一次设备读回为 Build 65。原始日志和二进制留在本机忽略目录。

## 外部可见的变化

Build 67 已出现在 Apple 内部测试组 Rooted 且状态为 `VALID`。未证明正式 App 发布、Build 67 真机播放或场地验收。
