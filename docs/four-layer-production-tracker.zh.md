# 四层制作 Backlog 与进度追踪

本页是**每次制作**的操作清单和状态入口。正式包、门禁和失效规则以[四层接口合同](multilingual-production-interfaces.zh.md)为准；本地 tracker 是工作记录，**不能**凭勾选、文件路径或百分比授予人工批准、发布资格、HTTP、设备或现场验收。

需要跨设备查看时，使用[Firebase 四层公开 Tracker](../experiments/sermon-dubbing-poc/tracker-admin/README.zh.md)：它从本地账本、source monitor 与发行收据生成脱敏的实时只读页面，显示每语言页面、语音和声纹状态。

## 四层制作 Backlog

每篇只有一份 Layer 1；从 Layer 2 起，每种目标语言各有一条独立分支。以下 ID 是 tracker 的检查点，工程实现的详细任务分别见[Layer 2/3 开发 backlog](multilingual-layer-2-3-backlog.zh.md)和[Layer 4 开发 backlog](multilingual-layer-4-delivery-app-backlog.zh.md)。两类 backlog 不互相冒充完成。

| 层 | 检查点 | 完成证据及放行条件 |
|---|---|---|
| Layer 1 共享英文事实与锚点 | L1-01 来源媒体、身份与人工范围；L1-02 冻结英文文本与词级对齐；L1-03 句界、停顿和锚点核验；L1-04 英文人工审核与正式 Source Package | 媒体 hash／时长、操作员范围、唯一英文对齐轴、审核收据与 `ready_for_translation` 的包；缺任何一项只保留 shadow 或待审状态。 |
| Layer 2 目标语言文字，每语言 | L2-01 语言策略与经文版本；L2-02 逐单元翻译与覆盖；L2-03 独立机器复核与语言检查；L2-04 人工文字审核与 Candidate | 同 Layer 1 hash 的目标语言策略、完整 source-unit 覆盖、独立复核及该语言人工批准，最终 `human_translation_approved`。中文、韩语、西语互不继承审核。 |
| Layer 3 目标语言音频与同步，每语言 | L3-01 授权音色／能力／Speech Job；L3-02 逐单元合成；L3-03 完整解码／哈希／回转写；L3-04 排程／字幕／完整音轨；L3-05 人工全文听审；L3-06 同视频同步审核与 Audio Package | 同语言文字 hash 一致；每个单元和完整音轨可解码、自然语速、字幕排程有效、全文听审和 1 倍速同视频检查有独立收据。纯文字路径应显式生成 `audio_unavailable` 包；若该次决定等三语音频齐全，则三语均须有合格音轨。 |
| Layer 4 多语言发布与播放，每语言 | L4-01 同语言 Release Package／文件清单；L4-02 目标环境构建与上传；L4-03 线上 HTTP／hash／Range；L4-04 客户端文字／语言／播放核验 | `pageId + targetLocale` 独立包和 allowlist；线上逐资产核验；Web／App 消费真实 catalog 与音轨。设备验收和现场验收分别记录，不从 HTTP 成功推断。 |

### Layer 1 工程 Backlog

Layer 1 目前已有确定性 package generator 和未来周 shadow 接入；下列项是走向稳定正式主线仍需逐项核验的工作，不能从单个片段推断整篇通过：

- [ ] **L1-B01**：把来源媒体、人工范围、英文文本、词时间轴和审核收据的 hash 绑定做成可重复的完整 run 校验；输入变化时使全部语言失效。
- [ ] **L1-B02**：对无安全切点、对齐异常、低置信文本建立可恢复的审核队列；禁止用翻译或配音阶段补改英文。
- [ ] **L1-B03**：完整真实证道的英文逐句、词时间和句界人工审核，并保存 `ready_for_translation` 收据。
- [ ] **L1-B04**：中文 legacy 输入与新 Layer 1 包做 golden replay，核对 source-unit ID、词时间和来源身份无漂移。
- [ ] **L1-B05**：正式入口自动报告 Layer 1 阶段状态、耗时、问题数和包路径；shadow 与正式放行分别显示。

