# 2026-10-04 制作耗时与 token 审计

## 统计口径

本报告补充 [制作日志复盘](20261004-production-log-retrospective.zh.md)，直接读取实际 accounting events。时间均为 **UTC，日期 2026-10-04**；洛杉矶时间为 UTC−7，因此凌晨 UTC 的制作发生在当地 10 月 3 日晚。统计覆盖本次来源的多轮生产及返工，不能解释为单轮最优耗时。

- 扫描本地 46 份 accounting 事件账本，以 eventId 去重，再以 attemptId 核对 API 尝试，以 responseId 排除重复响应。
- 231,220 个唯一事件，排除 9,033 条重复事件，未发现事件或 attempt 冲突；8,389 个唯一 API 尝试，无重复 responseId。
- 已知输入 22,579,732，输出 2,367,642，合计 **24,947,374 token**。83 次尝试缺完整用量字段，其中 82 次模型请求失败、1 次转录成功但未记录 token。缺失不是 0。
- 这不是完整项目总用量：不含 Codex 主会话/子 Agent 对话、ImageGen、未进入这些账本的调用、当地 TTS/ASR 内部序列 token，也不是供应商账单。
- cachedInputTokens 5,767,783，cacheWriteTokens 16,787,031，reasoningTokens 646,036 是记录中的明细字段，不再次加到 input+output；模型提示缓存与复用整份已完成结果是两种不同机制。
- 耗时采用根 stage 的 elapsedSeconds；阶段执行区间合并用于排除重叠。不把子 stage、API 延迟之和与根 stage 再相加。区间内可能含排队、I/O、缓存校验等，并非纯推理时间。
- 从首任务到末任务的跨度包含未分类间隙，不能把这些间隙全部叫作人工等待。没有可靠起止证据时写“缺失”，不用文件 mtime 推算。

## 阶段汇总

| 流程 | 已记录根 stage 区间并集 | API 尝试 | 已知输入 token | 已知输出 token | 缺完整用量的尝试 |
|---|---:|---:|---:|---:|---:|
| L1 媒体及转录 | 2.89 分钟 | 1 | 0 | 0 | 1 |
| L1 英文机器复核 | 48.31 分钟 | 222 | 1,343,205 | 327,207 | 66 |
| L2 阅读候选及前序修订 | 60.63 分钟 | 6,176 | 14,705,598 | 1,619,998 | 0 |
| 其他或回归 | 0.09 分钟 | 0 | 0 | 0 | 0 |
| L2 口播候选 | 12.36 分钟 | 1,318 | 4,024,742 | 283,712 | 0 |
| L2 时长修订及定向修复 | 2.84 分钟 | 672 | 2,506,187 | 136,725 | 16 |
| L3 后续渲染/重组 | 75.18 分钟 | 0 | 0 | 0 | 0 |

媒体子步骤中，首次 clip 81.219 秒、转录 25.867 秒；它们包含在 pipeline 根 stage 内。下载、人工源文修正、后续 MFA 重对齐缺少本审计可用的完整同一阶段起止账本，不能用以上几分钟代表全部 Layer 1 制作。

阅读候选及前序修订占已知 token 约 65.4%；口播候选约 17.3%；时长修订约 10.6%；英文复核约 6.7%。这是账本分组，不是成功产物所必需的最低成本；包含被拒候选和返工。下一步应按 source/policy/plugin 身份变化分析为何需要重新调用，而不是仅提高并发。

## 按模型

| 模型 | API 尝试 | 已知输入 | 已知输出 | 缺完整用量 |
|---|---:|---:|---:|---:|
| gpt-6-astra | 4,313 | 11,564,008 | 836,405 | 82 |
| gpt-6-sol | 4,075 | 11,015,724 | 1,531,237 | 0 |
| gpt-transcribe | 1 | 0 | 0 | 1 |

## 每次根流程记录

同一目录可能有多次 run；不能按目录只取最后一次。以下耗时为单次根 stage，存在并行重叠，不能直接求和当作整日耗时。failed 可能发生在模型已全部返回后的插件/排程关口，不表示之前的 token 或音频没有产生。

