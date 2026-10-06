# Codex CLI 三分钟翻译／复核流程测试

该入口使用真实 Codex 在线调用，复用现有 Layer 2 的逐组提示词、覆盖检查、Sol 独立复核和 evidence 汇总。固定三分钟样本的人工收据是模拟的，因此旧入口只运行明确隔离的测试请求，不能生成正式 Target-Language Candidate 或人工批准。另有下文的新冻结诊断入口，可执行实际 plugin 和候选准入，候选始终包在诊断 envelope 内、人工批准 pending、不可发布。旧入口支持中文、39 个 source units、13 个原分组；新入口不硬编码组数，一个 group/locale 顺序执行。不会重跑 ASR、TTS 或发布。

## 调用

```sh
.venv/bin/python -m scripts.run_codex_layer2_test \
  --fixture-dir artifacts/dev-180s-page-test-20261004/dev-merged-rerun-20261005/inputs \
  --policy config/target-language-policies/zh-Hans.json \
  --out-dir artifacts/codex-cli-layer2-180s-NEW-RUN \
  --reviewer-tier fast
```

Astra 翻译使用普通速度；Sol 审核可选 `default` 或 `fast`，推理强度来自所选策略（本例为 medium）。同一输出目录可用完全相同参数和实现恢复；改 CLI 版本、适配器、输入、策略、速度档位或测试实现须建立新目录，不覆盖旧证据。把 `NEW-RUN` 替换为独立运行标识。本轮实测回执留在 `artifacts/codex-cli-layer2-180s-20261005/`，代码补强后不能用当前实现恢复那个旧身份；见 [实测复盘](reports/20261005-codex-cli-layer2-180s.zh.md)。

[`run_codex_layer2_test.py`](../scripts/run_codex_layer2_test.py) 验证固定 fixture 的 simulation scope、媒体身份、39 单元、13 组和单 worker。只读取旧候选的 group membership，不读取其译文；真实翻译和审核由 [`codex_layer2_transport.py`](../scripts/codex_layer2_transport.py) 注入 [`run_target_language_models.py`](../scripts/run_target_language_models.py) 的共享循环。正式入口的 Layer 1/策略/plugin 门禁和默认 API 调用没有改动；本测试不能替代 canonical controller 端到端 dispatch 验收。

## 先跑 Mockup

在新的输出目录添加 `--mock-responses-dir artifacts/codex-cli-layer2-180s-20261005` 可通过同一分组循环回放历史完整响应。该模式不构造 Codex transport，不读取登录文件、不启动 CLI（包括 `--version`），也不调用 API。历史 payload、raw 响应和原 transport context 共 53 个文件进入 fixture 身份；请求必须精确匹配，每次回放重新核对文件哈希。输入、策略或响应变化即拒绝。

结果为 `fixture_replay_pass_test_only`，`realModelCalls=false`；历史 usage 不计入本轮真实调用或速度。回放通过只证明循环、覆盖、持久化及恢复路径。随后去掉该参数，以另一新目录运行真实 CLI，才能取得新的调用回执。

## 认证、终态与缓存

仅接受 ChatGPT 登录；从 CLI 子进程移除 `OPENAI_*` 和 `CODEX_API_KEY`，忽略用户配置，使用独立临时 cwd、ephemeral 会话和 read-only sandbox。指令禁止工具调用，适配器另检查实际 JSONL；任何工具事件、失败、缺完成事件或 final file/message 不一致均拒绝。没有 API fallback、自动重试或密钥加载。

