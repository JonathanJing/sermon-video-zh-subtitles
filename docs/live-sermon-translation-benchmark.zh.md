# 证道实时翻译 Benchmark 与 A/B Test 设计

更新日期：2026-09-03
状态：Benchmark Sol-reviewed Reference 与选择性音频后审计已完成并验证，A/B 基础设施测试已开始

## 0. Goal：`BENCH-LIVE-ST-V1`

**目标**：使用 5 篇从未进入训练集的 Mariners Church 完整公开证道，建立第一版冻结 Benchmark；以 **MacBook Pro M1 Max、64 GB 统一内存**为主要部署与性能目标，以 `gpt-5.6-sol`、`reasoning.effort=high` 为主要裁判，衡量“流式 ASR + 后训练翻译模型”相对于基础模型和直接 AST 的证道翻译质量与端到端速度。

**当前状态**：`macbook_first_translation_only_run_completed_replay_pending`。已经完成 5 篇、239 个语义段的 Terra High 中文初稿与 Sol High 全量审核，共保存 86 份调用 receipt，0 篇失败。教师前音频预审覆盖 11 段、6.119 分钟；教师后按 Sol/Terra 风险与稳定抽样覆盖 80 段、58.329 分钟，80 段音频证据均支持当前英文字幕。5 份完整音频均通过 `ffprobe` 解码/时长核验。Reference 仍称为 `sol_reviewed`，没有声称人工 Gold；5%–10% 人工校准尚未完成。MacBook Ollama/MLX 文本 Benchmark 的数据复用协议、运行 harness、独立评分器和资源采样器已经建立；`Hy-MT2-1.8B Q8_0` 已通过 Ollama 0.33.3 完成首个 239/239 MacBook translation-only run，进程树峰值 RSS 6.441 GiB、swap 增量 0、106.252 tok/s。ASR 共存、1.0× replay、50–60 分钟 soak、Sol High 语义/严重错误评分和 A1–A3 尚未执行。

### 0.1 主部署目标与结果层级

第一优先目标机器固定为 `MacBook Pro / Apple M1 Max / 64 GB unified memory`，机器可读配置见 `data/benchmarks/live-sermon-translation-v1/macbook-m1-max-64gb-profile.json`。Benchmark 采用两层结果：

1. **MacBook 主榜**：决定模型是否可进入 A0–A3、实时 replay、shadow test 和生产候选排序。模型必须在目标 MacBook 上完成加载、239 段翻译、ASR 共存 replay 和 50–60 分钟 soak。
2. **DGX/其他硬件参考榜**：可用于质量预筛、架构兼容性研究和理论上界，但速度、峰值内存、RTF 与可部署性不得迁移到 MacBook 主榜。

模型即使在 DGX 上质量更高，只要不能在 M1 Max 64 GB 上稳定加载并与 ASR、字幕客户端共存，就不属于本项目的优先翻译候选。反之，能够在 MacBook 上稳定实时运行的较小模型应优先完成全量质量审核与后训练实验。

**不改变的边界**：

- 不从现有 train/dev 集移除样本；
- 5 篇 Benchmark 证道持续保持 `split=test`、`untouched_test` 和禁止训练；
- 不把 Benchmark reference、Sol 审核结果或模型预测回流训练集；
- 不在 manifest、日志或 Git 中写入 API key 值；
- 付费 API 和共享 Codex 调用必须由执行命令的独立确认开关授权；本 Goal 不自动执行现场发布。

**完成条件**：

1. 5 篇视频的输入、字幕、reference 和授权状态均有可追溯 manifest；
2. 每篇都有冻结的英文 reference、Sol-reviewed 中文 reference 和风险标签；
3. 基础学生模型 A0 的质量与速度基线已经保存；
4. 在 MacBook 主目标上至少完成 A0/A1/A2/A3 与一个可在该设备运行的直接 AST 或级联基线的同输入比较；
5. Sol High 全量盲审、5%–10% 人工校准和严重错误清单完成；
6. 生成质量、TTSC、finalization、churn、RTF、成本和路线建议报告；
7. 所有结论能回溯到固定输入哈希、模型版本、prompt hash 和事件日志。

## 1. 目的

本方案用于验证：在周日证道现场，采用“流式 ASR + 领域后训练翻译模型 + 周六预备材料”的级联路线，能否在以下两方面达到或超过市面上的直接语音翻译方案：

1. **证道翻译质量**：经文、神学术语、讲员原意、即兴内容和中文可读性。
2. **实时体验**：从讲员开始说话到首个稳定中文字幕、句末定稿、字幕回改和长时间运行稳定性。

Benchmark 不只比较最终译文，也比较会众实际看到的整个流式过程。测试结果将用于：

- 决定实时生产主链路和 fallback；
- 衡量后训练、术语表和周六材料分别贡献了多少；
- 为 iOS/Web 会众端设定可验证的延迟与质量 SLA；
- 形成后续论文所需的实验、消融、误差分析和现场研究框架。

