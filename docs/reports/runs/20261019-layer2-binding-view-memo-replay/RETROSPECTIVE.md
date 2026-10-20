# 复盘：20261019-layer2-binding-view-memo-replay

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

- 交付类型：测试（本地 benchmark），不是 `four_layer_release`，不产出候选、审批或发布。
- 目的：测 package view 备忘、单次检查共享目录列举和绑定摘要复用之后，canonical Layer 2 worker 在缓存命中时的本地开销。before 是 PR #1150 的头 `claude/layer2-binding-memo` `a25e2b94`，after 是 `claude/layer2-binding-view-memo` `46215da8`（https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1161）。
- 结束状态：四次 replay 都是 `stopped_at_first_cache_miss`，停在 group-0025：c2 round-001 里这一组没有成功收据，replay 的 caller 拒绝任何 provider 调用。供应商调用 0，没有 API key，没有预算账本。`humanApproval=false`，`releaseEligible=false`。`bench-c2` 是在真实 c2 配置上只读计时，`completed`。
- 结果（本机负载均值约 220–350，比上一份报告的约 10 高得多，所以绝对值都偏大，只看同一时段交替跑出的 before/after）：
  - 同样 24 个缓存命中组，每组本地耗时中位数 **2.03 s → 0.49 s**（第一对）和 **3.25 s → 0.61 s**（第二对）。两侧都是重载 197 次、verify 49 次、reuse 48 次，完全一致，说明复核次数和位置没变。
  - c2（v7）上单次 `current_binding()`：CPU **111 ms → 32 ms**（三对交替，before 110–112，after 31–32）；墙钟中位数 240–368 ms → 40–79 ms。
  - 其中 `load_configuration` 在 c2 上 CPU 42 ms → 25 ms，在 v6 replay 配置上不变（约 18 ms：没有 partial recovery，共享列举和摘要复用都不适用）；warm `package_view` 199 ms → 1.2 ms。
  - 身份：在 `execution-zh-c2.json` 上只读核对，除 `codeIdentitySha256`（代码改了，必然变）外所有值逐字节相同：配置 `bcdc3af7…`、payload cache `0fe19b13…`、partial recovery `cf19d670…`、view 摘要、`stateRevision`、`packageIdentities`、durable job `1f70449c…`。新代码身份与不走备忘的重算一致。
- 证据边界：只说明本机本地计算开销，不是生产运行，不证明候选质量；高负载下墙钟数字噪声大，CPU 时间更可靠。

## 总时间

- `replay-base-1`：墙钟 0m52s；`replay-after-1`：0m15s；`replay-base-2`：1m16s；`replay-after-2`：0m18s（各含约 2 s 准入）。
- `bench-c2`：约 4m50s，含 before/after 各三轮 15 次调用和 `load_configuration` 对照。
- 没有等待或返工；全部顺序执行，但本机同时有大量其他会话（负载均值 220–350）。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | not_run | | | | | | | |
| L1 词级对齐（MFA） | not_run | | | | | | | |
| L1 英文机器评审 | not_run | | | | | | | |
| L2 初译 | reused：c2 round-001 的 payload-cache 成功收据（Sol 6.1，冻结 policy v3） | 冻结 | 0 次新调用，每轮 24 组命中 | before 2.03／3.25 s／组，after 0.49／0.61 s／组（本地，中位数） | 0 | n/a | $0 | `replay-*/summary.json` |
| L2 独立审核 | reused，同上 | 冻结 | 0 | 同上 | 0 | n/a | $0 | `replay-*/summary.json` |
| 文本质检（回译） | not_run | | | | | | | |
| L3 配音（TTS） | not_run | | | | | | | |
| L3 回转写筛查（ASR） | not_run | | | | | | | |
| 音频质检 | not_run | | | | | | | |
| L4 构建与发布 | not_run | | | | | | | |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L2 replay group-0025 | cache miss，拒绝调用 | c2 round-001 里该组没有成功收据（首轮失败、进入修复） | 预期 | 作为四次 replay 共同的停止点 | 无需 | 本报告 |
| 计划前提 | 任务估计配置绑定摘要的 JSON 编码每次约 40 ms | 实测 362 KB 快照编码约 3.5 ms；`load_configuration` 的大头其实是 stat 指纹把同一个约 3.2k 文件的 round 目录列举了两遍（v7 要求 recovery round 就是 payload-cache 根） | 预检（profile） | 改为每次检查只列举一次，摘要复用仍做（省约 3.5 ms） | `test_one_round_listing_per_load` | https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1161 |
| 基准时的并发测试 | 第一次宽测试和变异检查同时跑，变异脚本临时改了 `controller.py` | 操作顺序 | 运行中 | 那次结果作废，代码定稿提交后重跑 | 无需 | 本报告 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 速度 | package view 备忘、单次列举、摘要复用、`_overlap` 缓存 | c2 单次复核 CPU 111 → 32 ms；replay 每组约 4–5 倍 | c2 形状（约 400 组、每组约 12 次复核）每语言再省约 (111 − 32) ms × 12 × 400 ≈ 6 分钟 CPU；高负载或多线程时墙钟省得更多 | Claude | https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1161 |
| 速度 | 剩余开销主要是 stat 指纹本身：每次复核仍要 lstat round 目录约 3.2k 个文件和代码树约 765 个文件 | `load_configuration` c2 CPU 25 ms 中的大头 | 只能靠减少复核次数或批量 stat（macOS `getattrlistbulk`），都属设计改动 | 待定 | 后续 |
| 流程 | 基准要在低负载时重跑一次，才能和上一份报告（负载约 10）直接比较 | 本轮负载 220–350 | 绝对值可比 | 待定 | 后续 |
| 流程 | replay 仍需手工复刻插件路径和 request limits | 沿用上一份报告的脚本 | 可做成 `cache_recovery` 的只读 benchmark 模式 | 待定 | 后续 |

## 实际覆盖范围

只覆盖 Layer 2 worker 的缓存命中路径（准入 → auto-repair 首轮 → 逐组 payload-cache 命中 → 收据），在第 25 组停止；replay 用的是 v6 配置，v7 的共享列举和摘要复用只在 `bench-c2`（真实 c2 v7 配置的只读复核）里测到。没有修复轮、语言插件终检、候选落盘和 package 终验（有候选时 package view 不走备忘，这条路径由单元测试覆盖）。Layer 1、3、4 未执行。输入 artifacts 只读。

## 遗留状态

- scratch 输出、job 根、锁和 before 检出（临时 git worktree）都在会话 scratchpad，不在仓库或 artifacts 运行目录；before 检出用完已 `git worktree remove`。
- 没有 job hold、构建号或线上文件。

## 外部可见的变化

无：没有 Dev 发布、TestFlight 或受保护分支推送。代码改动在 https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1161，合并由用户决定。
