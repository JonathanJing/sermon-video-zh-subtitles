# 2026-10-05 Backlog 状态核对

本轮交付是[唯一顶层 backlog](../backlog.zh.md#backlog-status-audit-20261005)的状态和缺项更新。只读审计已提交代码、工作树差异、GitHub PR/CI、Git内报告及三份本地原始验收收据；没有重跑模型、软件测试、Spark作业、部署、通知或设备验收，没有修改其他任务的未提交实现。

## 审计范围与版本

代码基线为`2373bfff382f27c1dff68ca57a2a2faab5b77514`；新增并发代码为`ae7a7fef`，模型迁移为`17f7d026`，quota设计为`f7afa0a5`，prompt backlog为`d3368537`。检查38项当前P0/P1/P2顶层表、R242-001—024、PROMPT-001—004，以及近期STE/DIAG/交付/费用行。不是重新验收全部历史周次，也不从源码存在推断实际部署成功。未取得新证据的历史项目保持状态，其真实现场/设备/母语审核仍不能关闭。

GitHub只读回查确认：

| PR | 当前事实 | 合并commit |
|---|---|---|
| [#231](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/231) | 已合并，2026-10-03 | `c51e4bbba480efe2fcf70ee2b2d622adead0b59a` |
| [#232](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/232) | 已合并，2026-10-03 | `d31cdc2aac87c5358a80b40e55cf908af4279302` |
| [#235](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/235) | 已合并，2026-10-03 | `35c39e3a916ab5d29ca7b3524d8312b244795b05` |
| [#237](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/237) | 已合并，2026-10-04 | `57475fc56d8d6417c6d842559b3780a507a109da` |
| [#239](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/239) | 已合并，2026-10-04 | `3fd972bdeda535bed33d4c824a1dd16e529ca58b` |
| [#242](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/242) | 已合并，2026-10-05 | `5a67c81d7acc88bb540ae9d9f0d2db61567525fb` |
| [#245](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/245) | 已合并，2026-10-05 | `870f511554798d6028d37f7461a94ad71a6cbf37` |
| [#248](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/248) | 开放，未合并/部署 | 审计head `2373bfff` |

## 已完成的有限范围

[PR242实现报告](20261004-pr242-implementation-and-acceptance.zh.md)已记录001—024的软件交付，不能继续把已合并CLI/owner/Study/发布器写成从零待开发。以下三份原始收据本轮实际读回并核验SHA；没有重复执行其工作：

| 证据 | 已证明 | 未证明 | 原文件SHA-256 |
|---|---|---|---|
| `artifacts/pr242-layer3-validation/receipt-benchmark.json` | 同474句cache逐WAV完整解码，校验800.787065→48.098803秒，原生产文件未修改 | GPU/全流程加速、后续修改代码的全生产验收 | `e21d48b1d6988221d10b77768ceba5c2173376bcab550935cefee75e96a53aae` |
| `artifacts/pr242-unified-cli-acceptance-closed-runtime/acceptance.json` | 真实CLI/后台owner100转移、99交接、p95 0.224645秒、0付费/0runtime模型turn | 当前新模型实际三语内容及发布 | `2ce299851edcc58826f8dec0823634b68a60ac3eb728bec52a1ba712a2925769` |
| `artifacts/pr242-temporal-unified-acceptance-1/acceptance.json` | native server/SDK人工signal恢复、同账本canonical转交、无重复派发/0模型 | 生产迁移、高可用、新并行profile完整native验收 | `03eae6d6d26b8472777deb3e6c071d1ce055abe92965bd83f144c920562ca7b6` |

#231已合并候选隔离与离线费用导入；#232已合并Beta对齐状态/ActivityKit和本机纯文字通知；[Beta1.26.10(51)](../../apps/tongxing-ios/BETA-RELEASE-1.26.10.zh.md)有Git内归档、上传和当时Rooted Testing收据。它们不能代替当前真机/现场、APNs sender/收件、富媒体或正式发布。本次未找到Git内52/53发行收据，未凭记忆补写分发状态。

#245的[Dev重跑](20261005-dev-merged-180s-rerun.zh.md)有真实HTTPS/native repository读回，但复用旧内容并含模拟审核；不补成同一新身份的四层正式收据。

## 当前顶层38项：保留范围与下一验收

本表逐项说明核对结论，不把各项已完成组件相加为全流程完成率。`in_progress`含已交付基础和仍需接线/修复，`waiting_evidence`保留指定当前范围的真实验收，不抹掉已通过的旧范围收据。

| ID | 本轮状态 | 核对结论／剩余 |
|---|---|---|
| GOV-001 | verified_baseline | 原分支晋升基线已有；新PR仍经required checks |
| L1-001 | in_progress | Source/MFA/anchor/judge及审核绑定已有；新来源全文事实、人审及strict CLI待验 |
| L2-001 | in_progress | 新run采用Sol6.1 high→medium fast；历史冻结模型保留；新三语真实内容与人工批准待验 |
| L3-001 | in_progress | 正式render/screen/恢复软件及历史音频已有；当前同步修复、人听审/新包待验 |
| L3-002 | in_progress | source-bound自然句和lag诊断已有；自然时长/局部修复不能由拉伸或删义替代 |
| WEEK-001 | **in_progress** | 从pending更新：capability/窗口/metadata/release intent已有；新完整周scope/时长/双端矩阵未验 |
| L4-001 | in_progress | guarded Dev追加/旧资产保护及历史HTTP已有；新身份发布/恢复待验 |
| L4-005 | in_progress | preview/dry-run软件及旧样本读回已有；真实新周v3追加待验 |
| E2E-001 | in_progress | 四层mock/故障链已有；新模型实际全链、原收据恢复及同步待验 |
| CICD-001 | **in_progress** | 从pending更新：统一release身份/attempt/lease/收据已合并；真实跨环境交付待验 |
| L4-003 | in_progress | 跨包审计及拒绝负例已合并；当前新发布候选的全绑定待验 |
| L4-004 | in_progress | Production组装/基线/发布器已有；当前正式读回、回滚和双端刷新待验 |
| IOS-001 | in_progress | v3 reader/学习产物及模拟器已有；真机下载/离线/定位/大字/VoiceOver待验 |
| FIELD-001 | in_progress | 软件和A/B准备已有；远场触发、负样本、防误跳/设备现场待验 |
| TRACK-001 | in_progress | 自动日志/时间线/余量已有；新周完整provider/GPU/人审等待/实际debit仍缺 |
| REVIEW-001 | pending | review receipt/ingest不是两位审核者可用的私有后台；未取得后台交付证据 |
| LIVE-001 | in_progress | 独立直播实现/回放历史范围保留；没有新增现场关闭证据 |
| PROD-001 | blocked | 代码晋升已做；当前内容仍受同步/批准/发布输入门禁 |
| VOICE-001 | in_progress | registry及声音绑定已有；KO/ES当前Eric仍unverified_poc，不授予正式使用 |
| L4-002 | in_progress | locale siblings/rollback/lease软件已合并；当前目标竞争与回滚待验 |
| IOS-002 | in_progress | reader/系统状态实现已有；当前系统/机型/后台/锁屏/中断待验 |
| CICD-002 | in_progress | 路由/固定checks已有；审计head的root-1四层合同失败，当前CI未全绿 |
| CICD-003 | **in_progress** | 从pending更新：guarded publisher/环境入口已有；服务级Production smoke/回退待验 |
| CICD-004 | in_progress | build42及Beta51历史分发已有；目标SHA/当前安装/正式发布独立 |
| TRK-002 | pending | 第二周真实完整scope复现未取得关闭收据，不从已有恢复原语推断完成 |
| SPD-001 | in_progress | 组件/共享池/三locale/并行owner已提交；真实605秒与长队列/质量/听审待验 |
| SPD-002 | in_progress | accounting/关键路径框架已有；provider与GPU完整实测/ETA校准待验 |
| SPD-003 | in_progress | 100步真实离线命令及故障演练已有；新并行/实际媒体全链待验 |
| SPD-004 | in_progress | partial repair/cache/WAV恢复已有；实际局部裁定和跨版本恢复待验 |
| SPD-005 | in_progress | 去重用量/credit及同口径协议已有；真实完整生产/监督和实际账单缺口保留 |
| SPD-006 | in_progress | deterministic owner/Decision/CLI/Temporal已有；新并行及生产迁移/budget能力待验 |
| LOCALE-001 | in_progress | 界面候选已有；没有新增母语/VoiceOver/长文本复核关闭证据 |
| USAGE-001 | waiting_evidence | 统计软件/旧WebAPI读回已有；实体设备实际播放/撤回/跨端统计待验 |
| EXP-001 | in_progress | Gemini sidecar仍shadow；无人类Gold不得改正式事实 |
| EXP-002 | pending | Challenger正式替代不因小样本而成立，无新增盲听/晋级证据 |
| EXP-003 | pending | 历史Cloud/notes方向不等于当前周产缺少Study producer；非阻塞实验待安排 |
| EXP-004 | pending | Harness/Terra隔离调度比较未取得新实跑证据 |
| CICD-005 | pending | 受控CD迁GitHub runner尚缺大媒体/凭据/环境/回退证据 |

`DEV-`前缀在本表省略，主backlog保留完整稳定ID。未直接关闭设备/现场/母语审核/实验的行，是本次没有新关闭证据，不能读成重新做过这些实际检查。

## R242及专项状态修正

- 003、008、019、024改`waiting_evidence`，删除“474未测”“只有fixture”“Temporal尚未实现”等过时剩余项；当前范围证据和原已完成范围分别保留。
- 002/005/009/010/011/012/017/021更新已提交能力：single-flight、冻结输入、共享23业务+1监督、4分支、v2三locale、source4/judge8、CPU4/队列16、ASR batch8。旧controller v1仍单locale，不能静默扩容既有run。
- 006/007/013/014/018软件已合并；剩新身份发布/回滚、两学习产物真人审核及实际逐项裁决。015/020仍`waiting_evidence`。
- DIAG-018/019改`in_progress`：远端adapter/guarded publisher代码存在，真实跨机/新发布验收仍缺。
- L4-007保持`in_progress`但纠正#231“待合并”；L4-006的软件App四产物/reader接线已有，正式发布与人审缺。
- STE-006改`in_progress`，候选/hash/批准/费用/盲评准入原语已合并、不dispatch；新CLI严格预算及prompt-only评估仍缺。STE-001/002保留`pending`的行为改动，登记已有候选/离线原语，不能宣称新版prompt已投入生产。
- COST-002改`in_progress`：当前两环境launcher/config存在，dev/prod只读`--check`均exit0；未请求provider，不证明真实Project/key归属、权限/hard limit/账单。复用既有两项目/两运行key，不继续要求按用途新增多key。
- IOS-003/NOTIFY-001改`in_progress`：#232已合并Beta状态与本机通知。真机未见灵动岛的用户失败保留；远端sender/收件/富媒体和正式通知未完成。
- PROMPT-001—004保持`pending`：源码索引/部分L2快照与STE工具已有，全库映射、Review准入、iteration/晋级消费链没有实现。库清单补真实[Study v2](../../scripts/sermon_study_generation.py)及[审核ingest](../../scripts/sermon_unified_reviews.py)，不误写成无独立大纲/默想producer。

## 新发现的遗漏与阻断

新增R242-025模型默认迁移验收、026严格CLI预算、027额度fallback、028Spark整轮独占，状态与验收在主backlog唯一维护。公平/老化/角色队列、跨主机broker、GPU乱序补窗/跨job驻留/ASR迁移、replica计时口径和新并行Temporal验收补到原父项，不另建第二份排期。

[605秒准备报告](20261005-next-concurrency-test-preparation.zh.md)的138组三语/276mock响应证明共享业务峰值23、结束held0、恢复新增0；实际276译审、Spark TTS/ASR和Luna新参数监督未执行。新增exclusive_ready前置尚未验收，不能从fixture ready推断可以开跑。KO/ES经文pending诊断片段不是经核实版次/人工批准，也不能成为正式通过。

[Spark独占](../spark-exclusive-development-session.zh.md)在审计HEAD只提交设计。当前其他任务工作树有`production_spark_admission.py`、`spark_exclusive_session.py`及诸入口/测试修改，属于WIP。未将这些差异计为已提交/已验收；未停止或恢复任何远端常驻服务。实现变化需新冻结目录，不能覆盖旧准备身份。

严格CLI输出token/单次最坏费用边界仍不具备；L1/L2 CLI已在发送前拒绝不兼容的API输出cap。Study v2仍由[生成器](../../scripts/sermon_study_generation.py)读取API key，经SourceBudget直发bounded API；其[policy schema](../../schemas/sermon-study-generation-policy-v1.schema.json)仅接受旧Astra/Sol及default tier，尚未迁移Sol6.1 fast/schema/CLI adapter，补入013/025。这是现存迁移差距，不能称作已启用的quota fallback或已覆盖的CLI cap守卫。STE准入不dispatch，fallback未实现且关闭；这些目标的CLI严格预算适配沿026推进。新medium复核/Luna CLI速度、实际订阅debit、最多4个迁移测试worker的用量unknown继续挂025/017，不补零。

## CI读回与本次验证

审计读回时间为2026-10-05 21:56 UTC附近，head `2373bfff`。运行[37377440317](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/37377440317)的[root-1](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/37377440317/job/111990418553)失败；日志调用栈为`evaluate_backend_four_layer_dry_run.py::evaluate`，错误`Successful simulation lost its four-layer or safety contract`。root-0当时仍运行；mock/source/full-mock/native/contract等成功不抵消失败，skipped不计通过。日志通过只读job API保存到`/tmp/pr248-backlog-audit-root1.log`，没有推断尚未调查的根因。

本次文档提交的CI将另有新head，不沿用旧head成功声明。只执行diff、文档链接、唯一ID和状态迁移检查；不重新跑历史软件/模型验收。状态变更及对应证据索引见[结构化记录](20261005-backlog-status-audit-receipt.json)。当前新内容仍未形成完整正式四层/设备/现场完成收据。
