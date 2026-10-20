# 复盘：20261019-layer2-binding-memo-replay

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

- 交付类型：测试（本地 benchmark），不是 `four_layer_release`，不产出候选、审批或发布。
- 目的：测 canonical Layer 2 worker 在缓存命中时每组的本地开销，比较 dev `a5bd24df`（before）与 stat 备忘分支 `claude/layer2-binding-memo` `88c00c03`（after）。
- 结束状态：两侧都是 `stopped_at_first_cache_miss`。group-0025 在 c2 round-001 里没有成功收据，replay 的 caller 拒绝任何 provider 调用，所以在同一个位置停下。供应商调用 0，没有 API key，没有预算账本。`humanApproval=false`，`releaseEligible=false`。
- 结果：同样 24 个缓存命中组，每组本地耗时中位数 **3.30 s → 0.65 s**（均值 3.38 s → 0.645 s），worker 内配置重载累计 48.8 s → 3.0 s。两侧重载 197 次（约 8.2 次／组），verify 49 次，reuse 48 次，完全一致。
- 证据边界：只说明本机本地计算开销，不是生产运行，也不证明候选质量。

## 总时间

- `replay-base`：墙钟 1m25s（含约 2 s 准入），24 组后停在第 25 组。
- `replay-after`：墙钟 0m16s，同上。
- 没有等待或返工；两侧顺序执行，没有并发负载，但本机同时有其他会话（负载均值约 10）。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | not_run | | | | | | | |
| L1 词级对齐（MFA） | not_run | | | | | | | |
| L1 英文机器评审 | not_run | | | | | | | |
| L2 初译 | reused：c2 round-001 的 payload-cache 成功收据（Sol 6.1，冻结 policy v3） | 冻结 | 0 次新调用，24 组命中 | before 3.38 s／组，after 0.645 s／组（本地） | 0 | n/a | $0 | `summary.json` |
| L2 独立审核 | reused，同上 | 冻结 | 0 | 同上 | 0 | n/a | $0 | `summary.json` |
| 文本质检（回译） | not_run | | | | | | | |
| L3 配音（TTS） | not_run | | | | | | | |
| L3 回转写筛查（ASR） | not_run | | | | | | | |
| 音频质检 | not_run | | | | | | | |
| L4 构建与发布 | not_run | | | | | | | |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L2 replay 准入 | `plugin_does_not_match_frozen_policy` | c2 用的插件在另一个已删除 worktree 的 scratch 路径；插件依赖集按当前检出的内置插件根计算 | 预检 | 改用各检出自带的 `zh_hans_weekly_15030286.py`，两侧哈希都与冻结 policy 一致 | 无需 | 本报告 |
| L2 replay group-0001 | 首组 cache miss | 未施加 c2 预算授权里的 request limits，payload 少了 `max_completion_tokens`、`service_tier` 不同 | 预检（拒绝调用） | 按 worker 的方式用 `request_limits` 包住 `execute` | 无需 | 本报告 |
| L2 replay group-0025 | cache miss，拒绝调用 | c2 round-001 里该组没有成功收据（首轮失败、进入修复） | 预期 | 作为两侧共同的停止点 | 无需 | 本报告 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 速度 | stat 备忘 payload-cache／partial-recovery 快照和代码身份 | 3.38 → 0.645 s／组 | c2 形状（v7、约 400 组、每组约 12 次复核）每语言约省 30–40 分钟本地时间 | Claude | 代码 PR |
| 速度 | 剩余开销：`package_view`（约 55–60 ms／次）与配置绑定摘要的 JSON 编码（约 40 ms／次，含 5.5k 行快照） | 单线程 binding 91 ms 中的大头 | 再降一半左右 | 待定 | 后续 |
| 流程 | replay 需要手工复刻插件路径和 request limits | 上面两条错误 | 可做成 `cache_recovery` 的只读 benchmark 模式 | 待定 | 后续 |

## 实际覆盖范围

只覆盖 Layer 2 worker 的缓存命中路径（准入 → auto-repair 首轮 → 逐组 payload-cache 命中 → 收据），在第 25 组停止。没有修复轮、语言插件终检、候选落盘和 package 终验。Layer 1、3、4 未执行。输入 artifacts 只读。

## 遗留状态

- scratch 输出、job 根和锁都在会话 scratchpad，不在仓库或 artifacts 运行目录，可直接删除。
- 没有 job hold、构建号或线上文件。