## 2. 核心研究问题

### RQ1：后训练是否有效

在相同 ASR、切句、上下文窗口和推理参数下，领域后训练学生模型是否显著优于未经后训练的同一基础模型？

### RQ2：周六材料是否有效且安全

加入周六大纲、预提取证道稿、圣经文本和术语表后，是否能提高经文和术语准确率，同时避免把周六内容错误复制到周日不同的讲述中？

### RQ3：级联路线能否达到实时要求

ASR 与翻译串联增加的延迟，能否通过流式 ASR、增量翻译、缓存和小模型推理控制在会众可接受范围内？

### RQ4：与直接语音翻译相比是否值得

我们的级联系统相对于 NVIDIA Canary/Riva、Meta SeamlessStreaming、Azure Speech Translation 等直接或产品化语音翻译基线，在质量、速度、稳定性、成本和可控性上是否具有综合优势？

## 3. 待验证假设

| 编号 | 假设 | 主要证据 |
|---|---|---|
| H1 | 后训练模型显著减少经文、神学术语和教会专名错误 | 术语准确率、关键错误率、盲审胜率 |
| H2 | 周六材料主要改善同主题内容，但不会压过周日真实音频 | 偏离场景准确率、错误复制率 |
| H3 | 小型后训练模型可以在 M1 Max 64 GB 上与 ASR、字幕客户端共存并保持 `RTF < 1` | RTF、吞吐、统一内存峰值、memory pressure、swap、p95 延迟 |
| H4 | 级联系统最终质量优于直接 AST，同时首个稳定字幕保持在约 2–3 秒级 | TTSC、COMET、Sol High 主评分、严重错误率 |
| H5 | 字幕稳定性比“更早但频繁回改的首字”更影响会众体验 | 回改率、阅读中断次数、会众问卷 |

## 4. 被测系统

### 4.1 必测实验组

| ID | 系统 | 目的 |
|---|---|---|
| A0 | 流式 ASR → 基础学生模型翻译 | 未后训练对照组 |
| A1 | 流式 ASR → 后训练学生模型翻译 | 测量领域后训练的净收益 |
| A2 | 流式 ASR → 后训练模型 + 圣经/术语检索 | 测量稳定领域知识的收益 |
| A3 | 流式 ASR → 后训练模型 + 圣经/术语检索 + 周六材料 | 测量周六预备内容的收益与风险 |

A0–A3 必须使用相同的 ASR 输出、音频切分、解码策略和硬件配置。第一轮主榜硬件固定为 MacBook Pro M1 Max 64 GB；只有被研究的变量可以变化。既有 DGX A0 是历史研究基线，不能代替 MacBook A0。

### 4.2 外部基线

| ID | 系统 | 类型 | 备注 |
|---|---|---|---|
| B0 | NVIDIA Canary AST / Riva S2T | 直接 AST 或 NVIDIA 流式管线 | 支持英文到普通话；适合作为 NVIDIA 本地路线基线 |
| B1 | Meta SeamlessStreaming / SeamlessM4T v2 | 多语种端到端语音翻译 | 中文在支持范围；许可证和生产适用性需单独检查 |
| B2 | Azure Speech Translation | 商业云端实时语音翻译 | 作为成熟托管服务基线 |
| B3 | Qwen Omni 系列 | 通用音频多模态模型 | 探索组；先验证是否能稳定连续输出字幕 |
| B4 | Tencent Hy-MT2-1.8B | 专用文本翻译模型 | DGX Spark Q8_0 外部基线；使用模型原生 prompt/采样，非 A0 成员 |
| B5 | Hy-MT2-30B-A3B Heretic | 社区安全去对齐派生文本翻译模型 | DGX Spark 第三方 Q8_0 研究基线；与 B4 固定相同 prompt/采样；不得视为腾讯官方 30B 成绩或生产候选 |

外部模型版本、服务区域、API 版本、调用日期和价格必须写入每次 run manifest，不能只记录产品名称。

外部模型进入质量全审前先过 MacBook 可运行性筛选。只有 DGX 运行证据的系统保留在参考榜；没有 MacBook 完整 run manifest 的系统不得进入主榜综合排名。

## 5. 总体实验结构

```text
                 固定英语证道音频
                         │
          ┌──────────────┴──────────────┐
          │                             │
    固定流式 ASR 输出               直接语音翻译
          │                             │
   ┌──────┼──────┬──────┐        B0 / B1 / B2 / B3
   │      │      │      │
  A0     A1     A2     A3
   │      │      │      │
   └──────┴──────┴──────┴──────────────┐
                                       │
                    时间戳事件日志 + 最终字幕
                                       │
                 自动指标 + Sol High 盲审 + 轻量人工校准
                                       │
                           质量/延迟/成本决策报告
```

所有系统必须接收同一份音频波形。离线 replay 应按原始时间播放，不能让某个系统读取完整后文；否则不能称为实时 benchmark。

## 6. Benchmark 数据集

