# MiLMMT 后训练证据审计边界

本页记录从 `design/sermon-live-translation-ios` 移植的只读审计工具。
该分支的训练、翻译、盲审和报告数据仍保存在原受控环境，未随工具进入 Git。
本页是研究入口，不表示当前 `dev` 已具备训练或发布能力。

## 两道独立授权门

1. **证道来源训练权利**：设计分支的 2026-09-03 文档记录了项目负责人对所选来源的确认。审计工具本身不验证该确认的范围或收据；在新数据集上运行时，应单独核对来源、用途和保留期限。
2. **模型输出用于外部学生训练**：设计分支的治理文档仍将 GPT 输出作为外部 Qwen SFT 标签，以及用 GPT 判断直接选择训练样本，列为 `BLOCKED`，须取得明确、可归档的适用授权。来源权利确认不能解除这道门。

即使来源哈希、文本复审和选择性音频检查全部通过，模型复审结果仍是候选证据。不得把审计报告的 `evidence_collected_not_a_promotion_gate` 状态解释为 Human Gold、训练准入或发布通过。

## 审计工具

[`scripts/audit_milmmt_post_training_state.py`](../scripts/audit_milmmt_post_training_state.py) 对已有训练集、开发集及冻结清单做数量、哈希、覆盖和重叠检查；不调用模型，也不运行训练。它输出 `authorizationGates`，其中外部学生训练保持 `blocked`。

```bash
python3 scripts/audit_milmmt_post_training_state.py \
  --root /path/to/authorized/local/corpus \
  --output /path/to/private/report.json
```

`--root` 需要原受控语料目录。输出应保存在私有位置，不提交到 Git；报告含来源 ID、哈希与统计，但不应含完整译文。工具拒绝覆盖已有输出，也拒绝向 `data/` 下的语料或 benchmark 目录写入。

定向检查：

```bash
python3 -m unittest discover -s tests -p 'test_audit_milmmt_post_training_state.py'
```

历史设计分支中的 `data/reports/`、`data/benchmarks/`、缓存、解盲文件和正文未移植。本页不链接这些本地报告，避免把缺失的私有证据当作仓库内可复现产物。
