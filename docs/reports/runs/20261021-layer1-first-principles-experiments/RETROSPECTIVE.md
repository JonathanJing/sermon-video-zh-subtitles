# 复盘：20261021-layer1-first-principles-experiments

数据见同目录 INDEX.md 和 manifest.json。完整的实验设计、逐轮数字和汇总表在 [Layer 1 第一性原理改造：对照实验与度量](../../design/layer1-first-principles-experiments.zh.md)（分支 `worktree-l1-first-principles`）；本报告只记运行事实和边界。

## 结论先行

- **交付类型**：测试（Layer 1 对照实验，同一来源 `AKY0k5KiKns`、窗口 0:05.5–40:06；不是 `four_layer_release`，不产生任何人工批准）。
- **最终状态**：E1、E2c、E4c 三轮的机器裁判都 `approved_for_layer2_shadow`（709/709，0 高风险，`humanApproval=false`）；E2、E2b 各 1 句被拒后由规则修正；E4b、E3b 没有到裁判结束（见错误表）。
- **量到的收益（对本素材）**：裁判拒绝 4/709 → 0/709；一次规则或边界改动后重判 119 次 → 6–43 次；ASR 32 s → 14 s；裁判吞吐 3.5 → 2.2 s/次；MFA 改一块重对齐 57 s → 36 s。
- **证据边界**：以上是机器判定和计时；裁判本身对边界切法不稳定（同一切法 E1 pass、E2 fail）；MFA 与裁判时间含网络和进程启动；没有人工审核、没有 Layer 2–4。

## 总时间

- 实验墙钟：19:54Z（E1 开始）→ 20:35Z（E3 测量结束），约 41 分钟，含 7 轮裁判、3 轮完整 execute、3 轮 MFA 测量和中间的代码修改。
- 单轮计算：E1 裁判 387 s；E2 151 s；E2b 40 s；E2c 27 s；E4c 首段 132 s（切音频 6 + ASR 14 + MFA 54 + 锚点 1 + 裁判首批）+ 续跑 176 s（80 次裁判）；E3 测量 56 s（填充）与 36 s（改一块）。
- 返工：E4b 一整轮（代码身份变化中止）、E3b 一次零调用拒绝、MFA 测量两次 0 命中（缓存键缺陷）。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | `gpt-transcribe`（OpenAI dev） | default | E4b 14、E4c 14、e3b-skip 14 | 14 s / 轮（14 并发） | 2400.5 s 音频 / 轮 | — | 约 USD 0.18 × 3（估） | `e4c-execute-asr14-judge8.output/accounting` |
| L1 词级对齐（MFA） | DGX Spark MFA 3.4.2，beam 100/400，`--num_jobs 8`，按块缓存 | — | E4b、E4c、e3b-skip 各 1；E3 测量 5 次 | 54–60 s 整篇；36 s 改一块；11 s 整次命中 | 7303 词 | — | 本地算力 | `layer1-fp-context/e3-mfa-measure-mfa.json`、`e4c…/alignment-receipt.json` |
| L1 英文机器评审 | `claude-opus-5-5`（订阅 CLI） | high | E1 119、E2 43、E2b 9、E2c 6、E4b 17、E4c 80、e3b-skip 29 | 见总时间 | 单次中位 18–21 s | 6 并发 3.5 s/次，8 并发 2.2 s/次 | 订阅列价等价预留 | 各 `*.output/machine-judge.json` |
| L2–L4 | not_run | | | | | | | |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| E2 裁判 | 1 句高风险（`real, concrete, \| intensified`），同一切法 E1 通过 | 裁判对边界情况不稳定；规则允许了逗号系列中间的切点 | 占用资源后 | 逗号系列规则 | `test_anchor_unit_splitting` | 分支提交 `001892bb` |
| E2b 裁判 | 同一句换切法仍被拒（否定辖域被 `or` 切开） | 规则未识别否定辖域 | 占用资源后 | `or` 前不在否定辖域内切；句首状语可作从句开头 | 同上 | `3a14eac4` |
| E4b 裁判 | 首批返回后 `source_budget_execution_binding_changed` | 本会话在运行中改了包文件，代码身份变化 | 占用资源后 | 停止在运行中改代码；8 条已返回调用用新工具对账 | `test_reconcile_judge_cache_markers` | `a6e958e2` |
| E4c 裁判 | 碰到 E4b 留下的未知标记被拒绝重试 | 共享缓存里的未知标记按设计阻断同内容批次 | 占用资源后 | 对账后续跑 | 同上 | 同上 |
| E3b | `source_budget_identity_changed` | 账本绑定预算授权哈希，不能跨配置共用 jobRoot 回放 ASR | 预检（零调用） | 放弃；改为直接走 `mfa_backend` 测量 | — | 记入设计文档 |
| E3 测量 ×2 | 改一块后 14 块全部未命中 | 块键含读法文件哈希；目录键含读法文件哈希与 adapter 字节 | 占用资源后 | 块键只含该块词与映射，目录键只含运行时 | `test_mfa_alignment` 新增 3 例 | `1578e200`、`55c2abda`、`4e405a54` |
| 操作 | 误把 `e3b-skip` 当参数启动了一轮 execute，30 s 后杀掉 | 运行脚本没有 dry-run 参数 | 占用资源后 | 付了一次 ASR；7 个飞行中调用留下无返回的未知标记 | — | 记入设计文档 |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 速度 | 单元 ID 稳定化 | E2 一次 13 句改动重判 43 批，多数是同块后句顺延 | 重判只剩改动句所在批 | 待排 | 设计文档 |
| 速度 | `reuseBudgetRoots` 接入 Layer 1 producer | E3b、E4b/E4c 各重付 ASR | 跨配置零成本回放 ASR | 待排 | 设计文档 |
| 速度 | Spark 端按哈希复用已上传音频、常驻 MFA worker | E3 地板 11 s、改一块仍 36 s | MFA 改一块降到 10 s 量级 | 待排 | 设计文档 |
| 流程 | 预算授权与代码身份解绑 | E4b 整轮中止 | 改一行无关代码不中止运行 | 待讨论 | 设计文档 |
| 质量 | 裁判对边界情况不稳定 | E1/E2 同切法不同结果 | 规则层越保守越好；或裁判两次取并集 | 待讨论 | 设计文档 |

## 实际覆盖范围

- L1：E1/E2/E2b/E2c 复用 v10 的 ASR 与对齐，只跑锚点与裁判；E4b/E4c/e3b-skip 完整 execute（新 ASR 文本）；E3 直接走 `mfa_backend`。
- L2–L4：not_run。

## 遗留状态

- 本地 `layer1-fp/`：E1、E2c、E4c 的候选包（`blocked`/`succeeded`，均 `productionEligible=false`）；`.e4b…`、`.e3b-skip…` 账本有未知项，已关闭；共享 `judge-cache` 里有 7 个 e3b-skip 的无返回标记。
- Spark `jobs/chunk-cache/` 下有三个运行时键的块缓存目录（两个旧键方案留下，可清理）。
- 分支 `worktree-l1-first-principles` 已推送，待开 PR。

## 外部可见的变化

- 分支推送；Dev 发布、TestFlight、受保护分支：not_run。
