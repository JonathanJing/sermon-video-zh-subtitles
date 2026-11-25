# 周汇总：20261115

服务周 2026-11-09 至 2026-11-15。本页由 `tools/development/weekly_rollup.py` 从本周已入库的运行报告生成，数值来自 `weekly.json`；**机器生成，`humanApproval=false`**。审核人在本页写结论和决定，合并本 PR 即批准这些决定，不批准任何内容产物。

## 结论

- **本段由机器撰写，尚未经人审核（`humanApproval=false`）。**
- 交付：`20261115-jesus-is-better` 报告记录第 10 周页面（zh-Hans／ko／es）经 4 个发布意图上线，最终 7/7 HTTP 校验通过；真机展示与物理扫码为 not run。播客报告 `20261115-jesus-is-better-podcast` 的 journal 里 `l3.review.es`、`l3.review.ko`、`l3.review.zh-Hans`、`l4.publish` 未收尾，终态以该报告为准。
- 最贵的重做／晚发现：播客报告登记 12 个 Opus 翻译分片全部 0 行、`gpt-4o-transcribe` 两块静默丢段（均为占用资源后发现），另有 `firebase deploy` 两次被 SIGKILL；本页「对比上周」中全周错误 24 条，晚发现占比 20.8%（上周 81.8%）。主报告 `20261115-jesus-is-better` 还记录标题连续三次变更。
- 上周改进项：本页「上周改进项结果」显示没有待验证项；`publish.deployAttempts` 本周仍无数值。
- 采集缺口：9 份报告中 7 份缺 journal、5 份无 manifest、4 份复盘未填完、7 份私有证据未上传；`20261115-jesus-is-better` 复盘不是八项骨架。因此本周时间和部署数值不完整，不宜与上周直接比较。

## 本周运行

| 报告 | 类型 | 墙钟 | 计算 | 等待 | 重复轮次 | 部署 | 门禁 | 复盘 | 私有证据 |
|---|---|---|---|---|---|---|---|---|---|
| [20261109-local-tts-ab](../../runs/20261109-local-tts-ab/INDEX.md) | 其他 | — | — | — | — | — | — | 已填 | 未上传 |
| [20261112-web-modern-guidance](../../runs/20261112-web-modern-guidance/INDEX.md) | 其他 | — | — | — | — | — | — | 缺失 | 未上传 |
| [20261114-deepseek-asr-ab](../../runs/20261114-deepseek-asr-ab/INDEX.md) | 其他 | — | — | — | — | — | — | 缺失 | 未上传 |
| [20261114-deepseek-tts-speed](../../runs/20261114-deepseek-tts-speed/INDEX.md) | 其他 | — | — | — | — | — | — | 已填 | 未上传 |
| [20261114-live-capture](../../runs/20261114-live-capture/INDEX.md) | 其他 | — | — | — | — | — | — | 缺失 | 未上传 |
| [20261114-sfa-preproduction-rehearsal](../../runs/20261114-sfa-preproduction-rehearsal/INDEX.md) | 生产 | 1h03m | 0m00s | 0m00s | 0m00s | — | — | 已填 | 未上传 |
| [20261114-subtitle-filler-shadow](../../runs/20261114-subtitle-filler-shadow/INDEX.md) | 其他 | — | — | — | — | — | — | 缺失 | 未上传 |
| [20261115-jesus-is-better](../../runs/20261115-jesus-is-better/INDEX.md) | 其他 | — | — | — | — | — | — | 非骨架格式 | 已上传 7 |
| [20261115-jesus-is-better-podcast](../../runs/20261115-jesus-is-better-podcast/INDEX.md) | 生产 | 8h02m | 41m48s | 0m00s | 2m59s | — | — | 已填 | 已上传 6 |

墙钟取该报告所有 journal 的最早到最晚事件；没有 journal 的报告显示「—」，不是零。「重复轮次」是同一阶段再次启动后的计算时间，包含返工和变更，下面由审核人区分。

## 对比上周

