# GPT-6 模型分工实验结果

日期：2026-09-28（太平洋时间）。工作分支：`codex/model-production-experiments`。实验合同见[计划](20260928-model-production-ab-plan.zh.md)与[冻结输入](20260928-model-production-ab-inputs.json)。原始 API 响应和译文保存在本机 Git 忽略目录 `artifacts/model-production-ab-20260928/`，不进入仓库。

## E1：Agents API 调度影子实验

12 个脱敏固定状态分别由 `gpt-6-sol` 和 `gpt-6-luna` 以 `medium` reasoning、同一指令、同一只读工具及确定性校验执行，共 24 个真实会话。所有会话为 `completed`，每个调用 2 次工具；48 次工具调用经持久化 function-call item 与工具收据匹配，均为检查状态或提交影子决定。没有运行生产变更工具。原始报告的工具名字段曾为空；已根据同一会话的 `call_id` 补齐并保留修复前副本。

| 指标 | Sol | Luna |
| --- | ---: | ---: |
| 下一步 action 与固定状态一致 | 12/12 | 12/12 |
| `human_action_required` 与固定状态一致 | 12/12 | 12/12 |
| 完整状态决定被确定性校验接受 | 7/12 | 6/12 |
| 错误声称 `status=complete` | 0/12 | 0/12 |
| 会话完成 | 12/12 | 12/12 |
| 墙钟 p50 / p95 | 22.66 / 83.52 秒 | 79.12 / 82.40 秒 |
| API 用量有返回 | 4/12 | 0/12 |
| 实际 HTTP request ID 可得 | 0/12 | 0/12 |

五个需要 `blocked` 的状态，两臂都给了正确 action，却把 `status` 写为 `observed`；Luna 另把一例应为 `complete` 的状态写成 `observed`。这与现行指令中的“shadow observation”措辞可能有关，是从提示词和结果推断出的待验证原因，并非模型能力定论。宿主校验拒绝了这 11 个不匹配的完整状态对象；真实生产仍必须保留确定性状态验证。

延迟是双峰分布：表中 p50/p95 用最近秩法；虽然各臂自身 p50 差异大，逐状态配对的 `Luna − Sol` 中位差为 **−1.03 秒**，12 对中 Luna 较快 7 对、Sol 较快 5 对。当前样本不支持宣称任一模型有稳定速度优势。用量缺失使完整 token 总量和费用都为未知，不能把缺失当成零。人工定位分钟数未测。

**E1 处置：** 不修改正式 Supervisor 模型或状态门禁。下一轮先明确影子模式下 `blocked` 与 `observed` 的输出规则，并在同一固定状态集复测，再考虑速度或成本决策。

## E2：Layer 2 初译模型

三语同源 178 秒样本的批次正在运行。实验组为 A：Astra→Sol、B：Sol→Sol、C：Luna→Sol；A 是本次同提示词的同期对照，不能与既有正式 runner 的 prompt 字节等同。人工盲评和正式候选审批保持独立。

### 中文 `zh-Hans`：45 组终态

| 指标 | A Astra→Sol | B Sol→Sol | C Luna→Sol |
| --- | ---: | ---: | ---: |
| 完整响应 / 结构失败 | 45 / 0 | 45 / 0 | 41 / 4 |
| Sol 语义复核标为通过 | 45 | 45 | 41 |
| 冻结语言插件通过 | 43 | 43 | 39 |
| 两项机器检查均通过 | 43 | 43 | 39 |
| 复核修改初译的组数 | 14 | 6 | 18 |
| 已记录 API 响应 | 90 | 90 | 86 |
| 输入 / 输出 token | 55,862 / 21,824 | 55,760 / 25,018 | 52,962 / 27,345 |
| 完整组两次 API 调用耗时 p50 / p95 | 9.21 / 14.38 秒 | 10.24 / 17.13 秒 | 9.21 / 16.10 秒 |
| Standard token 费用估算 | $0.7400 | $0.3617 | $0.2245 |
| 每完整组估算费用，含失败请求 | $0.01644 | $0.00804 | $0.00548 |

三臂共有 **41 个完整配对组**进入本地匿名评分包，另 4 组列明 C 臂缺失。C 的 4 次失败都是初译 `targetUtterances` 结构不符合契约，原响应留存且没有自动重付。语言插件在三臂的相同两组报告 `cuv_exact_quote` 失败；不能用 Sol 自报的语义 `pass` 覆盖它。每条响应的用量字段齐全，缓存读写 token 均为 0；费用按 [OpenAI 官方定价](https://developers.openai.com/api/docs/pricing) 2026-09-28 的 Standard／short-context 费率、响应的 `service_tier=default` 与实际 token 计算，只是模型 token 估算，非账单回读。p50/p95 为完整组的初译加复核调用耗时，不含失败组；费用含失败请求。复核是否修改译文不等于语义错误数量。

韩语和西语仍在运行，完成后合并比较；上述中文机器结果不足以建议更改正式翻译政策。

## 发布与复现边界

这些都是影子证据。没有为实验内容生成正式 Target-Language Candidate、Audio Package 或 Release Package，也没有发布页面或修改人审结果。运行代码在 `scripts/experiments/`，定向测试在 `tests/test_supervisor_ab.py` 与 `tests/test_layer2_ab.py`；原始产物只在本地 Git 忽略目录。