### 6.1 数据层次

建议建立三个互相隔离的数据层：

1. **开发集**：2–4 小时，可反复用于调试流式切句、提示词和延迟参数。
2. **锁定测试集**：建议 10–20 篇完整证道、合计 8–15 小时；一旦锁定，不再用于训练或提示词调优。
3. **现场 shadow 集**：连续 2–4 个周日，只记录系统输出，不直接替代生产字幕。

已有训练语料不能自动成为测试集。划分必须以完整证道为单位，避免同一篇证道的不同片段同时进入训练集和测试集。

### 6.2 防止数据泄漏

- 按视频/证道 ID 做 group split，而不是随机切 segment。
- 尽可能保留不同日期、系列、讲员和经文范围作为未见测试。
- 若周六材料本来就属于该周日的允许输入，应登记为 `prepared_context`，不能混入参考译文。
- 圣经全文可以作为允许的外部知识，但需要单独报告“启用圣经检索”和“未启用”的结果。
- 教师模型生成的数据不得作为同一测试样本的 gold reference。

### 6.3 每个样本需要的内容

| 字段 | 说明 |
|---|---|
| `sermon_id` | 稳定证道标识 |
| `audio` | 获得授权的原始或标准化音频 |
| `english_reference` | 字幕/ASR 交叉核对并经 Sol High 审核的英文原文 |
| `chinese_reference` | 经 Sol High 审核的中文参考译文及校准状态 |
| `scripture_refs` | 经文书卷、章、节和显式/隐式引用 |
| `terms` | 神学术语、人名、地名、教会项目名 |
| `prepared_context` | 当周允许使用的周六材料 |
| `deviation_labels` | 周日相对周六稿的新增、删减、改述、换序 |
| `audio_conditions` | 噪音、混响、口音、停顿、串音等标签 |

### 6.4 压力测试

除真实历史证道外，还应建立受控压力测试：

- 周六稿有一段，但周日完全没有讲；
- 周日新增周六稿不存在的见证或例子；
- 经文顺序改变；
- 同一经文采用意译而非逐字引用；
- 包含否定、反问、纠正和讲员自我修正；
- 教会专名与普通英文词发音相似；
- 麦克风过远、混响、掌声、音乐和多人短暂串音。

这些测试重点测量 `prepared_context_copy_error`：系统是否因为过度相信周六材料而输出讲员没有说过的内容。

### 6.5 第一版冻结 Benchmark 清单

机器可读清单位于：

`data/benchmarks/live-sermon-translation-v1/benchmark-manifest.json`

| 视频 ID | 证道 | 讲员 | 时长 | 选择理由 |
|---|---|---|---:|---|
| `hoeJTwl-EJg` | When I am anxious | Eric Geiger | 33:31 | 最近的已见讲员新证道，适合测量同讲员泛化 |
| `hAWaaBVaMzY` | What Matters Most | Jared Kirkwood | 33:09 | 不同讲员与表达节奏 |
| `8u9B8u_5ISI` | If Christians are to be one, why are there so many denominations? | Ed Stetzer | 33:29 | `test_unseen_speaker`；神学术语和论证密度较高 |
| `z_UoOx-6mz4` | Does God care what I do with my body? | Christine Caine | 30:43 | 不同讲员及复杂伦理主题 |
| `qvImKpmvgaM` | Life After Rescue | Doug Fields | 27:20 | 第五位讲员，增强跨讲员泛化覆盖 |

合计约 2 小时 38 分。2026-09-02 的匿名 URL 探测确认 5 篇均为公开完整视频并带英文自动字幕；均已在原 split manifest 中标为 `test`，但仍需准备音频核对后的英文 reference 和 Sol-reviewed 中文 reference。

## 7. Gold Reference 制作

建议使用以下流程：

```text
原始音频
  → ASR 初稿
  → GPT-Transcribe/字幕交叉核对英文原文和断句
  → Terra/其他翻译模型生成中文草稿
  → GPT-5.6 Sol（thinking high）逐段审核、纠错和风险标记
  → 对高风险及抽样片段做最小人工校准
  → 锁定测试参考和错误标签
```

本项目默认使用 `gpt-5.6-sol`、`reasoning.effort=high` 作为主审核模型，不要求对 Benchmark 全量进行双人工审核。为避免把模型审核结果误称为完全人工 Gold，数据状态应区分：

- `sol_reviewed`：Sol High 已审核；
- `human_calibrated`：进入人工抽样校准；
- `human_confirmed_critical`：严重错误或关键经文已人工确认。

人工只保留三个最小职责：校准少量随机样本、确认可能影响上线判断的严重错误、批准最终生产门禁。论文中应如实将主体称为“Sol-reviewed reference”，只把实际人工确认的子集称为 human-confirmed。

## 8. 质量评估

### 8.1 自动指标

