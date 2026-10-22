# 复盘：20261022-es-ko-timeline-job-prep

本报告记录获批 ES/KO 候选的时间映射与 L3 handoff 准备，不代表四层发布。机器失败证据和批准例外仍按原状态披露。

## 结论先行

L1 timeline map 通过校验；西语和韩语 416 组 speech job 均为 `prepared_for_target_language_speech`、`synthesisEligible=true`。候选的 `modelReview.status=fail`，每语两组机审发现由用户批准按原文进入音频准备；模型证据未被改写，候选仍 `releaseEligible=false`。没有提交 Spark job、生成音频、构建页面或发布。

结束信号是 `outcome.json` 与两份 speech-job JSON 的 schema／收据验证。Spark Job API 读状态返回 HTTP 502 `SPARK_JOB_UNREACHABLE`；直连只读检查显示 Qwen 服务 inactive、GPU 利用率 0%。本轮未尝试合成。

## 总时间

未记录本阶段的 journal 或计时；不估算墙钟、计算、等待或返工时间。与上一份 L3 准备报告 [#1291](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1291) 相比，本轮新增 approved-window timeline map 与时间映射绑定 job，没有新增模型调用。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | reused | — | 0 | not_run | — | — | $0 本轮新增 | 已批准 source package |
| L1 词级对齐（MFA） | reused | — | 0 | not_run | — | — | $0 本轮新增 | 已批准 source package 与 anchor |
| L1 英文机器评审 | reused | — | 0 | not_run | — | — | $0 本轮新增 | 已批准 source package |
| L2 初译 | reused：OpenAI `gpt-6.1-sol` | 前序正式运行；见 #1273、#1274 | 0 | not_run | — | — | 本轮 $0 新增；前次实际计费未知 | 416 组候选及 v2 收据 |
| L2 独立审核 | reused：OpenAI `gpt-6.1-sol` | 前序正式运行；见 #1273、#1274 | 0 | not_run | — | — | 本轮 $0 新增；前次实际计费未知 | v2 收据绑定原始响应缓存 |
| 文本质检 | not_run | — | 0 | 0 | 0 token | — | $0 | 本轮无 QC 调用 |
| L3 配音（TTS） | not_run；Spark API 不可达 | — | 0 | 0 | 0 音频秒 | — | $0 | 两份 job 仅证明 handoff 准备可用 |
| L3 回转写筛查（ASR） | not_run | — | 0 | 0 | — | — | $0 | — |
| 音频质检 | not_run | — | 0 | 0 | — | — | $0 | — |
| L4 构建与发布 | not_run | — | 0 | 0 | — | — | $0 | — |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| Spark admission | DGX Job API 返回 502；Spark `llama-server.service` inactive，localhost 模型 API 拒绝连接 | 远端控制面与推理服务当前不可用 | 预检；未占 GPU | 停在准备阶段；恢复后经受控 admission 流程重查 | 只读状态复查仍 502；没有提交 GPU job | 外部运行状态；相关准备见 #1290、#1291 |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 保持在 Spark admission 前完成 timeline、override 收据和 v4 job 校验；API 可达后再申请算力 | 本轮两语 handoff 已准备，Spark API 返回 502 | 避免服务不可用时占用 GPU 或重复 L2 支出 | Codex | [#1290](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1290) |

## 实际覆盖范围

L1：复用已批准的 Drive source package、anchor、窗口审批、timeline report、source clip WAV 和 identity；生成共享 v4 clip timeline map。L2：复用两语 416 组候选、用户批准的 review sheet、override receipts 和响应缓存；未调用模型。L3：生成两语时间映射绑定 speech job，并验证收据与 schema；TTS、ASR、音频 QC 和人工听审均未运行。L4：未构建或发布。

## 遗留状态

没有活动 Spark job 或 session hold。忽略的本机 `artifacts/` 保存 timeline map 和两份新 speech job，路径位于 `artifacts/weekend-live/broadcast-20261018-es-ko-20261022/inputs/l3/` 与 `l3/{es,ko}/speech-job-v4-timeline/`。本轮没有部署文件、构建号或待清理的临时媒体。

## 外部可见的变化

没有更新 Firebase、catalog、网页、App 或 TestFlight。浏览器、设备播放和场地验收均为 `not_run`。
