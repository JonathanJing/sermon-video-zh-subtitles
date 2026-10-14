# 真实模型片段 E2E

从一场已制作周次的讲道里截一段（约 16 句），用真实模型和真实配音走完 Layer 1–4，发布到 Firebase Dev 的隔离测试页。用来验证合并后的整条链路，以及新规则（读法、质检、预算、发布）在真实输出上的表现。

入口是 [`scripts/run_clip_real_e2e.py`](../scripts/run_clip_real_e2e.py)。它只把现有的正式入口按顺序串起来，不另造规则：预算由 `plan_run_budgets.py` 规划，开工条件由 `check_run_start.py` 检查，Layer 2 走 canonical controller，质检、渲染和音频包也都用各自的正式脚本。

零模型的模拟 E2E 见[固定三分钟 Dev 页面测试](dev-180s-page-test.zh.md)（`run_dev_180s_beta_e2e.sh`）。它不调用模型，也不占用 Spark，适合只验证发布链路的情况。

## 边界

- **所有内容都是机器质检。** `humanApproval=false`，页面显示机器质检说明。
- **默认放行的人工门。** Layer 2 的术语回执、片段声音授权、页面信息批准、提纲和默想的复核，都按运行规格里 `authorization.defaultPass` 这句明确授权填写；规格校验要求这句写明 "not a human review"。
- **只发布到隔离测试页。** 测试页必须以 `mockup-` 开头，只出现在 Dev 的 v4 目录里；v3 人工投影的默认页不变。生产环境不受影响。
- **会花钱，也会占用 Spark。** 一轮三语片段的实际花费约 2 美元，但预算按最坏情况预留（见下文）。Spark 独占会话只在 GPU 阶段开启，所有语言做完就关闭。
- **发布要显式授权。** 只有加 `--publish` 才会部署到 Dev Hosting。不加时停在发布前：Layer 4 的准备和 Dev 基线都已完成。

## 前提

| 项目 | 检查方式 |
|---|---|
| 代码已合并、工作区干净，Spark 上部署的是同一提交 | `check_run_start.py` 的 code 和 spark 两项；编排器会用 `git archive` 把当前提交部署到 Spark 的 `<stageRoot>/clip-e2e-<name>/repo-<sha8>` |
| 显式 launcher 能解析 dev（或 prod）凭据，Spark 上的 env 文件是同一把 key | 开工检查的 openai 项；质检授权绑定凭据指纹，两边不一致会在派发前被拒绝 |
| Spark 可达；ASR 权重、运行时和说话人权重在 [`config/clip-e2e/spark-runtime.json`](../config/clip-e2e/spark-runtime.json) 写明的路径上 | `clip_e2e_spark.py` 每个阶段派发前都会探测 |
| 源周次的冻结政策、术语回执、声音授权和说话人登记都在本机 | 运行规格里填这些文件的路径 |
| 用户批准的总预算和出处 | 运行规格的 `budget`、`authorization` |

## 运行规格

复制 [`config/clip-e2e/example-run.json`](../config/clip-e2e/example-run.json) 到本次运行的目录，按实际情况填写。路径相对规格文件所在目录。

| 字段 | 含义 |
|---|---|
| `name` | 运行名，`[A-Za-z0-9-]`。Spark 目录、会话 ID 和 Layer 2 运行 ID 都由它派生 |
| `clipSpec` | `sermon-dev-clip-spec` v1/v2：源周次、句子范围（必须是完整的句子）、媒体 |
| `layer1` | 可选 `backend=claude_cli_opus` 和 `listPriceCapUsd`：从已批准周次的完整来源包按完整句子裁切，检查来源/时间轴绑定，再用订阅登录的 Opus 5.5 high 审核每句；收据仍为机器审核，测试用的重绑人工回执明确标为模拟 |
| `locales` | 本次的语言 |
| `openai` | `environment`（dev/prod）和 launcher 读取的 env 文件 |
| `authorization` | `approvedBy`、`evidence`（批准出处）、`defaultPass`（必须写明 "not a human review"） |
| `budget` | `totalUsd` 是批准总额；`settledUsdBefore` 是此前已结算的花费，包括未标价转写的预留 |
| `layer2.policyTemplates` / `plugins` | 每种语言：源周次冻结的政策，以及语言插件 |
| `layer2.backend` | 可选，默认 `openai_api`；显式 `claude_cli_opus` 会把片段政策重新冻结为 Opus 5.5 high 初译及 medium 复核。Claude 订阅调用的列价等价金额单列，不计入 `budget.totalUsd`；文本和音频质检仍计入批准的美元总额。 |
| `layer2.claudeListPriceCapUsdPerLocale` | 仅用于明确批准的单次 Claude 片段测试；覆盖该次 Layer 2 规划中的每语订阅列价等值上限，随运行规格和预算收据冻结，不改周更配置。 |
| `layer2.repairSpendFractionByLocale` | 运行规格 v2 专有，仅限隔离 Dev 且需本次明确授权；按语言把 Layer 2 自动修订的调用和 token 子上限从默认 10% 提高到最多 30%。执行配置用 v6；旧 v1/v3/v5 保持原语义。全局预算、单句次数及质检放行条件不变；比例写入修复账本，续跑不得更改。 |
| `layer2.scopeRegisterRules` | 可列出需要裁去片段外来源单元规则的语言；保留通用规则、片段内的来源绑定条目，并把结果重新冻结到片段政策。 |
| `layer2.initialClaudeCacheSources` | 可按语言引用先前失败运行第一轮已返回的 Claude 缓存。导入前核对来源、锚点、政策、插件、运行身份和每个返回；正式运行再次核对请求指纹。未返回的启动标记须由终态作业及有效预算账本证明没有预留，才能只跳过这些未派发项；其余未知结果拒绝导入。 |
| `layer3.attestationTemplates` / `speakerRegistry` | 源周次的用户声音授权（会改绑到本片段的来源包）和说话人登记 |
| `layer3.reuseAudioFrom` | 可按语言绑定一个先前运行的音频包、ASR 筛查和所在运行目录。续测先核对音频文件、来源、政策、候选文本、文本 waiver 和旧预算收据，再复用已筛查的包；不重复合成。 |
| `qc.maxRevisions` | 每种语言的文本质检最多打回 Layer 2 几次（0–3，默认 2） |
| `page` | `pageId`（`mockup-…`）、三语展示文案（必须标明是测试）、可选的 Dev 基线缓存 |

