# 复盘：20261017-pr846-preflight-closure-fix

证据：[INDEX.md](INDEX.md)、[脱敏摘要](sermon-unified-preflight-closure-fix/summary.json)、[结束状态](sermon-unified-preflight-closure-fix/outcome.json)。

## 结论先行

交付类型：测试。6 项定向测试通过；新增回归在不改真实文件的情况下模拟 `tools/ops/sermon_unified_preflight.py` 字节变化，确认 Layer 2 `code_identity()` 随之变化。`outcome.json` 为 `passed`、退出码 0。此结果只覆盖本地合成行为。

## 总时间

报告没有 journal、起止时间或 timings.tsv，无法可靠计算墙钟时间、等待、返工或同类运行差异。

## 各层模型、耗时与速度

L1–L4 均为 `not_run`；没有模型、token、音频、推理速度或模型费用。

## 错误

发现迁出的只读预检实现原先不在 Layer 2 的代码身份文件列表中，后续实现改动可能沿用同一 `codeIdentitySha256`。在代码预检阶段加入该单一文件并用合成字节变化测试回归；未占用生产资源。

## 可以改进的地方

今后迁移被闭包约束的脚本时，应检查目标路径是否仍被身份哈希覆盖。本次回归使这一个迁出文件的变化可由代码身份反映；不推断其他工具均已覆盖。

## 实际覆盖范围

覆盖原有预检测试与迁出文件字节变化的身份回归。L1–L4 生产阶段均为 `not_run`，无复用或生产产物。

## 遗留状态

新代码身份为 `1ec5fde48bc0bd3322919a63937704d1cc733f07845b3bf823016c6f4c6c7d62`。现有冻结运行仍须按新身份重新核验；本地测试没有产生 job hold 或构建号。真实运行状态未核实。

## 外部可见的变化

没有 Dev 发布、TestFlight、HTTP、设备或现场验收；均为 `not_run`。CI 与代码 PR 状态需另看 GitHub 收据。