| 指标 | 本周 20261115 | 上周 20261108 | 变化 |
|---|---|---|---|
| 运行报告数 | 9 | 3 | +6 |
| 其中生产运行 | 2 | 2 | 持平 |
| 生产墙钟 | 9h06m | 5h03m | +4h03m |
| 生产计算 | 41m48s | 49m30s | -7m43s |
| 生产等待 | 0m00s | 0m00s | 持平 |
| 重复轮次计算 | 2m59s | 3m40s | -0m42s |
| 重复轮次占计算比 | 7.1% | 7.4% | -0.3 个百分点 |
| 发布阶段失败事件 | 7 | 4 | +3 |
| 复盘登记的错误 | 24 | 11 | +13 |
| 预检发现 | 15 | 2 | +13 |
| 占用资源后发现 | 5 | 2 | +3 |
| 发布后发现 | 0 | 7 | -7 |
| 晚发现占比 | 20.8% | 81.8% | -61.0 个百分点 |
| 无 manifest 的报告 | 5 | 1 | +4 |
| 缺 journal 的报告 | 7 | 1 | +6 |
| 复盘未填完 | 4 | 1 | +3 |
| 未上传私有证据 | 7 | 1 | +6 |

两周的来源长度和运行数不同时，时间类指标不能直接算提速比。

## 上周改进项结果

没有待验证的改进项。

## 错误与发现时机

| 报告 | 层／阶段 | 现象 | 发现时机 | 提交或 PR |
|---|---|---|---|---|
| 20261109-local-tts-ab | 准备／传输 | `rsync` 立即失败：`unrecognized option --info=progress2` | 预检 | 复制后比对 `model.safetensors`／`config.json` SHA |
| 20261109-local-tts-ab | 编排／Spark 派发 | 第一次派发在启动 job 前 `FileNotFoundError: .../artifacts/experiments/spark-tts-memory-ab/spark_runner.py` | 预检 | 仅本地工具脚本 |
| 20261109-local-tts-ab | 编排／Spark 运行时 | 生产 harness 在构造 `QwenSynthesizer` 时 `spark_exclusive_session_required` 失败 | 未标明 | 本报告 |
| 20261109-local-tts-ab | 编排／Mac 套件 | 第一次启动立即退出，`artifacts/local-tts-ab-20261109/...` 找不到 | 预检 | 仅本地工具脚本 |
| 20261114-deepseek-tts-speed | 报告口径 | 初稿把 11-08 的 Spark 基线写成「8 副本 × batch 8」 | 占用资源后 | 本 PR |
| 20261114-deepseek-tts-speed | 摘要生成 | 摘要工具把 `timings.tsv` 的 `total` 行与各阶段相加，得出 41m36s | 占用资源后 | 本 PR |
| 20261114-deepseek-tts-speed | 服务返回 | WAV 头 data 长度是占位值 `0xFFFFFFFF` | 预检 | 本 PR |
| 20261114-sfa-preproduction-rehearsal | L4 预检 | `firebase` 不在 PATH，`npx --no-install` 也没有 | 预检 | 环境修复，未改仓库 |
| 20261114-sfa-preproduction-rehearsal | L2 预检 | `claude` 不在 PATH；CLI 未登录（`Not logged in · Please run /login`） | 预检 | 环境修复 |
| 20261114-sfa-preproduction-rehearsal | L4 预检 | Synology 镜像少 3 个受版本控制文件：`firebase/dev/.gitignore`、两处 `.well-known/apple-app-site-association` | 预检 | 环境修复 |
| 20261114-sfa-preproduction-rehearsal | 开工 | `prepare_clip` 报 “clip would start before the media” | 预检 | 今晚命令模板已更新 |
| 20261114-sfa-preproduction-rehearsal | Spark 会话 | `begin` 报 `unmanaged_running_container`（h3image） | 预检 | 运营步骤 |
| 20261114-sfa-preproduction-rehearsal | Spark 会话 | `begin` 报 `unmanaged_model_or_worker_process` | 预检 | 运营步骤 |
| 20261114-sfa-preproduction-rehearsal | Spark 会话 | 停 `spark-api` / `llama-server` 后单元进入 `failed`（OOM-kill），`begin` 报 `effect_requires_reconciliation` | 预检 | 今晚可能复现，步骤已写进清单 |
| 20261114-sfa-preproduction-rehearsal | L4 门禁 | 线上 11-08 页面跑 gate 失败：`catalog.defaultPageId` 指向另一页 | 预检 | 今晚顺序约束 |
| 20261114-sfa-preproduction-rehearsal | 发布链路 | `stage-english-reference` 对旧的 `baseline-english` 快照失败：目录 source identity 不匹配 | 预检 | 使用当天基线 |
| 20261114-sfa-preproduction-rehearsal | 通知 | `notify` 没有真正推送 | 预检 | 今晚如要推送需先放键 |
| 20261115-jesus-is-better-podcast | L1 文本 | `gpt-4o-transcribe` 两块静默丢段（191 词、152 词） | 占用资源后 | — |
| 20261115-jesus-is-better-podcast | L1 句表 | 第一版 v2 句表在句界串词（「room Our kids have no idea.」） | 预检 | — |
| 20261115-jesus-is-better-podcast | L2 派发 | 12 个 Opus 翻译分片全部 0 行 | 占用资源后 | — |
| 20261115-jesus-is-better-podcast | L1 句界 | `sfa_publish assets` 两次被 iOS cue 校验拒绝（零长、毫秒重叠） | 未标明 | — |
| 20261115-jesus-is-better-podcast | L3 收尾 | `finish_run.py` 首次在 zh 收尾时失败 | 占用资源后 | — |
| 20261115-jesus-is-better-podcast | L4 部署 | `firebase deploy` 两次被 SIGKILL | 未标明 | — |
| 20261115-jesus-is-better-podcast | L4 部署 | 增量发布首次上传 HTTP 412 | 未标明 | — |

