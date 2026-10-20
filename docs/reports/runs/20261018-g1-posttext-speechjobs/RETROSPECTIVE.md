# 复盘：G1 后三语 speech job v3 准备

证据见同目录 `INDEX.md`、`manifest.json`、脱敏的 `outcome.json` 与 `summary.json`。原始源文、译文和声音文件未公开。

## 结论先行

交付类型为确定性 Layer 3 准备。es、ko、zh-Hans 各用最终 W 绑定的新机器文字豁免及原冻结来源、锚点、候选、策略和声音授权，成功生成 speech job v3；每语 16 单元，`synthesisEligible=true`、`releaseEligible=false`。这不是音频合成、人工听审或发布资格。

## 总时间

三个准备命令各在一秒内完成；未记录独立 journal，无法精确拆分墙钟。模型计算和等待均未发生。

## 各层模型、耗时与速度

无模型调用，token、音频秒数与费用均为 0。L1、L2 内容仍来自原冻结输入，L3 只建立新身份绑定，L3 渲染/筛查与 L4 均为 `not_run`。

## 错误

三语准备命令均退出码 0，所引用的旧来源/策略/声音授权原始文件 SHA 与旧 job 记录匹配；新 job 的文字放行依据 SHA 与新机器文字豁免文件匹配。没有验证模型实际合成或 Spark 资源可用。

## 可以改进的地方

在 Spark 会话释放后，每语渲染前重新检查最终代码/模型/凭据与 job 身份，优先复用被 producer 明确验证的单元缓存；不改写旧 job 或旧音频收据。负责人为本任务主 Agent。

## 实际覆盖范围

覆盖三语正式 v3 speech job 的确定性准备和输入 SHA 绑定。音频渲染、压缩、ASR 筛查、音频 QC、人工听审、发布和设备验收均未执行。

## 遗留状态

三个新 job 在被忽略的本地 artifact 目录中；另一任务仍持有 Spark 独占会话，本轮未进入 GPU 阶段。旧 W 绑定的 speech job 和音频豁免保持原样。

## 外部可见的变化

没有 Dev 发布、TestFlight、实体设备或场地验收。仅此脱敏 docs-only 报告 PR 对外可见。