| 账本目录（相对本次 run） | 根 stage | UTC 起→止 | 秒 | 状态 | API 尝试 | 输入 | 输出 | 缺用量 |
|---|---|---|---:|---|---:|---:|---:|---:|
| `pipeline` | `sermon_pipeline` | 02:23:11→02:25:04 | 112.247 | failed | 1 | 0 | 0 | 1 |
| `pipeline` | `sermon_pipeline` | 02:26:06→02:26:22 | 15.990 | failed | 0 | 0 | 0 | 0 |
| `pipeline-pcm-v1` | `frozen_layer1_pcm_resume` | 02:27:22→02:28:07 | 45.289 | completed | 0 | 0 | 0 | 0 |
| `english-source-judge-v1` | `english_source_judge` | 02:31:07→02:44:47 | 820.440 | completed | 28 | 163,676 | 59,301 | 0 |
| `english-source-judge-v2` | `english_source_judge` | 02:48:13→03:01:12 | 778.773 | completed | 28 | 215,075 | 58,953 | 0 |
| `english-source-judge-v3` | `english_source_judge` | 03:04:04→03:12:07 | 482.873 | completed | 18 | 186,018 | 38,718 | 0 |
| `english-source-judge-v3` | `english_source_judge_parallel_prewarm` | 03:07:00→03:07:07 | 7.342 | failed | 66 | 0 | 0 | 66 |
| `english-source-judge-v3` | `english_source_judge_parallel_prewarm` | 03:07:53→03:08:44 | 50.483 | completed | 26 | 256,804 | 52,728 | 0 |
| `english-source-judge-v4` | `english_source_judge_parallel_prefill` | 03:19:11→03:20:04 | 53.196 | completed | 28 | 296,390 | 57,797 | 0 |
| `english-source-judge-v4` | `english_source_judge` | 03:20:29→03:20:30 | 0.451 | completed | 0 | 0 | 0 | 0 |
| `english-source-judge-v6` | `english_source_judge` | 04:24:48→04:37:31 | 762.640 | completed | 28 | 225,242 | 59,710 | 0 |
| `canonical-layer2-v6-override/text/es` | `canonical_layer2_worker` | 05:12:03→05:12:03 | 0.336 | failed | 0 | 0 | 0 | 0 |
| `canonical-layer2-v6-override/text/es` | `canonical_layer2_worker` | 05:13:50→05:14:52 | 61.902 | failed | 74 | 127,929 | 16,591 | 0 |
| `canonical-layer2-v6-override/text/ko` | `canonical_layer2_worker` | 05:16:18→05:28:19 | 720.378 | failed | 948 | 1,694,621 | 305,267 | 0 |
| `canonical-layer2-v6-override/text/zh-Hans` | `canonical_layer2_worker` | 05:31:50→05:32:59 | 69.539 | failed | 82 | 148,115 | 22,182 | 0 |
| `canonical-layer2-v6-override/text/es-repair-v1` | `canonical_layer2_worker` | 05:42:31→05:53:28 | 656.552 | failed | 876 | 1,517,536 | 228,083 | 0 |
| `canonical-layer2-v6-override/text/zh-Hans-repair-v1` | `canonical_layer2_worker` | 06:01:29→06:02:36 | 67.146 | failed | 84 | 153,365 | 24,393 | 0 |
| `canonical-layer2-v7-user-confirmed/text/ko-v7` | `canonical_layer2_worker` | 06:24:55→06:35:10 | 615.403 | failed | 948 | 1,661,609 | 300,661 | 0 |
| `canonical-layer2-v7-user-confirmed/text/ko-v7-repair-v1` | `canonical_layer2_worker` | 06:36:59→06:37:12 | 13.191 | failed | 2 | 4,114 | 804 | 0 |
| `canonical-production-v8/text/zh-Hans` | `canonical_layer2_worker` | 06:57:51→06:59:09 | 77.144 | failed | 172 | 349,724 | 41,066 | 0 |
| `canonical-production-v8/text/ko` | `canonical_layer2_worker` | 06:59:42→07:00:47 | 64.764 | failed | 136 | 269,272 | 35,422 | 0 |
| `canonical-production-v8/revision-2/text/zh-Hans` | `canonical_layer2_worker` | 07:01:20→07:07:54 | 394.245 | failed | 948 | 3,885,932 | 209,731 | 0 |
| `canonical-production-v8/revision-2/text/ko` | `canonical_layer2_worker` | 07:08:12→07:14:41 | 389.319 | failed | 948 | 2,141,679 | 235,752 | 0 |
| `canonical-production-v8/revision-2/text/es` | `canonical_layer2_worker` | 07:14:49→07:16:20 | 90.329 | failed | 172 | 495,333 | 36,272 | 0 |
| `canonical-production-v8/plugin-revision-v1/zh-Hans` | `layer2_models` | 07:17:28→07:17:30 | 2.223 | completed | 0 | 0 | 0 | 0 |
| `canonical-production-v8/revision-3/text/es` | `canonical_layer2_worker` | 07:20:33→07:26:56 | 382.766 | failed | 778 | 2,234,747 | 161,133 | 0 |
| `source-preparation/cache-migration-v2-review/regression-zh-Hans-v1` | `layer2_models` | 07:25:06→07:25:08 | 2.472 | completed | 0 | 0 | 0 | 0 |
| `source-preparation/cache-migration-v2-review/regression-ko-v1` | `layer2_models` | 07:25:11→07:25:14 | 2.741 | completed | 0 | 0 | 0 | 0 |
| `canonical-production-v8/plugin-revision-v2/ko` | `layer2_models` | 07:26:37→07:26:39 | 2.512 | completed | 0 | 0 | 0 | 0 |
| `canonical-production-v8/revision-3/text/ko` | `canonical_layer2_worker` | 07:27:52→07:28:12 | 19.472 | completed | 6 | 15,026 | 2,185 | 0 |
| `canonical-production-v8/plugin-revision-v2/es` | `layer2_models` | 07:36:15→07:36:17 | 2.039 | completed | 0 | 0 | 0 | 0 |
| `canonical-production-v8/revision-4/text/es` | `canonical_layer2_worker` | 07:36:57→07:37:08 | 10.981 | completed | 2 | 6,596 | 456 | 0 |
| `canonical-spoken-v1/zh-Hans` | `canonical_layer2_worker` | 08:30:22→08:31:51 | 89.465 | failed | 160 | 712,794 | 34,409 | 0 |
| `canonical-spoken-v2/zh-Hans` | `canonical_layer2_worker` | 08:37:45→08:37:58 | 12.688 | completed | 2 | 9,001 | 390 | 0 |
| `canonical-spoken-v3/zh-Hans` | `canonical_layer2_worker` | 08:42:30→08:42:42 | 12.263 | completed | 2 | 9,007 | 385 | 0 |
| `canonical-spoken-v4/zh-Hans` | `canonical_layer2_worker` | 08:57:11→08:57:33 | 21.846 | completed | 16 | 70,850 | 2,605 | 0 |
| `canonical-spoken-v4/es` | `canonical_layer2_worker` | 09:19:01→09:21:21 | 139.838 | failed | 262 | 845,246 | 53,165 | 0 |
| `canonical-spoken-v5/es` | `canonical_layer2_worker` | 09:31:31→09:31:42 | 11.360 | completed | 8 | 25,002 | 1,504 | 0 |
| `canonical-spoken-v5/ko` | `canonical_layer2_worker` | 09:32:51→09:40:10 | 439.379 | failed | 858 | 2,327,566 | 189,269 | 0 |
| `canonical-spoken-v6/ko` | `canonical_layer2_worker` | 09:43:58→09:44:12 | 14.752 | completed | 10 | 25,276 | 1,985 | 0 |
| `formal-layer2-timing-revision-v1/runs/zh-Hans` | `layer2_models` | 12:46:44→12:46:45 | 1.673 | failed | 16 | 0 | 0 | 16 |
| `formal-layer2-timing-revision-v1/runs/zh-Hans-attempt2` | `layer2_models` | 12:48:19→12:49:42 | 83.007 | completed | 396 | 1,759,358 | 77,739 | 0 |
| `formal-layer2-timing-revision-v1/runs/ko-attempt1` | `layer2_models` | 12:50:42→12:51:32 | 50.323 | completed | 188 | 511,038 | 46,325 | 0 |
| `formal-layer2-timing-revision-v1/runs/es-attempt1` | `layer2_models` | 12:51:32→12:51:45 | 12.852 | completed | 62 | 199,250 | 10,438 | 0 |
| `formal-layer2-timing-revision-v1/runs/zh-Hans-attempt3` | `layer2_models` | 12:57:16→12:57:24 | 7.871 | completed | 4 | 18,070 | 902 | 0 |
| `formal-layer2-timing-revision-v1/runs/ko-attempt2` | `layer2_models` | 12:57:24→12:57:31 | 7.165 | completed | 2 | 5,450 | 373 | 0 |
| `formal-layer2-timing-revision-v1/runs/es-attempt2` | `layer2_models` | 12:57:32→12:57:39 | 7.473 | completed | 4 | 13,021 | 948 | 0 |
| `formal-layer3-execution-v2/es-publication-v1/collected-es-render-v1` | `layer3_formal_render` | 14:04:06→14:19:48 | 942.313 | failed | 0 | 0 | 0 | 0 |
| `zh-publication-v1/audio-render` | `layer3_formal_render` | 14:34:16→14:55:22 | 1265.496 | completed | 0 | 0 | 0 | 0 |
| `ko-publication-v1/audio-render` | `layer3_formal_render` | 14:51:11→15:12:06 | 1255.328 | failed | 0 | 0 | 0 | 0 |
| `formal-layer3-execution-v2/es-publication-v1/collected-es-render-v1` | `layer3_formal_render` | 17:19:25→17:41:03 | 1298.616 | failed | 0 | 0 | 0 | 0 |

