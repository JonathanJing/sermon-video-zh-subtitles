# MiLMMT-46-4B MacBook 运行时选择与证道后训练方案

更新日期：2026-09-03  
状态：`runtime_bakeoff_ready_training_manifest_pending`

## 结论

第一阶段优胜模型固定为 `xiaomi-research/MiLMMT-46-4B-v1.0`。下一步不是立即训练，而是先在目标机器 `MacBook Pro / M1 Max / 64 GB` 上冻结运行时和量化：

- 暂定主候选：MLX 5-bit；
- 兼容性候选：llama.cpp GGUF `Q5_K_M`；
- 体积边界：MLX 4-bit、GGUF `Q4_K_M`；
- 质量确认：MLX 6-bit、GGUF `Q6_K`；
- 质量参考：官方 BF16 的 text-only MLX 转换。

社区 MLX 5-bit 与 GGUF 只用于快速赛马。最终生产产物必须从固定的官方权重，或后训练后合并的同一份 BF16 checkpoint 自行转换并保存 hash。

运行时选择和训练基础模型是两件事：无论 MLX 还是 llama.cpp 胜出，训练都从官方 BF16 v1.0 开始，不能从 MLX/GGUF 量化文件反向训练。后训练合并后，再导出胜出的主格式和一个回退格式，并重新验证量化回归。

## 模型身份与约束

| 项目 | 冻结值 |
|---|---|
| 上游模型 | `xiaomi-research/MiLMMT-46-4B-v1.0` |
| revision | `aa3262750cf493cc638fc9b82fcd26de8b0068fb` |
| 架构 | Gemma 3 4B 派生；官方 artifact 含多模态 wrapper，当前任务仅使用文本部分 |
| 任务 | 英文到简体中文的纯 completion 翻译 |
| 推理模板 | 官方 `Translate this from English to Chinese (Simplified): ...` |
| 解码 | deterministic：temperature 0、top-k 1 |
| 禁止项 | chat template、system/user turn 包装、`MiLMMT-46-4B-Pretrain` |

这里的“base 优胜模型”是项目角色，不是模型训练阶段名称。v1.0 本身已经过持续预训练、SFT、RL 和模型合并，所以领域训练必须低学习率、短周期并持续与原始 v1.0 比较，防止把已有翻译能力训坏。

使用前归档模型卡、Gemma 条款、上游 revision 和文件 SHA-256。向教会统一分发任何模型 artifact 前，另做许可证审查；本文件不把可下载等同于可任意再分发。

## R0：先选 MacBook 运行时和量化

### 候选矩阵

| 编号 | 后端与 artifact | 约体积 | 用途 |
|---|---|---:|---|
| R0 | MLX BF16 text-only | 约 8 GB | 质量参考，不作为默认部署 |
| R1 | MLX 5-bit / group 64 | 约 2.7 GB | 暂定主候选 |
| R2 | llama.cpp GGUF `Q5_K_M` | 约 2.8 GB | 暂定回退候选 |
| R3 | MLX 4-bit | 约 2.2 GB | 最小体积边界 |
| R4 | GGUF `Q4_K_M` | 约 2.5 GB | 最小体积边界 |
| R5 | MLX 6-bit | 约 3.2 GB | 检查 5-bit 是否损失质量 |
| R6 | GGUF `Q6_K` | 约 3.2 GB | 检查 Q5 是否损失质量 |

快速赛马的已知社区入口为：

- MLX 5-bit：`translate-studio/MiLMMT-46-4B-v1.0-5bit-MLX`，当前已核实 revision `8227b351ad0580e35ff3f92f5f8c623da1788c48`；
- GGUF：`mradermacher/MiLMMT-46-4B-v1.0-GGUF`，当前已核实 revision `765aa350dc9aa28c41e2a9e34e1b25d56c0d3911`；只下载单个 `Q4_K_M/Q5_K_M/Q6_K` 文件；
- MLX 4/6-bit：分别使用 `translate-studio/MiLMMT-46-4B-v1.0-4bit-MLX` 与 `...-6bit-MLX`，下载时再记录精确 revision。

当前 Mac 已有 `mlx-lm 0.31.3`，但没有 `llama-cli`/`llama-server`；MiLMMT 量化文件尚未进入本地 cache。磁盘当前约有 238 GiB 可用，足够完成单文件赛马，但不能下载包含全部 GGUF 量化的约 37 GB 仓库快照。安装/构建 llama.cpp 并完成版本 receipt 是 R0 的准备步骤。

