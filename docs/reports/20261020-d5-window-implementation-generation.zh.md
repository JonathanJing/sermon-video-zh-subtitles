# D-5 闭包窗口实现身份代记录：宿主门面、`path_aliases` 键与诊断链迁移

> 2026-10-20（洛杉矶日期）；只记录代码、身份与本地测试，是草稿 PR 的一部分。三语付费复验（文字 QC、校准、音频 QC）要等用户批准预算、草稿一起合并后另行运行，各有收据和运行报告。本文不是发布批准，`humanApproval=false` 不变。

## 依据与范围

- 决定：[scripts/ 迁移计划](../design/scripts-remaining-migration-plan.zh.md) §9.1 的 D-5（用户 2026-10-20 确认）与 §9.2；[门面计划](../design/facade-removal-plan.zh.md) §7。做法照 [D 窗口代记录](20261019-d-window-implementation-generation.zh.md)：草稿一起合并，只重新校准一次。
- 入站基线 `dev@810349e2`（含 N1–N4）。下面的“D-5”值在代码分支头 `26cb6880` 上计算；合并后按文末命令在真实 `dev` 上读回，值不同以读回为准并补记。
- 实际集合、去向与留下的门面见迁移计划 §11。概要：删宿主点名的门面 39 个，移出 `scripts/` 65 个文件，再删调用方已随窗口移走的门面 18 个；新增 `ports.Diagnostic.validate_runtime` 与 dual_pdf 的 `ports.Leases`。

## 身份值

| 身份 | 入站 `dev@810349e2` | D-5（`26cb6880`） |
|---|---|---|
| W（`review.waiver.implementation_sha256`） | `1c28f4aa38c05b9287db01cc8668995e10ba31c21d9d05fbaa508474a8a19961` | `b6ecff232e60ebbdcfe5f4ed6c0659264367ac72192dcb3918e04c6c4b15410e` |
| T（`compute.qc_audio_transports`） | `8ec15fe1556ba0ff5e3b64c9ff5d2f82896216f06bb2c25495385feaf4f5a851` | `2d85dac8caddcae9dae292877444656fdbdb4bdb42a30f9e084b085381324595` |
| 计分（`audio.screening`） | `9f2ff8077671b22a29d1846e30cdfb8c7c9999d30054bd67e7c4b50fa2c20310` | `a210a65205d013807e11efb93d96c8d7c6ae4ee51a1dc6e3a7e6d4daf4d329e9` |
| 语速（`audio.predicted_schedule.rate_implementation_sha256`） | `8f50c233e07bf130d569e15b91abeb35a231f26d18b3e3874b2c7de3581ed9f2` | `06515788efd8575cd92230001ffc5b906cbac8842107a754832ac91bcbe5b398` |
| 预览执行绑定 `previewExecutionBindingSha256` | `794bb5f1c7ac87bbddbd75b27633958835373b1d71c6c01a3b3355e7aa9c9de9` | `b51259f6ee12a38c5cbd9861bd23661250bc14c5f68c1af4c9c04840c97e62c2` |
| `RENDERER_SOUND_IDENTITY_SHA256` | `fef7604882470137f46f1b01fbd06c7c3c9a07166da91003243608785fa47f0b` | `fef7604882470137f46f1b01fbd06c7c3c9a07166da91003243608785fa47f0b`（不变） |
| L1 producer compatibility 最新代 | `c-batch-facade-import-removal-v12` | `d5-window-diagnostic-package-move-v13` |
| Prefect `code_identity()` | `02a1083084f1e3dce038957513574a36afbc9ad29a4435e15cd6fdd03b1ca3e4` | `bf6665767e4bf3218f281dece02553f5f78cf4c4a09bab7292816c4d3016cc24` |
| 模拟 TTS `implementation_sha256()` | `db8f0832df947eff0f7667bb5848af10905f1482b564125766ac4a1270017cce` | `73901a3181903a43e0dcdc7637e602fd95e3fed4c0a2c405d22c4956bd4b4cb3` |
| L2 `text.controller.code_identity()` | `f3a81a3ced24dd7a4d23dcdd731c72cfaafb86b61960f66da78a7b98a28805ef` | `d29579ab9a945f132ed02e142bd8d4a358a715b1646481385cabae5951049608` |