## 首轮三语正式配音队列

这些记录不在上面的 46 份本地 accounting 账本内，独立来自 `formal-layer3-execution-driver-v1/snapshot-122126.json` 的 queueState。采用 locale 启动到 renderer 返回的区间，包含加载、生成及验证，不能视为纯 GPU 推理。

| 语言 | UTC 起→止 | 耗时 | WAV/收据 | renderer 返回 |
|---|---|---:|---:|---|
| zh-Hans | 10:29:13→10:51:23 | 22.16 分钟 | 474/474 | exit 1，排程失败 |
| ko | 10:51:23→11:13:40 | 22.28 分钟 | 474/474 | exit 1，排程失败 |
| es | 11:13:40→11:36:00 | 22.34 分钟 | 474/474 | exit 1，排程失败 |

三语顺序运行，队列 10:29:13→11:36:00，共约 66.78 分钟。每语 474 个单元不等于完整轨通过。后续中文与韩语约 21 分钟的 layer3_formal_render 记录均有 474 个 layer3.reuse 单元，无 synthesis/model_load 阶段，是缓存复用及校验，不应当作又做了一轮 GPU TTS。西语 14:04 的尝试有 288 句复用、32 句新生成后内存失败；17:19 续跑有 122 句复用并继续合成。续跑阶段总耗时不能只归到新句生成。