## 命令

```bash
.venv/bin/python scripts/run_clip_real_e2e.py run --spec artifacts/<run>/run-spec.json --run-dir artifacts/<run>
```

- **续跑：** 同一条命令。已完成的阶段跳过；运行目录绑定首次使用的规格，改过的规格会被拒绝。
- **只跑到某一步：** 加 `--through layer2`，或 `qc.ko`、`audio.es` 等。
- **发布到 Dev：** 加 `--publish`。
- **修复音频质检失败：** 当 `audio.<语言>` 的 `nextActions` 全部为 `resynthesize_new_seed` 时，运行 `repair-audio --spec artifacts/<run>/run-spec.json --run-dir artifacts/<run> --locale ko --seed 43`。它按同一总预算为新提交规划独立质检授权，在独立渲染根保留旧失败与修复账本，对新音频重新压缩、筛查、打包和质检。通过后再用原 `run --publish` 续跑 Layer 4；结果未知先对账，不换种子盲试。
- **已定位发音问题时：** 可加 `--unit-instructions artifacts/<run>/l3/<语言>-repair-instructions.json`，只为失败单元提供与批准文本绑定的朗读提示；提示文件必须在本次运行目录内，哈希随修复尝试冻结。不得借提示改译文或绕过失败账本。
- **查看状态：** `run_clip_real_e2e.py status --spec … --run-dir …`，显示各阶段状态、已结算花费和仍未结束的质检上限。

运行目录必须在 `artifacts/` 下，因为音频质检会把它镜像到 Spark，并挂载在同一个绝对路径。每一步的输出在 `logs/<步骤>.log`，耗时记在 `timings.tsv`，结束时写 `summary.json`。

## 阶段

| 阶段 | 做什么 | 结果 |
|---|---|---|
| `inputs` | 默认由 `build_dev_180s_simulated_inputs.py --clip-spec` 截出片段；`layer1.backend=claude_cli_opus` 时由 `prepare_clip_layer1_opus.py` 只截真实来源、按原周次已批准范围检查裁切和时间轴，再调用 Opus 做 Layer 1 机器审核；`clip_timeline_map.py` 生成片段时间轴映射 | 片段输入在 `artifacts/dev-180s-page-test-20261004/clip-e2e-<name>/inputs/`；运行目录里有 `l2/src/` 的副本和 `l3/clip-timeline-map.json`。Opus 路径另有 `layer1-opus-summary.json`、逐批返回收据和来源包绑定 |
| `layer2-setup` | 每种语言：把源周次的冻结政策收窄到本片段的来源范围和术语后重新冻结（片段里出现、但源周次回执没有译法的术语会被拒绝）；来源绑定的原周次语言插件经原政策哈希核实后只改绑片段来源和锚点哈希，生成独立插件并重新冻结其哈希；写 canonical 执行配置（v3）；在 launcher 里取得非秘密的 API 路由和凭据指纹，写入质检输入 | `l2/policy/`、必要时的 `l2/plugin/`、`l2/execution.json`、`l2/qc-inputs.json` |
| `layer2` | 规划 Layer 2 预算 → 开工检查 → 逐语言 tick controller，直到全部 `succeeded`；有语言 `blocked` 就停 | `l2/text/<语言>/candidate.json` |
| `qc.<语言>` | 为该语言规划质检预算（文本质检、校准、音频质检共用一个根）→ 开工检查 → 文本质检。失败的组带着质检收据回到 Layer 2，开新修订（执行配置 v5，[gate 4](layer2-bounded-auto-repair.zh.md)），再质检新候选，最多 `maxRevisions` 次 | `textqc-<语言>/`；修订在 `l2-<语言>-r<N>/` |
| `audio.<语言>` | 开 Spark 会话、部署代码（每次运行一次）→ 带 `--spark-stages` 的开工检查 → 声音授权、配音作业 → `clip_e2e_spark.py` 依次 render、compact、screen → 构建音频包 → 镜像到 Spark → 音频质检 | `l3/<语言>/audio-package.json`、`aqc/<语言>/` |
| `layer4` | 三语都通过后：`clip_e2e_release.py` 准备机器质检版本 → Dev 基线 → 有 `--publish` 才受控发布 → 浏览器冒烟测试 | `l4/` |
| `report` | `export_run_digest.py` 导出脱敏运行报告；公开报告仍由 `publish_run_report.sh` 单独执行 | `artifacts/run-reports/<日期>-clip-e2e-<name>` |