物理清单不变：W 30 个文件、T 7、计分 8、语速 10，文件集合与入站逐一相同。

### 为什么变

- **W、T、计分、语速、预览绑定。** 四个闭包和预览绑定都含 `path_aliases.py` 与 `scripts/tongxing_host.py`。W 的 30 个物理文件里只有这两个字节改变，其余 28 个与入站逐字节相同：

| 仓库相对路径 | 入站物理 SHA-256 | D-5 物理 SHA-256 |
|---|---|---|
| `packages/production/src/tongxing_production/path_aliases.py` | `f96b722e627bb4792c6c2387f6bb3105408d017bb786d08b85361d269cc5d31a` | `8e3b2031fe1f8194c1754c941e29a423b1e72e76451695990e015936a67ca50d` |
| `scripts/tongxing_host.py` | `8f69b29d53405e9fa6544dfb303c0eadfcf6369faea94c85ade2edd04391e18f` | `3b128ce23f675654f96d2baa9ec840b8c5dd681d0c9eca5ca258107c2e5cb680` |

  `path_aliases.py` 新增 `D5_WINDOW` 一节（65 个旧键），宿主改为导入包内模块并新增两个端口。`audio/`、`review/`、`compute/qc_audio_transports.py` 和 `storage/` 下没有文件改变；`source/` 下只有 `producer_compatibility.py`（v13，不在这几个闭包里）。
- **Prefect 与模拟 TTS。** 两个闭包仍以 `scripts/` 旧名为键，经新增别名读迁入包内的文件。成员 `sermon_dag_contract`、`sermon_prefect_dag`、`run_sermon_prefect_dag`、`sermon_execution_harness`、`sermon_model_resources`、`sermon_job_liveness`、`sermon_release_workflow`、`sermon_guarded_command` 和三个 `sermon_mock_tts_*` 的字节随迁移改了导入，所以两个身份都换代。只用于模拟、诊断；旧 pilot 根的 `runtime.json` 会报 `pilot_code_changed_requires_explicit_migration`，要另起新根。
- **L2 代码身份**随 `scripts/` 与包内任何 `.py` 变化而变，每批都会变。

### 声音身份不变的证明

- `RENDERER_SOUND_IDENTITY_SHA256` 是 `audio/renderer.py` 里的常量，入站与 D-5 相同（上表）。
- `audio/renderer.py` 在本窗口与入站逐字节相同（`git diff 810349e2 26cb6880 -- packages/production/src/tongxing_production/audio/` 为空），合成、单元指令、排程与 MP3 编码代码都没有动。
- 预览执行绑定随 `path_aliases.py` 和宿主字节换代，预览缓存与正式复用按规则失效；已渲染的声音按声音身份判断复用。

## 其他绑定的变化

