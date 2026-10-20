# 复盘：G1 后 Spark 音频准入预检

证据见同目录 `INDEX.md`、`manifest.json`、脱敏的 `preflight.json`、`outcome.json` 与 `summary.json`。

## 结论先行

交付类型为只读开工预检，状态 `waiting`。最终 `dev@974862e6` 的代码已部署到独立 Spark 目录；不带 GPU 阶段的远端代码检查对 W 的 50 个物理文件通过，模型路径、镜像与 Dev 凭据路由只读核对通过。带 `--spark-stages` 的正式预检退出码 1，因为本轮尚未开始自己的独占会话。另一 Layer 1 任务仍持有 `exclusive_ready` 会话，本轮没有占用或结束它。

## 总时间

只读检查各在数秒内结束；没有独立 journal，无法精确拆分墙钟。GPU、模型计算及付费 ASR 耗时均为零。

## 各层模型、耗时与速度

L1–L4 模型阶段均为 `not_run`。没有 TTS、ASR 或 OpenAI 请求；token、音频秒数、速度和费用不适用。Spark 模型文件和容器镜像仅检查存在，不证明实际推理质量。

## 错误

GPU 阶段准入失败：本轮没有已开始的 `SPARK_EXCLUSIVE_SESSION_ID/OWNER`。只读会话检查显示另一任务持有空闲独占会话，当前无运行中 job 或队列；不能借用或擅自结束。代码/预算/输出目录检查均通过。

## 可以改进的地方

待原会话释放，或得到用户针对该会话的明确处理决定后，先开始本轮独占会话，再带本轮 ID/owner 重跑 `--spark-stages`，随后逐语渲染。负责人为本任务主 Agent；没有确定基础设施故障，不启动 MacBook fallback。

## 实际覆盖范围

仅覆盖 Spark SSH、远端冻结代码、模型路径/镜像、Dev 凭据身份与会话占用状态。三语新的 speech job 已在本地准备；渲染、压缩、回转写、音频 QC、发布及设备验收均未执行。

## 遗留状态

独立代码目录保留在 Spark；未创建本轮模型容器、GPU job 或远端未知派发。另一任务的独占会话原样保留。三语新预算根只发生了已另行报告的文字 QC 调用。

## 外部可见的变化

没有 Dev 发布、TestFlight、实体设备或场地验收。仅此脱敏 docs-only 报告 PR 对外可见。
