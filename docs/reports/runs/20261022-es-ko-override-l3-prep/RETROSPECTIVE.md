# 复盘：20261022-es-ko-override-l3-prep

数据见同目录 `INDEX.md` 和 `manifest.json`。本报告仅记录 L3-01 准备，不代表完整四层发布。

## 结论先行

西语和韩语的 416 组 speech job 均为 `prepared_for_target_language_speech`、`synthesisEligible=true`。v2 人工覆盖收据绑定完整 review sheet、用户决定、832 份译者／复核缓存哈希和未改变的模型失败证据；两语候选 `modelReview.status=fail`，每语保留两组人工接受的原机审发现，`releaseEligible=false`。没有开始 Spark 合成、音频 QC、人工听审或 L4 发布。

结束时 Spark Job API 返回 `SPARK_JOB_UNREACHABLE`；直连 Spark 显示 `llama-server.service=inactive`。没有提交或运行本轮 GPU job，也没有改动 Spark 服务。

## 总时间

本轮没有 `journal.ndjson`、起止时间或阶段计时，无法可靠拆分墙钟时间、计算、等待和返工。不估算耗时。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | reused | — | 0 | not_run | — | — | — | 已批准 source/anchor 输入 |
| L1 词级对齐（MFA） | reused | — | 0 | not_run | — | — | — | 已批准 source/anchor 输入 |
| L1 英文机器评审 | reused | — | 0 | not_run | — | — | — | 已批准 source/anchor 输入 |
| L2 初译 | reused：OpenAI `gpt-6.1-sol` | 前次运行；见 [ES #1273](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1273) 与 [KO #1274](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1274) | 0 | not_run | — | — | 本轮无新增调用；费用沿用前次报告 | v2 收据绑定缓存 |
| L2 独立审核 | reused：OpenAI `gpt-6.1-sol` | 前次运行；同上 | 0 | not_run | — | — | 本轮无新增调用；费用沿用前次报告 | v2 收据绑定缓存 |
| 文本质检 | API backend preflight only | — | 0 | 本地校验；时长未记录 | 0 token | — | $0 | locale summary 绑定 preflight summary SHA |
| L3 配音（TTS） | not_run；Spark API 不可达 | — | 0 | 0 | 0 音频秒 | — | $0 | `synthesisEligible=true` 只证明 job 准备通过 |
| L3 回转写筛查（ASR） | not_run | — | 0 | 0 | — | — | $0 | — |
| 音频质检 | not_run | — | 0 | 0 | — | — | $0 | — |
| L4 构建与发布 | not_run | — | 0 | 0 | — | — | $0 | — |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L3-01 | speech job 把用户 attestation 当成候选绑定的 voice authorization，schema 拒绝 | 两种收据合同不同 | 预检；未占 GPU | 从已批准 attestation 生成绑定源、语言和候选的 v2 authorization | CLI 重新验证通过 | [#1290](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1290) |
| L3-01 | 初版 authorization producer 为 v1 attestation 写出 v1 收据，v2 新字段被拒绝 | producer 没有对应 v2 分支 | 预检；未占 GPU | 支持 v2 收据并保留源、媒体 hash、授权窗口和用途 | v2 receipt 生成及两语 speech-job 准备通过 | [#1290](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1290) |
| Spark admission | Spark Job API 不可达；直连读取到 `llama-server.service=inactive` | 当前 Hub API／模型服务未运行 | 预检；未提交或启动 GPU job | 停在本地准备；服务恢复后再重查，不直接改服务 | live status readback：502 `SPARK_JOB_UNREACHABLE` | 等待外部服务恢复 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 把用户的窗口级 attestation 明确派生为 candidate-bound source authorization，并在申请 Spark 前检查 Hub 可达和服务状态 | 两次 schema 错误和一次 API 不可达均在预检发现 | 避免占用资源后才暴露授权形状或 host admission 问题 | Codex | [#1290](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1290) |

## 实际覆盖范围

L1：复用原人工批准的 source package 与 anchor。L2：复用上轮的 416 组缓存响应；从已批准 review sheet 构建两语 candidate，收据保留每个输入缓存 hash、原始 machine findings 和完整用户批准绑定。文本 QC 只运行无模型调用的 preflight。L3：两语 speech job 与 source voice authorization v2 准备通过；Spark TTS、ASR 回转录、音频包、音频 QC 和人耳听审均未运行。L4：未构建、未发布。

## 遗留状态

没有未结束的 Spark job 或 hold；没有部署或构建号。候选、收据、speech job、QC preflight 和本机日志仍在被忽略的 `artifacts/` 下；原始缓存和译文未复制进本公开报告。Spark Hub 恢复后可从已准备的 speech job 继续，无需重新发起 L2 API 请求。

## 外部可见的变化

没有更新 Dev catalog、Firebase、App/TestFlight 或公开页面。浏览器、设备播放和场地验收均为 `not_run`。
