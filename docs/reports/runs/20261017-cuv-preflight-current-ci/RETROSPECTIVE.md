# 复盘：20261017-cuv-preflight-current-ci

证据见同目录 `INDEX.md`、`manifest.json` 与 `outcome.json`，以及 GitHub Actions 运行 39061226300。

## 结论先行

交付类型为代码 CI 测试。PR #629 在精确 head `f1eaddb4`（纳入 #625 后的冲突合并）完成完整 Python CI：八个 root 分片与 `unittest` 汇总均成功。原生合约按路径范围跳过。这是代码测试，不是实际讲道校对或发布验收。

## 总时间

GitHub 运行从 19:09:28 至 19:27:10 UTC，墙钟 17 分 42 秒，包含 runner 排队；没有 journal 或计算/等待拆分，不能视为纯计算时间或作速度比较。

## 各层模型、耗时与速度

L1–L4 均为 `not_run`；无模型、token、音频、远端生产调用或费用。

## 错误

本次 CI 无失败。此前 #625 合入后 `path_aliases.py` 有冲突；分支合并保留了 CUV 和 review diagnostics 两个路径别名，定向测试结果在 #740。本次 CI 验证合并后的精确 head。

## 可以改进的地方

共享 `path_aliases.py` 的迁移 PR 按序合并，合并后的树重新取得 CI 收据；本次冲突证据说明旧 head 的 CI 不能替代合并后的验证。

## 实际覆盖范围

八个 Python root 分片与汇总门禁运行成功；没有 L1–L4 真实工作流、Dev 发布、HTTP 读回、设备或场地验收。

## 遗留状态

无 job hold、构建或待上传生产产物；本地摘要来源留在被 Git 忽略的 `artifacts/`。代码 PR #629 尚待合并。

## 外部可见的变化

本次仅在 GitHub Actions 产生测试记录。Dev 发布、TestFlight、设备和场地验收均为 `not_run`。
