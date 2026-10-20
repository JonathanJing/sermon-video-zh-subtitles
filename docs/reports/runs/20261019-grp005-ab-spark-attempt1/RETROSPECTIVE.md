# 复盘：20261019-grp005-ab-spark-attempt1

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：**测试**（`DEV-GRP-005` 批次身份 A/B 的"单独渲染"组，15030286 的 ko、es 各 10 组，走预览通道），不属于 `dual_pdf`、`live_session` 或 `four_layer_release`。最终状态 `failed_input_validation`（outcome.json，exit 1）。

ko 在预览通道的输入校验处停下：`Speculative speech may not rewrite target text`，模型尚未加载，合成 0 个单元。es 用同一份操作策略文件，必然停在同一处，所以没有派发。独占会话已正常结束，Spark 服务已恢复。修复见 PR #1100。

证据边界：只有代码校验与 Spark 会话收据，没有音频、听审、发布或设备证据。`humanApproval=false`。

## 总时间

自动汇总：墙钟 1m43s（会话 15:54:55 开启，15:56:38 关闭）。

- 会话开启到 `exclusive_ready` 约 4 秒，停掉 5 个单元。
- ko 派发 15:55:13–15:55:23，约 10 秒：上传与核验输入，再到容器内校验失败。
- 判断 es 不必派发、结束会话约 1 分钟。

没有返工或等待人工。上一轮同类运行无可比。

## 各层模型、耗时与速度

除 L3 配音外各层都未执行（`not_run`），费用为 0。L3 配音（TTS）：Qwen3-TTS SFT（steve_bang_lee checkpoint），cuda:0、bfloat16、sdpa、seed 43，调用 0 次，模型未加载。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L3 预览通道输入校验 | `Speculative speech may not rewrite target text`，exit 1 | 正式 job 绑定 normalization v2（`exact_approved_text_with_registered_spoken_forms`，ko 规则 `ko-sino-chapter-verse-numerals-v4`）。预览通道只接受 v1 `exact_human_approved_target_text_no_rewrite`。所选 20 组都没有被改读，但校验按策略名拒绝 | 占用资源后（独占会话已开、llama-server 已停） | 立即结束会话。预览通道改为也接受渲染器登记过的 v2 策略，但所选组中只要有一组会被改读就拒绝，从不改读 | `tests/test_render_speculative_target_language_speech.py` 新增 3 个测试 | PR #1100 |

应补的预检：派发脚本开会话前，在本机对真实输入跑一遍预览通道的 `checked_context`（只替换 Spark 上的 checkpoint 路径）。这次 dry-run 只核对了输入哈希和命令，没有调用这一校验。修复后已在本机这样核对过：ko、es 都通过；ko 规则改读 8 组，与正式 job 一致，所选 10 组都不在其中。

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 派发脚本的 `--dry-run` 在本机调用预览通道的完整输入校验 | 本轮错误在开会话、停 llama-server 之后才暴露 | 校验类错误不再占用 Spark | DEV-GRP-005 派发脚本 | 本报告；重跑前加入 |

## 实际覆盖范围

- **L1、L2：** 只读使用 15030286 的已冻结产物，哈希与正式 job 一致；未执行。
- **L3：** 预览渲染尝试 1 次（ko），在输入校验失败，0 个单元；es 未派发。
- **L4：** 未涉及。

## 遗留状态

- 会话 `grp005-batch-ab-20261019` 已关闭，唯一的 job 为 `terminal`。没有剩余 job hold、容器或队列。
- 结束后检查：llama-server（Qwen3.8-27B）运行且健康；spark-api、spark-agent、llama-performance-collector 都在运行，job-reasoning-review.timer 为 waiting。
- Spark 上留有 `results/grp005-batch-ab-20261019/`（暂存代码 `repo-7ae4b59be1df`、按哈希存的输入、日志），留给重跑用。
- 本机 `artifacts/local-runs/20261019-grp005-batch-ab/` 留有派发记录，被 Git 忽略。

## 外部可见的变化

无。没有 Dev 发布或 TestFlight。设备播放、场地验收：`not_run`。
