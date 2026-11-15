# 复盘：20261108-jesus-is-just-podcast

2026-11-08 播客「If I Had More Time · Jesus is just and will bring sin to its end」（Eric Geiger · Steve Bang Lee，启示录 15–16，50:08）的三语生产与正式发布。交付类型 `four_layer_release`，页面 `if-i-had-more-time-jesus-is-just`。

## 结论先行

- **最终状态**：正式站 `https://ai-for-god-sermon-audio.web.app` 页面 `if-i-had-more-time-jesus-is-just` 三语上线；托管版本 **`52626ab9d163a8cc`**（英文对照第三次部署）。`sfa_publish_gate` pass，`verify` 12/12，readback 三语 release + 英文对照通过，浏览器 smoke 三语 pass（`--no-session`）。
- **页面终态**：`defaultPageId` = 本页；标题 zh「如果我有更多时间 · 耶稣是公义的，必终结罪恶」/ ko「If I Had More Time · 예수님은 공의로우시며 죄를 끝내실 것입니다」/ es「If I Had More Time · Jesús es justo y pondrá fin al pecado」；类别「证道播客 / Sermon Podcast」；三语 `capabilities=[text,captions,audio]`，**没有 alignment**（用户明确要求不用音频对齐，播客页合同也不含听音定位）。
- **音轨**：zh 3080.77 s（51:21）、ko 3395.10 s（56:35）、es 3407.26 s（56:47）；MP3 61.6 / 67.9 / 68.1 MB，192 kb/s，独立音轨、自然语速、不跟视频钟。
- **审核**：英文来源表、讲员映射、整期窗口由用户 2026-11-08 13:06 PST 确认；三条整轨由用户 16:22 PST 确认听完通过（`reviewMode=whole_track`，收据 `artifacts/sentence-first-agent/20261108-jesus-is-just-podcast-review/human-review-verdict.json`）。译文经 Opus 独立保真审计（zh 3 / ko 1 / es 10 条），采纳 zh 2 / ko 1 / es 9 条并加 5 处源文修正的译文调整。
- **证据边界**：统计目录未同步（本机没有 `sermon-feedback-api` 仓库），`/api/session` 在本页音轨上报 400，所以浏览器 smoke 用 `--no-session`；真机、现场和海报 `not_run`；译文的独立审计是机器复核，不是逐句人工审校。

## 总时间

墙钟 **约 4 h 04 min**（2026-11-08 12:29 → 16:33 PST）。拆分：

| 阶段 | PST | 时长 | 性质 |
|---|---|---|---|
| 下载、OpenAI 两遍转写、OpenAI 说话人区分、句表 | 12:29–12:52 | 23 min | 计算 |
| 英文表人审（用户确认英文表/映射/窗口） | 12:52–13:06 | 14 min | 等待 |
| Opus 三语初译 + 独立审计 | 13:06–13:10 | 4 min | 计算（12+3 子代理并行） |
| Spark 三语配音（两讲员/语顺序 job） | 13:09–13:48 | 39 min | 计算（GPU 串行） |
| 三语合并、review MP3、播放器 | 13:22–13:50 | 6 min | 计算（与后续 TTS 重叠） |
| 用户整轨听审 | 13:50–16:22 | 2 h 32 min | 等待 |
| assets / 三次部署 / 核验 / gate / smoke | 16:23–16:33 | 10 min | 计算 |

计算约 **1 h 20 min**，等待约 **2 h 46 min**，返工约 **4 min**（gpt-4o 二遍一个坏块重跑、句界 0.005–0.04 s 重叠归一化、英文对照绑定 fallback）。

## 各层

| 层／阶段 | 模型或后端 | 调用 | 计算耗时 | 规模 | 费用 | 证据 |
|---|---|---|---|---|---|---|
| L1 ASR 词时间 | OpenAI `whisper-1` verbose_json | 1 | ≈2 min | 3008.23 s / 8351 词 / 855 segments | 未结算（脚本未落 usage 收据） | `layer1/raw-whisper.json`、`words.json` |
| L1 文本 | OpenAI `gpt-4o-transcribe` 240 s 分块 | 13 | ≈6 min | 8073 词，逐块词数 0.9–1.05×whisper | 未结算 | `layer1/raw-gpt-4o-transcribe.txt`、`gpt-4o-chunks.json` |
| L1 说话人区分 | OpenAI `gpt-4o-transcribe-diarize` + 8 s 讲员参考 | 3（1350/1350/318 s） | ≈21 min | 1200 segments；Eric 1988.1 s / Steve 742.6 s | 未结算 | `openai-asr/openai-diarize-raw.json` |
| L1 句表/映射 | 本机 Python + `assign_speakers.py --use-text` | 1 | <1 min | 883 句；Eric 573 / Steve 310；低置信度 21 | 0 | `layer1/anchor-manifest.json`、`english-review.csv` |
| L2 初译 | Claude CLI Opus 5.5 | 12 分片（3 语×4） | ≈4 min（4 并发） | 883 句/语 | 未结算（订阅额度；CLI 输出未落收据） | `translate/output-*.jsonl`、`translations.jsonl` |
| L2 独立审计 | Claude CLI Opus 5.5 | 3（1/语） | ≈70 s（3 并发） | 883 句/语 | 未结算 | `audit/audit-*.jsonl` |
| L3 配音 | Spark Qwen3-TTS 讲员 SFT：Eric `eric_pilot`、Steve `steve_bang_lee` | 6 job（3 语×2 讲员），batch 8 | zh 751 s、ko 813 s、es 约 800 s；合计约 39 min | 883 句/语 | 0（本地 GPU） | `tts/`、`tts-run.log`、`run.md` |
| L4 发布 | `sfa_publish.py` 单一驱动 | 3 次部署 | ≈10 min | 15 个资产 + 3 release + 3 目录 + 英文对照 | 0 | `stage1`/`stage2`/`stage-english2`、`publish-gate.json` |