| 指标 | 用途 | 限制 |
|---|---|---|
| WER | 测量英文 ASR 准确率 | 不能代表翻译正确性 |
| COMET | 语义级机器翻译质量 | 需固定版本；领域错误可能被平均掩盖 |
| chrF | 字符级译文相似度 | 对合法改写不够敏感 |
| BLEU | 与既有研究可比 | 不作为主决策指标 |
| Term Accuracy | 经文、人名、神学术语准确率 | 需要人工维护术语 reference |
| Scripture Accuracy | 书卷、章、节和译名正确率 | 应区分显式引用与暗引 |

自动指标必须按整篇证道和关键片段分别汇报，不能只给一个全局平均数。

### 8.2 Sol High 主评分量表

由 `gpt-5.6-sol`、`reasoning.effort=high` 对每段采用 1–5 分评分，并额外标记严重错误：

| 维度 | 权重 | 判断重点 |
|---|---:|---|
| 原意与逻辑准确 | 30% | 主旨、因果、条件、否定、转折 |
| 完整性 | 15% | 是否漏译或添加内容 |
| 经文与神学准确 | 20% | 经文、教义含义、固定译名 |
| 中文自然度 | 15% | 口语转字幕是否自然易懂 |
| 实时可读性 | 10% | 手机两行内是否容易跟读 |
| 全篇一致性 | 10% | 人名、术语、称谓是否漂移 |

Sol 必须输出结构化 JSON，包括各维度分数、A/B 偏好、错误标签、引用的英文证据、中文问题说明和置信度。低置信度、位置交换后结论不一致或命中严重错误的样本进入复审队列。

### 8.3 严重错误分类

以下错误必须单独统计，不能被平均分抵消：

- `meaning_reversal`：原意或否定关系翻反；
- `unsupported_addition`：添加音频中不存在的内容；
- `critical_omission`：遗漏决定段落意义的内容；
- `scripture_misattribution`：经文书卷、人物或教义关系错误；
- `prepared_context_copy_error`：照搬周六材料而违背周日音频；
- `unsafe_instability`：字幕先显示错误关键结论，随后大幅改写。

主系统的上线判断应优先看严重错误率，而不是 BLEU 或总平均分。

## 9. 流式延迟与稳定性评估

### 9.1 统一时间点

| 时间点 | 定义 |
|---|---|
| `t_speech_start` | VAD 检测到有效语音开始 |
| `t_audio_ingest` | 对应音频帧进入被测系统 |
| `t_first_partial` | 首个非空中文字幕 partial 到达 |
| `t_first_stable` | 首个之后不再发生实质修改的正确中文字到达 |
| `t_source_end` | 当前语义单元在音频中结束 |
| `t_final` | 当前字幕被标记 final 且不再修改 |
| `t_render` | 字幕实际显示在 iOS/Web 客户端 |

服务器延迟和端到端会众延迟应分别报告。端到端延迟必须包含网络、SSE/WebSocket 分发及客户端渲染。

### 9.2 核心指标

- `TTFP = t_first_partial - t_speech_start`：首个 partial 延迟。
- `TTSC = t_first_stable - t_speech_start`：首个稳定正确字符延迟，作为首要首屏指标。
- `Finalization Delay = t_final - t_source_end`：讲完一个语义单元后多久定稿。
- `Render Delay = t_render - t_source_end`：会众实际看到定稿的延迟。
- `Revision Rate`：已显示字幕发生实质性改写的 segment 比例。
- `Normalized Edit Churn`：所有 partial 到 final 的编辑距离总和除以 final 长度。
- `RTF`：处理耗时除以音频时长；持续服务必须小于 1。
- `Recovery Time`：网络或模型故障后恢复到可读字幕所需时间。

每项至少报告 p50、p90、p95 和最大值。不能用平均值掩盖现场长尾卡顿。

### 9.3 初始工程目标

以下是待 benchmark 校准的初始目标，不代表已验证成绩：

- `TTSC p50 ≤ 1.5 秒`；
- `TTSC p95 ≤ 3.0 秒`；
- `Finalization Delay p95 ≤ 4.0 秒`；
- 连续 50–60 分钟运行 `RTF < 1`；
- 实质回改 segment 比例 `< 10%`；
- 断线或模型切换后 `< 10 秒` 恢复可读字幕。

首字符非常容易通过过早猜测取得好成绩，因此不能只用 TTFP 宣称系统更快。

### 9.4 MacBook M1 Max 64 GB 资源门禁

以下门槛先作为第一轮可校准工程预算，并在首个完整 replay 后冻结修订：

- 模型必须使用 Apple Silicon 原生运行时；主路径为 llama.cpp Metal，MLX 可作为独立引擎组测试；
- 翻译进程峰值 resident memory 目标不超过 40 GiB，并为 macOS、ASR、字幕客户端和缓存保留至少 8 GiB 可用内存；
- 稳态 memory pressure 保持绿色，不允许出现红色；完整运行期间 swap 增量目标不超过 1 GiB；
- 不允许 OOM、进程被系统终止、持续热降频造成积压，或在音频结束时仍有翻译 backlog；
- translation-only 通过后，必须再验证 ASR、翻译和字幕客户端共存；只证明模型能单独加载不算通过；
- 每个主榜 run 必须记录冷/热启动、进程峰值内存、系统 memory pressure、swap、温度/功耗、tokens/s、RTF 和延迟分位数。