社区转换者在 4,500 条 FLORES+ 样本上报告：5-bit 相对 BF16 的平均 chrF++ 差异不显著，而 4-bit 有可测退步。这是选择 5-bit 为起点的证据，不是证道域验收结果。GGUF 社区仓库提供多个静态量化但没有本项目语料生成的 imatrix，因此最终 GGUF 应从同一份合并 BF16 自行转换，并在工具支持时用独立证道校准集生成 imatrix。

### 同条件评测

量化选择必须使用新的、非 `untouched_test` 的 dev 集。建议 300–500 段，按完整证道分组，至少覆盖：

- 普通叙事、经文原句、神学术语、人物与地名；
- 数字、否定、转折、引用关系；
- 口语、幽默、ASR 噪声、长句和句子中断；
- 20/40/80/160 token 的实时前缀。

目前 5 篇、239 段冻结集仍是最终 `untouched_test`，不得用于选择 MLX/llama.cpp、量化、上下文或提示词。现有仓库还没有合格的非 test 证道 dev manifest；这是正式赛马前必须补齐的数据产物。

所有候选必须保持：同一 source revision、同一 dev 输入、原生 completion prompt、无 chat template、temperature 0、top-k 1、相同输出上限。MiLMMT 的停止条件需核对 EOS token `1` 和 `<end_of_turn>` token `106`；出现跑满 max tokens、重复或空输出立即 fail closed。

### 记录指标

- warm TTFT p50/p95/p99、prefill tok/s、decode tok/s、整段 wall time；
- 冷启动、常驻/峰值内存、swap、memory pressure；
- 75 分钟实时前缀 replay 的延迟漂移和热稳定性；
- 与本地 ASR 共存时的 TTFT、吞吐和峰值内存；
- chrF++，以及可用时的 COMET/xCOMET；
- 经文、数字、否定、专名准确率；
- 错误语言、截断、重复、无依据增译和意义反转。

现有非流式 runner 只能给出整段延迟，不能证明首字延迟。正式 R0 必须增加 streaming 计时，分别记录请求发出、首 token 和完成时间。

### 暂定门禁与决策规则

- 300–500 段均非空，输出语言正确率 100%，无重复循环；
- curated hard set 的经文、数字、否定严重错误为 0；
- 相对 BF16 的 chrF++ 下降不超过 0.2，且 Sol 盲审无显著语义退步；
- 输入不超过 80 token 时，warm model-only TTFT p95 目标不超过 350 ms；
- decode 不低于 25 tok/s；
- translation-only 峰值内存目标小于 6 GiB、无 swap；ASR 共存时通过整机资源门禁；
- 75 分钟后 p95 延迟漂移小于 20%。

门禁在看结果前冻结。若 MLX 在质量相当时 TTFT 或吞吐领先约 10–15%，采用 MLX 5-bit 为 MacBook 主运行时；若 llama.cpp 性能差距在约 10% 内且 C++ 服务化、监控和恢复明显更简单，则采用 `Q5_K_M`。无论谁胜出，都保留另一种格式作为可回滚产物。

当前倾向是“MLX 5-bit 主、GGUF Q5_K_M 备”，但在 R0 receipt 完成前不是最终决定。MacBook 中央生产者的结论也不自动决定未来 iPhone 端运行时；iOS 客户端需要另做功耗、内存和后台音频评测。

## R1：冻结后训练输入

R0 结束后冻结：官方 model revision、tokenizer、原生 prompt、runtime、主/备量化、dev/test manifests、数据 schema 和评测版本。

训练数据继续 fail closed：

- 只使用明确标记 `trainingEligibility=eligible` 的 `train` 样本；缺字段即禁止；
- `dev` 只用于选择 checkpoint 和超参数，`untouched_test` 只在最终验收使用；
- 按 `sermonId` group split，同一证道不得跨 split；
- source/target 都保存来源、审核状态、授权依据和 SHA-256；
- 5 个 test 视频及其改写、参考译文和模型预测不得进入训练；
- 不把教师模型生成文本称为蒸馏数据；只有取得相应训练用途授权且审核通过的译文，才能作为普通监督训练数据。

用户已经确认这些数据允许用于本项目后训练，而且本项目把经人工/模型审核的双语对作为普通监督数据，不定义为知识蒸馏。仓库内旧记录仍带有历史 `source_training_rights_unconfirmed` / distillation blocker；在批量训练前必须生成授权 receipt 并重新核对每条记录，只有验证器输出 `eligible` 的样本才可进入 shard。也就是说，授权方向已确定，但机器可读 manifest 还没有完成迁移，当前不能直接忽略旧 blocker 启动训练。

