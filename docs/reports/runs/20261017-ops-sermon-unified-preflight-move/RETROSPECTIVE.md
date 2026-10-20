# 复盘：20261017-ops-sermon-unified-preflight-move

证据：[INDEX.md](INDEX.md)、[脱敏摘要](sermon-unified-preflight-move/summary.json)、[结束状态](sermon-unified-preflight-move/outcome.json)。基线 `origin/dev` 为 `212027ee`，代码提交为 `859998f6`。

## 结论先行

交付类型：测试。本地合成验证通过：5 项定向测试成功；旧、新脚本路径及模块调用对无效配置返回相同 JSON 与退出码 2；同一份合成 fixture 的预检结果除 `codeIdentitySha256` 外相同，包身份相同且没有写入、凭据读取或任务派发。`outcome.json` 为 `passed`、退出码 0。

`canonical_layer2_controller.code_identity()` 哈希整个 `scripts/**/*.py`，因此旧脚本改为门面后，闭包 SHA 从 `19e105ffefe0cbf58babd4ea5a317bfd6045c1faf392e464a7877b38cd42bba6` 变为 `963e6027399bbdd9a9fe15398e5dd3d8b12b7dcd42f7b5650194fa96a9eb548d`。这是冻结运行身份变化；已有运行不能凭本次结果直接复用其旧代码身份。

## 总时间

报告没有 journal、起止时间或 timings.tsv，无法可靠计算墙钟时间、等待、返工或同类运行差异。

## 各层模型、耗时与速度

L1–L4 均为 `not_run`。没有模型调用、token、音频处理、推理速度或模型费用；这些指标不适用于本次代码测试。

## 错误

本次定向测试和合成 CLI 对照没有失败。旧与新代码闭包 SHA 不同是预期的身份结果，后续冻结运行应据新代码身份重新核验，不能作为旧批准的延续证据。

## 可以改进的地方

若实际运行需要使用新预检，操作者应先核对该运行的冻结代码身份和适用批准，再决定是否可继续；本报告不替代该运行的审查收据。没有本次测试支持的速度或成本改进项。

## 实际覆盖范围

覆盖旧模块门面对象身份、合成 fixture 的 Layer 2 预检与包身份、四种 CLI 入口，以及移动实现除直调路径深度外的字节一致性。L1–L4 生产阶段均为 `not_run`，没有复用或产生生产产物。

## 遗留状态

没有本次测试遗留的 job hold 或生产构建号。实际运行是否持有旧代码身份、Dev 文件状态和本地产物清理状态未由本报告核实。

## 外部可见的变化

本次没有发布、TestFlight、HTTP、设备或现场验收；均为 `not_run`。代码与报告 PR 的状态以各自 GitHub 页面为准。
