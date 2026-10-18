# 复盘：20261017-browser-cache-smoke-ci

证据见同目录 `INDEX.md`、`manifest.json` 与 `outcome.json`，以及 GitHub Actions 运行 39061346871。

## 结论先行

交付类型为代码 CI 测试。PR #741 精确 head `949bdfe2` 的完整 Python CI 成功：八个 root 分片与 `unittest` 汇总全部通过；原生合约按路径范围跳过。这是目录迁移的代码收据，不代表线上缓存或设备验收。

## 总时间

GitHub 运行从 19:11:06 至 19:30:49 UTC，墙钟 19 分 43 秒，包含 runner 排队。没有计算/等待拆分，不能视为纯计算时间或作性能比较。

## 各层模型、耗时与速度

L1–L4 均为 `not_run`；无模型、token、音频、远端生产调用或费用。

## 错误

本次 CI 无失败。此前本地在一次性浏览器环境中对比旧、新 CLI 的合成缓存 smoke，见 #742；本报告只记录当前 head 的完整 CI。

## 可以改进的地方

本次 CI 的墙钟包含排队，未提供性能优化证据。本批不改动 CI 配置。

## 实际覆盖范围

执行八个 Python root 分片与汇总门禁；没有运行真实 App 线上缓存、生产流程、Dev 发布或设备验收。

## 遗留状态

无 job hold 或部署构建；本地摘要来源文件留在被 Git 忽略的 `artifacts/`。代码 PR #741 仍待合并。

## 外部可见的变化

仅 GitHub Actions 产生测试记录。Dev 发布、TestFlight、设备与场地验收均为 `not_run`。
