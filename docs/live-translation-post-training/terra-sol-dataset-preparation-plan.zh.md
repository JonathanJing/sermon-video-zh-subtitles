# Terra 初译、Sol 复审的数据集准备方案

日期：2026-09-01

状态：已完成六段混合链路试跑和全量编排器；未启动全量付费生产，未开始学生模型后训练

## 1. 决策

本阶段固定采用：

- `gpt-5.6-terra`：批量英文到简体中文初译；
- `gpt-5.6-sol`：在全新上下文中逐段对照英文复审，并直接修正可确定的问题；
- 冻结 YouTube 英文字幕：已有字幕证道的候选英文事实来源；
- `gpt-transcribe`：只核对 Sol 风险段、确定性异常段和 5% `pass` 抽样，不自动覆盖字幕；
- Sol High 模型审定：取代常规人工双语文本复核；无法从文本确定、仍需回听的条目直接排除；
- 轻量学生模型：在后训练阶段另行选型、训练和部署，不让 Terra 或 Sol 进入周日现场关键路径。

Terra 和 Sol 是**离线数据教师流水线**，不是师生同时在线的推理架构。模型审定不能写成“人工审核”；Sol 复审后的文本也不是自动可训练数据，仍受来源权利和外部蒸馏授权门禁约束。

## 2. 数据生产流程

```text
公开证道视频 + 冻结英文字幕时间轴
  -> 字幕整理为英文语义段 + source hash
  -> Terra 初译（6 段/批，high reasoning）
  -> Sol 独立复审（6 段/批，high reasoning）
  -> ID/顺序/空值/hash/must_fix 确定性校验
  -> needs_audio_review、确定性异常、5% pass 抽样：GPT-Transcribe 音频核对
  -> 一致：模型审定候选
  -> 不一致或转写无效：排除并核对英文来源；修正后重新跑 Terra/Sol
  -> 冻结 train/dev/test
  -> 生成整段翻译、prefix WAIT/WRITE、术语纠错训练样本
  -> 轻量学生模型 LoRA/QLoRA 后训练
```

两次模型调用必须是新的临时上下文。Sol 必须直接看到冻结英文和 Terra 候选，不能只做中文润色。`must_fix` 必须返回实际改正后的中文；无法脱离音频确认时只能标记 `needs_audio_review`。

## 3. 数据分层与训练资格

| 层级 | 条件 | 用途 | 可训练 |
|---|---|---|---|
| Bronze | 自动字幕、边界或来源尚未确认 | 检索、排队和问题发现 | 否 |
| Model-reviewed Candidate | 字幕英文 + Terra 初译 + Sol High 复审 + 选择性音频门禁通过 | 候选数据、模型比较 | 否，当前受权利和蒸馏授权阻塞 |
| Excluded Audio | 音频核对与字幕不一致、转写无效或来源仍有歧义 | 来源核对、错误分析 | 否 |
| Human Gold（可选） | 人工听音频并独立确认英文、中文、专名/经文，且权利清楚 | 论文真值或高价值测试集 | 是，但仍须满足模型输出使用授权 |
| Test | 完整证道级隔离、从未参与提示优化或训练 | 最终盲测 | 只评估，不训练 |

当前 blocker 保留：

- `source_training_rights_unconfirmed`；
- `gpt_external_student_distillation_not_authorized`；

在外部学生训练授权未确认前，Terra/Sol 产物只能作为隔离参考和人工审核材料，不能因为质量好就解除 blocker。

## 4. 六段混合试跑

输入为同一篇证道 `nre_3kR0PHk` 的前六段。为避免重复消耗，试跑复用了已生成的 Terra 初译，只新建一次 Sol 复审对话。

| 阶段 | 实测输入 tokens | 实测输出 tokens | 耗时 | 折算 credits |
|---|---:|---:|---:|---:|
| Terra 初译 | 16,783 | 1,306 | 27.6 秒 | 1.231 |
| Sol 复审 | 21,862 | 2,833 | 65.1 秒 | 3.603 |
| 合计 | 38,645 | 4,139 | 92.8 秒 | 4.834 |