40 GiB、8 GiB 和 1 GiB 是初始工程预算，不是已经验证的硬件事实；首轮完整共存 replay 可以收紧，但不能在看到某个候选失败后临时放宽而不重新跑全部候选。

## 10. 性能、成本与运行指标

本地模型应记录：

- 模型和量化文件的精确名称、版本与 SHA-256；
- 推理引擎及 commit/version；
- 硬件、功耗模式、显存峰值和系统内存峰值；
- context length、batch、并发、解码参数；
- tokens/s、RTF、冷启动和热启动时间；
- 50 分钟连续运行的温度、降频、OOM 和错误次数。

云端模型应记录：

- provider、模型版本、区域和 API 版本；
- 音频分钟、输入/输出 token 和实际账单单位；
- 网络 RTT、限流、重连和请求失败；
- 单场 50 分钟成本及每 100 场成本；
- 数据保留和隐私配置。

DGX Spark、MacBook M1 Max 和云端结果不可混在同一性能表中，必须分别报告。综合决策报告默认先展示 MacBook 主榜；DGX 与云端结果置于参考榜。质量指标可以在输入、模型文件和解码完全一致时跨硬件复用，但性能、内存和运行稳定性必须在 MacBook 上重新测量。

## 11. 以 Sol High 为主的 A/B 盲审协议

### 11.1 离线配对盲审

1. 对同一音频并行生成所有系统的完整事件日志和最终字幕。
2. 以 15–45 秒语义窗口制作评审单元，并保留必要上下文。
3. 随机化 A/B 左右位置，隐藏模型名称、版本和路线。
4. 使用 `gpt-5.6-sol`、`reasoning.effort=high` 先独立评分候选 A 和 B。
5. 再由 Sol High 做一次 pairwise 判断，并交换 A/B 左右位置重复判断。
6. 两次位置交换结论一致时直接进入聚合结果；不一致时再发起一次独立 Sol High 裁决。
7. 除分数外，必须记录偏好、错误标签、置信度和可定位证据。

Judge 配置需要固定：

- 使用完全相同且带版本号的 rubric；
- 保存模型 ID、reasoning effort、prompt hash、请求 ID 和完整结构化输出；
- Judge 只能看到允许的英文原文、参考译文、候选译文和必要上下文，不能看到系统身份；
- 不用译文风格相似度代替语义、经文和严重错误判断；
- 对同一比较随机交换候选顺序，检测位置偏差；
- 若使用可锁定 snapshot，应在同一轮实验中固定 snapshot。

由于 Sol 同时参与训练数据复审和 Benchmark 裁判，可能偏好接近自身表达风格的译文。因此保留一个轻量人工校准集，而不是设计全量双人工审核。

### 11.2 最小人工校准

人工审核限定为：

- 对每轮结果做 5%–10% 分层随机抽查；
- 抽查所有被 Sol 标记为 `meaning_reversal`、`unsupported_addition`、`scripture_misattribution` 或 `prepared_context_copy_error` 且会改变上线结论的样本；
- 仅在 Sol 三次判断仍冲突或置信度低时裁决；
- 最终上线前由一名授权人员确认聚合报告和严重错误清单。

不要求每段两名人工审核者，也不要求第三名人工对全部争议逐段复核。需要报告抽样方法、人工与 Sol 的一致率，以及人工校准后是否改变系统排名。

### 11.3 统计方法

- 所有核心比较使用 paired samples，因为每个系统处理的是相同音频。
- 报告系统间差值及 95% bootstrap confidence interval。
- 报告按 segment、按 sermon macro-average 两组结果。
- A/B 胜率应排除平局后报告，同时保留原始平局比例。
- 不只追求统计显著，还要预先定义具有产品意义的最小改善幅度。

建议将“Sol High 主评分提高至少 0.25/5 分且人工校准未推翻方向”或“严重错误率相对下降至少 25%”作为后训练路线具有实际价值的初始判断标准，最终门槛在 pilot 后锁定。

## 12. 消融实验

完整系统 A3 至少进行以下消融：

| 对比 | 回答的问题 |
|---|---|
| A1 vs A0 | 后训练本身带来多少收益？ |
| A2 vs A1 | 圣经文本和术语检索带来多少收益？ |
| A3 vs A2 | 周六材料带来多少额外收益和错误复制风险？ |
| A3 无历史上下文 vs 有历史上下文 | 跨 segment 上下文是否减少代词和术语漂移？ |
| 小窗口 vs 大窗口 | 上下文质量改善是否值得额外延迟？ |
| partial 翻译 vs stable-only 翻译 | 更早输出和字幕回改之间如何权衡？ |

