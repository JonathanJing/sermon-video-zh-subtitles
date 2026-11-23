# 复盘：20261122-jesus-will-return-podcast（第 12 周双人播客《耶稣必再来》）

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

- **交付类型**：`four_layer_release` 的播客页（`mediaType=podcast`，类别「证道播客」），三语 zh-Hans / ko / es。
- **最终状态**：正式站 `https://ai-for-god-sermon-audio.web.app` 页面 `if-i-had-more-time-jesus-will-return` 三语上线。三次部署：assets `315f5a1cd18559ac`、release 与目录 `28e0fbc77460ac87`、英文对照 `fd3f2e169a0bc6f7`；`readback` 7/7 通过，`sfa_publish_gate` = pass（failed 空），三语页面/文稿/字幕/MP3 与英文对照 smoke 全部 200，MP3 Range 206。
- **音轨**：独立音轨、自然语速、不跟视频钟；zh 2365.3 s（39:25）、ko 2570.1 s（42:50）、es 2521.5 s（42:02）；MP3 192 kb/s，47.3 / 51.4 / 50.4 MB。
- **审核**：英文表与整期窗口由用户 2026-11-22 14:39 在对话中批准（`reviewedAt=2026-11-22T14:39:32-0800`）。中文整轨交用户听审；用户 2026-11-22 15:00 明确选择「不等韩/西试听，按提前授权直接发布」。审核收据 `human-review-verdict.json` 绑定三条 `track.wav`、`review.mp3` 的 SHA-256，并在 `note`、`listenedLocales`、`advancedAuthorizationLocales`、`localeReview` 中写清范围。页面中文徽章「已人工审核」；韩/西徽章改为「사용자 승인 배포 / Publicación autorizada」，备注写明未做整轨试听。
- **证据边界**：翻译为 Opus 初译 + 独立 Opus 保真审计（机器复核），不是逐句人工审校；韩/西音频未整轨试听；无现场对齐 sidecar、无研读手册（播客页合同不含）；统计目录未同步、真机与推送 `not_run`。

## 总时间

墙钟 **13:38–16:26 PDT（约 2 小时 48 分）**，大致拆分：

| 阶段 | 时间 | 性质 |
|---|---|---|
| 下载、whisper、gpt-4o、说话人区分、句表、英文修订 | 13:38–14:03 | 计算（约 25 分） |
| 英文表审核等待 + 同期的三语 Opus 翻译与审计 | 14:03–14:39 | 等待（用户）与计算重叠 |
| 中文 TTS（双路）+ 合并 | 14:35–14:58 | 计算与等待（约 23 分）；期间一次内存事件 |
| 韩语 TTS（先 Eric 单路、后 John 单路） | 14:58–15:34 | 约 36 分 |
| 西语 TTS（Eric 单路、John 单路） | 15:34–16:08 | 约 34 分 |
| 收据、preflight、assets、三次部署、gate、smoke | 16:08–16:26 | 约 18 分 |
| 返工 | — | 韩语 `1,000년` 读法、英文 20 处修订、内存事件（约 10 分） |

