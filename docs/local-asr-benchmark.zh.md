# MacBook 本地英文 ASR Benchmark V1

更新日期：2026-09-03  
状态：`qwen_and_small_streaming_replay_completed_human_listening_confirmation_pending`

## 模型选择

当前正式比较：

1. `whisper.cpp small.en`：现场主候选，模型较小，优先检查实时性与 MiLMMT 共存；
2. `whisper.cpp medium.en`：同运行时的质量上限对照，用于判断精度收益是否值得额外资源；
3. `NeMo-Speech.cpp Parakeet TDT 0.6B v3 Q8_0`：紧凑速度/质量挑战者；
4. `NeMo-Speech.cpp Nemotron Speech Streaming EN 0.6B Q8_0`：原生流式架构挑战者；
5. `MLX Whisper large-v3-turbo`：Apple 原生质量挑战者。
6. `Distil-Whisper large-v3 GGML F16`：英语专用的蒸馏 Whisper 质量挑战者；
7. `Qwen3-ASR-0.6B MLX 8-bit`：小型多语言 Apple 原生挑战者。

`small.en` 和 `medium.en` 都是英语专用 Whisper。`large-v3-turbo` 没有 `.en` 版本，但它是官方为推理速度优化的 798M 模型，适合作为 Apple 原生运行时的补充 Pareto 点。

## 数据层级

- **工程 smoke**：20 个现有证道 MP3 片段，只验证解码、输出、错误、冷加载 RTF 与进程 RSS。英文来源不是人工 Gold，不计算 WER，也不据此选择生产模型。
- **模型审核参考集**：60 个精确 30 秒音频块、29.811 分钟，直接复用对应的 GPT-Transcribe timeline chunk 文本。它可作为统一裁判运行 WER、关键术语和静音评分，但状态固定为 `model_reviewed_reference`，只产生 provisional 排名。
- **ASR dev Gold**：50–100 个片段、约 30 分钟，由人工逐字校正。只使用这一层选择模型、VAD、窗口和 initial prompt。
- **连续 replay**：独立 10 分钟音频，以 1.0× 送入，记录 partial、final、修改次数和说话结束到 final 延迟。
- **共存 soak**：ASR、MiLMMT、浏览器和录音同时运行 50–60 分钟。

翻译 Benchmark 的 239 段 `untouched_test` 及其参考译文不得成为 ASR 调参 Gold。现有片段只承担无评分 smoke；正式 ASR Gold 应从获得许可且未进入最终 test 的独立录音或 train/dev 来源建立。

## Gold 制作

模型审核参考集与人工 Gold 分层保存。GPT-Transcribe / Sol 审核文本可直接担任第一轮统一裁判，但不得改写成 `human_gold`；人工 Gold 必须听音频校正。每条保留音频 hash、参考文本、参考层级、reviewer、时间范围和标签，覆盖：

- 经文书卷、章节、数字；
- 人名、地名、神学术语；
- 否定、反问和自我修正；
- 掌声、音乐、停顿和近乎静音；
- 混响、远距离麦克风和环境噪声。

至少 10% 双人复核，所有经文、数字、专名和可能改变含义的差异必须复核。静音样本的 reference 必须显式为空且标记 `speechExpected=false`。

## 指标与门禁

离线质量记录 WER，但决策同时要求：

- 经文、人名、专名和神学术语 recall；
- 数字、否定和意义反转错误；
- 静音幻觉次数；
- 每片 RTF、吞吐和峰值 RSS。

流式阶段另外记录：

- partial 到 final 的修改次数和 edit churn；
- 说话结束到 final 的 P50/P95；
- 丢帧、音频 backlog 和长时间漂移；
- ASR → MiLMMT → 页面 render 的端到端 P50/P95；
- 进程树 RSS、系统 memory pressure、swap 和温度状态。

暂定门禁为：静音幻觉 0、关键经文/专名/术语 recall ≥95%、共存 RTF <0.7、端到端 P95 目标 ≤4 秒、无持续 swap 增长。门槛须在查看最终 test 前冻结。

## 运行配置

机器可读配置：`data/benchmarks/live-sermon-translation-v1/local-asr-benchmark-v1.json`。

第一轮离线 smoke 固定 `language=en`、temperature 0、beam 1、best-of 1、关闭 temperature fallback、不使用 initial prompt。此阶段每片单独启动 CLI，因此性能只代表冷加载工程 smoke；生产性能必须通过 persistent provider 或 `whisper-stream` 的连续 replay 测量。