样本序列化固定为：

```text
Translate this from English to Chinese (Simplified):
English: {source.contentText}
Chinese (Simplified): {target.contentText}<eos>
```

不套 chat template，训练 loss 只覆盖中文 target 与 EOS。`contentText` 保留口语重复、自我纠正、否定与标点，移除时间码、字幕控制符、HTML、JSON 和 speaker label；经文/专名元数据用于分层评测，不默认塞进 prompt。

## R2：DGX Spark 领域 LoRA/SFT

第一阶段只做保守 LoRA，不直接全参训练，不从 GGUF/MLX 量化权重训练，也不先做 RL 或知识蒸馏。

- 基础权重：固定 revision 的官方 BF16 v1.0；
- text-only：冻结/排除 vision tower 与 multimodal projector；
- 目标模块：先从实际模型 `named_modules` 生成 receipt，再选择语言模型的 attention `q/k/v/o`；是否加入 MLP `gate/up/down` 作为消融，禁止用宽泛 glob 误选视觉模块；
- 初始对比：rank 16 vs 32，alpha 32 vs 64，dropout 0.05；
- BF16，sequence length 1024 起步，micro-batch 1–2，gradient accumulation 到 effective batch 32–64；
- 学习率先搜 `1e-5 / 2e-5 / 5e-5`，1–3 epochs，按 dev early stop；
- 每个 checkpoint 同时报告证道域 dev 与通用 EN→ZH 保持集，防止灾难性遗忘。

先做 500–1,000 条、1 epoch pilot，验证 loss mask、EOS、模块选择、显存和导出链；通过后才运行全量。按当前约 2.0–3.3M token/epoch 的预估，单台 DGX Spark 全段 LoRA 3 epochs 约 3–7 小时，实际以 pilot tok/s 重算。

## R3：实时前缀适配

完整句领域模型通过后，才增加实时前缀训练：

- 每个合格完整段生成 3–8 个自然前缀，输入模拟 ASR 滚动窗口；
- target 只包含当前已能稳定翻译的内容，不能让模型提前猜尚未说出的后文；
- 建议完整段与前缀按 30:70 或 40:60 混合，学习率降到 R2 的约一半，1–2 epochs；
- 额外评测 first-readable latency、无依据预判、译文 revision rate、append-only 稳定性；
- `WAIT/WRITE`、去重和字幕提交策略优先由 App 状态机控制，不把 JSON 或助手式解释混进主翻译模型。

前缀数据量预计是完整段的 2.5–4.5 倍，单台 Spark 约 8–24 小时。单个认真候选从 pilot、R2、R3、合并、量化到 MacBook 回归，预计 14–36 小时；两组超参数和 seed 验证约 2–4 天。

## R4：合并、导出和最终验收

产物链固定为：

```text
官方 BF16 v1.0
  -> LoRA adapter
  -> merged BF16
  -> 主格式：MLX 5-bit 或 GGUF Q5_K_M
  -> 备格式：另一后端的等价量化
  -> MacBook dev 回归 + ASR 共存 + 75 分钟 soak
  -> 一次性 untouched_test + Sol High 盲审
```

每一步保存 base revision、数据 manifest/hash、prompt version、训练代码 revision、seed、adapter hash、merged hash、转换工具版本、量化参数、artifact hash 和评测报告。后训练后若 5-bit/Q5 不再满足质量门禁，允许升到 6-bit/Q6；不能根据 test 结果反复调量化。

## 执行顺序

1. 建立新的 300–500 段证道 dev/前缀评测集，保持 239 段 test 不可见。
2. 固定并下载 R0–R6 所需的单个 artifact；不要下载含全部 GGUF 量化的整个仓库。
3. 用 raw completion 和 streaming runner 完成 MLX/llama.cpp 同条件赛马。
4. 冻结 MacBook 主/备运行时与量化。
5. 清除训练授权 blocker，生成 train/dev manifests 并验证零泄漏。
6. 在 DGX Spark 做 R2 pilot、全段 LoRA，再决定是否进入 R3 前缀适配。
7. 从同一 merged BF16 导出主/备格式，在 MacBook 重跑回归和最终验收。

机器可读计划位于 `data/benchmarks/live-sermon-translation-v1/milmmt-post-training-v1.json`。
