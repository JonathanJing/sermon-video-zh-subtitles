# MacBook Q5 / DGX BF16 最小运行时对照契约

日期：2026-09-06。状态：冻结开发输入与计时定义；本文件不代表新运行已经完成。对应 [手机媒体方案](PLAN.zh.md) 的 M1 运行时诊断，手机媒体 M0 和后续 ASR 音频实验分别记账。

## 1. 这次比较回答什么

比较同一 v4.1 来源模型在 **MacBook MLX Q5** 与 **DGX 合并 BF16** 两种可部署运行配置上的暖调用成本、输出完整性及输出差异。两端量化、运行库、硬件不同，结果不能归因于纯硬件、纯量化或云端位置；本地进程计时也不包含手机上传、ASR、断句、网络、TTS 或耳机输出。

优先复用已存在的合并 BF16，保持两端均为合并权重。旧 DGX 基准使用未合并 PEFT LoRA，不能冒充此次合并 BF16 的复跑。若现有合并文件无法核验，先记录阻塞；改测未合并候选必须另设 arm 并明确增加了合并方式这个变量。

本次是重复使用开发数据的性能/完整性诊断；不训练、不打开 sealed final/untouched_test、不重跑付费评审，不产生新的质量胜负或发布资格。v4.1 仍是 `releaseEligible=false` 的实验候选。

## 2. 冻结的 12 条输入

- 新文件：[runtime-samples.jsonl](runtime-samples.jsonl)，25,203 bytes，12 行；SHA256 `40225fdf940901428ecff712c50d210bc6ca4f3717569cf7d4d67ad7e1efdeec`。
- 原开发文件：旧 `sermon-video-zh-subtitles-ios-design` worktree 的 `data/benchmarks/milmmt-v4-pilot-dev80-v1/samples.jsonl`，80 行；SHA256 `e6af2e3ae53cedc9f038ea0349e2e9eb5a0afb6c2fdbbd818c3212b8cdeb1a0f`。
- 12 条全部属于旧 Mac/DGX 共同的 30 条延迟子集，原文和 prompt 与两端旧 candidate 生成记录逐条一致。按短/自然长段、经文文字/编号、否定与条件边界覆盖挑选，不按新运行速度或胜负选择。
- `sourceIndex` 为原开发 JSONL **从 1 开始**的行号；`sourceRowSha256` 对该原始行的 UTF-8 字节计算，排除换行符。每项另存原文件、英文及 prompt 的哈希。
- `source` 与兼容字段 `sourceEn` 完全相同；没有参考中文、评审译文、未来英文或上下文示例。`diagnosticTags` 只用于报告，不能进入模型 prompt。

| 新行号 | 原行号 | 分层 / 原词数 | 原始 sample ID | 保留的诊断内容 |
|---:|---:|---|---|---|
| 1 | 31 | short / 12 | `live-grain::3nCjC894qHs_seg_0035:cue_00566:cue_00567` | 教会与耶稣的关系 |
| 2 | 34 | short / 9 | `live-grain::0ukVuw8CZpI_seg_0008:cue_00144:cue_00144` | 经文式问句，未补经文出处 |
| 3 | 35 | short / 14 | `live-grain::GNTHmg2a8TM_seg_0021:cue_00358:cue_00359` | Jerusalem、no longer |
| 4 | 45 | short / 7 | `live-grain::qzpxdENv6a4_seg_0038:cue_00638:cue_00638` | 原有 `4:4-7`，不推测书名 |
| 5 | 55 | short / 7 | `live-grain::3nCjC894qHs_seg_0015:cue_00211:cue_00211` | Nero did not |
| 6 | 57 | short / 8 | `live-grain::Ab2zQbGwmY8_seg_0026:cue_00476:cue_00478:prefix1` | can't / unless，原有未完条件句 |
| 7 | 5 | natural / 91 | `3nCjC894qHs_seg_0007` | 教会叙事、否定 |
| 8 | 6 | natural / 141 | `3nCjC894qHs_seg_0029` | Babylon、专名、90ft；原有未完成结尾 |
| 9 | 11 | natural / 146 | `7iMGdft4cfQ_seg_0010` | 国度、条件与否定关系 |
| 10 | 18 | natural / 146 | `ArgSmQwhWp0_seg_0019` | 身份、施受关系、宗教伪善 |
| 11 | 28 | natural / 87 | `H2PAN4J8nn4_seg_0029` | Solomon、经文转述、否定 |
| 12 | 30 | natural / 106 | `qzpxdENv6a4_seg_0046` | 否定指令、耶稣的同在 |

