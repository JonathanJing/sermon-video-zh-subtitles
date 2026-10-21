# 复盘：20261021-john-thomas-voice

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

测试运行：在 DGX Spark（GB10）上为讲员 John Thomas 训练 Qwen3-TTS 单讲员音色（speaker key `john_thomas`），属于**训练工程 smoke**。素材只有一期 Mariners 播客《If I Had More Time | Jesus sends and resurrects His own》（两人对谈，40 分 12 秒），不能证明泛化。

- 结束状态：`succeeded_pending_human_review`（`outcome.json`）。训练、权重更新检查、试听生成和机器回转写都完成；用户听审尚未完成。
- checkpoint SHA-256：`3f722b17b8e204e60d376fc08ef631b9d55a6a1eb02c106d612bf12b5d855c8c`，在 Spark 的本轮结果目录 `checkpoints/checkpoint-epoch-0/`，从原始 Base 训练，没有覆盖已有 checkpoint。
- 证据边界：`productionEligible=false`，`humanApproval=false`。逐段讲员身份只来自 diarization 加用户确认的编号映射，没有逐段人工听审。`config/speaker-voice-registry.json` 未改动；用户听审确认后再另开 PR 新增条目。
- 授权：用户在主会话的原话“需要训练一个新的音色”“你需要并行去 Spark 里面单独训练一个John的音色。”，记为 `voice_training` 与 `voice_audition`，见 `decisions.ndjson`。正式配音的用途与适用语言等试听时确认。

## 总时间

自动汇总（核对后保留）：

- `2026-10-21-john-thomas-voice`（journal）：墙钟 12m51s；计算 12m51s，等待 0m00s，返工 0m00s（0 次重跑）；未结束阶段 audition.human-review

核对：04:26:10 开始暂存输入，04:37:47 回转写结束，04:40 把试听发给用户，约 14 分钟。journal 中 `train.sft` 与 `probe.generate-and-screen` 的结束行是事后补记（`note` 写了 Spark 文件的实际时间），所以自动拆分把 04:34–04:39 的空档也算进了训练阶段。两次中途停止（见“错误”）各重跑了一次准备和生成，共约 2 分钟。之后的用户听审时间不算在内。

对比 2026-09-05 Steve Bang Lee 音色（54 段、414.0 秒）：编码 27.9 秒，训练 126.7 秒；本轮 34 段、270.5 秒：编码 17.8 秒，训练 78.9 秒，按片段时长成比例。

## 各层模型、耗时与速度

本轮不是四层交付。下表按本轮实际阶段填写。

| 阶段 | 模型或后端 | 调用次数 | 计算耗时 | 音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|
| 讲员片段转写 | Qwen/Qwen3-ASR-0.6B `5eb14417`，Spark CUDA BF16，speech runtime 容器（12 GiB / 4 CPU） | 52 个 John 轮次 | ASR 和对齐合计约 2 分钟，含模型加载 | 1168.2 | 约 10× 实时（ASR+对齐合计） | 0 | `prep-receipt.json`、`spark/prep.attempt1.log` |
| 词级对齐 | Qwen/Qwen3-ForcedAligner-0.6B `c7cbfc20` | 52 | 同上 | 1168.2 | 同上 | 0 | 同上 |
| 筛选与切片 | 规则：丢弃每个轮次首尾句，4–15 秒，VibeVoice 覆盖率 ≥0.95，YouTube 覆盖率 ≥0.85，`>>` 换人标记 ±0.5 秒，MLX 8bit 区分出另一方 ±0.2 秒，峰值、响度、静音 | — | 第二次运行（复用第一次的 ASR）约 1 分钟 | — | — | 0 | `prep-receipt.json` |
| 训练集编码 | Qwen/Qwen3-TTS-Tokenizer-12Hz `7dd38ad4`，官方 `prepare_data.py` | 34 段 | 17.8 秒 | 270.48 | 15.2× 实时 | 0 | `training-receipt.json` |
| 单讲员 SFT | Qwen/Qwen3-TTS-12Hz-1.7B-Base `fd4b2543`，官方 `sft_12hz.py`（Qwen3-TTS `022e286b`），batch 1，梯度累积 4，学习率 2e-6，1 epoch，bf16，SDPA，seed 42；容器 32 GiB / 6 CPU，无网络 | 34 步 | 78.9 秒 | 270.48 | 3.4× 实时 | 0 | `training-receipt.json`、`spark/training.log` |
| 试听生成（L3 TTS 能力试听） | 本轮 checkpoint，`generate_custom_voice`，temperature 0.7，repetition penalty 1.05，max 768 tokens，自然语速 | 4（zh-Hans、ko、es、英文留出句） | 43.0 秒 | 57.36 | 1.33× 实时 | 0 | `audition-receipt.json` |
| 回转写筛查 | Qwen/Qwen3-ASR-0.6B `5eb14417` | 4 | 约 0.8 分钟，含加载 | 57.36 | — | 0 | `audition-receipt.json` |
| L1 词级对齐（MFA）、L2、文本质检、音频质检、L4 | not_run | | | | | | |

