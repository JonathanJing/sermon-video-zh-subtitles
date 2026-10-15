# 复盘：20261012-clip-real-model-ko

数据见同目录 INDEX.md 和 manifest.json。上周片段（2026-10-11 第 216–241 句，约 130 秒）的真模型测试，在 PR #351 分支代码上跑。授权：用户在聊天中「授权隔离测试默认放行，美元，先跑韩语」，预算 10 美元（dev 项目）。默认放行只用于人工门，机器检查的失败不改判。

## 实际覆盖范围

- **三语文字质检（沿用本周译文）**：中、韩、西各 26 组，回译筛查全部通过，注错校准每语检出 100%、干净误报 0%，签发豁免。走 Codex CLI，不花 API。
- **韩语 Layer 2（新译）**：按片段重新冻结韩语 policy（术语只保留片段里出现的 Mount Sinai、Old Testament，译名沿用 10-11 人工批准的收据，标为默认放行），canonical controller 用 Sol 6.1 high 初译、medium 复核，经 dev 项目 API。26 组 52 次调用，约 7.95 万输入、1.73 万输出 token，按最坏价约 0.37 美元。候选为 `machine_review_pass_human_review_pending`。
- **韩语文字质检（新译）**：1 组失败，未签发豁免，止步于此。Layer 3（Spark 配音、回转写、音频包）与音频质检没有跑。

## 结果和结束信号

`translation-chunk-0005-u021`：英文「before the trumpets are ever given」，新译「나팔이 주어지기도 전에」，回译成单数 trumpet，记为重大数量问题。本周已发布的译文是「나팔들이」。韩语复数标记常可省略，这可能是 QC 的误报，但按规则失败只能修，不能放行。

## 耗时

文字质检每语约 10–11 分钟，其中注错校准的预取约 8.5 分钟。韩语 Layer 2 一轮约 45 秒。

## 错误

1. **预算按预留计。** 第一轮（r1）预算上限 3 美元，每次调用按最坏情况（16k 输入加 4k 输出）预留约 0.06 美元且不退回，52 次里第 52 次预留被拒（`budget_exhausted`）；实际用量约 0.36 美元。r3 把上限放到 6 美元后一次通过。
2. **被拒的预留在 Spark 会话里留下 unknown 作业。** 预留在发请求前被拒，但会话作业已登记，会话变为 `reconcile_required`，下一轮（r2）在任何模型调用前以 `session_not_ready` 失败。用 `reconcile --confirm-dispatcher-terminal` 对账（证据：worker 日志止于预留，账本 51 次预留 51 个结果），再 `resume-begin`。
3. **片段英文源包的窗口批准缺媒体哈希**，Layer 3 的时间轴映射要求它；已在 PR #351 修正，片段改从源包绑定的 `audio-clean.flac` 剪（视频音轨解码后与它不同，按新规则被拒）。
4. **文字质检不核对 policy 的 sourceScope**：沿用整篇 policy 的片段候选能通过质检，到 Layer 3 才被拒。

## 占用资源之后才暴露的错误

错误 2：预留被拒应在会话里把作业记为已终止，而不是 unknown。错误 4 应在文字质检预检就拒绝。

## 遗留状态

本周生产的 Spark 独占会话（10-11 02:31 UTC 起）在测试前由用户同意结束，llama-server、spark-api、spark-agent、性能采集恢复；测试会话已结束，五个单元（含 job-reasoning-review.timer）恢复，模型健康。Spark 上新建测试目录 `results/clip-test-20261012-ko-l3`（代码副本，未渲染）。

## 外部可见的变化

OpenAI dev 项目：约 104 次 Sol 调用，按最坏价约 0.74 美元（r1 0.36、r3 0.37，r2 无调用）。没有发布。

## 后续

- 门 4（回译 QC）失败接回 Layer 2 重译还没实现（自动修复设计第三节、`fix` 命令设计稿），这是本周人工重做多轮的根源。
- Spark 上没有任何凭据文件，音频质检的二级 ASR 无法在 Spark 上跑；需要用户放置 dev 凭据或把二级 ASR 移到 Mac。
- 预留被拒时会话作业应记为终态；文字质检预检应核对 policy 的 sourceScope。