“natural”沿用旧开发集的自然长段分组，不保证每段都是完整句子。短项来自离线字幕边界模拟，并非实际本地 ASR emission；原拼写、重复、未完边界不修正，不能据这些时间戳推导真实 ASR 延迟。若输出擅自补完未说出的内容，保留为诊断结果。

## 3. 模型和解码冻结

| 项目 | 两端共同约束或应核验的身份 |
|---|---|
| Base | `xiaomi-research/MiLMMT-46-4B-v1.0`，revision `aa3262750cf493cc638fc9b82fcd26de8b0068fb` |
| v4.1 adapter 来源 | SHA256 `16ef2fb03cd4468a4d0288b450905e80fc90299adb983d0d3338384975254bba`，原生强度 1.0；已合并时不能再次叠加 adapter |
| Mac 候选 | `milmmt-sermon-v41-experimental-mlx-q5`，affine 5-bit / group64，非量化参数 BF16；权重文件 SHA256 `6057e793922b8aa0c30c5180b490d8e5cac14a3dcd1a000b1b906d0da8fa6987` |
| DGX 候选 | `milmmt-sermon-v41-experimental-merged-bf16`，模型配置 `Gemma3ForConditionalGeneration`；使用现有 safe-merge 文件，不在本轮重新合并 |
| Tokenizer / 特殊词 | 两端输入 token IDs 应相同；`add_special_tokens=false`，不加 BOS，不调用 chat template；EOS `[1,106]` |
| Prompt | `milmmt-official-text-translation-v1`，逐字使用每行冻结的 source-only prompt |
| 解码 | greedy，temperature 0 / do_sample false，num_beams 1，repetition penalty 1，最多 512 新 token；不继承模型文件内未明确采用的 sampling defaults |
| 状态 | 每次新 KV cache，无历史对话、router、RAG、译文修正或后处理；记录 raw text 和原始 token 证据 |

合并 BF16 的 3 个权重分片预期 SHA256，来自已核验的旧合并回执；本轮运行方必须核对目标机器实际文件，不能只信目录名：

| 文件 | 预期 SHA256 |
|---|---|
| `model-00001-of-00003.safetensors` | `47289601e956e211dd93fae970b76b16d332d2d247e67c33a8af8878ece46e6a` |
| `model-00002-of-00003.safetensors` | `3787cb56aa0d08b33a8bed7d6ec7dabe2c6cb5a84ba051d36335e7c1029f9cb8` |
| `model-00003-of-00003.safetensors` | `972b5054a480b25dfb0bef29b3b283ad1b42fff30d185cb3ea9972fa9cd0b093` |
| `tokenizer.json` | `33753cc9825494361904313ed469063a8b3e05f1648c18e4b2936f5aa3c78202` |

运行报告同时保存实际库版本、模型/config/tokenizer manifest、进程/设备身份、脚本 SHA256、精度、attention backend、线程/电源/并存工作负载。旧 Mac 为 MLX 0.32.2 / MLX-LM 0.31.3；旧 DGX 为 PyTorch `2.13.0a0+8145d630e8.nv26.6.54250401` / Transformers 4.57.1 / PEFT 0.18.1。这些是历史版本，不冒充新运行环境。

## 4. 公共计时口径

每台机器使用本机单调时钟；不直接相减两台机器的绝对时间。每次调用 `t0` 放在 source→官方 prompt / tokenization 之前。对照首先报告现有 `MLXEngine.translate` 已提供的 `firstChineseMs` 与 `elapsedMs`；后者仅在正常 EOS 完整返回时可作为本次完整调用时间。

| 指标 | 边界 |
|---|---|
| `engineInitMs` | 初始化完整 engine 前 → engine 可用并完成设备同步。若包含 imports、权重校验和文件扫描，明确列出，不能称纯加载时间 |
| `modelLoadMs` | 精确包围实际模型 load/from_pretrained，结束前物化权重并同步；仅在有对应观测点时给数字。不能拆分时记 unknown |
| `tokenizationMs` | 本次调用中 source→prompt 和 encode 的实际 CPU 耗时；若只包围 encode 则另标。另跑一次 encode 只能叫独立微测，不能代替本次分项 |
| `inputPrepareMs` | token IDs 构造设备输入到对应物化/传输/同步完成；无法分离时记 unknown |
| `firstTokenMs` | `t0` → 首个生成 token ID 在 CPU 可见，不能把未同步 kernel enqueue 作为终点 |
| `firstChineseMs` | `t0` → CPU 侧输出文本第一次出现 U+3400–U+9FFF 中文字符；不以首 token、空白或替代字符代替 |
| `fullEosMs` / `elapsedMs` | `t0` → 正常 EOS、detokenizer flush、generator close 和最终设备同步完成；包含当前实现的返回前校验/组装开销时须说明 |
| `generationMs` | 输入准备及前置同步结束 → 完整生成与后置同步完成；有真实分界时另报，不由不完整分项猜测 |
| `clientWallMs` | 测量方进入本地调用到返回的墙钟；若以后改为 HTTP，另标 transport，包含请求/响应开销，不能混作纯模型数字 |