没有付费模型调用，Spark 上常驻的 llama-server 没有停止或重启。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 片段准备 | ASR 和对齐完成后报 `KeyError: 'end_time'` | MLX 8bit 的 VibeVoice 结果用 `start`/`end` 字段，BF16 版用 `start_time`/`end_time`；脚本按 BF16 的写法读取 | 占用资源后（ASR 已跑完） | 统一两种字段名；第一次的 ASR/对齐结果写过缓存，按轮次和模型版本核对后复用，没有重复转写 | 无（一次性工具） | 本报告 `tooling/prep_candidates.py` |
| 试听生成 | 启动后因“Demo script changed”停止 | 2026-09-21 试听清单记的 `scriptJsonSha256`（`ebdd5e…`）是 JSON 规范化后的哈希，脚本按文件字节（`cbd034…`）比较；两份文件逐字节相同 | 占用资源后（容器已启动，未加载模型） | 改为绑定文件字节哈希并注明原因 | 无 | 本报告 `tooling/probe_john.py` |

要补的预检：读取 diarization 结果前先检查字段名；比较哈希前先确认对方记录的是文件哈希还是规范化 JSON 哈希。

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 质量 | 补充 John Thomas 其他场次的录音，按整场划分 train/validation 后重训 | 本轮只有一期；训练 270.5 秒，验证 82.2 秒，都来自同一期 | 才能判断泛化和音色稳定性 | 用户提供素材 | 试听交付时询问 |
| 质量 | Qwen3-ASR 会把专有词转错（如 amillennialist），本轮 27 段因与 VibeVoice 不一致被排除 | `prep-receipt.json` 的 `vibevoice_text_disagreement: 27` | 用三方一致性过滤可以保证标签质量，但会损失约一半的长句 | 训练工具维护者 | 无 |
| 流程 | 把单期双人播客的讲员片段准备脚本收进 `packages/production` 或 `experiments/sermon-dubbing-poc` | 本轮使用一次性的 `tooling/` 脚本 | 下一位播客讲员可以直接复用 | 待定 | 无 |

## 实际覆盖范围

- L1：没有制作本期英文源文（主会话负责）。本轮只为训练做了 John 片段的 ASR、对齐和标签。
- L2：not_run。
- L3：只生成了音色能力试听（固定试听文稿，不是本期译文）：zh-Hans 13.92 秒（CER 0.030，只有“祂/他”同音字差异），ko 14.88 秒（CER 0），es 15.04 秒（WER 0），英文留出句 13.52 秒（WER 0）。MP3 两遍 loudnorm 后为 −18.2 至 −18.4 LUFS，全部能完整解码。正式配音 not_run，要等两位讲员的音色都具备对应语言能力。
- L4：not_run。

## 遗留状态

- Spark：`dgx-spark-benchmark/results/john-thomas-voice-20261021/` 存放 checkpoint（3.8 GB）、片段、清单、日志和试听 WAV，文件属主为 root（容器写入）。没有遗留的容器或 job hold。
- Mac：试听 MP3、原声对照、授权记录和完整收据在本轮 worktree 被忽略的 `artifacts/sermon-dubbing/2026-10-21-john-thomas-voice/`。
- Registry：未改动。等用户听审结果再决定。
- 本报告 `tooling/train_john.py` 与实际运行的版本相比，只把变量名 `authorization` 改成 `permission`（以免触发导出脱敏规则），文件名字符串保持不变。实际运行版本 SHA-256 为 `c7696643…`，其余三个脚本与运行版本逐字节相同。

## 外部可见的变化

无。没有 Dev 发布、TestFlight 或受保护分支推送。设备播放和场地验收为 not_run。