- **Layer 1 producer compatibility v13。** `sermon_diagnostic_context.py` 与 `sermon_fresh_diagnostic_source.py` 迁为 `workflows/diagnostic/context.py`、`fresh_source.py`：前者只少了一行宿主导入；后者改为按包名导入迁走的严格链与诊断模块，仓库根取自宿主。新增精确迁移 `d5-window-diagnostic-package-move-v13`：历史侧等于 v12 当前表，只这两个键的字节变（`1e122cf32911…`、`58eb9afbe098…`），其余 8 个键经别名读到的字节与 v12 相同；只读复用原 Source，零新 ASR／source check／MFA，`productionEligible=false`。各代不能跨代组合（测试 `test_d5_generation_covers_only_the_two_moved_producers`）。
- **诊断插件实现哈希。** `diagnostic_structural` 与 `diagnostic_pinned_quotes` 的实现哈希包含诊断上下文文件，所以换代：`7d5d8164805a…` → `383f7bfdd961…`、`42aa0e135a8f…` → `609206c2f16d…`。插件文件本身没动；其余 20 个插件（含全部生产插件）哈希不变。本地 `artifacts/` 里没有绑定这两个旧哈希的 policy。
- **durable job 与 worker argv。** Prefect 节点 worker、模拟 TTS worker、release workflow（`sermon_end_to_end` 派发）、预览 worker 和原生运行时探针改为 `[python, tools/ops/run.py, <模块>, …]`。旧 argv 记录的 job 不再与新请求相等；入站时这些 job root 都已终结（见下“前置条件”）。harness 与监督代理的守护子进程仍按路径运行标准库脚本（`orchestration/guarded_command.py`、`guarded_worker.py`）。
- **执行身份。** `EAGER_PRODUCER_IMPORTS` 全部改用包内模块名；`ENTRY_LOAD_TIME_IMPORTS` 新增监督代理加载时导入的 `backend.cloud`、`backend.leases`、`backend.observability`，已加载文件集合仍覆盖它们实际运行的代码。
- **Temporal。** 文件留在 `scripts/sermon_temporal/`（D-3）。`integration_check` 的 `dependencySha256` 键不变，经别名读新文件；隔离 venv 由 `local_io.py` 按路径加载 `storage/files.py`；项目 Python 的 adapter 改导入包内 harness 与监督代理、`tools/ops/run_saturday_harness.py`。

## 需要重新校准的语言

在主检出与各 worktree 的 `artifacts/`、`tmp/` 里按完整 W 检索（只读，2026-10-20）：

- **当前 W `1c28f4aa38c0`：** 只有 post-G1 测试片段 `artifacts/opus-e2e-dev216-20261014-g/post-d-window-qc-20261019/`（es、zh-Hans、ko 的文字与音频 QC 收据、计划和预算根），以及 N3 会话的本地测试产物。合并后它们与 `dev` 不符，三语都要在新 W 下复验。
- **没有未发布的生产语言持有当前 W 的收据。** 15030286 生产运行（`artifacts/weekend-live/…`）的 text-qc 与 audio-qc 绑定 W `51e2b9cae580`，按冻结检出续跑，不受本窗口影响；zh-Hans 仍只有 `prepared-zh-v1`、未发布，若改在 `dev` 上续跑要按新 W 重新校准。
- 预算授权的 `qcContext.qcImplementationSha256` 绑定 W，所以旧授权文件不能沿用，复验要新写授权。

## 付费复验建议（待用户批准，未花钱）

做法同 D 窗口：在 post-G1 测试片段（`artifacts/opus-e2e-dev216-20261014-g`）上，复用冻结来源、锚点、政策、已审 L2 候选和声音授权，在新 W 下对 es、zh-Hans、ko 各跑文字 QC 与注错校准（Mac，Dev OpenAI API judge），再在 Spark 上重新生成 speech job、渲染、压缩、筛查、打包，跑音频 QC 与校准。估算按 D 窗口的结算（运行报告 #1146–#1148、#1152–#1154）：

| 语言 | 文字：D 窗口请求数／预留／冻结费率估算 | 建议文字预留上限 | 二级 ASR：D 窗口请求数／预留 | 二级 ASR 上限 | 本语预算根总上限 |
|---|---|---|---|---|---|
| es | 220／US$2.221／US$0.299 | US$2.30 | 20／US$0.090 | US$2.025 | US$4.325 |
| zh-Hans | 212／US$2.289／US$0.355 | US$2.30 | 24／US$0.108 | US$2.025 | US$4.325 |
| ko | 216／US$2.335／US$0.358 | US$2.34 | 1／US$0.0045（停在 u007，未校准；若进入校准约 20–24 次、约 US$0.11） | US$2.025 | US$4.365 |

