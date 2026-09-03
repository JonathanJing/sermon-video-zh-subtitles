# MiLMMT-46-4B 证道翻译后训练与 MacBook 优化计划

更新日期：2026-09-03  
状态：`plan_frozen_training_data_blocked`

## 决策

下一阶段以 `xiaomi-research/MiLMMT-46-4B-v1.0` 为 MacBook 主优化模型。当前 Q8_0 Ollama run 是 A0 推理零点；训练不从 Q8 GGUF 开始，而从固定 revision 的官方权重进行 LoRA/SFT，合并后再分别生成 MLX 与 GGUF 量化产物。

本阶段优化四件事：

1. 只使用明确允许训练的 `train` 样本做领域后训练；
2. 固定 MiLMMT 原生英译简中模板，清理 `contentText`，避免多余 chat/system 包装；
3. 用 `dev` 比较数据清理、上下文、训练超参数和量化；
4. 在 M1 Max 64 GB 上比较 Ollama 与 MLX 的质量、速度、内存和稳定性。

239 段冻结 Benchmark 持续保持 `test / untouched_test`。其英文、Sol-reviewed 中文、模型预测和错误分析均不得用于训练、早停、提示词选择、量化选择或超参数选择，只在方案锁定后用于最终验收。

## 当前零点

固定运行：`MB-B4-MiLMMT-46-4B-v1-Q8-Ollama`

| 指标 | 当前值 |
|---|---:|
| 完成率 | 239 / 239，0 error |
| BLEU-zh | 35.3638 |
| chrF2 | 33.4680 |
| 严格术语召回 | 68.125%（327 / 480） |
| 解码速度 | 54.753 tok/s |
| 平均 / p95 延迟 | 2.736 s / 3.981 s |
| 进程树峰值 RSS | 13.1274 GiB |
| swap 增量 | 0 GiB |

这些数字只属于当前社区 Q8_0 GGUF、Ollama 0.33.3、ctx 8192 的 translation-only run；不能外推到 MLX、其他量化或 ASR 共存场景。

## 数据门禁

当前冻结 Benchmark reference 的 `trainingEligibility` 是 `blocked`，并带有 `source_training_rights_unconfirmed` 与教师输出外部蒸馏未授权等 blocker。因此本计划可以先完成格式、验证器、上游模型转换和无训练的运行时实验，但在授权状态变为机器可读的 `eligible` 前不得生成训练 shard 或启动后训练。

训练数据必须同时满足：

- `split` 只能为 `train`；调参数据只能为 `dev`；
- `trainingEligibility` 必须显式为 `eligible`，缺字段按禁止处理；
- 以完整证道做 group split，禁止同一 `sermonId` 跨 train/dev/test；
- source 与 target 均有 SHA-256、来源、审核状态和授权依据；
- 不包含 5 个冻结 test 视频 ID，也不包含它们的改写、参考译文或候选预测；
- 教师生成中文只有在对应 provider 条款和项目授权均允许时才能进入训练。

## 数据记录与 `contentText`

机器可读 schema 位于：

`data/benchmarks/live-sermon-translation-v1/templates/milmmt-sft-record-v1.schema.json`

每条记录把训练文本与元数据分开：

- `source.contentText`：讲员实际说出的、已经核对的英文语义段；
- `target.contentText`：授权且审核合格的简体中文译文；
- `metadata`：证道 ID、时间范围、内容类型、经文、专名、来源质量和 hash；
- 经文、专名、审核意见等不直接塞进 prompt，先用于筛选、分层和误差分析。

`contentText` V1 规则：

- Unicode NFC、换行压成单空格、去首尾空白；
- 保留标点、否定、重复、自我纠正和口语连接词；
- 删除字幕控制符、时间码、HTML、JSON、speaker label 和非语义性的 `>>`；
- 不把前后段、术语表、审核意见或周六材料混入单段文本；
- source 和 target 为空、只有标点、hash 不匹配或语言错误时 fail closed。

V1 序列化固定为官方最小翻译格式：

```text
Translate this from English to Chinese (Simplified):
English: {source.contentText}
Chinese (Simplified): {target.contentText}<eos>
```