若没有这些对照，不能把完整系统的改善归因于“后训练”。

## 13. 执行阶段

### Phase 0：冻结协议

- 固定测试集、评分表、延迟定义和通过门槛；
- 固定所有模型版本和推理参数；
- 确认音频授权、脱敏和数据保留要求；
- 先用 5–10 分钟开发样本验证日志完整性。

### Phase 1：离线正确性 benchmark

- 不按实时速度播放，先确认所有路线可以完成；
- 检查输出格式、断句、编码和 reference 对齐；
- 排除系统接入问题后再测速度。

### Phase 2：实时 replay benchmark

- 以 1.0× 原始时间送入同一音频；
- 保存每个 partial/final 事件和单调时钟时间戳；
- 每个系统至少重复三次，分离冷启动与热启动；
- 执行完整 50–60 分钟 soak test。

### Phase 3：盲审与误差分析

- 自动指标先运行，但不向 Sol Judge 显示；
- 完成 Sol High 独立评分、随机盲评、位置交换和冲突裁决；
- 对 5%–10% 分层样本和可能改变上线结论的严重错误做人工校准；
- 汇总严重错误、经文错误和周六材料错误复制；
- 对延迟—质量关系绘制 Pareto frontier。

### Phase 4：周日 shadow test

- Admin 麦克风只采集一次，同时镜像到候选系统；
- 候选输出默认不向会众发布；
- 验证现场网络、声学、连续运行、重连和 fallback；
- 服务结束后与锁定参考文本对齐并复盘。

### Phase 5：受控会众 A/B

- 只有通过 shadow gate 的两个系统进入现场 A/B；
- 对参与者明确测试性质，并提供稳定 fallback；
- 记录“是否跟得上、是否易读、是否因回改中断理解”；
- 首次测试不应全量替换已验证的生产路线。

## 14. 建议决策规则

### 14.1 综合评分

| 类别 | 权重 |
|---|---:|
| 原意准确与严重错误 | 30% |
| 经文、神学术语和专名 | 20% |
| 实时延迟 | 20% |
| 字幕稳定性与可读性 | 15% |
| 可靠性与故障恢复 | 10% |
| 成本与资源占用 | 5% |

### 14.2 硬门禁

无论综合分数多高，出现以下情况都不能直接成为生产主链路：

- 关键意义反转或无依据添加超过锁定门槛；
- 周六稿偏离时仍频繁输出未说内容；
- `RTF ≥ 1` 或 50 分钟持续运行出现不可恢复积压；
- p95 稳定字幕延迟超过现场可接受上限；
- 无法生成完整可审计的输入、输出和时间戳日志；
- 故障时不能安全切换至英文字幕或备用翻译路线。
- 未在 M1 Max 64 GB 上完成与 ASR、字幕客户端共存的完整 replay；
- 峰值统一内存、memory pressure 或 swap 超出冻结预算，或者只能依赖 DGX 才能运行。

### 14.3 路线选择

- A3 质量最高且延迟达标：作为实时主链路。
- A3 质量高但延迟稍慢：低延迟直接 AST 做 draft，A3 做稳定修正版。
- 直接 AST 质量和延迟都占优：将级联系统降为审核、纠错和离线归档链路。
- 周六材料产生明显错误复制：生产禁用自由文本注入，只保留检索到的经文和术语约束。

## 15. 事件与结果文件设计

建议每次运行写入：

```text
artifacts/benchmarks/live-translation/<run_id>/
  manifest.json
  input/
    sermon.json
    prepared-context.json
  events/
    A0.jsonl
    A1.jsonl
    A2.jsonl
    A3.jsonl
    B0.jsonl
  outputs/
    <system>.final.jsonl
    <system>.vtt
  metrics/
    latency.json
    quality.json
    cost.json
    errors.jsonl
  review/
    blind-pairs.jsonl
    human-ratings.jsonl
    llm-ratings.jsonl
    adjudication.jsonl
  report.md
```

每条流式事件至少包含：

```json
{
  "run_id": "...",
  "system_id": "A3",
  "sermon_id": "...",
  "segment_id": "...",
  "event_type": "partial|final|correction|error",
  "source_text": "...",
  "target_text": "...",
  "audio_start_ms": 0,
  "audio_end_ms": 0,
  "received_monotonic_ms": 0,
  "rendered_monotonic_ms": 0,
  "model_version": "...",
  "context_policy": "..."
}
```

原始音频、授权受限文本和 API 凭据不得提交到公开 Git。Git 只保存脱敏 manifest、评分协议、聚合指标和允许公开的样本。

## 16. 可复现实验要求

每个结论必须能追溯到：

- 固定输入音频哈希；
- 模型/服务版本和配置；
- 周六材料、圣经版本和术语表版本；
- 原始 partial/final 事件；
- 评审样本随机化 seed；
- Sol Judge 评分 rubric 版本及人工校准协议版本；
- 指标计算脚本 commit；
- 实际运行硬件、区域和时间。

