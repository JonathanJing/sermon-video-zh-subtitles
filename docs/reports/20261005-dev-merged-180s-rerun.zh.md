# 合并后固定三分钟 Dev 重跑复盘

本轮从远端 `dev` 的 `870f511554798d6028d37f7461a94ad71a6cbf37`（PR #245 合并）建立 `codex/dev-rerun-20261005`。复用固定 180.013167 秒源片段，SHA `79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b`；39 个 source units，三语各 13 个组。仅重新构建、准备和发布独立模拟页面；未重跑 ASR、翻译或 TTS，模拟审核不构成正式内容批准。

## 实际结果

页面 ID：`mockup-dev-180s-dev-merged-rerun-20261005`。Dev Hosting 最终版本 `dd452b16a1ece249`；9 个执行阶段成功，首轮发布执行器耗时 157.074 秒。保留全部 5 个既有页面和默认页，只增加本轮测试页。

| 验证 | 实际结果 |
|---|---|
| 媒体 SHA、ffprobe、完整音频解码、CLI 正负准入 | 通过 |
| 三语正常 delivery prepare、验证及封存 | 通过 |
| 资源优先发布、更新基线、目录发布、HTTP SHA/bytes 读回 | 通过 |
| 当前 Web reader 实际 HTTPS 读取 | 新页三语通过；每语 13 条全文／口播 cues、大纲和默想可用 |
| 当前 dev 代码编译的原生 repository 实际 HTTPS 读取 | 三语 release、全文、口播字幕、大纲、默想、HTML、音频下载及 SHA 通过 |
| production catalog 投影隔离 | Web／原生均隐藏模拟页 |
| 相同参数恢复 | 已成功的 8 个阶段复用；仅 live_readback 再执行一次，无额外部署 |
| Beta/TestFlight 分发、音频播放、真机／场地 | not_run |

源时钟仍为 180.013167 秒；中文／韩文／西文音轨分别为 191.6／215.2／194.08 秒。客户端按双时钟契约成功读取，音频仅下载和校验，未播放。

## 监督和凭据

Luna 在本轮是 Codex CLI 监督模型，确定性执行器负责生产工具。CLI 使用 `chatgpt` 登录，启动时移除全部 `OPENAI_*` 和 `CODEX_API_KEY`，不消费项目 API key；普通速度请求 `service_tier=default`，忽略用户 CLI 配置以避免继承加速设置。第一次指定 `gpt-6-luna` 被 ChatGPT 登录拒绝，失败回执保留；本机模型列表确认可用 `gpt-5.6-luna` 后以该模型完成监控。模型名是配置身份，CLI 没有独立返回服务端模型身份。

生产工具通过显式 dev 启动器加载 `tongxing-dev-runtime`，未转发 prod key；本轮模型 API 调用为 0，API 推理 token／费用均为 0。Codex 的订阅使用与 API 费用分开。

完成的 Luna CLI 会话报告输入 307,284 token（其中缓存输入 268,032），输出 5,555 token，耗时 326.823 秒；会话输出吞吐约 17.00 token/s。该耗时包含工具和等待，不是模型生成速度；内部生成耗时和生成 TPS 保持 null。失败启动没有 token 回执，不补造为 0。

## 复盘与改进

1. 新页链路通过，恢复机制按预期避免重复部署。历史模拟页 `mockup-20261005-dev-180s` 仍有三语 `Invalid published transcript cue`，本轮 Web readback 明确记录这些旧错误，未把全目录宣称无错误，也没有覆盖或删除保护范围内的旧页面。应将失效模拟页的修订或退役作为独立任务处理。
2. Luna 独立复盘没有从它检查的日志中确认缓存命中。主进程随后在 test-complete 加入明确 `cacheEvidence`：源缓存身份、0 次新模型调用、baseline sourceKind 计数和已成功阶段复用数量。以后应在监督可读取的结构化报告中直接提供这些字段，而非依赖人工阅读多个大文件。
3. 监督输入量偏高，即使多数命中缓存仍占用额度。下一轮应让确定性监控输出阶段差异和简短摘要，减少全日志／大 JSON 反复送入上下文；常规轮询由程序完成，监督模型只在状态变化、异常或最终复盘时判断。
4. 在启动前核对 CLI 可用模型列表，避免把桌面可用别名直接假定为 CLI ChatGPT 登录也支持。此次失败未影响确定性生产任务，也未转为付费 API。

## 证据和重现

本轮 ignored 产物根为 `artifacts/dev-180s-page-test-20261004/dev-merged-rerun-20261005/`。关键回执：`run-context.json`、`verification/`、`inputs/simulation-scope-report.json`、`baseline/baseline-receipt.json`、`workflow/run-report-first.json`、`workflow/workflow-state.json`、`workflow/final-overlay/deployment-attempt-v2.json`、`web-readback.json`、`native-readback.json`、`credential-routing-check.json`、`monitor-accounting/summary.json`、`monitor-accounting/model-calls.csv`、`luna-review.txt` 和 `test-complete.json`。秘密和媒体未写入 Git。

构建及执行命令见 [固定片段工具](../dev-180s-page-test.zh.md) 和 [诊断执行器](../dev-diagnostic-delivery-runner.zh.md)；本轮原参数恢复只能复用其原始输入及实现身份，后续代码变化需建立新 run，不能绕过哈希准入。

## 后续核实：GPT-6 Luna 失败是旧 CLI 调用路径问题

本轮调用的 `/Users/jonathan_jing/.local/bin/codex` 指向独立安装，版本 `0.153.4`；该版本出现 Unknown model 与 ChatGPT 渠道拒绝。桌面应用自带 `/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex` 为 `0.159.0-alpha.12.1`，其模型目录包含 `gpt-6-luna`。使用同一 ChatGPT 登录、移除 API key、普通速度配置，在新版 CLI 做最小测试，退出 0 并返回 `OK`。这说明账号可以通过新版 CLI 使用 GPT-6 Luna，不能把旧版错误泛化为 ChatGPT 登录整体不支持。

最小测试只验证模型可调用，不改变本轮已经由 GPT-5.6 Luna 完成的监督结果与速度计量。下一轮监督应明确使用已验证的新 CLI 路径和 `-m gpt-6-luna`；全局 CLI 符号链接和凭据没有改动。证据保存在本轮 `gpt6-luna-compatibility/result.json` 与 `new-cli.jsonl`。官方 [模型说明](https://learn.chatgpt.com/docs/models) 也列出 GPT-6 Luna 的 Codex CLI／ChatGPT 额度支持，并说明可用性依赖客户端与登录渠道。