Layer 2 的实现、`zh-Hans` 兼容、韩语 fixture／整篇审核和语言策略任务见[详细清单第 3 节](multilingual-layer-2-3-backlog.zh.md#3-layer-2目标语言文字-backlog)。西班牙语需要同级策略、审核插件、经文版本、fixture、整篇人工审核和独立收据，不能由韩语通过推断完成。

Layer 3 的 renderer、音色能力、筛查、滚动排程、字幕、听审和恢复任务见[详细清单第 4 节](multilingual-layer-2-3-backlog.zh.md#4-layer-3目标语言音频与同步-backlog)。西班牙语同样需要独立音色／发音和整篇音轨验收。

Layer 4 的发布包、catalog、Web／iOS 语言选择、回滚和验证矩阵见[详细清单第 6 节](multilingual-layer-4-delivery-app-backlog.zh.md#6-layer-4-与-app-改进-backlog)。要把三语 Dev 页面用于实际发布，还须核对西语在 catalog 和客户端的能力，不能把韩语两语言用例当成三语言完成。

### Tracker 接入 Backlog

- [x] **TRK-001**：建立每次制作、每层／每语言的状态账本，显示检查点进度、阻塞、证据引用和条件 ETA。
- [ ] **TRK-002**：从正式 Layer 1–4 producer 的收据自动同步状态与实测耗时；同步前核对包 schema、source／locale hash 和 validator 结果。
- [ ] **TRK-003**：积累足够同类运行后，按片长、source-unit 数、语言和模型建立估时基线，显示区间与校准误差；人工审核等待另算。
- [ ] **TRK-004**：将 Dev／正式环境的 HTTP、设备、现场收据自动关联到对应 `pageId + targetLocale`，保留部署、设备和现场三个不同终点。
- [x] **TRK-005a**：提供四层步骤命令计时入口，复用现有追加式 `sermon-workflow-accounting-v2`，按检查点和语言记录实际执行、失败与重试；提供只读计时覆盖预检。旧步骤不得按文件时间补造耗时。
- [ ] **TRK-005b**：把 Layer 1–4 正式 producer 逐一接入计时入口，并将审核发出／回复、依赖就绪／开始的时间作为独立事件记录。区分程序执行、资源排队、人工审核等待、外部阻塞和返工；记录输入单元数、模型／prompt、缓存与 API 用量的可用性。
- [ ] **TRK-006**：本轮三语 Dev 流程结束后，对同一 `pageId + source hash + locale` 做完整审计：核对日志覆盖、重试、并行重叠、人工等待、资源竞争及真实关键路径；用实测墙钟时间校准 Tracker ETA，并列出仍未知的时间。审计前不依据检查点百分比或文件时间给瓶颈排名。

### 周日页面提速 Backlog（本轮结束后按审计证据实施）

- [ ] **SPD-001**：验证 Layer 1 放行后三语 Layer 2 独立并行；每种语言经本语言人工批准后立即进入本语言 Layer 3，不等待其他语言文字。保留 source／locale hash 门禁和三语正式音轨齐全后的最终发布汇合点。
- [ ] **SPD-002**：把经文策略、音色授权与能力探针、页面外壳和来源监控等不消费正式下游包的准备工作前移，与 Layer 1／2 重叠。正式 Speech Job、Release Package 仍只消费已批准且 hash 匹配的输入。
- [ ] **SPD-003**：用相同片段和设备比较 Layer 3 单任务、两路及必要时三路合成；同时记录模型加载、单位音频墙钟、GPU／内存峰值、失败重试和音质。只采用实测端到端更快且不降低质量的并发数。
- [ ] **SPD-004**：审核稿在候选稳定时立即发出，三语可各自审核并批量展示风险单元；分别保存语言、版本 hash、请求／回复时间及修订轮数。压缩等待和重复呈现，不合并或推断人工批准。
- [ ] **SPD-005**：对冻结的同一批源单元做 Astra／Luna 文字阶段影子 A/B。比较端到端延迟、Token／费用、覆盖与经文引用错误、独立复核发现数、人工修订时间；先试低风险候选／检查，过同一质量门禁后才调整正式路由。Luna 不替代 Qwen TTS。
- [ ] **SPD-006**：按三语分支的实际最长路径、资源排队和最终汇合计算 Dev 发布 ETA 的区间；HTTP／Range、设备和现场验收继续分列。每次优化只改变一个变量，保留上一轮可比基线与回退方式。

## Status tracker 和 progress tracker

状态枚举：`pending`、`running`、`waiting_review`、`blocked`、`complete`。`complete` 必须附证据引用；引用只是定位信息，审核仍由各层正式 validator／人工收据决定。完成的检查点需要重做时用 `invalidate`，不要改写旧收据。共享 Layer 1 失效会重开所有语言的 Layer 2–4；Layer 2/3 失效只重开本语言下游。

用[本地 tracker](../scripts/four_layer_progress.py)为每个 page 建立一个**忽略 Git 的运行目录**中的账本。它不自动调用翻译、TTS 或部署；操作者在阶段完成、等待、阻塞时登记真实证据和时间。示例路径只用于新 run，不会覆盖已存在账本：

```bash
python scripts/four_layer_progress.py artifacts/my-multilingual-run/four-layer-progress.json init \
  --page-id my-page --target dev --locales zh-Hans ko es

python scripts/four_layer_progress.py artifacts/my-multilingual-run/four-layer-progress.json update \
  --step L1-01 --status complete --evidence source-media-report.json --elapsed-minutes 18

python scripts/four_layer_progress.py artifacts/my-multilingual-run/four-layer-progress.json update \
  --step L3-02@ko --status running --done-units 12 --total-units 45 \
  --elapsed-minutes 28

python scripts/four_layer_progress.py artifacts/my-multilingual-run/four-layer-progress.json update \
  --step L3-05@ko --status waiting_review --reason '等待韩语全文听审'

python scripts/four_layer_progress.py artifacts/my-multilingual-run/four-layer-progress.json show
python scripts/four_layer_progress.py artifacts/my-multilingual-run/four-layer-progress.json show --json

python scripts/four_layer_progress.py artifacts/my-multilingual-run/four-layer-progress.json acceptance \
  --locale ko --kind device --status passed --evidence iphone-ko-review.json
```

对尚未开工的检查点，可用 `update --step L2-02@es --status pending --estimate-minutes 40` 输入明确的人工估时。对可按单元计数的工作，用 `--done-units`、`--total-units`、`--elapsed-minutes` 计算实测剩余时间，并显示该单元进度。没有估时／实测速率、待审核或阻塞时，ETA 显示**未知**及原因。已有数字时，ETA 在命令行按洛杉矶时间显示，是“所有剩余工作连续串行、无人等待”的最早时间；它不包含休息、排队、返工、模型故障或发布窗口，不是承诺完成时间。层级百分比仅表示检查点完成数，不表示内容质量或媒体生成比例。

上游修订后，明确失效并保留历史事件：

```bash
python scripts/four_layer_progress.py artifacts/my-multilingual-run/four-layer-progress.json invalidate \
  --layer 2 --locale ko --reason '韩语批准译文修订'
```

正式生产入口尚未自动写入本账本；接入自动采集属于后续工程工作。接入时应只读取已通过 validator 的包状态和时间，不把 tracker 的人工 `complete` 回写成正式批准。设备／现场验收按语言独立记录，须以各自收据为准。制作正式环境时把 `--target dev` 改为 `--target production`，重新建账本并重新核验，不能把 Dev 状态原样晋升。

### 从现在开始保留真实耗时

对尚未执行的四层命令，使用[计时入口](../scripts/four_layer_measure.py)运行。它在账本旁的私有 `accounting/events.jsonl` 追加实际执行 span，继承已有子流程日志，保留非零退出；**不**自动把 Tracker 步骤标为完成，也不授予审批。`--` 后使用原本要执行的命令：

```bash
python scripts/four_layer_measure.py run \
  --ledger artifacts/my-multilingual-run/four-layer-progress.json \
  --step L3-02@ko --billing local -- python scripts/YOUR_EXISTING_RENDER_COMMAND.py
```

人工审核发出时及时将对应步骤更新为 `waiting_review`，收到决定时再按正式收据更新状态；两次操作时间可算**操作员登记的等待区间**，不是人实际审阅时长。命令执行时间来自日志的独立开始／结束 span，重试各记一次。中途未用计时入口运行的步骤保持“未知”，不以 Tracker `updatedAt`、产物 mtime 或模型音频长度倒推。审计预检只读，不启动生产或改变账本：

```bash
python scripts/four_layer_measure.py audit \
  --ledger artifacts/my-multilingual-run/four-layer-progress.json
```

当前 9 月 20 日 178 秒片段的 19 个已登记完成步骤是事后根据正式收据回填，均无执行计时。新入口只对**此后通过它运行**的步骤建立实测时间；本轮结束时审计必须把这 19 项列为计时缺口，并结合已有正式收据与人工审核时间线说明可证范围。
