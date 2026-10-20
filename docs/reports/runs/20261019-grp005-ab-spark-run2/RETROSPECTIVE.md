# 复盘：20261019-grp005-ab-spark-run2

数据见同目录 INDEX.md 和 manifest.json。前一次尝试见 `docs/reports/runs/20261019-grp005-ab-spark-attempt1/`（PR #1101）。

## 结论先行

交付类型：**测试**（`DEV-GRP-005` 批次身份 A/B 的"单独渲染"组，15030286 的 ko、es 各 10 组，走预览通道），不属于 `dual_pdf`、`live_session` 或 `four_layer_release`。最终状态 `completed_preview_rendered_blind_packets_built`（outcome.json，exit 0）。

- ko、es 各渲染 10 个 `preview_only` 单元，都能完整解码。
- `batch_identity_ab.py pack` 核对通过：每个预览单元的声音参数都与正式批次的被测身份一致（ko `f6bdd661bc29`，es `9a246266ab1a`）。
- 每个语言各生成 10 对随机标 X/Y 的盲听包。

证据边界：只有渲染与打包的代码证据，**盲听尚未进行**，A/B 结论为 `pending`。不得据此把批次成员关系移出声音身份（§12 决定 1）。`humanApproval=false`，`releaseEligible=false`。

## 总时间

墙钟 3m23s（会话 16:06:52 开启，16:10:15 关闭）。

| 阶段 | 时间 |
|---|---|
| 开启到 `exclusive_ready` | 约 4 秒 |
| ko 派发（含上传核验、容器启动、模型加载、10 个单元） | 16:07:05–16:08:27，82 秒 |
| es 派发 | 16:08:27–16:09:53，86 秒 |
| 结束会话与恢复服务 | 约 22 秒 |

没有返工。开会话前已在本机对真实输入跑过预览通道的完整输入校验，这是第一次尝试之后补上的预检。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1、L2、文本质检 | not_run（只读使用已冻结产物） | | 0 | | | | $0 | 哈希与正式 job 一致 |
| L3 配音（TTS，预览通道） | `Qwen/Qwen3-TTS-12Hz-1.7B-Base` + steve_bang_lee SFT checkpoint；DGX Spark GB10，cuda:0、bfloat16、sdpa、seed 43、batch 1 | 本地，无 tier | 20 | ko 82 s，es 86 s（派发墙钟，含模型加载） | ko 52.4 s，es 48.7 s 音频 | 约 0.64×、0.57× 实时（含加载） | $0（本地） | `*-unit-*.receipt.json` |
| L3 回转写筛查、音频质检 | not_run | | | | | | | |
| L4 构建与发布 | not_run | | | | | | | |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 无 | 本轮无错误 | | | | | |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 把"本机跑一遍预览通道输入校验"写进派发脚本的 `--dry-run`，不再手工执行 | 第一次尝试在占用 Spark 后才发现校验错误；本轮手工预检后零返工 | 校验错误不再占用 Spark | DEV-GRP-005 | 本报告 |

## 实际覆盖范围

- **L1、L2：** 只读使用，未执行。
- **L3：** 只做预览通道单独渲染 20 组，加上盲听打包。正式批次那一组复用已有的 ko、es seed-43 原始批次渲染（402/402 绑定）。没有回转写、音频包或同步轨。
- **L4：** 未涉及。

## 遗留状态

- 会话 `grp005-batch-ab-20261019-r2` 已关闭，两个 job 均为 `terminal`；没有剩余容器或队列。
- 结束后检查：llama-server（Qwen3.8-27B）运行且健康，其余服务都已恢复。
- Spark 上 `results/grp005-batch-ab-20261019/` 留有暂存代码、按哈希存的输入、预览输出和日志。
- 本机 `artifacts/local-runs/20261019-grp005-batch-ab/` 留有盲听包（含 `key.json`）和不含 key 的听审目录 `listen/`，都被 Git 忽略。`key.json` 未导出。
- 待做：用户盲听，然后运行 `batch_identity_ab.py record` 记录结果。

## 外部可见的变化

无。没有 Dev 发布或 TestFlight。设备播放、场地验收：`not_run`。
