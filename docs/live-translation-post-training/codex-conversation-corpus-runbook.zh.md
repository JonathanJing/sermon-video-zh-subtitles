# 使用 ChatGPT/Codex 共享额度制作证道译文

## 目的

该流程让 `codex exec` 使用本机已保存的 ChatGPT-managed 登录，由 Terra 完成初译、Sol High 在独立上下文中复审，不向教师脚本传递 OpenAI API key，也不产生常规 API 项目账单。它会消耗 ChatGPT Work/Codex 共享使用额度。下游只对风险段和稳定抽样段调用 GPT-Transcribe，使用常规 API key 和 API 账单；两种认证严格隔离。

脚本入口：`scripts/run_codex_conversation_sermon_translation.py`。

## 工作方式

每个批次创建两个新的、临时且互不继承上下文的 Codex 对话：

1. Terra 翻译器读取冻结英文、前后英文上下文和元数据，输出结构化初译。
2. Sol 校对器在全新上下文中读取冻结英文和初译，输出修订译文及风险等级。
3. 本地脚本校验 segment ID、顺序、非空中文、输入哈希和缓存身份。

脚本使用 `--ephemeral`、`--sandbox read-only`、`--ignore-user-config` 和 JSON Schema。它会主动移除 `OPENAI_API_KEY` 与 `CODEX_API_KEY`，并要求 `codex login status` 明确显示 ChatGPT 登录。

## 安全试跑

默认只处理前三段，并且必须显式确认共享额度：

```bash
python3 scripts/run_codex_conversation_sermon_translation.py \
  --video-id nre_3kR0PHk \
  --segment-limit 3 \
  --batch-size 3 \
  --confirm-shared-codex-usage
```

默认模型已经固定为 `--translate-model gpt-5.6-terra` 与 `--review-model gpt-5.6-sol`；如需审计复现，可显式写出这两个参数。默认输出根目录为 `data/derived/sermon-terra-sol-dataset-preparation-v1`。

单独处理第 4–6 段，可使用独立输出根目录，避免覆盖第一批试跑：

```bash
python3 scripts/run_codex_conversation_sermon_translation.py \
  --video-id nre_3kR0PHk \
  --start-segment 4 \
  --segment-limit 3 \
  --batch-size 3 \
  --out-root data/derived/sermon-codex-conversation-pilot-usage-v1 \
  --confirm-shared-codex-usage
```

`--segment-limit 0` 表示整篇。全量请使用 [字幕优先、选择性音频审核方案](./full-audio-dataset-pipeline.zh.md) 的编排器，不要手工循环单篇脚本。

## 质量边界

- 两次对话上下文隔离且角色固定，但仍属于同一 GPT-5.6 家族；Sol High 是模型审定，不能标记成人工审核。
- 已有英文字幕是候选英文来源；Sol `needs_audio_review`、确定性异常和 5% `pass` 抽样进入选择性 GPT-Transcribe 音频核对。
- 音频转写只提供证据，不自动覆盖字幕；不一致项排除并核对英文来源，修正后重新运行 Terra/Sol。
- 产物继续标记 `trainingEligibility: blocked`，直到内容权利和外部蒸馏授权完成。

## 成本与容量

该方式不产生常规 API token 账单，但消耗 Codex 共享额度。官方说明 GPT-5.6 消息通常消耗约 5–30 credits，实际取决于输入、输出、推理和工具。

若每篇约 50 段、每批 6 段，则翻译和校对合计约 18 次对话。153 篇约需 2,754 次对话，可能迅速耗尽共享额度。因此该流程适合 POC、抽样复核和额度利用，不应在未测量 credit/token 使用前被视作免费的大规模数据生产方案。

### 2026-09-01 历史 all-Sol 基线

同一篇证道的前六段，以一个批次完成翻译与校对：

- 新建临时对话：2 次；
- 输入 tokens：38,798，其中缓存输入 21,248；
- 输出 tokens：3,837；
- 按 Sol 共享额度率折算：约 3.89 credits；
- 平均：约 0.65 credit/段；
- 墙钟时间：268.6 秒，其中校对 229.6 秒。

对照三段批次约为 5.14 credits，即 1.71 credits/段。六段批次把单位 credit 降低约 62%，说明系统提示和代理运行时上下文是主要固定开销。当前建议使用六段批次，不使用三段批次做规模化生产。

按 153 篇、平均每篇 44.2 段线性估算，all-Sol 六段批次约消耗 4,380 credits。该数字只保留为历史基线，不再作为当前 Terra/Sol 组合预算。

### Terra/Sol 组合实测

相同六段、相同提示、相同 high reasoning 的单模型对照显示：Terra 更快、更省，Sol 的质量更高。因此正式候选链路改为 Terra 全量初译、Sol 全量复审，人工再处理风险队列和抽检。

混合链路六段实测：Terra 初译阶段为 1.231 credits、27.6 秒；Sol 复审阶段为 3.603 credits、65.1 秒；合计 4.834 credits、92.8 秒。Sol 判定 5 `pass`、1 `needs_audio_review`、0 `must_fix`。按 153 篇、平均每篇 44.2 段线性外推约为 5,448 credits；全量前仍需用 50 段重估均值与 p95。详见 [Terra/Sol 数据集准备方案](./terra-sol-dataset-preparation-plan.zh.md)。

## 产物

输出位于忽略目录：

```text
data/derived/sermon-terra-sol-dataset-preparation-v1/<video-id>/
  segments.codex.first.jsonl
  segments.codex.final.jsonl
  run-report.json
  cache/translate/gpt-5.6-terra/*.json
  cache/review-v2/gpt-5.6-sol/*.json
```

回执只保存模型、认证模式、共享额度声明、输入绑定、耗时和 token usage；不保存认证材料。
