# 复盘：20261108-jesus-is-just

数据见同目录 INDEX.md 和 manifest.json。本轮后半段（现场对齐、统计目录、研读手册、海报）的产物都在被忽略的
`artifacts/`，没有进这份 digest（导出器 2 MB 上限只收了 zh run），这里按实际执行写。

## 结论先行

- **交付类型**：`four_layer_release`（三语页面 + 英文对照 + 现场声音对齐 + 研读手册 + 统计目录 + 三语海报）。
- **最终状态**：已发布并核验。`sfa_publish_gate --require-guide --require-alignment` = pass；
  页面、release、目录、英文对照、对齐 sidecar/索引、手册清单、`/api/session` 三语全部 200。
- **但首轮的完成信号是错的。** 这是一次标准周日证道生产，页面、英文对照、三语配音都发出去之后，
  我跑了一次**不带** `--require-guide --require-alignment` 的 gate，它返回 pass，我就当成收尾了。
  实际上漏掉三件同一发布意图内的产物：**现场声音对齐、研读手册、统计目录**；
  用户在 21:50 之后逐项追问，才在 22:00–22:15 补齐。海报也是完成后才知道要做、并从「雨后街区」改了两版。
- **证据边界**：真机 iPhone 麦克风、设备输入延迟、场地实测、二维码真机扫码与印刷都未验证；
  研读手册是机器译稿 `humanApproval=false`；海报只有机器目视检查（`humanApproval=false`）。

## 总时间

墙钟约 **2h57m**（19:38 下载完成 → 22:35 海报第三版收稿）。

| 阶段 | 时段 | 时长 | 性质 |
|---|---|---|---|
| 下载 + 两遍 OpenAI 转写 + 句表修订 + 英文审核 | 19:38–20:02 | 24m | 计算 + 人审等待 |
| 三语 Opus 翻译 + 独立审计 + 修订 | 20:02–20:12 | 10m | 计算 |
| Spark 首轮 TTS（三语） | 20:14–20:38 | 24m | 计算 |
| 滞后修复：三语精简 + 全量重配 | 20:38–21:16 | 38m | **返工** |
| 人工整轨听审 | 21:16–21:20 | 4m | 等待（人） |
| 发布与英文对照（13 次托管部署里的大部分） | 21:20–21:48 | 28m | **返工** |
| 现场对齐 + 统计目录 + 研读手册 | 21:50–22:15 | 25m | **补漏** |
| 海报三版 | 22:15–22:35 | 20m | 交付（换方向） |