- **预计实际花费：** 文字三语合计约 US$1.01（发票未核验）；二级 ASR（`gpt-transcribe` 行未标价，按预留计）合计约 US$0.20–0.31。全部约 US$1.2–1.4。**预留上限合计 US$13.015**（文字 US$6.94 + 二级 ASR US$6.075）。
- **预算根布局：** 每语只开一个预算根，授权的 `costMicrousd` 一次给到“文字上限 + 二级 ASR 上限”。音频 QC 的文字判定从同一根重放（D 窗口 es、zh-Hans 就是这样，音频阶段没有新增文字请求）。上次 ko 的文字根只授权了文字（总界 US$2.34，预留 US$2.335 后没有余量），音频阶段只好另开一根、再预留一份文字上限；这次 ko 的根直接授权 US$4.365，就不需要第二份文字预留。
- **Spark 时间：** D 窗口每语渲染约 87–89 s、压缩约 17 s、筛查约 39–43 s、打包约 5 s、音频 QC 23–150 s，即每语约 3–5 分钟计算；加上独占会话开关和容器启动，三语顺序跑约 25–35 分钟独占 Spark。文字 QC 在 Mac 上，每语约 190–225 s。上 Spark 前先在本机用 spawn 方式冒烟一次 `tools/ops/run.py audio.renderer`（#1151 的教训）。
- **预期结果：** 输入与 D 窗口完全相同，最可能复现同样的结论：es 签发；zh-Hans 校准 `audio.dropped_key_word` 7/9 而拒绝签发；ko 在 seed 42 的 u007 `requires_repair`、停在校准前。这次复验证明的是新身份下结论不变，不是修复这两项。
- 新授权要绑定新 W（`qcContext.qcImplementationSha256`），旧授权文件不能沿用。

## 前置条件（2026-10-20 20:41Z，只读）

- 没有进行中的 Layer 2、统一 CLI 或 app-delivery 进程（只有约 21 小时前留下的 48 个 `multiprocessing.spawn` 孤儿进程）。
- durable job：主检出 181 个请求全部终结（82 succeeded、99 failed），其中旧 argv 160 个 `canonical_layer2_controller.py`、14 个 `sermon.py`、7 个 `sermon_mock_tts_worker.py`；各 worktree 没有 job。
- Spark：没有会话占用。最后一个会话 `clip-e2e-grp20261020-es` 在 20:07Z 关闭，单元已恢复，无容器，`llama-server` 健康。合并前要重新确认这三项。

## 验证

本地（CI 自 2026-10-19 关闭）：完整 unittest 十个分片、pytest 风格文件、§5.5 测试 ID 清单、附录 A、`scripts/` 布局守卫与 `git diff --check`。结果见本窗口的本地运行报告 PR。测试 ID 6066 → 6067（新增 v13 测试 1 个，没有丢失）。附录 A：`dev` 73 个门面 → 18 个，宿主不再点名任何门面；窗口集合里只剩 Cloud Run 镜像用的 `sermon_production_supervisor` 与 `run_sermon_production_supervisor_agent`（D-2，随下次部署删）。

## 合并后读回

```bash
.venv/bin/python -c "from scripts import tongxing_host; from tongxing_production.review import waiver; from tongxing_production.compute import qc_audio_transports as t; from tongxing_production.audio import screening, predicted_schedule as p, renderer as r; from tongxing_production.text import controller as c; from tongxing_production.orchestration.prefect import dag; from tongxing_production.compute.mock_tts import contract as m; print(waiver.implementation_sha256(), t.implementation_sha256(), screening.implementation_sha256(), p.rate_implementation_sha256(), r.preview_execution_binding_sha256(), r.RENDERER_SOUND_IDENTITY_SHA256, dag.code_identity(), m.implementation_sha256(), c.code_identity())"
```