计算约 1 小时 50 分，人工等待约 20 分，返工约 10 分；其余为渲染串行时间。上一轮同类运行（2026-11-15 播客）墙钟约 7 小时 25 分，其中用户听审 6 小时 09 分。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|
| L1 词时间 | OpenAI `whisper-1` verbose_json | 1 | 111 s | 6507 词 / 549 段 / 2231 s | ≈20× 实时 | ≈ $0.22（估算） | `layer1/raw-whisper.json` |
| L1 文本第二遍 | OpenAI `gpt-4o-transcribe` 240 s 分块 | 10 | ≈110 s | 6535 词 | — | ≈ $0.22（估算） | `layer1/gpt-4o-chunks.json` |
| L1 说话人区分 | OpenAI `gpt-4o-transcribe-diarize`（Eric/John 已知参考） | 3（300 s + 2×1355 s） | 94 + 429 + 290 s | 943 段 | 0.29× 实时 | 未结算 | `openai-asr/openai-diarize-raw.json` |
| L1 句表与修订 | 本机对齐 + 人工 | — | <10 min | 493 句，20 处修订，1 处按换人拆句 | — | 0 | `sentences.jsonl`、`layer1/english-corrections.json` |
| L2 初译 | Claude Code CLI `opus`（2.1.330，claude.ai 订阅） | 12 分片 | zh 160 s / ko 193 s / es 145 s | 493 句 × 3 语 | — | 订阅额度，未结算 | `translate/dispatch-*.json` |
| L2 独立审计 | Opus 只读 | 3 | 86 / 87 / 74 s | zh 2 / ko 7 / es 4 条问题，全部采纳 | — | 订阅额度，未结算 | `audit/audit-*.jsonl` |
| L2 一致性检查 | `consistency_check.py` | 3 | <5 s | ko 称呼 share 0.875、numbers 由 spokenForms 覆盖 | — | 0 | `journal.ndjson` |
| L3 配音 | Qwen3-TTS 12Hz 1.7B Base，MBP16 MPS/float32 batch 8 | 6 条渲染（3 语 × 2 讲员） | zh 2131 s（双路）；ko 1919 s；es 1879 s | 2365 / 2570 / 2522 s 音频 | 1.05–1.27× 实时 | 0（本机 GPU） | `tts/tts-log.jsonl`、`tts-batches.jsonl` |
| L4 构建与发布 | `sfa_publish` + Hosting REST 增量发布 | 3 次部署 | 22 s 构建 + 10.6 / 1.7 / 1.6 分部署 | 13 + 6 + 1 个文件 | — | 0 | `stage*/incremental-publish.json` |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L1 | 开场丢词（"to the"/"I'm"）、"Lon John"、"Stutzer"、"all millennials"、"Amuletist" 等同音错误 | 冷开场与 ASR 听错 | 预检（人工读句表） | 20 处修订 + 开场 12.0 s 按换人拆句 | 英文表由用户批准 | 本轮 `run.md`、`layer1/english-corrections.json` |
| L1 | 句表初版出现重叠时间，切片失败 | whisper 单字单元 start==end 与插值 | 占用资源前（切片命令立即报错） | 句界强制单调、非重叠后重切 | `slice_sentences` 493/493 | 本轮 `l1_asr.py` |
| L2 | 韩语口播把 `1,000년` 读成「일,영년」 | `spoken_forms.py` 把 "1,000" 拆成 "000" | 渲染前（build_speech 输出检查） | 增加 `1,000→천` 并重建 speech | `spokenTextWithDigits` 为空 | 待登记 |
| L2 | 西班牙语混入西班牙半岛用语（`hacer mates`、`Vale`） | 模型方言漂移 | 审计（合并后） | 采纳审计建议统一为拉美用语 | `consistency_check` pass | 本轮 `review.json` |
| L3 | 双路加载把宿主可用内存压到约 0.3 MB、swap 4.1/5.1 GB | 在 zh Eric 仍在运行时加载 ko John（第三个模型峰值） | 占用资源后 | 立即停止 ko John；zh Eric 存活完成；改为一次只跑一路 | 后续 4 条渲染单路完成 | 本轮 `run.md` |
| L4 | `preflight` 报英文标题在标题表匹配 0 行 | `titleCheck.seriesKey` 误填 `if-i-had-more-time`（标题表按证道系列分节） | 发布前（预检） | 改为 `revelation-comfort-and-hope` | `preflight` pass | 本轮 `pages/...json` |
| L4 | 私有证据上传失败：GCS bundle 路径与 2026-11-21 的 MBP14 记录冲突 | evidence store 的 bundle 路径按 layer1 固定 | 发布后（自动导出） | 报告已生成本地版本；私有证据未上传，记入遗留状态 | — | 待重推 |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 双讲员本机渲染前按「可用内存 ≥ 30 GiB 才允许第二路」硬门，或直接固定单路 | 14:48 内存事件 | 避免 swap 抖动与重跑 | 本地模型开发者 | 新增 |
| 工具 | `spoken_forms.py` 处理千分位数字（`1,000` 不拆成 `1`+`000`） | 韩语口播返工 | 每期少一次 speech 重建 | 工具维护 | 新增 |
| 质量 | 双人播客的说话人归属抽检加入对话逻辑核对（谁问谁答），不只按区分票 | 译者与审计都指出 s0183/s0198/s0464 附近可疑；本轮按提前授权未逐句听审 | 减少错配声音 | 生产代理 | 新增 |
| 流程 | 播客页也用固定发布清单（含英文对照），并把统计目录与公告 sidecar 标为可选 | 11-15 复盘同项；本轮统计目录未同步 | 发布后少一处人工补 | 生产代理 | `DEV-USAGE-001` |
| 发布 | 私有证据 store 的 bundle 路径加运行身份（日期+runId），避免跨机撞名 | 本轮上传失败 | 云端复盘可读私有证据 | 工具维护 | 新增 |

## 实际覆盖范围

- **L1**：执行（下载、whisper 词时间、gpt-4o 文本、gpt-4o 说话人区分、句表与人工修订、用户英文/窗口批准）。未执行 MFA 与正式 Layer 1 机器裁判。
- **L2**：执行（三语 Opus 初译、独立 Opus 审计、口播读法、一致性检查）。机器审计不是逐句人工审校。
- **L3**：执行（三语双讲员本机 TTS、合并、review MP3、逐句播放器、审核收据）。中文整轨用户听审；韩/西按提前授权发布。未执行回转写（2026-10-28 退役）。
- **L4**：执行（页面/文稿/字幕/MP3、release v2、v5/v4/v3 目录、英文对照、gate、smoke）。对齐 sidecar 与研读手册 `not_run`（播客页合同不含）；统计目录与推送 `not_run`。

## 遗留状态

- 私有证据上传失败（见错误表）；`private-evidence.json` 记录了所需的 store URI。
- 统计目录（`sermon-feedback-api` 的 `catalog.json`）未同步本页三条音轨；`/api/session` 未验证。
- 海报 final 已渲染并双二维码校验（`artifacts/sermon-poster/2026-11-22-podcast-zh/`），状态 `draft_shown_not_uploaded`，未上传、未外发。
- 本机 `artifacts/` 内 493×3 WAV、track、MP3、快照保持忽略，不进 Git。
- 未做真机 App 播放验收、物理扫码、印刷与 TestFlight 推送（`not_run`）。

## 外部可见的变化

- 正式页三语上线：`https://ai-for-god-sermon-audio.web.app/pages/if-i-had-more-time-jesus-will-return/{zh-Hans,ko,es}/index.html`。
- `/english-reference/if-i-had-more-time-jesus-will-return.json` 上线（每语 493 blocks），`readback` 通过。
- 目录 v5/v4/v3 已含本页；`defaultPageId` 仍为周日证道 `revelation-jesus-will-return-20261122`（播客不抢默认页）。
- 部署版本：`315f5a1cd18559ac` → `28e0fbc77460ac87` → `fd3f2e169a0bc6f7`。
- 本报告以 docs-only PR 发布到 `docs/reports/runs/20261122-jesus-will-return-podcast-r2/`。
