# 复盘：20261019-layer2-cache-hit-end-binding-replay

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

- 交付类型：测试（本地 benchmark），不是 `four_layer_release`，不产出候选、审批或发布。
- 目的：测 Option D 的效果，即缓存命中不再逐次复核绑定，只在准入、每次付费派发前和结束时复核。测量对象是 canonical Layer 2 worker 在缓存命中时的每组本地耗时。
- 三侧：
  - dev `e8b197be`（before）；
  - `claude/layer2-cache-hit-end-binding` `49f087c5`（Option D）；
  - dev + PR #1150（stat 备忘）+ D 的 scratch 合并，只作参考。
- 结束状态：三侧都是 `stopped_at_first_cache_miss`。group-0025 在 c2 round-001 里没有成功收据，replay 的 caller 拒绝任何 provider 调用，所以在同一位置停下。供应商调用 0，没有 API key，没有预算账本。`humanApproval=false`，`releaseEligible=false`。
- 结果（同样 24 个缓存命中组）：

  | | 每组中位数 | 墙钟 | 配置重载 |
  |---|---|---|---|
  | before | 3.44 s | 85.5 s | 197 次，51.1 s |
  | D | 0.017 s | 2.2 s | 3 次，0.76 s |
  | D + 备忘 | 0.019 s | 1.2 s | 3 次，0.05 s |

  D 剩下的 3 次重载是准入一次，加第 25 组付费派发前的两次检查；那两次检查放行后，caller 拒绝了调用。
- 证据边界：只说明本机本地计算开销，不是生产运行，也不证明候选质量。没有跑到结束复核（`post_model_binding`），结束复核的行为由单元测试覆盖。

## 总时间

- before：墙钟 1m25s；D：0m02s；D + 备忘：0m01s。
- 无等待、无返工；三侧顺序执行。本机同时有其他负载（load average 约 30）。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | not_run | | | | | | | |
| L1 词级对齐（MFA） | not_run | | | | | | | |
| L1 英文机器评审 | not_run | | | | | | | |
| L2 初译 | reused：c2 round-001 的 payload-cache 成功收据（Sol 6.1，冻结 policy v3） | 冻结 | 0 次新调用，24 组命中 | before 3.44 s／组，D 0.017 s／组（本地） | 0 | n/a | $0 | `summary.json` |
| L2 独立审核 | reused，同上 | 冻结 | 0 | 同上 | 0 | n/a | $0 | `summary.json` |
| 文本质检（回译） | not_run | | | | | | | |
| L3 配音（TTS） | not_run | | | | | | | |
| L3 回转写筛查（ASR） | not_run | | | | | | | |
| 音频质检 | not_run | | | | | | | |
| L4 构建与发布 | not_run | | | | | | | |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L2 replay group-0025 | cache miss，拒绝调用 | c2 round-001 里该组没有成功收据（首轮失败、进入修复） | 预期 | 作为三侧共同的停止点 | 无需 | 本报告 |
| 测试 `test_layer2_large_fan_in` 65 组 | 高负载（load average 60–150）下 D 分支 4/4 报 `utc_clock_discontinuity_between_spans`，dev 0/2；负载约 30 时 D 2/2 通过 | 推测：accounting 先读 monotonic、后读 UTC，容差 10 ms；D 去掉了 I/O 密集的复核后，worker 线程更久地持有 GIL，两次读之间的切换可能超过 10 ms | 测试 | 不在本 PR 修；作为后续项 | 已有 | 代码 PR 说明 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 速度 | 缓存命中不逐次复核绑定（Option D） | 3.44 → 0.017 s／组 | c2 形状（约 400 组）每语言约省 20+ 分钟本地时间；16 路并发的 GIL 争用随之消失 | Claude | 代码 PR |
| 质量 | accounting 在 `stage_started` 紧挨着读 monotonic 与 UTC，或放宽跨 span 的偏移容差 | 上面的测试错误 | 高负载下不再误报时钟不连续 | 待定 | 后续 |

## 实际覆盖范围

只覆盖 Layer 2 worker 的缓存命中路径：准入、auto-repair 首轮、逐组 payload-cache 命中、写收据，在第 25 组付费派发前停止。没有修复轮、语言插件终检、结束复核和候选落盘。Layer 1、3、4 未执行。输入 artifacts 只读。

## 遗留状态

- scratch 输出、job 根和锁都在会话 scratchpad，可直接删除。
- 没有 job hold、构建号或线上文件。