两端必须记录 `timingBoundary`：Mac 原生 `stream_generate` 的 delta 发出，与 HF CPU token callback 累积解码不是完全相同的首中文边界。优先使公共首中文指标落在相同应用层 emit 回调；若暂时保留不同边界，明确标作各运行时“CPU 可见首中文”，不得据其小差异声称硬件 prefill 加速。额外 instrumentation 不改变原输出或解码设置。

MLX 最终同步须覆盖生成使用的 stream；CUDA 在计时开始前与结束时 `torch.cuda.synchronize()`，不得只量异步提交耗时。不要为了形式对齐给每个 token 额外插入昂贵同步；保留运行库自身 CPU 可见 token 的同步与开销。MLX lookahead 和流式缓冲也属于实际运行时成本，不能事后扣除。

现有 [MLXEngine](../../scripts/serve_milmmt_v41_local.py) 的 `elapsedMs` 从 tokenize 前开始并在 `finally` 中同步，适合复用；constructor 先 `verify_package` 再导入和 `load(lazy=False)`，包住整个 constructor 的时间应标 `engineInitMs`。同一线程加载和生成；不启动、重启或改动已有服务来取得本地进程计时。

## 5. 最小执行与统计

1. 只读确认两端当前资源足够，再独立加载一个候选；保存模型初始化、可用内存、并存任务和失败信息。加载时间单列，不通过清 OS 文件缓存或停其他任务制造“冷启动”。首次启动应标 `process_cold / filesystem_cache_unknown`。
2. 预热新 JSONL 第 1 条短句与第 7 条自然段各一次，单独保存结果，不计正式统计。
3. 两端同一冻结文件，各运行 3 轮：文件正序、逆序、正序；每次新 KV。每端 36 次正式调用、2 次预热，仍只有 12 个不同输入。
4. 每个输入先取 3 次中位数，再对 short/natural 各 6 个输入报告 p50/p95/max 和每条配对差。p95 使用线性插值 `rank=(n-1)*0.95`。两端配对差按同一 sample ID 计算，不以总体中位数相减冒充配对差。
5. 保留每次源/prompt/token IDs 哈希、input/generated token 数、原始译文、首中文、完整 EOS、取消/超时/error、完整时间和运行顺序。若接口只提供生成 token 摘要，保存摘要并标明不能据此复原 token 序列。
6. 所有 36 次调用都进入完整性分母。空输出、没有中文、到 512 上限仍无 EOS、超时或错误不能算完整成功；失败样本保留原结果，不为凑满成功次数静默重跑。成功延迟分位数附成功率及失败 ID；存在失败时该轮只能是部分诊断。

每组只有 6 个输入，p95/max 为描述数据，不是服务 SLA。比较完整耗时要同时看输出 token 数和内容：少译或截断不能成为速度优势。两端因 BF16/Q5 产生不同 token/text 本身不判失败，也不证明质量升降。若与同一 runtime 的旧输出相比有差异，保存逐条差异并查模型/解码/环境，不能新付费评审或改原参考来“对齐”。

## 6. 可复用的历史证据

以下路径均相对旧 `sermon-video-zh-subtitles-ios-design` worktree，2026-09-06 已读取并重新计算文件哈希。大权重的目标机器状态由新运行方另验。

