# 复盘：20261018-pr895-python-success

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`；原始 CI 运行见 [39080066441](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39080066441)。

## 结论先行

测试类型为 PR CI。`Python tests` 在 #895 提交 `89aea32e1214bf2cd5f7d69955dae5f370a723a6` 上结束为 `success`。`changes`、8 个 root 测试分组及总 `unittest` 门禁成功；`Native and shared client contracts` 按变更检测跳过。结果只绑定该提交与当时的 PR 合并上下文；后续 dev 基线更新需要另行核对。

## 总时间

工作流创建于 2026-10-17 23:42:45 UTC，更新结束于 2026-10-18 00:00:52 UTC，墙钟 18 分 07 秒，包含并行队列、依赖安装和测试。无人工等待或返工；缺少逐步计算归因，不与不同 CI 运行作速度比较。

## 各层模型、耗时与速度

L1–L4 均 `not_run`。此工作流无生产模型调用，token、音频速度和费用不适用。

## 错误

无失败。原生与共享客户端合同 job 按变更范围跳过。

## 可以改进的地方

流程：报告保留准确 head 和 job 级终态，便于新基线或新提交出现时判定哪些结果必须重跑。证据为 `summary.json`；负责人为迁移 Agent，跟踪 #895。

## 实际覆盖范围

8 个 root 测试分组及汇总门禁成功；原生与共享客户端合同未运行。生产 L1–L4、真实 Hosting 输入和部署均未执行。

## 遗留状态

无 Dev 文件、job hold 或构建号；本地忽略目录保留证据供审阅。

## 外部可见的变化

PR CI 运行公开可见；无 Dev 发布、TestFlight、设备或场地验收，均 `not_run`。