## 重复轮次：返工还是变更

<!-- 审核人在「归类」填 返工 或 变更。用户改主意、口径变化造成的重做是变更，不算返工。 -->
| 报告 | 阶段 | 重跑次数 | 重复轮次计算 | 归类 |
|---|---|---|---|---|
| 20261114-sfa-preproduction-rehearsal | l1.start | 1 | 0m00s | — |
| 20261114-sfa-preproduction-rehearsal | l3.finish | 2 | 0m00s | — |
| 20261115-jesus-is-better-podcast | l4.baseline | 2 | 1m36s | — |
| 20261115-jesus-is-better-podcast | l3.finish | 1 | 0m52s | — |
| 20261115-jesus-is-better-podcast | l4.assets | 3 | 0m23s | — |
| 20261115-jesus-is-better-podcast | l4.stage2 | 1 | 0m03s | — |
| 20261115-jesus-is-better-podcast | l4.publish | 3 | 0m02s | — |
| 20261115-jesus-is-better-podcast | l4.readback | 1 | 0m01s | — |
| 20261115-jesus-is-better-podcast | l1.preflight | 1 | 0m01s | — |
| 20261115-jesus-is-better-podcast | l1.preflight | 2 | 0m01s | — |
| 20261115-jesus-is-better-podcast | l4.preflight | 2 | 0m00s | — |
| 20261115-jesus-is-better-podcast | l4.publish-check | 3 | 0m00s | — |
| 20261115-jesus-is-better-podcast | l4.validate | 1 | 0m00s | — |
| 20261115-jesus-is-better-podcast | l1.preflight.setup | 1 | 0m00s | — |
| 20261115-jesus-is-better-podcast | l2.consistency | 2 | 0m00s | — |
| 20261115-jesus-is-better-podcast | l1.preflight | 1 | 0m00s | — |
| 20261115-jesus-is-better-podcast | l1.preflight.setup | 1 | 0m00s | — |
| 20261115-jesus-is-better-podcast | l2.consistency | 2 | 0m00s | — |
| 20261115-jesus-is-better-podcast | l1.preflight.setup | 2 | 0m00s | — |
| 20261115-jesus-is-better-podcast | l2.consistency | 2 | 0m00s | — |

## 候选改进