## 尚不能精确归因的流程

| 流程 | 已有证据 | 时间/token 限制 |
|---|---|---|
| 源文人审、翻译人审、音频听审 | 版本绑定的决定/批准收据 | 决定时间不是开始审核时间；实际阅读/聆听耗时缺失 |
| 静音裁切、完整 ASR、声纹生成 | 音频哈希、筛查覆盖率、产物收据 | 本地收据不足以给出各任务可靠起止；当地模型 token 不适用 API 账本，内部 token 未记录 |
| 中文先发布、标题补修、韩语/西语发布 | HTTP pass、资产哈希、页面读回 | 部分候选复制了旧 deployment-command-receipt；旧起止不能算新发布耗时。最终 HTTP 收据未记录起止 |
| 三语海报 | ImageGen 产物、提示词、二维码与检查收据 | 无独立计时/token 收据，缺失 |
| Codex 调度、修复和子 Agent | 本次对话工作 | 不在生产 accounting 中；无法由模型生产 API token 反推出对话 token |

## 对流程的判断

1. 已记录模型运行时间远小于跨阶段跨度，优先补齐交接、身份失效、修复、人审等待的事件；不能由差值直接推断“全是人工等待”。
2. 大头是阅读候选及前序修订，需区分源稿改变、policy 改变、插件误拒与缓存迁移，减少无必要整批重跑。
3. 时长返工本身已知新增约 264 万 token，尽早做实测连续段预检有明确优化对象；尚未证明能减少多少。
4. 每次新发布应产生自己的 started/finished/version 收据，不能复制旧部署时间。恢复程序应拒绝时间身份不匹配的收据。
5. 下次统一统计当地 GPU/CPU 时间、API token、Codex 用量和人工等待，分别计量后汇总，不伪造完整总量。

## 可复核产物

本地 `timing-token-audit-v1/accounting-audit.json` 保留唯一事件/attempt 统计、每次根 stage、模型分组及 46 份输入 SHA-256；`attempts.csv` 为逐 run 表。原始账本和媒体继续留在 ignored artifacts。报告中只提交汇总，不提交提示词、译文响应或私人数据。