任何只保存最终 VTT、没有 partial 事件的测试，只能比较最终质量，不能用于实时延迟或字幕稳定性结论。

## 17. 论文推进框架

后续论文可以按以下结构组织：

1. 现场证道实时翻译问题与周六/周日内容偏差；
2. 流式 ASR、领域后训练和检索增强架构；
3. 证道双语语料、测试集和错误分类；
4. 与直接 AST、商业云服务和基础学生模型的比较；
5. 后训练、圣经检索、术语表、周六材料的消融实验；
6. 延迟—质量 Pareto 分析；
7. 周日 shadow test 与会众可读性研究；
8. 隐私、版权、授权、偏差和部署限制。

论文结果必须明确区分：离线 replay、模拟实时、现场 shadow 和会众真实 A/B，不能把其中一种结果外推成另一种已经验证。

## 18. 第一轮最小可行 Benchmark

为了尽快得到方向性结论，第一轮可限制为：

- 3 篇完整未见证道，至少包含 1 篇与周六材料明显偏离的样本；
- A0、A1、A2、A3、一个直接 AST 基线，共 5 组；
- 在同一台 MacBook Pro M1 Max 64 GB 上运行 A0–A3；
- 每组一次完整实时 replay，加关键 10 分钟片段三次重复；
- Sol High 全量裁判 + 5%–10% 分层人工校准；
- 输出质量、TTSC、finalization、churn、RTF、严重错误和成本报告。

第一轮只用于筛选路线，不用于论文最终结论。通过后再扩展到 8–15 小时锁定测试集和多个周日 shadow test。

### 18.1 建立步骤与状态门禁

#### Step 1：冻结清单与防泄漏

- [x] 选定 5 篇完整证道；
- [x] 确认它们均为 `test/untouched_test`，未进入 train；
- [x] 匿名验证公开视频与英文自动字幕；
- [x] 建立机器可读 Benchmark manifest；
- [x] 验证训练入口 split gate：train/dev 请求若命中这 5 个 test ID 必须 fail closed；
- [x] 计算并冻结整理后字幕 source hash；
- [x] 下载完整音频、使用 `ffprobe` 验证并冻结各篇 source audio hash；
- [x] Reference 完成后冻结英文、Sol-reviewed 中文和音频审计版本 hash。

#### Step 2：准备英文 Reference

- [x] 提取并整理英文自动字幕，保留来源、时间轴和 source hash；
- [x] 使用 GPT-Transcribe 完成教师前字幕风险、固定抽样和每篇最低抽样核对（11 段，均支持字幕）；
- [x] 使用 Sol High 全量检查翻译及源风险，并把需音频证据的片段送入后审计；
- [x] 输出冻结 `segments.en.reference.jsonl`；
- [ ] 记录不能从音频可靠确认的片段，不把不确定文本伪装成 Gold。

#### Step 3：准备中文 Reference

- [x] Terra 生成第一版中文；
- [x] Sol High 全量审核、纠错并输出严重错误标签；
- [ ] 对 5%–10% 分层样本和关键严重错误做最小人工校准；
- [x] 输出 `segments.zh.sol-reviewed.jsonl` 和 reference version；
- [ ] 冻结后禁止因某个候选模型的表达不同而随意修改 reference。

#### Step 4：建立训练前 Baseline

- [x] 固定两组学生基础模型、BF16 格式、推理引擎和解码参数，见 `data/benchmarks/live-sermon-translation-v1/a0-config.json`；
- [x] 在完全相同英文 reference 上完成 `Qwen3.5-4B-Base` 与 `Qwen3.5-9B-Base` 的 A0（各 239/239 段）；
- [ ] 保存逐段预测、tokens/s、显存、RTF 和模型哈希（预测、tokens/s 和模型哈希已完成；单模型峰值显存与实时 RTF 待 replay）；
- [ ] 使用 Sol High 运行单候选评分与错误分类；
- [ ] 完成 `baseline-report.md` 的质量评分部分，作为后训练收益的最终零点（生成与速度部分已完成）。

现有 DGX BF16 A0 继续保留为历史研究零点。MacBook 已用相同 BF16 GGUF、prompt 和解码配置建立独立 Ollama 运行，不覆盖或改写 DGX 预测与速度记录；未来生产量化版仍需独立 run ID。

#### Step 4B：MacBook 可运行性与主榜 Baseline

- [x] 冻结 `MacBook Pro / M1 Max / 64 GB` 主硬件 profile；
- [x] 为 Qwen3.5-4B-Base、Qwen3.5-9B-Base、Hy-MT2-1.8B 和 MiLMMT-46-4B-v1.0 选择可复现的 GGUF artifact，并固定 revision、量化和 SHA-256（Qwen 使用与 DGX A0 相同 BF16，Hy-MT2 使用官方 Q8_0，MiLMMT 使用固定社区转换 Q8_0）；
- [x] 按“小模型优先”执行冷加载与 10 段 smoke，失败模型不进入昂贵的全量评分；
- [x] 对通过 smoke 的四个模型完成 239 段 translation-only run；
- [x] 记录峰值 resident memory、memory pressure、swap、冷启动、tokens/s 和延迟分位数；
- [ ] 与本地 ASR、字幕客户端共存执行 1.0× replay 和 50–60 分钟 soak；
- [ ] 生成独立 MacBook 主榜，不复用 DGX 性能数字；
- [ ] 只把通过资源、实时和安全门禁的模型送入 A1–A3 后训练及生产候选比较。