OpenAI 与 Claude 的 token/金额收据本轮没有落盘（一次性脚本只写了 tail 日志）；报告不猜数。按同规模上期（477 句三语 Opus 约 $7.4）估算本轮三语 Opus 约 $12–14 等价，仅供参考，不是发票。

## 发布过程

1. `baseline`：`ec37b31db142688b`（424 文件）。
2. `stage1` → 部署资产 `0ee525db82fc0ca1`；`verify` 12/12（页面/文稿/字幕/MP3，MP3 Range 206）。
3. `stage2` → 部署 release + v5/v4/v3 目录 `017a911d3ab89dd3`；readback 三语 release 通过；`defaultPageId` 改为本页。
4. `baseline-english` → `stage-english-reference` → 部署 `/english-reference/if-i-had-more-time-jesus-is-just.json` `52626ab9d163a8cc`；三语各 883 blocks；readback 通过。
5. `sfa_publish_gate --page-id if-i-had-more-time-jesus-is-just` = pass（播客页无 alignment/guide，gate 不要求这两项）。
6. `smoke_published_page.py --no-session` 三语 pass；未跑 `/api/session`（统计目录未同步）。

## 问题、修复与教训

| # | 问题 | 影响 | 修复 | 教训 |
|---|---|---|---|---|
| 1 | `gpt-4o-transcribe` 第二遍 200 s 分块有一块只返回 6 词 | 文本缺 200 s | 重写分块脚本：240 s、重编码、逐块与 whisper 词数核对、最多 3 次重试、逐块缓存 | 分块转写必须逐块验收，不能只看总 token |
| 2 | OpenAI diarize 每块约 9.4 min | L1 等待约 21 min | 接受；逐块落 raw，未再切小 | 22.5 min 音频的 diarize 约 0.4× 实时，预算要按此算 |
| 3 | 句界有 19–20 处 5–40 ms 重叠 | `sfa_publish` 的 iOS cue 检查拒绝 | 归一化句表 start/end 到单调不重叠；重建英文包，未重配音频 | 发布前先跑 iOS `validateCues` 等价检查 |
| 4 | `sfa_publish.py` 把独立播客音轨 `apad -t window_end` 截到 3008.238 s | zh/ko/es 会被截掉 72/387/399 s | 新增 `independent_audio()` 分支：播客页且 `synchronization` 含「not on the source video clock」时不 pad/truncate；加测试 | 双钟页面必须显式保留完整配音 |
| 5 | 英文对照构建 `Transcript binding mismatch` | 第三次部署失败 | agent-built 英文包没在 manifest 头写 `mfaSegmentsSha256`；改为 manifest 缺失时回退到 package 的 `anchors.input.mfaSegmentsSha256`，保留双向哈希核对；测试通过 | 合同绑定的两个副本，允许其中一个缺失但不能放宽哈希 |
| 6 | 发布 gate `content.drift` 对独立播客音轨按 ±1 s 判 | gate 失败 | 新增 `content_clock()`：无 alignment 的播客页按 0.75–1.35× 比率；有 alignment 或非播客页仍按 ±1 s；加测试 | 11-01 复盘写的双钟规则没有进当前 checkout，需补回并测试 |
| 7 | 用户批准英文表后，交叉核对又修正 5 处同音/切词错误 | 英文来源与批准表不完全一致 | 记录 `english-corrections.json`，重建英文包；收据 note 明写 | 批准后改源文必须留 corrections 文件并在收据/报告披露 |
| 8 | 统计目录未同步 | 本页 `/api/session` 400，赞踩/收听统计缺失 | 本机无 `sermon-feedback-api` checkout；记为 gap | 播客发布也要把统计目录列入发布意图 |
| 9 | 公告 sidecar 无本页条目 | 无公告；播客无海报 | 本轮不交付（没有海报/推送要求） | 不把「无公告」写成发布失败 |

## 覆盖范围

- **L1**：执行（下载、whisper-1 词时间、gpt-4o 文本、OpenAI diarize、句表、讲员映射、人审英文表与窗口）。未执行 MFA。
- **L2**：执行（Opus 初译、独立 Opus 审计、spokenForms、build_speech）；机器审计不是人工逐句审校。
- **L3**：执行（三语两讲员 TTS、合并、review MP3、逐句播放器）；回转写 `not_run`（2026-10-28 退役）。
- **L4**：执行（三语页面/文稿/字幕/MP3、release v2、v5/v4/v3 目录、英文对照、gate、smoke）；对齐 sidecar `not_run`（用户要求）；统计目录未同步；海报/公告/推送 `not_run`。

## 遗留状态

- Spark 独占会话 `sfa-20261108-jesus-is-just-podcast` 已 `finish` 收尾，服务恢复；容器按会话结束清理。
- 本机产物、原始音频与 883×3 wav 全部在忽略的 `artifacts/`，不进 Git。
- 英文来源包、审核收据和页面配置的哈希绑定见 `layer1/english-source.json` 与 `publish/`。
- 统计目录、真机与现场验收、海报：`not_run`。