模型文件保存在本机 cache，不提交 Git。每次 run 必须记录上游 revision、SHA-256、对应运行时版本、Metal/MLX 状态和完整解码参数。

## 通过顺序

1. 两个 whisper.cpp 模型完成 20/20 非空、0 error smoke；
2. 用精确对齐的 GPT-Transcribe chunk 建立 `model_reviewed_reference`，完成第一轮统一离线评分；
3. 对分歧、静音、歌词、关键术语和分层抽样片段执行独立 GPT-Transcribe 重听，再把仍有差异的片段交给人工确认；
4. 胜出模型完成 10 分钟 1.0× streaming replay；
5. 与 MiLMMT Q8、浏览器和录音完成 50–60 分钟共存；
6. 对新增的 NeMo-Speech.cpp 与 MLX 候选按相同参考集与 replay 协议测试；
7. 锁定 ASR provider 后接入 gateway，不修改 MiLMMT 或前端协议。

## 2026-09-03 工程 Smoke 状态

`whisper.cpp 1.9.2` 已通过 Homebrew 安装，Metal 后端在 M1 Max 上成功加载。官方转换的 `small.en` 与 `medium.en` F16 文件已经下载到本机 cache，并用固定上游 revision 与 SHA-256 校验。

两个模型均在同一 20 段、16.803 分钟音频上完成受控顺序运行：20/20 成功、20/20 非空、0 error。`small.en` 冷加载每片平均 RTF 0.0312、峰值 RSS 0.7446 GiB；`medium.en` 平均 RTF 0.0669、峰值 RSS 1.8241 GiB。

这些结果证明两者都可在本机运行，并说明 `small.en` 的工程开销明显更低；工程 smoke 本身不承担质量结论。

仓库内另有两篇不属于冻结 translation test 的 post-live 音频，并保存了 operator window approval。它们被登记为 ASR dev Gold 人工标注候选池：2026-08-23 选择全部 15 个 30 秒块，2026-08-30 从 72 个块中均匀选择 45 个，合计 60 段、29.811 分钟。冻结 translation untouched test 没有进入这批 ASR 调参数据。

人工标注队列仍保持 `needs_human_gold`，位于 `data/benchmarks/live-sermon-translation-v1/local-asr-gold-annotation-queue-v1.json`。另从完全相同的音频边界生成 `local-asr-model-reviewed-reference-v1.json`，使用 GPT-Transcribe 的 exact-chunk 文本作为 provisional 裁判；runner 会明确报告 `scored_model_reviewed_reference`，不会把分数标成正式人工 WER。

## 2026-09-03 模型审核参考集结果

评分先做了两项防偏修正：关键术语必须按完整词或短语匹配，不能把 `Christ` 命中到 `Christian`；`[Music]`、`(upbeat music)` 等非语音事件标签在 WER 与静音幻觉中归一为空。歌词仍属于应输出文本，不能用音乐符号替代。

MRQS（Model-Reviewed Quality Score）固定为：60% WER fidelity、30% 关键术语 recall、5% 完整输出、5% 静音纪律。它只用于快速排序；完整输出、关键术语 ≥95% 和静音幻觉为零仍是独立 hard gate，标量总分不能覆盖 gate failure。

| 模型 | MRQS | 参考 WER | 关键术语 recall | 有效输出 | 静音幻觉 | 平均 RTF | 峰值 RSS | 当前门禁 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `whisper.cpp small.en F16` | 96.536 | 4.32% | 97.10% | 60/60 | 0 | 0.0368 | 0.7188 GiB | PASS |
| `whisper.cpp medium.en F16` | 93.620 | 5.87% | 91.30% | 57/60 | 0 | 0.0777 | 1.8215 GiB | FAIL |

`medium.en` 的三个无效输出都位于歌词片段，模型只给出音乐符号，导致歌词完全漏转并同时漏掉 `Christ` / `Jesus` 等关键词。逐片 word-error 对比中，`small.en` 赢 24 段、`medium.en` 赢 21 段、15 段打平；最终由总 WER、关键术语与完整性共同拉开差距。

这一版初始 leaderboard 保留为校准前基线，位于 `data/benchmarks/live-sermon-translation-v1/runs/local-asr/model-reviewed-quality-leaderboard-20260903.json`。

## 2026-09-03 GPT-Transcribe 重听校准

13 段、6.5 分钟校准队列已使用独立 GPT-Transcribe 请求重新听审：13/13 成功、0 error、API usage 合计 403 秒。密钥来自 GCP Secret Manager，响应、usage、音频 SHA、请求参数 hash 均已保存，产物不含 API key 或认证头。