journal 只记了 zh run 的 1h27m／计算 3m17s，**严重低估**：发布阶段的部署与返工没有走 `run_journal`，
这也是本轮要改的地方。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR（词级时间） | OpenAI `whisper-1` verbose_json | — | 1 | 1m26s | 2147 s 音频 | — | ≈$0.22 | `layer1/raw-whisper.json` |
| L1 转写文本（第二遍） | OpenAI `gpt-4o-transcribe` | — | 9（240 s 分段） | 3m | 2147 s 音频 | — | ≈$0.22 | `layer1/raw-gpt-4o-transcribe.txt` |
| L1 词级对齐（MFA） | not_run | — | 0 | — | — | — | 0 | 用 whisper 词时间替代 |
| L1 英文机器评审 | not_run | — | 0 | — | — | — | 0 | 用户直接审 460 行 CSV |
| L2 初译 | Claude CLI Opus | — | 12 分片 | ≈10m | 460 句 ×3 语 | — | 订阅内，未计费 | `translate/output-*.jsonl` |
| L2 独立审核 | Claude CLI Opus | — | 3 | 46–69 s | 1380 句 | — | 订阅内 | `audit/audit-*.jsonl` |
| L2 同步精简 | Claude CLI Opus | — | 10 | ≈15m | zh 165／ko 269／es 235 句 | — | 订阅内 | `trim/trim-*.jsonl` |
| 文本质检（回译） | not_run（ASR 链已于 2026-10-28 退役） | — | 0 | — | — | — | 0 | — |
| L3 配音（TTS） | Spark Qwen3-TTS，Eric checkpoint，batch 8 | — | 2 轮 × 3 语 | 24m + 22m | 2×1380 句 | 5.03× 实时（zh） | 本地 GPU | `tts/tts-log.jsonl` |
| L3 回转写筛查 | not_run（已退役） | — | 0 | — | — | — | 0 | — |
| 音频质检 | 人工整轨 1× 听审（用户） | — | 3 轨 | — | 3 × 35:44 | — | — | `human-review-verdict.json` |
| L4 构建与发布 | sfa_publish / guarded publisher | — | **13 次托管部署** | ≈28m | — | — | 0 | 部署版本见 run.md |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L4 发布范围 | 首轮只发页面/英文对照，漏掉现场对齐、研读手册、统计目录 | 把 `sfa_publish` 的子命令清单当成完整发布意图；`docs/sentence-first-agent-publish-gate.zh.md`（2026-11-01 起强制）是部署之后才读的 | **发布后（用户指出）** | 补三项并重跑 gate | `--require-guide --require-alignment` | — |
| L4 完成信号 | 首次 gate 返回 pass 就当成收尾 | gate 的 guide/alignment 两个检查是可选开关，默认不查 | 发布后 | 以后周日证道固定带两个开关 | — | — |
| L4 部署粒度 | 一个页面 **13 次**托管部署，远超「一次发布意图 ≤3 次」 | 发布意图没有在首次部署前列全，导致英文身份、音轨补齐两次返工各走 replace 通道（每次 2 部署） | 发布后 | 无（已发生） | — | — |
| L1 英文包 | 包缺 `approvedWindow.evidence`、`transcript.artifact`、`review.evidence`，英文对照无法构建 | 自建包只满足 `preflight.py` 的宽松检查，没按发布合同校验 | **占用资源后（首次部署后）** | 补证据绑定、重建资产、走 replace 通道 | 应加 `build_reference` 干跑 | — |
| L4 目录身份 | catalog `sourceIdentitySha256` 停在首版包 | replace 通道只重绑 release，不重绑身份 | 发布后 | 手写 v5 并投影 v4/v3 | — | — |
| L4 门禁 | `content.drift` 失败，音轨比窗口短 2.5–4.2 s | 精简后整轨变短，assets 不补齐窗口 | 发布后（gate 发现） | assets 用 `apad` 补齐到窗口终点 | gate 复跑 pass | 已提交 `fa8f6ecc` |
| L3 滞后 | 首版整轨滞后 zh 18.8 s／ko 214.6 s／es 117.0 s | 译文逐句略长叠加；韩语天然比英文长 1.21× | 占用资源后（首次 finish_run） | Opus 精简 + 全量重配 | `lag-loop-report` gate clean | — |
| L3 数字读法 | 千分位被拆成裸 `000`：`삼,영년`、`tres.cero años` | `spoken_forms` 短键先匹配，`3,000`/`3.000` 没在表里 | 预检（合成前） | 补 `3,000→삼천` 等并前置 | `spokenTextWithDigits=0` | — |
| 研读手册 | 工具里第 9 周标题「必使罪恶终结」与标题表「必终结罪恶」不一致，bind 会拒 | 常量没随标题表更新 | 预检（bind 前） | 改常量后重 stage | week-08 字节不变 | `b1180124` |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 开跑前先写「发布意图清单」七件套（页面/release/目录/英文对照/对齐/手册/统计目录），写进 run.md 再动手 | 首轮漏 3 件，用户追问才补 | 一次列全，避免补漏 25m | 主代理 | 待开 backlog |
| 流程 | 周日证道收尾只认 `--require-guide --require-alignment` 的 gate；不带开关的 pass 不算完成 | 首次 gate 的假 pass | 消除假完成信号 | 主代理 | 同上 |
| 预检 | 英文包在首次部署前跑一次 `published_english_reference.build_reference` 干跑（对候选快照） | 首次部署后才发现包缺证据绑定，多走 4 次 replace | 省 2 次返工部署 | 主代理 | 待开 backlog |
| 预检 | 候选快照阶段先跑一次 gate（文档已要求三处都跑），再首次部署 | 音轨补齐问题是线上 gate 才发现的 | 部署前挡住 drift | 主代理 | 同上 |
| 速度／成本 | 精简后先在本地用 `lag_loop --check-only` 估收敛，再一次全量重配 | 三语各做了一轮全量重渲（22m） | 省一次全量 TTS | 主代理 | — |
| 质量 | 对齐索引绑定**已发布 MP3** 的 sha，不是 `track.wav` | `Invalid fingerprint binding` 一次 | 少一次重建 | 主代理 | run.md 已记 |
| 流程 | 研读手册标题、页面标题、海报标题统一从 `docs/series-sermon-titles.zh.md` 取；工具常量随表更新 | 手册标题不一致一次 | 消除 bind 失败 | 主代理 | `b1180124` |
| 可观测 | 发布阶段的部署与返工也走 `run_journal`，否则 timings 只有 3m17s | journal 1h27m vs 实际 2h57m | 复盘数据可信 | 主代理 | `DEV-SF-007` |

## 实际覆盖范围

- **L1**：执行，但走的是代理直做路径——OpenAI 两遍转写 + 自建英文来源包（含证据绑定），没有 MFA、没有英文机器评审；英文表由用户人工批准。
- **L2**：执行，Claude CLI Opus 逐句翻译，独立 Opus 保真审计，同步精简。没有 DeepSeek 连贯翻译，也没有 `audit_deepseek`。
- **L3**：执行，Spark Qwen3-TTS batch 8 全量重配；人工整轨听审通过；无回转写、无机器听审。
- **L4**：执行并部署——页面/文稿/字幕/MP3、release v2、三语目录 v5/v4/v3、英文对照、对齐 sidecar + 三语指纹索引、`weekly-guides` 清单与资源、统计目录（函数重部署）、三语海报。

## 遗留状态

- 托管部署 13 次，快照都留在忽略的 `artifacts/sentence-first-agent/20261108-jesus-is-just-publish/` 下（`stage1`、`stage2`、`replace-A..B5`、`stage-english5`、`alignment-A`、`baseline*`）。
- 作废海报两版保留：`artifacts/sermon-poster/2026-11-08/`（雨后街区）、`…-rev2/`（殿门的光）；当前方向是 `…-rev3/`（成了之后的静），尚未定稿。
- 研读手册重 stage 的 v1 只在本地（`artifacts/weekly-guide-staging/v1-week09/`），GCS 上的原始 staging 仍是旧标题；后续周次沿用已提交的常量即可。
- 统计函数部署源在 `artifacts/sentence-first-agent/20261108-feedback/`（本地），线上 `updateTime 2026-11-08T06:01Z`。
- 本报告 PR #1550 待填完复盘后合并；页面与旁路绑定的后续变化需另开发布意图。
