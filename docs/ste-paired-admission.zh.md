# STE paired A/B 的软件准入

延续[原候选与 paired A/B 计划](backlog-2026-10-04.zh.md#运行前签字清单)，
入口为 `scripts/experiments/ste_paired_admission.py`。它只冻结和验证实验，不运行模型，
不修改生产 prompt，也不把离线通过当作 API／模型效果验收。

```sh
.venv/bin/python -m scripts.experiments.ste_paired_admission \
  --plan /absolute/plan.json --out /absolute/new-admission.json
```

`admit(plan, base)` 校验：

- A/B 候选全文文件 hash、精确替换起止位置与替换文本。拒绝超出单一变化的修改或用追加保留冲突句。
- 阅读稿、元数据、口播三种引用范围分别明确；一次只比较一个候选分支。
- 同一正式已批准 source/anchor；语言、分层、留出样本、引用和部分／完整修复／未解疑点类别固定。
- reviewer-issues 的两臂消费同一固定草稿；完整 API payload 中模型、采样参数、英文单元与 user message 相同，system prompt 是唯一变化。
- 新 prompt/policy 身份、每次重复独立请求身份；缓存只在 `artifacts/ste-ab/`，unknown 必须对账，不能自动重试。
- 官方价格快照、输入/输出 token 上限、每臂调用次数、重复次数、总费用和总时限；按整数向上取整计算最坏费用，缺少数值不猜测。
- 至少两名盲评者、随机逐对编码、评分冻结后揭盲、分歧裁决；运行前固定非劣界值及不确定性方法，严重错误停止。
- 独立人工批准收据绑定整个计划 hash，覆盖候选、样本、预算与时间窗。任何相关字段变化都使收据失效。

准入输出 `admitted_for_isolated_runner` 也不启动请求。实际 runner 仍须落实逐请求 token、
费用与截止时间预算；生产晋升仍是单独审查。当前没有创建任何真实实验批准或付费运行。

`blind_pairs(plan, outputs)` 复用既有 `layer2_ab._validate_group` 语义门禁和
`build_blind_review_scores.blank_score` 评分字段。公众评分表不暴露 A/B、模型或机器 pass/fail；
独立 key 保存编码映射及原结果 hash，失败输出不丢弃。该函数不替代完整听审或翻译批准。

`check_unresolved_concerns(known_ids, resolved_ids, retained_ids, status=...)` 是离线逐项真值门禁：
修复一个问题不能清掉其余未解项，有未解项必须 fail；全部解决才允许 pass。
该检查不能自行发现模型未上报的语义问题，仍需独立人工裁定。

精确计划字段与可运行离线 fixture 见 `tests/test_ste_paired_admission.py`。
fixture 中的价格、批准和模型名仅供测试，不是实际实验参数或生产授权。
