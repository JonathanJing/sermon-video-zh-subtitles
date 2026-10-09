# 复盘：20261009-api-luna-g013-rerun-l3

## 实际覆盖范围

- **L1**：复用冻结的 39 个英文源单元、13 组锚点、60–240 秒窗口和原媒体 SHA-256 `374662dc7c00993820360b2095e277ecd7ebf17bc4d873ccf7e2b76a6c7c7930`；没有重做源文审核。
- **L2**：只重译/复核 `fresh-g013` 的三个单元；其他 12 组的 24 个既有 API 响应和审核结果按原 identity 复用。Sol 6.1 high 翻译、Luna medium 独立复核各调用一次，保留阿拉伯数字 `4`。语言结构插件和诊断候选准入通过。
- **L3**：Spark 上完成 13 组 TTS 和 ASR 回转写，共生成 13 个 WAV。候选及音频均属诊断范围。
- **L4**：未执行；没有页面发布、设备播放或场地验收。候选仍是 `humanAcceptance=pending`，`humanApproval=false`、`productionEligible=false`、`releaseEligible=false`。

## 结果和结束信号

- `run-03`：两次尝试都在新请求前停止；旧操作标识已释放，未预留或发送 provider 请求。输出目录没有 `outcome.json`，以其预派发收据和 operations 日志为证。
- `run-04` 至 `run-07`：均以 `outcome=failed` 结束；transport 收据显示每次 API 请求数和预算预留均为 0。
- `run-08`：`outcome=succeeded`。G013 的两次新请求均收到响应；新增最坏预留为 75,736 micro-USD。加上先前 956,221 micro-USD，总预留 1,031,957 micro-USD，低于已授权 40,000,000 micro-USD。
- `audio-r1`：TTS 容器在模型加载前因远端缺少术语表文件退出；没有 TTS/ASR manifest 或推理。远端进程和容器检查完成后，Spark job 以 `known_terminal` 结束，并保存 reconciliation receipt。
- `audio-r2`：`outcome=succeeded`，结果 `completed_diagnostic`；TTS、ASR 的 13 组 manifest、输出哈希和 ASR 对 TTS manifest 的绑定均回读通过。Spark 独占会话随后关闭；四个服务恢复为 active，模型健康，队列为空。

## 耗时

- L2 的两次新 API 请求耗时约 11.65 秒和 8.77 秒；这是完整 HTTP 请求时间，不包含整个 L2 编排耗时。
- L3 TTS：进程墙钟 96.92 秒，模型加载 52.54 秒，推理 62.75 秒，8 副本 × batch 8，CPU worker 4。
- L3 ASR：进程墙钟 28.64 秒，模型加载 16.28 秒，推理 8.97 秒，1 副本、batch 8。
- `run-04` 至 `run-07` 的短耗时是本地校验失败，不是模型运行时间。`audio-r1` 约 27 秒的结束过程也没有进入模型推理。

- 全流程墙钟跨度：第一次有 outcome 的运行尝试 `run` 从 2026-10-09 01:09:46.363 UTC 开始，到 `audio-r2` 于 01:45:39.012 UTC 完成，共 **35分52.649秒**。若从首轮实际 API 运行 `run-02` 开始，则为 35分45.827秒。
- outcome 可计时命令累计 **278.615秒（4分38.615秒）**；未包含没有 outcome 的 `run-03` 尝试、预检和人工排错。因此总墙钟跨度包含大量排错/等待，不等于模型计算时间。关键命令耗时：`run-02` 72.193秒、`run-08` 21.919秒、`audio-r1` 26.470秒、`audio-r2` 153.637秒。
- Luna 吞吐按 `run-02` 的 13 次 reviewer 请求和 `run-08` 的 1 次 reviewer 请求汇总：14,995 completion tokens / 133.681秒 reviewer 阶段耗时 = **112.17 completion tokens/s**。usage 含 8,729 reasoning tokens；扣除 reasoning 后约 **46.87 非 reasoning tokens/s**。G013 重跑的单次 Luna 请求为 1,052 completion tokens / 8.775秒 = **119.9 tokens/s**（其中 648 reasoning tokens）。这是完整请求端到端吞吐，不是纯解码速度；累计输入 54,757 tokens 不计入输出速率。

## 错误

- `run-03`：首次缺少 Spark exclusive session；随后同一内容的重试命中已释放的资源操作 ID。修订 brief 会改变请求身份；旧失败记录保留，没有盲目重发。
- `run-04`：入口默认 timeout 为 180 秒，与缓存冻结的 300 秒 transport identity 不同；缓存校验拒绝继续。改用原始 300 秒 identity 后重跑。
- `run-05`：CLI 将 brief 文件路径传给 JSON 校验器。入口改为读取 brief 文件。
- `run-06`：repair validator 只允许默认生产角色模型，拒绝 fixture 明确冻结的 Luna reviewer。校验器改为使用已验证的运行模型配置。
- `run-07`：预派发 JSON 放在 runner 要求为空的输出目录内。后续尝试将预派发收据放在目录外。
- `audio-r1`：代码 stage 漏了 `docs/series-terminology.zh.md`，因此运行时 policy 校验在 TTS 模型加载前失败。新 stage 加入该文件并验证全部 618 个代码/配置文件哈希后，`audio-r2` 成功。
- 修复代码已提交并推送至工作分支：`9278ace1df96a95ef3d5487ed0f33dba77006fa1`。完成了 `py_compile` 和 `git diff --check`；未新增专门的单元测试，端到端证据仅限上述诊断路径。

## 占用资源之后才暴露的错误

`audio-r1` 的术语表路径错误在独占 Spark job 和输入 staging 之后才暴露，尽管 TTS 容器尚未加载模型。代码清单通过了哈希核验，但清单并未保证所有运行时数据依赖都在 stage 中。后续应让 L3 预检或 code-stage manifest 显式校验 policy 引用的系列术语表等静态数据文件，再申请独占 job。

## 遗留状态

- 没有未结束的 Spark job；独占会话已关闭。四个服务 active、Qwen 健康、队列空。
- 本轮没有向 Dev 发布文件、没有 TestFlight 构建、没有设备或场地动作。诊断 artifact 和媒体均保留在 ignored `artifacts/`。
- 13 个 WAV 和 ASR 逐组结果留在本机诊断目录，没有复制到公开报告或 Git。

## 外部可见的变化

没有页面发布、公开媒体、TestFlight 版本或设备播放变化。L2 候选和 L3 音频只作为本地诊断产物；设备播放与场地验收为 `not_run`。

## 后续

- 维护者在本报告 PR 中审阅错误、耗时和范围，填写云端复盘；合并报告 PR 不代表诊断候选可发布。
- 工程跟进 L3 code-stage 的静态数据依赖预检；本轮修复代码在 `9278ace1`，工作分支为 `codex/api-luna-concurrency`。
- 若要转入正式内容流程，仍需按四层合同创建正式身份，并完成相应人工/豁免、声音审核和 Layer 4 发布授权；本报告不提供这些批准。