#### Step 4C：MiLMMT 主优化路线

- [x] 固定 `MiLMMT-46-4B-v1.0 Q8_0 / Ollama` 为 MacBook 后训练前推理零点；
- [x] 固定数据 schema、官方纯文本 prompt、`contentText` 规则和 test denylist；
- [x] 固定 MLX 4/5/6/8-bit 与 GGUF Q4/Q5/Q6/Q8 的 dev 实验矩阵；
- [ ] 解除 source training rights 与教师输出蒸馏授权 blocker；
- [ ] 生成合格 train/dev inventory，并按完整证道做 group split；
- [ ] 从官方未量化权重运行 LoRA/SFT pilot，禁止直接训练 Q8 GGUF；
- [ ] 在 dev 上锁定单一后训练与量化候选，再运行 untouched test。

完整计划见 [MiLMMT-46-4B 证道翻译后训练与 MacBook 优化计划](./milmmt-sermon-post-training-plan.zh.md)，机器可读配置见 `data/benchmarks/live-sermon-translation-v1/milmmt-post-training-v1.json`。

#### Step 5：运行文本 A/B 与消融

- [ ] A0：基础学生模型；
- [ ] A1：后训练学生模型；
- [ ] A2：A1 + 圣经/术语检索；
- [ ] A3：A2 + 周六材料；
- [ ] Sol High 进行独立评分、位置交换盲评和冲突复判；
- [ ] 计算总体与逐证道结果，检查后训练是否显著改善且没有错误复制。

#### Step 6：运行实时 Replay

- [ ] 使用同一标准化音频以 1.0× 输入各系统；
- [ ] 记录 partial/final、单调时钟和客户端 render 时间；
- [ ] 对关键 10 分钟片段重复三次；
- [ ] 对五篇完整证道至少各执行一次 soak run；
- [ ] 生成 TTSC、finalization、revision churn、RTF 和故障报告。

#### Step 7：决策与扩展

- [ ] 对照硬门禁选择主路线、稳定修正路线和 fallback；
- [ ] 输出第一轮 Benchmark 报告；
- [ ] 决定是否扩展至原冻结 test split 的其余 13 篇；
- [ ] 通过后再设计周日 shadow test，不从离线 replay 直接推断现场已验证。

### 18.2 API Key 复用规则

允许复用项目现有 OpenAI API key 或 Secret Manager 中已有的 secret reference，但必须遵守：

- 只读取现有环境变量或 secret reference，不复制 key value；
- manifest 只记录 `credentialSource` 类型，不记录 secret 名称、资源路径或值；
- 日志和模型请求回执不得包含 Authorization header；
- dry run、清单冻结和本地指标计算默认不调用 API；
- 首次 Sol/GPT-Transcribe 请求前单独做最小 preflight，并明确记录将产生计费；
- 所有可续跑步骤按已存在的 request/segment receipt 去重，避免重复计费。

## 19. 当前未决事项

- MacBook 主榜的最终学生基础模型、量化和推理引擎；
- M1 Max 64 GB 首轮完整共存 replay 后是否需要收紧 40 GiB 模型进程预算、8 GiB 系统余量和 1 GiB swap 增量预算；
- DGX Spark 上 Riva/Canary 的实际运行兼容性与速度；
- 锁定测试集的具体证道 ID 和人工校准抽样率；
- 中文圣经参考版本及其授权边界；
- 现场 TTSC/定稿延迟的最终会众接受门槛；
- 会众 A/B 的招募、告知和反馈方式。

这些事项在 Phase 0 冻结协议前确定；在此之前，所有门槛均视为设计目标，而非已验证事实。

## 20. 参考资料

- [Meta Seamless Communication](https://ai.meta.com/research/seamless-communication/)
- [Meta SeamlessM4T v2 model card](https://huggingface.co/facebook/seamless-m4t-v2-large)
- [NVIDIA Riva ASR/AST language support](https://docs.nvidia.com/deeplearning/riva/user-guide/docs/asr/asr-overview.html)
- [NVIDIA Riva Translation](https://docs.nvidia.com/deeplearning/riva/user-guide/docs/public/translation/translation-overview.html)
- [Azure Speech language support](https://learn.microsoft.com/en-us/azure/ai-services/Speech-Service/language-support)
- [Qwen2.5-Omni](https://qwenlm.github.io/blog/qwen2.5-omni/)
- [OpenAI GPT-5.6 Sol model](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