某种语言在 `qc` 或 `audio` 阶段失败时，记为 `failed`，其他语言照常继续；Layer 4 要三语齐全才执行。续跑时，记录为 `failed` 的阶段只报告原因，不会自动重试。要处理它，先读失败证据，例如质检收据、音频质检的 `nextActions`。

## 预算

规划每个预算阶段时，"已结算"按以下几项相加：

1. `settledUsdBefore`；
2. 本运行 Layer 2 的实际结算；
3. 质检账本里已标价的花费；
4. 未标价的行（例如 `gpt-transcribe`），按它的预留金额计入；
5. 本运行其他还没做完音频质检的语言，按其质检预算的完整上限计入。

所以同时开着的上限加上已结算，始终不超过批准总额。三语片段的质检上限是每语 5.525 美元（含二级 ASR），按语言依次开启，这是[周更运行配置](weekly-run-profile.zh.md)的规则。如果规划器判定放不下，就不写任何授权文件，这一阶段停下，等用户另行批准。

## 失败与续跑

- **结果未知时先对账。** 每个 Spark 阶段派发前会写 `*.started.json`，有标记但没有结果文件，说明结果未知，同一阶段会拒绝再跑。Layer 2 的未知结果由 controller 的持久 job 处理。
- **长片段 Claude 账本。** Claude 片段 Layer 2 按语言分别授权和记账，每语仍受冻结的订阅标价等值上限约束；这避免数百次调用挤满默认的共享账本文件。
- **Spark 会话开不起来。** `begin` 最多尝试 3 次，每次的输出都保留在 `logs/spark-begin-<n>.log`。编排器退出前一定会 `finish` 会话。
- **渲染退出码为 1。** 渲染器自身的初筛标出了句子，后续的压缩和正式 ASR 筛查照常进行；只有退出码不在 0–2 才算未知。
- **音频质检失败。** 该语言记为 `failed`，并记录 `nextActions`，例如 `resynthesize_new_seed`。修复不会自动执行；按上面的显式命令使用新的种子和独立根。修复沿原语言的音频修复账本计数，只有新音频通过质检才把该语言改为 `done`。
- **音频 QC 预算耗尽后的隔离 Dev 续测。** 保留旧运行和预算根，新的阶段预算须单独批准并纳入原总额。`run_audio_qc_budget_continuation.py` 只从旧预算根回放已返回的评审调用，缺失的评审调用由新授权付款；已通过的音频 QC 收据按绑定复制到新状态，二级 ASR 如需新调用也只使用新授权。两个根的来源、锚点、政策、运行身份和 QC 实现须一致。新运行通过 `reuseAudioFrom` 使用原音频包并记录来源；旧根的未知调用或任何哈希变化均阻止续测。
- **部署结果未知。** 按 [Layer 4 公开交付](layer4-four-product-public-delivery.zh.md)的规则，用 `guarded_hosting_publish.reconcile()` 对账，不要重新部署。
- **Dev 发布成功但浏览器冒烟失败。** 先保留原浏览器收据并独立复查；续跑检查已发布工作流的页面、输入哈希及 HTTP 读回终态，跳过部署，只使用发布后且三语通过的浏览器收据。若发布收据不完整则停下对账。冷启动复查给页面 15 秒稳定时间，不把设备或场地状态从浏览器结果推断出来。

## 已知限制

- **质检修复回 Layer 2** 需要执行配置 v5（PR #402）。只有确定性检查失败、没有回译问题的组，还不能自动修复。
- **声音授权模板** 取自源周次的片段证明，`userStatement` 会改写为本次运行的授权说明。
- **Layer 4 的模板目录** `artifacts/unified-cli-acceptance/native-four-product-fixture-v2` 是本机产物，与 `build_dev_180s_simulated_inputs.py` 共用。
- **Spark 的运行时路径和镜像摘要** 写在 `config/clip-e2e/spark-runtime.json`。换了镜像或权重要改这里，并重新校准相关质检。