训练 loss 默认只覆盖中文 target 与 EOS；prompt token 不计 loss。是否加入历史上下文、术语检索或周六材料属于后续 A2/A3 消融，不修改 A1 的 V1 样本模板。

Tokenizer 固定 `add_special_tokens=false`，不套 chat template；训练 target 末尾只追加模型 EOS。这样与官方模型卡的纯文本调用方式一致，也避免 Ollama、MLX 和 Transformers 因额外 system/chat token 形成不同任务。

## 后训练路线

### PT0：数据资格与冻结

- 完成 source/target 授权核对；
- 生成 train/dev group split manifest；
- 运行重复、泄漏、语言、hash、长度和格式检查；
- 冻结数据版本、样本数、token 数和 schema hash。

### PT1：LoRA/SFT pilot

- 基础模型固定为官方 MiLMMT revision，不使用 GGUF 训练；
- 先做小规模 LoRA pilot，候选 rank、学习率、epoch 只在 dev 上选择；
- 以经文、神学术语、专名、否定/转折和 announcement 分层报告；
- 早停和 checkpoint 选择只看 dev，test 不参与；
- 保存 base revision、adapter hash、训练代码 revision、随机种子和完整数据 manifest。

初始搜索范围为建议值而非已锁定参数：LoRA rank 16/32、alpha 32/64、dropout 0.05、学习率 `1e-5` 至 `5e-5`、1–3 epochs。数据规模和 token 分布确认后再冻结 batch、sequence length、packing 与 gradient accumulation。

### PT2：质量门禁

先用 dev 比较 A0 与 A1。进入量化阶段的暂定条件：

- 严重错误不增加，尤其是 `meaning_reversal`、`unsupported_addition` 和 `scripture_misattribution`；
- 严格术语召回目标至少 72%；
- 自动指标不出现有意义退步；
- Sol High 主评分提高至少 0.25/5，或严重错误率相对下降至少 25%；
- 没有记忆训练句、跨段复制或异常长输出。

最终门槛在 pilot 前冻结；上面数值不能根据 test 结果回调。

## MLX 与量化实验矩阵

后训练得到同一合并权重后，再生成独立产物并保存各自 hash：

| 后端 | 量化候选 | 角色 |
|---|---|---|
| Ollama / GGUF | Q4_K_M、Q5_K_M、Q6_K、Q8_0 | 部署兼容、现有基线可比 |
| MLX | 4-bit、5-bit、6-bit、8-bit | Apple Silicon 原生速度与内存优化 |

每个产物必须使用相同 source、官方最小 prompt、temperature 0、top-k 1 和输出限制。运行顺序为：dev smoke → dev 全量质量/性能 → ASR 共存 replay → 50–60 分钟 soak → 锁定单一候选 → 最终 untouched test。

主选择采用 Pareto 门禁，不把速度与质量混成不可解释的单一分数：

1. 先淘汰严重错误或质量退步超限的版本；
2. 在合格版本中选择 p95 延迟最低且峰值内存较低者；
3. Q4 只有在语义与术语门禁均通过时才可成为生产候选；
4. Ollama 与 MLX 分别记录，不拼接两者最优单项。

同时比较 ctx 4096 与 8192；只有 dev 证明长上下文改善质量时才保留 8192。目标是 translation-only 保持至少当前 Q8 的质量，同时提高吞吐或降低峰值内存；生产资格仍需 ASR 共存和 soak 通过。

## 下一批可执行产物

1. 授权后的 train/dev inventory 与 group split manifest；
2. fail-closed 数据验证与 MiLMMT 序列化脚本；
3. 官方权重 LoRA/SFT pilot 配置与 adapter receipt；
4. 合并权重到 MLX 4/5/6/8-bit 和 GGUF Q4/Q5/Q6/Q8 的转换 receipts；
5. dev Pareto 报告和锁定候选；
6. 最后一次 239 段 untouched test、Sol High 盲审、ASR 共存 replay 与 soak 报告。

机器可读阶段配置位于 `data/benchmarks/live-sermon-translation-v1/milmmt-post-training-v1.json`。