二次听审与原 GPT exact-chunk reference 比较后，9 段词级完全一致，3 段有不超过 10% 的小差异，1 段歌词存在重大差异。新参考状态固定为 `gpt_reaudited_reference`；`humanListeningCompleted=false`，不宣称人工 Gold。校准版 manifest 位于 `data/benchmarks/live-sermon-translation-v1/local-asr-gpt-reaudited-reference-v1.json`。

冻结的本地模型预测在校准版 reference 上重新计分，未重新运行推理，因此以下变化只来自裁判参考更新：

| 模型 | 校准后 MRQS | 校准后 WER | 关键术语 recall | 有效输出 | 静音幻觉 | 当前门禁 |
|---|---:|---:|---:|---:|---:|---|
| `whisper.cpp small.en F16` | 96.244 | 4.09% | 95.65% | 60/60 | 0 | PASS |
| `whisper.cpp medium.en F16` | 93.772 | 5.61% | 91.30% | 57/60 | 0 | FAIL |

在当时的两模型校准榜中，`small.en` 仍是 provisional offline winner，排名在校准前后没有反转。`medium.en` 仍因三段歌词完全漏转以及关键术语不足而 fail closed。该历史 leaderboard 位于 `data/benchmarks/live-sermon-translation-v1/runs/local-asr/gpt-reaudited-quality-leaderboard-20260903.json`；后续七模型榜结论见下节。

剩余人工工作已缩小到 4 个有文本差异的片段、合计 2 分钟，尤其是 1 个重大歌词差异；专用队列位于 `data/benchmarks/live-sermon-translation-v1/local-asr-human-confirmation-queue-v1.json`。只有人工真正听审后才可升级为 `human_gold`。生产选型仍需后续 10 分钟 streaming replay 和 MiLMMT 共存 soak。

## 2026-09-03 五个新增候选实测

新增候选均在同一台 M1 Max 64 GB、同一份 60 段 GPT 校准参考集上串行运行。NeMo-Speech.cpp 固定为官方 `0.1.0` Metal 构建；Whisper MLX 固定为 `mlx-whisper 0.4.3 / mlx 0.32.2`；Qwen3-ASR 使用社区转换的 `mlx-community/Qwen3-ASR-0.6B-8bit` 与隔离安装的 `mlx-audio 0.3.1`。模型 revision、权重 SHA-256、逐段预测、stderr、run report 和资源数据均已保存；权重本身只在本机 cache。

| 模型 | MRQS | WER | 关键术语 recall | 有效输出 | 静音幻觉 | 平均 RTF | 峰值 RSS | 门禁 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `Qwen3-ASR-0.6B MLX 8-bit` | 96.893 | 3.73% | 97.10% | 60/60 | 0 | 0.0653 | 1.1519 GiB | PASS |
| `whisper.cpp small.en F16` | 96.244 | 4.09% | 95.65% | 60/60 | 0 | 0.0368 | 0.7188 GiB | PASS |
| `NeMo Parakeet TDT 0.6B v3 Q8_0` | 95.045 | 4.36% | 92.75% | 58/60 | 0 | 0.0362 | 0.8007 GiB | FAIL |
| `NeMo Nemotron Streaming EN 0.6B Q8_0` | 93.931 | 5.49% | 91.30% | 58/60 | 0 | 0.0531 | 1.6688 GiB | FAIL |
| `whisper.cpp medium.en F16` | 93.772 | 5.61% | 91.30% | 57/60 | 0 | 0.0777 | 1.8215 GiB | FAIL |
| `Distil-Whisper large-v3 GGML F16` | 92.453 | 3.52% | 98.55% | 60/60 | 1 | 0.0531 | 1.6866 GiB | FAIL |
| `MLX Whisper large-v3-turbo` | 91.823 | 3.12% | 95.65% | 60/60 | 1 | 0.0729 | 1.7174 GiB | FAIL |

MLX Turbo 的 WER 最低且 60/60 均有文本，但唯一静音片段幻觉出 `Thank you.`；静音纪律项因此为 0 分，并触发独立 hard gate。Parakeet 的平均 RTF 略优于 `small.en`，峰值 RSS仅高 0.0819 GiB，但与 Nemotron 一样在 `gold_043`、`gold_044` 两段歌词上输出为空，关键术语 recall 也低于 95%。

Distil-Whisper 的文本质量很强，但在唯一无语音片段反复生成 `Thank you` 和碎片词，触发静音 hard gate。Qwen3-ASR 对该片段输出单独的 `Music.`；根据预先采用的“非语音事件标签不计作语音幻觉”政策，裸事件标签与 `[Music]`、`(Music)` 使用相同归一规则。该规则对七个模型统一应用，复核显示只有 Qwen 这一条预测的归一结果发生变化。