<!-- 审核人填后三列：决定写 接受／拒绝／推迟；接受的必须有 backlog ID 和验证信号，信号写成 `指标 比较符 数值`，指标名见 weekly.json 的 metrics。每周最多接受 3 条。可以自己加行。 -->
| 编号 | 来源 | 类别 | 改进 | 依据 | 决定 | backlog ID | 验证信号 |
|---|---|---|---|---|---|---|---|
| C1 | 20261109-local-tts-ab | 流程／质量 | 让 `benchmark_formal_tts.py` 在非 Spark 主机上有明确的诊断模式（例如显式 `--diagnostic-unbound-session`），而不是让操作员各自打 verifier 补丁 | 第 3 条错误：生产 harness 在 Mac 上必然被门禁拒绝 | — | — | — |
| C2 | 20261109-local-tts-ab | 预检 | 把「派发脚本路径/工作目录自检」加入 TTS 基准的新运行检查，或复用 `check_run_start.py --spark-stages` | 第 2、4 条错误，合计约 8 分钟返工 | — | — | — |
| C3 | 20261109-local-tts-ab | 速度 | 冷启动差距主要来自 Spark 容器与模型加载（30–37 s），可评估预热常驻或容器预留 | cold 表：Spark 加载 30.95–36.96 s，Mac 2.42–3.28 s | — | — | — |
| C4 | 20261109-local-tts-ab | 成本 | 本轮为 0 付费 API；后续若把 A/B 扩到整篇，需要按既有预算合同登记 | 报告与摘要中费用列为 0 | — | — | — |
| C5 | 20261114-deepseek-tts-speed | 速度 | 云 TTS 按并发而不是按句排队：1.1 秒/句的固定开销只能靠并发摊薄 | 串行 RTF 0.351、8 并发 0.045，单句延迟不变 | — | — | — |
| C6 | 20261114-deepseek-tts-speed | 质量 | 换声音或换服务前先做人工整轨听审，并把 60 秒 ASR 抽查升级为分句抽查 | 本次只有 1 次 60 秒机器转写 | — | — | — |
| C7 | 20261114-deepseek-tts-speed | 同步 | 若要接云 TTS，先确定性地处理每单元首尾静音，并作为 L3 改动记录 | 原样最大滞后 42.9 秒；裁首尾后 6.3 秒 | — | — | — |
| C8 | 20261114-deepseek-tts-speed | 预检 | 对接前把「WAV 头未回填、无语速参数、无续传」写进入口检查 | 本次冒烟才发现头问题 | — | — | — |
| C9 | 20261114-sfa-preproduction-rehearsal | 预检 | 把 `firebase` CLI 与登录、AASA 点目录、h3image/前端服务、`reset-failed` 处理写进开工前固定检查 | 本轮四个问题都在预检阶段发现，任何一个留到发布或 GPU 后都会白占时间 | — | — | — |
| C10 | 20261114-sfa-preproduction-rehearsal | 模型栈 | 把 OpenAI/Opus/TTS 身份、脚本哈希与安装清单写成 `docs/sentence-first-model-stack.zh.md`，每周只换标题/经文/讲员等内容字段 | 转录、翻译、TTS 三处都缺全局 CLI 或登录，靠口头记忆容易漏 | — | — | — |
| C11 | 20261114-sfa-preproduction-rehearsal | 预检 | 给 `prepare_clip` 在 unit 0 起点为 0 时给出明确的边距提示，或在锚点清单里记录推荐边距 | 默认 1.0 s 直接失败 | — | — | — |
| C12 | 20261114-sfa-preproduction-rehearsal | 流程 | 在 `sfa.py start --plan` 输出里提前检查 `h3image`/未登记容器与 `failed` 单元 | 这三类都在 `begin` 才暴露 | — | — | — |
| C13 | 20261114-sfa-preproduction-rehearsal | 流程 | 为 DeepSeek 阶段提供不调用 API 的 plan 输出 | 没有 `--execute` 时直接报 “call required”，本轮无法验证窗口与预算路径 | — | — | — |
| C14 | 20261114-sfa-preproduction-rehearsal | 质量 | 预演使用上期已批准译文与收据副本，并明确标 `REHEARSAL-FIXTURE` | 避免把机器生成的 approved 收据误当人审 | — | — | — |
| C15 | 20261115-jesus-is-better-podcast | 流程 | 把 `hosting_incremental_publish.py` 接到 `sfa_publish publish` 的默认路径（CLI 失败时自动回退） | 本轮 2 次 CLI 部署被系统杀死，占用约 40 分钟并留下 lease 冲突 | — | — | — |
| C16 | 20261115-jesus-is-better-podcast | 速度 | `finish_run.py` 自动识别纯音频媒体并跳过视频 mux | zh 首轮收尾失败重跑 | — | — | — |
| C17 | 20261115-jesus-is-better-podcast | 预检 | 句表生成后立刻跑一次 iOS cue 等价检查（零长、单调、时长上限） | assets 两次被拒 | — | — | — |
| C18 | 20261115-jesus-is-better-podcast | 质量 | `gpt-4o-transcribe` 分块加逐块词数覆盖率门禁（<0.9 即重转） | 两块丢段到对齐阶段才发现 | — | — | — |
| C19 | 20261115-jesus-is-better-podcast | 流程 | 统计目录 `sermon-feedback-api` 纳入发布意图的固定项或明确记 gap | 连续两期 `/api/session` 无法验证 | — | — | — |
| N1 | 20261115-jesus-is-better | 预检 | 把 firebase CLI 所需的 Node 版本（22）写进发布前固定检查，避免 Node 26 下部署被 SIGKILL | 复盘要点：首次 stage1 被 SIGKILL，改 Node 22 重发 | — | — | — |
| N2 | 20261115-jesus-is-better | 预检 | 句表生成后检查句界重叠（0.04 s 级），与 C17 合并评估 | 复盘要点：字幕 9 处句界重叠，修后重出资产 | — | — | — |
| N3 | 20261115-jesus-is-better | 流程 | 开发布前先定稿主标题和三语标题规则，避免连续多次 `published_page_replace` | 复盘要点：标题经 3 次变更，各走一轮 A/B/C | — | — | — |
| N4 | 20261115-jesus-is-better | 流程 | `stage2 --with-english` 在封存后写英文对照，需补封后发布；把该顺序写进 runbook 或让其在封存前完成 | 复盘要点：封存后补写英文对照并补发布 | — | — | — |

