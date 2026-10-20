# 复盘：D 窗口后韩语音频 QC 与校准

证据见同目录 `INDEX.md`、`manifest.json` 与脱敏的音频 QC 汇总、渲染/压缩/筛查计时和预算结算摘要。原始音频、转写和账本未公开。

## 结论先行

交付类型为 Dev 机器音频质检（测试证据，不是发布批准）。W=`1c28f4aa38c0…`、声音身份 `fef760488247…` 不变。汇总 `requires_repair`。结论：音频 QC 失败：`translation-chunk-0005-u007` 不通过，修复阶梯给出 `resynthesize_new_seed`；整轨核对通过。未进入校准，未签发豁免。原始 10-14 运行中同一单元也在 seed 42 失败，只在 seed 44 加修复提示后通过；本轮按要求不换种子、不复用绑定旧 speech job 的提示，原样报告。

**本轮发现的回归（已修复）：** D 窗口后第一次真实 Spark 渲染在 TTS 副本池启动时失败（`ReplicaPoolError: TTS replica 3 closed its channel`）。multiprocessing spawn 子进程先以 `__mp_main__` 重跑父进程主脚本；原门面导入时绑定宿主，`tools/ops/run.py` 只在 `main()` 里绑定，所以副本导入 `audio/renderer.py` 时未绑定。修复 [#1151](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1151) 在 `__mp_main__` 时绑定宿主（合并为 `dev@5eb39da3`），W/T/计分/语速/预览绑定和声音身份不变。失败尝试未合成任何音频、未付费。

## 总时间

渲染 88 s（退出码 1，同上）、压缩 17 s、筛查 41 s、打包 5 s、音频 QC 23 s（在单元失败处停止）。 各阶段之间的等待（Spark 被其他会话占用约 1 小时、等待 #1151 合并）未计入。

## 各层模型、耗时与速度

- L3 配音：正式渲染器 Qwen TTS（speech job v3，绑定 D 窗口后的新文字豁免；seed 42，CUDA/BF16，Spark 容器）。
- L3 回转写筛查：Qwen3-ASR（本地，Spark）。
- 音频 QC：一级 ASR 取筛查收据；二级 ASR 1 次，预留 US$0.0045（未标价）；因未校准，文字判定 0 次。本根累计预留 US$0.0045，上限 文字 US$2.34 + 二级 ASR US$2.025。
- L1、L2 生成、L4 发布：`not_run`。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L3 渲染（Spark） | TTS 副本池启动即失败 | `tools/ops/run.py` 在 spawn 子进程（`__mp_main__`）中未绑定宿主 | 占用资源后（D 窗口后首次真实渲染） | 修复后重跑 | `test_spawned_children_bind_the_host_before_unpickling` | #1151 |
| 驱动 | 渲染崩溃后仍做压缩 | 渲染器退出码 1 同时表示“单元被标记”和崩溃 | 占用资源后 | 驱动改为要求 `unit-timing-diagnostics.json` 存在才继续 | — | 后续：区分崩溃与标记 |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | Spark 渲染前用 spawn 方式在本机冒烟一次包入口 | 本轮回归只在真实 Spark 渲染时暴露 | 不占 Spark 就发现入口回归 | D 窗口会话 | #1151 的测试 |
| 质量 | 渲染器崩溃与“单元被标记”用不同退出码 | 编排器与本轮驱动都把崩溃当作终态 1 | 崩溃时不继续压缩 | 待定 | 后续 PR |

## 实际覆盖范围

复用冻结来源、锚点、政策、已审 Layer 2 候选与原片段的声音授权；用 D 窗口后的新文字豁免重新生成 speech job，在 Spark 上重新渲染、压缩、筛查、打包，再跑机器音频 QC 与校准。单独的新预算根（用户 2026-10-19 批准：「批准 ko 音频单独开一份新预算：文字判定再预留最多 $2.34（实际约 $0.36），二级 ASR 最多 $2.025」，已用 `record_decision.py` 绑定；最初在 `e8b197be` 规划的同额度计划未使用，改在 `5eb39da3` 重新规划）。Spark 会话 `d-window-audio-20261019-r2`。

## 遗留状态

Spark 独占会话已结束，单元恢复，`llama-server` 健康，无容器。预算根无未知或未结算行（`gpt-transcribe` 行未标价，按预留计）。未发布 Dev 页面，未做设备或场地验收。

## 外部可见的变化

仅此脱敏 docs-only 报告 PR。
