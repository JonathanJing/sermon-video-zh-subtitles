# 复盘：20261017-prepare-v3-bucket-move

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json`、`summary.json` 和脱敏 `test.log`。

## 结论先行

测试通过：3 项合成定向用例；迁移前脚本、旧 facade、新脚本对同一合成 Hosting snapshot 生成的 23 个候选文件逐字节一致，`migration-report.json` 除 `createdAt` 外相同，stdout 一致；原 snapshot 字节不变。没有真实 Hosting 快照、上传、部署、网络或模型调用。

## 总时间

本地墙钟 1.367 秒，其中 unittest 0.708 秒；无远端排队、人工等待或返工。不同输入环境下不作速度比较。

## 各层模型、耗时与速度

L1–L4 均 `not_run`。仅本地合成视频字节、catalog 与 Firebase 配置测试；模型调用 0，token、音频速度和费用不适用。

## 错误

本轮无失败。测试中坏 bucket 与已有输出目录按预期拒绝，源 snapshot 未改变。

## 可以改进的地方

质量：迁移路径敏感 CLI 时同时比较旧代码与新入口的生成文件和规范化报告，避免 `createdAt` 掩盖实质字节差异。依据为 `summary.json`；预期提升变更可审性；负责人为迁移 Agent，跟踪后续代码 PR。

## 实际覆盖范围

覆盖旧代码基线、旧直达脚本、新直达脚本的合成候选输出比较，以及旧/新 `-m` 与脚本四入口等价测试。只测试候选构建，未执行生产 L1–L4 或发布。

## 遗留状态

无 Dev 文件、job hold 或构建号；合成临时输入已清理，忽略目录中的本地报告保留审阅。

## 外部可见的变化

无远端报告 PR、Dev 发布、TestFlight、设备或场地验收；均 `not_run`。代码尚未 push 或开 PR。