折算约为每段 `0.806 credit`。Sol 输出为 5 `pass`、1 `needs_audio_review`、0 `must_fix`；它识别出一处需要回听的英文 ASR 疑点。此次 Sol 复审没有命中 cached input，因此混合链路的实测 credits 反而高于此前 all-Sol 六段试跑；不能先验地把“Terra 初译”解释为整条链路必然更省。此结果只证明链路和风险路由可用，不代表六段已获人工批准。

按 153 篇、平均每篇约 44.2 段、6 段一批线性外推，约需 1,127 个 Terra 批次和 1,127 个 Sol 批次，约 5,448 credits。该数字不含重试、长文本波动、人工审核和后训练；全量前必须用 50 段样本重新估计均值与 p95。

## 5. 全量选择性音频审核预算

159 篇 train/dev 的实际 dry-run 共 7,334 个字幕语义段、98.546 小时。现有 6 篇 calibration 的 265 段中，Sol 标记 44 段 `needs_audio_review`（16.60%）。按翻译前风险的实际时长占比与 Sol 风险率合并，工作预计审核 29.36%，即 1,736.15 分钟、约 7.81 美元；不扣除两类规则重叠的保守预计上界为 31.90%、1,886.35 分钟、约 8.49 美元。全量音频 5,999.20 分钟、约 27.00 美元只保留为绝对成本上界。完成全量 Terra/Sol 后再以实际入选清单替代外推值。

## 6. 分阶段扩展门禁

1. **6 段链路试跑**：已完成；验证模型角色隔离、结构化输出和 fail-closed 校验。
2. **50 段 calibration**：按内容类型分层抽样，由 Sol High 模型审定；记录 Terra 错误、Sol 修复率、Sol 新增错误率和音频排除率。若作为论文真值，另做独立人工 Gold。
3. **10 篇 canary**：验证跨讲员、经文引用、专名、吞吐、重试和预算 p95。
4. **153 篇生产**：仅在授权、质量、预算和人工产能门禁通过后启动；每批可恢复，不接触冻结 test。

50 段门禁建议：重大忠实度错误为 0；所有 `must_fix` 已产生真实修正；`needs_audio_review` 全部排除；再对否定、数字、经文、主客体和专名做独立模型对照。论文 Gold 仍需人工听音频。

## 7. 轻量学生模型后训练

学生模型与教师流水线解耦。第一轮保留 `4B` 和 `9B` 开放权重候选，不在数据准备阶段提前锁死具体 checkpoint。

训练数据至少包含三种任务：

- 完整语义段：稳定英文段到忠实中文；
- 流式 prefix：英文增量到 `WAIT` 或可追加中文，用来直接优化首字延迟和字幕稳定性；
- 领域纠错：经文、专名、教会术语和常见 ASR 噪声。

DGX Spark 先运行 BF16 LoRA，小样本完成后再根据显存和吞吐决定是否使用 QLoRA。学生必须与未训练 base、云端翻译基线和 `prefix + Context Pack` 在同一套冻结 replay 上比较。晋级同时要求翻译忠实度、首字延迟、增量稳定、长时运行和可回滚 artifact receipt 通过。

周日运行时只保留：流式 ASR、轻量学生、Context Pack matcher 和分发服务；Terra 与 Sol 不参与现场推理。

## 8. 产物与可追溯性

每段保留冻结英文、源 hash、Terra 初译、Sol 最终文本、severity、问题类别、模型与提示版本、人工决定和训练 blocker。每批保留 token、耗时、缓存身份和认证模式，但不保存认证材料。

单篇教师脚本：`scripts/run_codex_conversation_sermon_translation.py`

全量编排器：`scripts/run_full_sermon_dataset_preparation.py`

完整运行说明：[字幕优先、选择性音频审核](./full-audio-dataset-pipeline.zh.md)

六段试跑：`data/derived/sermon-terra-sol-hybrid-pilot-v1/nre_3kR0PHk/`