因此 `Qwen3-ASR-0.6B MLX 8-bit` 以 MRQS 96.893 成为新的 provisional offline winner，`small.en` 以更低资源和更快 RTF 排第二；两者均通过当前离线门禁。完整统一榜单位于 `data/benchmarks/live-sermon-translation-v1/runs/local-asr/gpt-reaudited-quality-leaderboard-7-model-20260903.json`。这些性能值仍是每片 CLI 冷启动离线测量，不等同于持续 provider、流式 final 延迟或与 MiLMMT 共存时的资源占用。

## 2026-09-03 连续 10 分钟 1.0× Replay

冻结 replay 取自 2026-08-30 post-live 音频的 31:30–41:30，转为 16 kHz mono PCM；源音频、replay WAV、参考文本及 manifest 均以 SHA-256 固定。Qwen3-ASR 与 `small.en` 各自完成一次完整 600 秒墙钟回放，均无空 final、无 swap 增长，也没有 provider 掉线。

| 模型 | 流式协议 | WER | partial / final | 墙钟比 | final 响应 P50 / P95 | 峰值 RSS |
|---|---|---:|---:|---:|---:|---:|
| `Qwen3-ASR-0.6B MLX 8-bit` | MLX Audio 原生 WebSocket partial/final | 5.09% | 120 / 123 | 1.0097 | 308 / 363 ms | 1.1532 GiB |
| `whisper.cpp small.en F16` | 持久 HTTP 5 秒窗口；partial 为 harness 探针 | 6.56% | 120 / 120 | 1.0003 | 214 / 277 ms | 0.7586 GiB |

Qwen 在连续音频上比 `small.en` 低 1.47 个 WER 百分点，并且 partial/final 是 provider 原生事件，因此保持 provisional winner。`small.en` 峰值 RSS 少 0.3946 GiB，是低内存 fallback。

两套 latency 契约不同，不能把表中延迟当成严格同构排名：Qwen 记录 final 相对最新 PCM 块可用的返回时间；`small.en` 记录完整 5 秒窗口可用后 HTTP final 请求的响应时间，其 partial 是 runner 在 1.5 秒重新转写同一窗口得到。完整对比位于 `data/benchmarks/live-sermon-translation-v1/runs/local-asr-streaming/qwen-vs-small-10min-1x-20260903.json`。

该 replay 的参考仍是 GPT-Transcribe 模型审核文本而非人工 Gold，且本轮没有同时运行 MiLMMT、浏览器或录音。下一门禁是 Qwen3-ASR + MiLMMT Q8 的 50–60 分钟共存 soak，然后再对剩余五个候选执行同一 replay。

## 2026-09-03 Qwen3-ASR + MiLMMT Q8 共存 Smoke

在连续 ASR replay 之后，同一份 600 秒 PCM 又以 1.0× 运行一次 Qwen + MiLMMT 自动化共存 smoke。每个 Qwen final 通过 Local Live Gateway 的 `contextPolicy=none` 接口调用 MiLMMT Q8，继续使用冻结 A0 prompt 和 decoding contract；runner 同时增量写录音 WAV、轮询前端 HTTP 并采样两个 provider 的 RSS 与系统 swap。

结果为 120/120 条翻译成功、0 failed、0 queue full；MiLMMT P50/P95 为 444/599 ms。Qwen 峰值 RSS 1.1446 GiB、Ollama MiLMMT 峰值 RSS 5.4477 GiB，同采样合计峰值 6.5916 GiB；594/594 次前端健康探针通过，swap 增长为 0，录音 PCM 与输入逐字节一致。

本轮 Qwen WER 为 5.55%，相同音频的 ASR-only 运行是 5.09%。final 数也从 123 变为 120；由于 MLX Audio 使用实时 VAD/端点，先把它视为端点非确定性复测项，不能凭单次差异认定资源竞争导致质量下降。

该 run 仍不是完整浏览器门禁：前端只是 HTTP 健康探针，录音由 runner 写入，不是麦克风/MediaRecorder。完整报告位于 `data/benchmarks/live-sermon-translation-v1/runs/local-asr-streaming/qwen-milmmt-coexist-10min-1x-20260903/report.md`。下一步是在不改变前端协议的前提下给 Gateway 增加 Qwen provider，然后执行真实 session + 浏览器录音的 50–60 分钟 soak。