| 文件 | SHA256 |
|---|---|
| `data/reports/teacher-b-astra-medium-v1/v41-macbook-q5-v1/latency/run-report.json` | `885304b8cdb64e97164f65b2cee0a33ac39b290f61ab3151c18816fc2a9d8203` |
| `data/reports/teacher-b-astra-medium-v1/v41-macbook-q5-v1/latency/measurements.jsonl` | `e4a2ef43bb5353a9497c19db285a285d622da9585a3a8dff8f82a9c22ec71b29` |
| `data/reports/teacher-b-astra-medium-v1/v41-macbook-q5-v1/dev80/generation/candidate.jsonl` | `dada8bb94ac0ae9ef8c2fba156decc67be5ef51cab8581fbd74670039515bd4c` |
| `data/reports/teacher-b-astra-medium-v1/v41-dev80/generation/candidate.jsonl` | `8f9491ce81a517900538460d60ed5777a55fe30d440172cd7d2d4eb61ad4089a` |
| `data/reports/teacher-b-astra-medium-v1/v41-latency-ab-v1/run-report.json` | `4b06fb7d4168c50bd9b3bf6bebbe981aab4d0c1327e144e43e23a42de4e65592` |
| `data/reports/teacher-b-astra-medium-v1/v41-latency-ab-v1/measurements.jsonl` | `331586dc7667188f51274e5dd3e345bca67fd4b5f018ae29e6bed90ea45f6f9b` |
| `data/reports/teacher-b-astra-medium-v1/v41-macbook-q5-v1/merge-verification.json` | `6079a13bcc69dc018d5361274d07324a33af2cb824feeb9b59f3eed917348116` |
| `scripts/run_milmmt_mlx_paired.py` | `578863e8bc365597b1ae8a1da11690ff6a7ae1652317adaf61dcb527e9f046e8` |
| `scripts/run_milmmt_latency_ab.py` | `498906aa6b7da47640d467b953d3488d40a2458c1f80b983c7528ebde4d53371` |
| `scripts/run_milmmt_paired_diagnostic.py` | `80d528162bb2bbfd0eff9c7891507703b2177eeaa16cf20963c7b9f5edb23506` |

旧 Mac 两臂是同 runtime/Q5 的 base 与 candidate，短字幕 candidate 完成 p50 238 ms、自然段 2.171 s；旧 DGX candidate 是未合并 LoRA，短字幕完成 p50 698 ms、自然段 8.89 s。这些历史数字还排除了 tokenization/加载，首中文观测边界也不同，不能直接推导此次合并 BF16 与 Q5 的加速比。旧 Mac harness 在进入 `wired_limit` 后开始计时、退出前结束；原生 `stream_generate` 则把该 context 的进入/退出、模型遍历、wired-limit 设置与恢复、stream 同步都纳入调用。这一范围差异经源码核对，但各项占多少时间仍需单独 profiling，不能凭差额归因。

旧脚本可复用 prompt、EOS、输入身份检查和“先逐输入中位数再汇总”的统计逻辑。`run_milmmt_mlx_paired.py` 对完整 dev80/regression30 哈希有限定，`run_milmmt_latency_ab.py` 的选择器要求 natural10/short20；不能直接把新 12 行塞进去，再改掉旧限制。新入口保存自己的 schema、脚本哈希和结果目录。

## 7. 后续 ASR 可复用的固定原声

已找到并验证 [原始证道 45 秒 WAV](../local-live-poc/artifacts/benchmarks/v41-poc-integration-20260905/source/original-sermon-1906-1951s-16kmono.wav) 与 [来源转换回执](../local-live-poc/artifacts/benchmarks/v41-poc-integration-20260905/source/original-sermon-1906-1951s-source.json)。媒体及完整日志保持 ignored，不复制进 Git。

| 身份 | 已重新核对的值 |
|---|---|
| 原视频 | `0SMeXJXsqKM`；canonical URL 为来源回执中的 YouTube 原链接 |
| 时间轴 | 原下载文件 `[1906,1951)` 秒；位于原已批准证道 `[1876,3866)` 秒内 |
| WAV | 45.000 秒、16,000 Hz、mono、PCM16、720,000 样本，1,440,078 bytes |
| WAV SHA256 | `2ba2651b0ce6e38bb25541a58c98442da426238de9085c615d83ac0263579c22` |
| PCM payload SHA256 | `147e9a49eb90877c5a9a3d7ce690cc6a8d7c63d3c9afa28d30e764c7cc44d39e` |
| 来源回执 SHA256 | `5138498261b8087d81e56cbc0d6d52f389eb47db6a76f993daec8af364b53914` |
| 原始 M4A SHA256 | `5af241408951b17c1c97532b4f8a4aaefe5b84e155fb970fddad00362e024c72` |
| 原时间窗口批准文件 SHA256 | `a6b38b246db5c8efc91242f8d15c100eea386240191c672ebf57e4fcd74b87b6` |

本轮核对了 WAV header、完整文件/PCM 哈希、源 M4A、来源回执和批准文件哈希；未播放、录音或运行 ASR。该文件直接裁自原下载音频，无额外响度处理，不是旧麦克风录音。旧文件回放已记录 450 个 100 ms 帧及 17 个 ASR/translation final，只是历史文件路径证据，无手机收音、耳机发声或人工 Gold 证明。

后续可两端以相同 1 倍速、100 ms PCM、同一 ASR 分段/尾静音策略对照；实际 ASR 模型和量化也必须单独冻结。此 45 秒与上面的 12 条文本不构成一一配对，不把旧 ASR 输出变成参考真值，也不把文件回放标为真实手机声学路径。