CLI 新返回使用独立 `codex-cli-layer2-response-v2` envelope，含版本化 `creditUsage` 估算，reader 继续接受历史 v1；不伪造 OpenAI Chat Completions 返回。requestId 为本地 `codex:<threadId>`，模型与速度档位是请求配置，未返回的服务端身份保持 null。每组两个独立进程／会话；输出 JSON schema 校验之后仍经过现有语义检查。机器审核失败保留返回并停止，不静默放行。详见[credit 日志与迁移](model-call-logging.zh.md#codex-cli-credit-估算)；历史 v1 缺少估价设置时保持未知，不新增模型调用补测。

CLI 版本、入口及二进制 SHA、适配器 SHA、输出 schema、速度档位和超时一起进入 `codex-layer2-transport-identity-v1` 执行身份及调用 fingerprint。API 原缓存 fingerprint 保持不变；API 与 CLI 缓存不能混用。仅支持同一 run 内的验证后缓存／raw 恢复，不开放跨 run carry-forward 或迁移。

已有 `.started.json` 没有 durable raw/cache 表示未知结果，必须先对账，恢复不能重发。默认单次 CLI 超时 180 秒；超时保存诊断并保留未知标记，不认为服务端没有执行。返回已持久化但 JSON/schema 不合格时保留 raw，恢复校验不重新调用。首次 dispatch 前在输出目录旁持久化 `<run-name>-pre-dispatch-context.json`，并在运行结束保存 `test-context.json`；两者绑定测试实现和实际 runner 的 hash，强制中止或实现变化不能跳过绑定。

## 证据与计量

输出包括原始请求、run identity、逐组 policy preview、private raw 和 cache、汇总 `evidence.json`、`test-context.json`、`test-report.json`、`_cli_calls/` 的完成／失败回执，以及 `accounting/`。原始提示词/返回/认证相关 stderr 仅留 ignored artifacts；不要将其整份上传或写入 Git。正式 API Project/key 配置保持原样，CLI 的订阅调用不填项目 API 费用归因。

账本使用 provider=codex、backend=agent_session、role=production；阶段名区分 translator/reviewer。`billing=local` 在这里表示非 API 调用，不能解读为离线模型或零成本。接收 CLI host telemetry 的 input、cached input、output、reasoning token；elapsed 是真实进程区间，包含启动、认证、排队及等待。输出 token/elapsed 是会话吞吐，未取得 generationSeconds 时生成 TPS 为 null，缺 usage 也保持未知。Fast 的实际额度扣减和服务端档位均需独立回执，不能仅凭配置推算。

恢复验收应确认：13 组按源顺序汇总，26 个唯一 role/session ID，源单元各覆盖一次；全部机器语义检查通过。随后同参数恢复，确认 `_cli_calls` 数量及返回哈希不变，没有新模型调用。语言插件、canonical candidate admission、人工审核、正式生产 dispatch、音频和发布保持 not_run。

后续 [1–24 路并发实测](reports/20261005-codex-cli-concurrency-24.zh.md) 验证了独立 CLI 调用的容量；不改变本入口 workers=1、正式 controller 的语言／组预算或 GPU／发布锁。

## 接本地模型诊断

[固定片段本地 worker](../scripts/experiments/replay_fixed_clip_local_models.py) 消费本轮新的 `evidence.json` 和同一源视频，运行真实 TTS batch=2、回听 ASR batch=4。它复用注册 voice/checkpoint 的验证与现有 QwenSynthesizer，始终 `diagnosticOnly=true`、`humanApproval=false`、`formalEligible=false`；不创建正式 speech job、同步轨或发布包。checkpoint map 使用该执行容器内的本地权重路径，留在 ignored artifacts。

```sh
python scripts/experiments/replay_fixed_clip_local_models.py tts \
  --evidence NEW-RUN/cli/evidence.json --media FIXED-SOURCE.mp4 \
  --registry config/speaker-voice-registry.json \
  --checkpoint-map LOCAL-CHECKPOINT-MAP.json --out NEW-RUN/tts
python scripts/experiments/replay_fixed_clip_local_models.py asr \
  --tts-manifest NEW-RUN/tts/manifest.json \
  --model-path LOCAL-ASR-SNAPSHOT --out NEW-RUN/asr
python scripts/experiments/assess_fixed_clip_local_models.py \
  --tts-dir NEW-RUN/tts --asr-dir NEW-RUN/asr \
  --anchor FIXTURE/anchor.json --media FIXED-SOURCE.mp4 \
  --out NEW-RUN/assessment.json
```

在具备 GPU/本地权重的隔离容器执行前两个命令，关闭网络；最后的评估只需 Python、ffmpeg/ffprobe，可在 Mac 执行。路径占位符替换为本轮独立目录。完整完成回执可同参数恢复，不加载模型或重新推理；unknown 批次先对账，不通过删 started marker 重发。评估检查全量解码、时长、源窗口和 ASR 绑定，即使全部相似度通过也不赋予发布资格。首轮与恢复计量分别保留。

见 [Mockup、真实 CLI 和本地模型本轮复盘](reports/20261005-fixed-180s-mock-codex-local-rerun.zh.md)：真实链完成，但 185.92 秒配音超过 180.013 秒源视频，8 组超源窗口；该指标在 v2 中仅作警告，实际同步仍有延迟和片尾溢出，保持发布阻塞。

## 复盘后的资源与驻留增量

真实 CLI 测试可显式添加 `--resource-policy /absolute/path/policy.json`，使用[统一资源策略](unified-resource-admission.zh.md)中的 `codex_cli` 池，每次调用占一个槽。该入口仍是单 worker；上限是准入容量，不是自动创建并发任务。策略和适配器进入运行身份，使用新目录。Mockup 不能同时配置资源策略；已验证的 cache/raw 恢复不占模型槽。

共享循环先准入、再保存 started、最后调用模型。容量忙时零 dispatch、无 started 标记，容量释放后可重试；本测试命令没有自动等待队列。成功或明确失败的 CLI 终态事件、response 和资源 outcome 先私有原子写入并 fsync，再释放。超时、损坏／缺失终态或写入失败保留 held，不自动回收，也不绕过 unknown 重发。

独立本地 `tts`／`asr` 命令也接受 `--resource-policy`，两者保守共用 `spark_tts=1`，覆盖整个 job。完成批次、模型释放和 GPU 清理收据、最终 manifest、outcome 持久化之后才释放。清理失败或结果未知保持占槽。必须在同一协调主机共用 brokerRoot；这不是 Mac 与 Spark 间的跨主机调度。canonical.audio 已占 GPU 时不要再嵌套这份许可。

Python producer 的 `render_tts`／`back_asr` 新增可选 `model_session` 与 `runtime_identity_sha256`，供隔离实验复用 [`LocalModelSession`](../scripts/experiments/local_model_session.py)。调用者须冻结实际容器／依赖运行时身份 SHA，使用显式 session 生命周期；同一权重、checkpoint、设备、dtype、attention、运行时和实现才复用。只允许一个缓存模型和一个活动借用，切换先释放旧模型；加载、清理或借用期间失败即禁止后续复用。该实验接口尚未部署常驻服务，不能与每 job GPU 策略同时启用：跨 job 驻留必须先实现覆盖整个 session 的 GPU 许可。fake factory 测试证明复用机制，真实冷暖速度尚未测量。

评估输出升级为 `fixed-clip-local-model-assessment-v2`，保留旧 v1 文件作为历史证据，用新输出路径运行。新增只读[时间修复计划](../scripts/target_audio_timing_plan.py)，复用未修改的正式 scheduler：源句超长是警告，累计延迟和片尾溢出分别判断。计划不修改文本／音频，也不授予批准。详见[本次开发复盘](reports/20261005-fixed-180s-followup-development.zh.md)。

## 隔离测试的 Sol 6.1 翻译配置

用户选择的新三分钟测试可添加 `--translator-model gpt-6.1-sol`，明确固定翻译为 high/fast，审核保持 `gpt-6-sol` medium/fast、workers=1。原 baseline policy 先按现有合同验证，然后测试入口创建带 `simulationModelConfiguration` 的隔离有效配置，绑定 request、policy、transport、payload、cache 与 pre-dispatch context。正式路径拒绝该配置；未传参数仍使用原 Astra 配置。请求模型如实记录为 Sol 6.1；历史 `astra` 文件后缀和 `astraDraft` wire 字段只为兼容原循环，不代表实际使用 Astra。

该参数不能与历史 mock responses 同用：旧 Astra 请求与新模型请求不相同。默认精确 fixture 回放和新配置的 fake transport 测试分别验证；真实调用须使用新目录及 ChatGPT 登录，无 API fallback。更改模型、effort、tier 或实现后不能沿用旧运行身份。当前 override 仅用于固定片段实验，不改变正式生产策略或扩大批准范围。

2026-10-05 已实际完成该配置的 26 次 CLI 调用和 Spark TTS/ASR，并验证零新调用恢复与资源释放：[复测报告](reports/20261005-sol61-high-fast-fixed-180s-retest.zh.md)、[机器汇总收据](reports/20261005-sol61-high-fast-fixed-180s-retest-receipt.json)。同步仍有 4 组 lag 失败和片尾溢出，不具备发布资格。

## 新规则冻结与实际 plugin／候选诊断链

[`codex_layer2_diagnostic.py`](../scripts/codex_layer2_diagnostic.py) 接收真实未批准的 English Source Package，不把历史批准包重新标为未批准，也不制造人审收据。冻结 source、clip-relative anchor、source-scoped v2 policy、完整分组、plugin 实现、授权引用 hash、代码 commit 与父媒体绝对窗口。首个 CLI transport 建立前完成源、边界、覆盖、术语和 modelRules 前检。

```sh
.venv/bin/python -m scripts.codex_layer2_diagnostic \
  --source SOURCE.json --anchor ANCHOR.json --policy SCOPED-V2-POLICY.json \
  --group-plan GROUP-PLAN.json \
  --plugin scripts/language_review_plugins/diagnostic_structural.py \
  --out artifacts/NEW-FIXTURE --authorization-ref '本次隔离测试授权引用' \
  --code-commit FULL-COMMIT-SHA --translator-model gpt-6.1-sol \
  --scripture-classification no_direct_quotations
.venv/bin/python scripts/run_codex_layer2_test.py \
  --diagnostic-fixture --fixture-dir artifacts/NEW-FIXTURE \
  --out-dir artifacts/NEW-RUN --reviewer-tier fast --timeout-seconds 240
```

路径与 commit 占位符替换为实际输入；policy 必须绑定这份 source/anchor 与当前 plugin，不能直接用未绑定的默认策略。翻译 high/fast、审核 medium/fast 固定在 fixture；正式政策仍拒绝隔离 override。可添加既有 `--resource-policy`，保持 workers=1。mock 可回放该新链自己的精确响应，不能借旧 legacy payload 证明新规则已经被消费。

新链将同一冻结 modelRules 送入 translator/reviewer，核验实际 payload，再运行 pinned plugin 并由真实候选准入函数独立重跑 plugin 读回。输出 `diagnostic-language-review.json` 和 `diagnostic-candidate.json`；后者 `actualHumanApproval=false`、`productionEligible=false`、`releaseEligible=false`，候选人审保持 pending。CLI/规则/plugin 任一失败均留证并停止；同身份恢复复用返回，不因 plugin 失败重新翻译；unknown 不重发。此入口使用现有编辑式 reviewer，尚未完成正式 controller 或 strict/RQC reviewer adapter。

`diagnostic_structural` 只验证文字结构、冻结术语、数字表面与引用范围，不能验收直接经文。冻结时必须提供 `--scripture-classification`，直接引文可用重复的 `--source-quotation-unit` 记录实际风险单元；未检查或直接引用样本在结构 plugin 下拒绝。声明无引文也不能绕过引用检测。较长片段保留整句；父媒体窗口与相对 anchor 分开绑定，不能用片段时长替代父媒体身份。

2026-10-05 新链真实复测先拦截1组pending书名表面不匹配；保留失败包，另建策略明确保留有源证据的原英文书名后，26次新CLI、13组plugin与诊断候选准入通过，同身份恢复0新调用。详见[扩大样本复盘](reports/20261005-cli-rule-chain-expanded-sample-retest.zh.md)；10分钟直接经文片段当前仍在调用前拒绝，474旧缓存只读规划与实际恢复资格分开。