## 前端

前端数值是私有运营资料，不进本页（[使用统计](../../../sermon-app-usage.zh.md)规定不提交 Git）。本周三份报表在私有证据库 `frontend/<周>/`，带前端数值的私有周汇总在 `weekly/<周>/`。审核人在此只写结论：

待填写。

## 采集缺口

- `20261109-local-tts-ab`：私有证据未上传。
- `20261112-web-modern-guidance`：不是导出器生成的（无 manifest），没有可比数值；复盘未填写；私有证据未上传。
- `20261114-deepseek-asr-ab`：不是导出器生成的（无 manifest），没有可比数值；复盘未填写；私有证据未上传。
- `20261114-deepseek-tts-speed`：私有证据未上传。
- `20261114-live-capture`：不是导出器生成的（无 manifest），没有可比数值；复盘未填写；私有证据未上传。
- `20261114-sfa-preproduction-rehearsal`：私有证据未上传。
- `20261114-subtitle-filler-shadow`：不是导出器生成的（无 manifest），没有可比数值；复盘未填写；私有证据未上传。
- `20261115-jesus-is-better`：不是导出器生成的（无 manifest），没有可比数值；复盘不是八项骨架，错误和改进没有进表。
- `20261115-jesus-is-better-podcast`：journal 里未收尾的阶段：l3.review.es、l3.review.ko、l3.review.zh-Hans、l4.publish。

## 证据边界

- 本页只汇总已入库的运行报告；不在仓库里的运行不在本页。
- 代码与测试、发布与 HTTP、浏览器渲染、设备播放、场地验收是分开的状态；本页的数值不证明后两者。
- 私有证据（译文、审核表、听审结论、反馈正文）在私有证据库，本页只引用计数和哈希。
