# 本地制作计算策略：Spark 默认，MacBook fallback

决定日期：2026-10-01。今后的预制本地制作默认由 **DGX Spark 执行模型计算，MacBook 作为 fallback**。MacBook 仍可协调任务、取得媒体、保存收据、执行 CPU 媒体处理和提供人工审阅入口。此策略覆盖预制制作，不改周日独立 live_session 的现场设备要求，也不把当前 Astra/Sol API 改成本地模型。

## 默认与恢复

- 新任务先检查 Spark 的连接、所需运行时、模型和授权 checkpoint；实际执行写入 host、模型 revision/hash、设备、精度与耗时收据。
- Spark 的连接、依赖、设备、内存或明确运行故障才允许使用已配置的 MacBook fallback。输入损坏、checkpoint 不符、未知读法、内容或质检失败、待人审和远端结果未知均不得靠切机绕过。
- fallback 使用同一冻结来源、文字、声音身份和生成设置；换设备／精度进入新的执行身份及独立产物目录。不能把部分 MPS 与 CUDA 音频拼成同一正式 render。已经完成或可恢复的旧任务继续原后端，不因默认策略改变全篇重算。
- 两端不可用时保留产物并停止。MacBook 缺少匹配的授权 checkpoint 不自动换声音；远端结果未知先对账，不并发制造第二份结果。
- 项目代码中的默认值与后台任务的实际部署分开验证。显式指定后端用于诊断或恢复，不能改变四层门禁与发布范围。

## 当前接入范围

| 路径 | 默认与边界 |
|---|---|
| reading MFA | `mfa_backend.py` 选择 Spark 优先、本机备用，保留显式选择与关闭 Spark 的兼容选项；见 [MFA 说明](mfa-production.zh.md) |
| legacy weekly TTS | `run_weekly_dubbing.py` 新任务先用 Spark CUDA；恢复已存在的 render 时沿用原后端；见 [语音运行合同](../experiments/sermon-dubbing-poc/SPEECH-RUNTIME.zh.md) |
| legacy Qwen ASR/ForcedAligner | `SERMON_SPEECH_BACKEND=auto` 先用 Spark，受限故障时回到 MacBook MLX；`spark`/`macbook` 可强制指定 |
| canonical 多语言 TTS | [正式 renderer](formal-layer3-renderer.zh.md) 已默认 `cuda:0`/BF16；按本策略在 Spark 运行。它仍需操作员指定模型路径、传输和任务目录，不具备完整跨机自动 dispatch |
| canonical 配音回转写 | CUDA worker 当前硬编码 CUDA；按本策略在 Spark 运行。完整 MacBook 自动 fallback adapter 尚未接入，不把 legacy 适配器代称为正式 producer |
| 转写、翻译、复核 API | 继续当前周次的生产 policy；迁移机器只迁移调用与账本，不更换内容模型和人审要求 |
| FFmpeg、打包、hash、发布 | 选靠近输入的 CPU worker，减少媒体搬运；发布目标及 HTTP、设备、现场证据保持各自边界 |

这是项目默认选择与已接入口的策略；不声称所有 canonical producer 已由统一控制器自动完成 Spark→MacBook 切换。

## 为什么优先 Spark

[10 月 1 日分层 A/B](local-model-layer-latency-ab-20261001.zh.md)中，同 checkpoint 的 TTS 热推理按音频时长归一后，Spark CUDA/BF16 约为 MacBook MPS/FP32 的 4.5 倍。按 9 月 27 日三语工作量外推，纯 TTS 约 56 分钟与 249 分钟。不同运行时、精度、语言和正式 checkpoint 的边界见原报告，这些数值不是整篇实测或质量晋级。

Spark 上的全本地预算中，文字初译＋复核代理约 71 分钟，已经超过 TTS 的约 56 分钟；优化不能只盯配音。总体加速、云端资源和成本调研见 [生产时长与 GCP 评估](gcp-production-feasibility-20261001.zh.md)。

预算假设模型驻留。路由修改之后，四项提速代码已完成并行开发和离线验证，入口、恢复边界与验收状态见[提速 backlog](local-production-speed-backlog.zh.md)。legacy 语音采用受限批次内驻留，正式 TTS/ASR 提供显式 batching，CPU 保存可与合成重叠；真实吞吐仍待测，不能据此降低原预算。云端编排尚未实现。

## 路由策略验证

120 项相关离线测试通过：MFA、上游参数转发和 pipeline 61 项；ASR/TTS 路由、会计、并发、执行恢复和远端导入恢复 59 项。回归覆盖 Spark 默认、强制后端、关闭 Spark、fallback 原因、冻结输入变化、内容／身份失败不降级、远端未知执行不重跑，以及部分 CUDA 产物不能自动换成 MPS。文档相对文件链接、费用 JSON 数学及 `git diff --check` 通过。

本轮没有重跑生产模型、安装后台 runner、改动 Spark 服务或创建 GCP 资源；离线代码验证与后台实际部署分开报告。

后续四项提速的代码和离线回归独立记录在[开发验收](local-production-speed-backlog.zh.md#完成证据)，不把上述 120 项路由回归当作 GPU 性能证据。
