# 复盘：20261101-jesus-marks-podcast

数据见同目录 `INDEX.md` 和 `manifest.json`。本轮是双人播客「If I Had More Time: Jesus Marks His Own」（Eric Geiger · Steve Bang Lee，启示录 14，57:53）的三语生产与发布。

## 结论先行

- **交付类型**：`four_layer_release`（双人播客，逐句优先代理路线）。
- **最终状态**：三语页面、文稿、字幕、MP3、release v2、v5/v4/v3 目录与英文对照全部上线；`sfa_publish_gate` **pass**；HTTP 核验 12/12。
- **结束信号**：三次部署 `5f1beed447648e8d`（资产）→ `bc30c3c3cb25f3ba`（release + 目录）→ `b608b9c0406b9d7f`（英文对照）；`outcome.json` 三语为 `track_ready_for_review`，随后人工批准并发布。
- **证据边界**（原样记录，不写成端到端通过）：
  - 听审是用户**按标记抽查**（`reviewMode=flagged_only`，中文 119、韩语 118、西语 127 句），不是逐字核对整轨；
  - **MFA 未跑**，词级时间来自本机 `mlx-whisper large-v3-turbo`（`timingBasis=asr_word_timestamps`）；
  - **英文机器评审未跑**，由人工审表代替；回转写（ASR）按 2026-10-28 政策退役，`not_run`；
  - **设备与现场验收 `not_run`**；统计目录未同步（本机没有 `sermon-feedback-api` 仓库）；公告侧车没有本页条目（缺海报）。

## 总时间

- **墙钟**：14:33 → 17:20 PDT，约 **2h47m**（含约 1h 用户听审与确认等待）。
- **计算**：L1 约 11 min（下载 2 min、whisper 分块 4 min、讲员区分 3.4 min、句表与预检 1 min）；L2 约 45 min（三语翻译与审计并行，含 ko 首版返工）；L3 约 57 min（GPU 46m53s + 中文收尾 10 min）；L4 约 12 min（三次部署与核验、gate 排障）。
- **等待**：约 1h（英文表/映射确认、三条整轨听审、发布授权）。
- **返工**：翻译三语各重跑一次（同步预算误判），约 25 min 与约 $3.6；OpenAI 三源对比另花 19.5 min（非必需交付，但补上了 whisper 漏字的证据）。
- **自动汇总为何偏小**：本轮只给 `l1.preflight`、`l3.finish`、`l3.review.*` 打了 journal，翻译/审核/队列阶段没有打点，所以导出工具算出“计算 1 分钟”。真实耗时以上面手工拆分和 `tts-queue.log` 的时间戳为准。
- **与上一轮同类运行（2026-10-26 jesus-wins 播客）比较**：单语 TTS 由 849 s 增至约 874–928 s（句数 890 → 940，句更短、每句开销占比更高）；本轮新增三源转写对比、发布 gate 排障与二维码卡片，合计约多 40 min。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | `mlx-whisper large-v3-turbo`（本机 Metal，8×480 s 分块、1 s 重叠） | temperature 0，贪心 | 8 块（重跑）+ 单遍首跑 | 241 s（重跑） | 3,472.7 s 音频 / 9,155 词 | 14.4× 实时 | $0（本机） | `whisper/source-chunked.json` |
| L1 讲员区分 | `pyannote/speaker-diarization-community-1`（本机 MPS） | 2 人约束 | 1 | 205.7 s | 3,472.7 s | 16.9× 实时 | $0 | `diarization/pyannote-community-1-raw.json` |
| L1 交叉验证（新增） | OpenAI `gpt-4o-transcribe-diarize` + Eric/Steve 各 8 s 声音参考 | diarized_json | 3 | 1,157 s | 3,472.7 s / 172,137 tokens（输入 64,117、输出 108,020） | 3.0× 实时 | 未结算（账单未核对） | `openai-asr/openai-diarize-raw.json` |
| L1 词级对齐（MFA） | not_run | — | — | — | — | — | — | `anchor-manifest.json` 的 `policy.timingBasis` |
| L1 英文机器评审 | not_run（人审代替） | — | — | — | — | — | — | `english-source-review.json` |
| L2 初译 | `deepseek-flash` | low | zh 350、ko 262、es 187 | zh 288 s、ko 967 s、es 466 s | 940 句/语 | — | zh $0.99、ko $1.74、es $0.91 | `coherence-ds/cost.json` |
| L2 独立审核 | `deepseek-flash` | high | 38/语（25 句窗口） | 见证据 | 940 句/语 | — | zh $0.31、ko $0.55、es $0.36 | `audit-cost.json` |
| 文本质检（回译） | 回译 not_run；`spoken_forms.py` + `consistency_check.py` | — | 3 | 秒级 | 940 句/语 | — | $0 | `review.json`、`speech.jsonl` |
| L3 配音（TTS） | Qwen3-TTS 讲员 SFT：Eric `eric_pilot`、Steve `steve_bang_lee`；Spark GB10，batch 8，seed 7 | — | 每语 2 个 job（按讲员） | zh 874 s、ko 887 s、es 928 s | 940 句/语；配音总长 zh 3,046 s、ko 3,131 s、es 3,208 s | 约 3.5× 实时 | $0（本机 GPU） | `tts/tts-log.jsonl`、`tts-queue.log` |
| L3 回转写筛查（ASR） | not_run（2026-10-28 退役） | — | — | — | — | — | — | — |
| 音频质检 | 机器 not_run；人工按标记抽查 | — | — | — | — | — | — | `human-review-verdict.json` |
| L4 构建与发布 | `sfa_publish.py` 单一驱动 | — | 3 次部署 | 约 12 min | 12 个新资产 + 3 份 release + 3 份目录 + 1 份英文对照 | — | $0 | `deployment-attempt-v2.json`、`http-verification.json`、gate JSON |

费用小结：可结算的模型费用 = 翻译 **$3.64**（最终一版；中文首版另有 $0.71 被重跑覆盖，es/ko 首版结算被覆盖、未知）+ 审核 **$1.22** = 约 **$4.9**；OpenAI 转写 172,137 tokens 未结算。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L1 ASR | 单遍 whisper 在 285 s、1058 s 各漏掉一段真实讲话（合计约 90 s） | 长音频解码漂移，未分块；首次跑完才发现空档 | 占用资源后（英文表已生成） | 改 8 分钟分块 + `condition_on_previous_text=False` 重跑，9155 词补齐；三源对比确认 OpenAI / YouTube 在这两段都有内容 | 三源 60 s 窗口无低一致度时段 | 本报告 |
| L1 句表 | `build_layer1_candidate.py` 报 “transcript has no words inside the window” | 自写分块脚本用 `text` 键，正式 builder 读 `word` 键 | 预检阶段（prepare 之前，未占 GPU） | 转换键名后重跑，940 单元 | anchor manifest 940 单元、preflight pass | 本报告 |
| L1 句表 | 8 个零长度单元 + s0786/s0787 重叠 0.02 s | whisper 单字单元与切句边界 | 发布前（assets 的 iOS `validateCues` 规则） | 零长单元延至 0.25–0.6 s；上一句 end 收到下一句 start−0.02；音频未动，track.wav 哈希与收据一致 | assets 940 cues 通过 | 本报告 |
| L2 翻译 | 三语首版各把 13 个短句判成“超预算失败”，不写 `translations.jsonl` | 同步预算（源秒 × cps）用在**非同步** run 上 | 占用资源后（首版翻译结束） | 用 relaxed 校验器重跑（提示词不变、缓存命中），失败 0；额外开销 zh $0.99、es $0.91、ko $1.74 | 940/940 译文、独立审核通过 | 本报告 |
| L2 翻译 | ko 首版在 repair 循环里跑了 29 分钟 | 同上；失败句按单句反复重试 | 运行时发现 | 中止并改 relaxed 重跑 | ko 940/940 | 本报告 |
| L3 队列 | `spark_queue --pool-replicas 8` 仍失败：`--steps must be exactly tts or asr` | `spark_session_job.py` 的白名单只有 `tts`/`asr`，而 `spark_run.sh` 已支持 `tts-pool`；连续第三周踩到 | 占用资源后（队列第一批即失败） | 回退按讲员分两个 job，未影响交付 | 三语 940/940 wav | 待开修复 PR |
| L4 发布 | 发布 gate 判三语 `content.drift` 失败（−6.44 / −4.35 / +88.42 s） | 规则假设音频时长 ≈ 原片窗口，与自然语速配音（iOS 的独立双钟模型）冲突；本周才加的 gate 没有覆盖播客形态 | 发布后（gate 在部署之后运行） | 改为：两钟接近（−0.1…1.1 s）按同步页严格检查；不一致时按独立双钟检查音轨在文稿时长的 0.75–1.35 倍；文档第 5 行同步更新 | 本页 gate pass；同步页（周 8 证道）其余检查通过，仅因 `defaultPageId` 已指向本页而失败 | 本次提交 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 成本／预检 | 非同步 run 一律 `--no-budget`，或把预算从缓存键里分离 | 三语各重跑一次，多花约 $3.6、25 min | 省一次全量重译 | 生产线 | 新增项（待登记） |
| 预检 | `spark_session_job` 接受 `tts-pool`，与 `spark_run.sh` 对齐 | 连续三周同一条错误 | 每期省一次失败与约一分钟 | 生产线 | 新增项（待登记） |
| 预检 | 自写转写脚本先用正式 builder 空跑一遍 | 键名错误到 prepare 前才暴露 | 少一次返工 | 生产线 | 本报告 |
| 质量 | 把“三源转写对比”固化为 L1 常规步骤 | 单遍 whisper 漏 90 s，靠 OpenAI/YouTube 才定位 | 早发现漏字 | 生产线 | 新增项（待登记） |
| 流程 | L1/L2 各阶段补 journal 打点 | 本轮自动汇总“计算 1 分钟”，严重低估 | 复盘时间线可信 | 生产线 | [`DEV-RUNREPORT-001`](../backlog.zh.md#backlog-run-report-20261008) |
| 质量 | 给 gate 的双钟规则补测试 | 本轮改了强制 gate 的规则，尚无单测 | 防回退 | 生产线 | 本次提交 |
| 成本 | OpenAI diarize 只在有争议时跑 | 与本地 whisper 一致度 96%，结论相同 | 每期省 19.5 min、未结算 token | 生产线 | 本报告 |

## 实际覆盖范围

- **L1**：执行（下载、whisper 分块转写、pyannote 区分、按换人切句、OpenAI 交叉验证、英文人工审表）；未执行 MFA 与英文机器评审。
- **L2**：执行（DeepSeek 初译、独立审核、spokenForms、一致性检查）；未执行回译质检（ASR 已退役）。
- **L3**：执行（双讲员 TTS 三语、合并、MP3、播放器、中文配音视频预览）；回转写 `not_run`。
- **L4**：执行（三语 page/content/captions/MP3、release v2、v5/v4/v3 目录、英文对照、gate）；学习大纲与默想 `not_run`；统计目录未同步；公告侧车无本页条目。

## 遗留状态

- **Spark 会话 `sfa-20261101-jesus-marks`**：本轮结束时执行 `finish` 收尾（恢复 llama-server 等服务）；三个 TTS 容器退出后未删除，随会话收尾清理。
- **本机 artifacts**：原始产物、模型输出与音频全部留在被忽略的 `artifacts/`，不进 Git；Spark 侧 `~/sentence-first-agent/20261101-jesus-marks-podcast-*` 保留 wav 与 speech。
- **未结束 job**：无。
- **报告 PR**：本文件所在 PR，只含文档。

## 外部可见的变化

- 正式站 `https://ai-for-god-sermon-audio.web.app` 新增播客页 `if-i-had-more-time-jesus-marks-his-own`（三语），v5/v4/v3 目录由 10 页增至 11 页，`defaultPageId` 改为本页。
- HTTP：三个页面 200、三份文稿 200、三份字幕 200、英文对照 200（三语各 940 blocks）、三条 MP3 `206` 且 `Content-Range` 正确（69.4 / 69.4 / 71.3 MB，192 kb/s）。
- **not_run**：iOS 真机刷新与播放、浏览器交互 smoke（只核了页面渲染）、统计目录同步（`sermon-feedback-api` 仓库不在本机）、公告侧车条目与海报（海报由用户独立 agent 出）。
