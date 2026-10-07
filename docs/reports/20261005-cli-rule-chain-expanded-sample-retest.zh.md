# 新规则 CLI 候选链与扩大样本复测

2026-10-05，PR [#248](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/248)，工作分支 `codex/dev-rerun-20261005`，开发基线 `a93e59f0ab745e470be9f89e41b30be2c760d4b4`。修订后真实39单元/13组CLI→plugin→诊断候选通过，同身份恢复0新调用；10分钟经文样本正确零调用拒绝，474单元只读导出/规划成功但实际恢复仍blocked。本轮落实[测试审计](20261005-pr248-test-coverage-backlog-audit.zh.md)的 T01 隔离链与 T04 当前 producer 快照。实际执行代码文件 SHA、测试日志 SHA、来源及结果见[汇总收据](20261005-cli-rule-chain-expanded-sample-retest-receipt.json)；原始提示词、返回和媒体留在 ignored `artifacts/next-iteration-repair-20261005/`。

## 修复

新入口冻结真实未批准 source/anchor、source-scoped v2 policy、分组、plugin 实现与诊断授权身份；使用同一 modelRules 的实际 CLI translator/reviewer 返回，经 pinned plugin，再由当前候选准入函数独立读回。候选留在诊断 envelope，`humanAcceptance=pending`、`productionEligible=false`、`releaseEligible=false`。新增精确恢复／raw 恢复、unknown 不重发、plugin 拒绝不重新翻译与禁止正式旁路的回归。默认正式 Astra→Sol API 和 strict/RQC 接线未切换。

Layer 3 exporter 从当前 renderer 共享 `_intent` 和完整批窗输入 builder，显式绑定所有模型/assembly 设置，持已有 shared formal lock，保护输入及依赖哈希；不读旧 intent 来冒充当前身份，不加载权重或创建 cache/owner/批准。精确 direct-parent batch implementation 兼容仅对应这次不改变合成输入的纯函数提取，相关恢复回归已过，不授予任意跨版本迁移。

## 样本扩大

| 样本 | 时长／规模 | 本轮用途与实际边界 |
|---|---|---|
| 原三分钟 | 父源 60–240 s；39 单元／13 组 | 新规则真实 CLI→plugin→诊断候选链与同身份恢复 |
| 同源完整句片段 | 63.32–668.820007 s；605.500007 s，136 单元／114 父句／46 组 | 已构建并绑定父源、原英文与相对时间线；直接经文负例前检，0 模型调用 |
| 9月27日整篇 | 1891.677333 s；420 英文单元 | 本地完整媒体与已批准源包可用；本轮未重译或合成 |
| 10月4日讲道窗口 | 2015.321–3957.444 s；1942.123 s，474 单元 | 真实历史 ES 缓存的当前 exporter→planner，只读、0 推理 |

前两份来自同一父媒体 SHA `374662dc7c00993820360b2095e277ecd7ebf17bc4d873ccf7e2b76a6c7c7930`。10分钟申请窗口 60–660 s 会切断父句，实际按完整句界取 63.32–668.820007 s；英文不改写、timing 只减实际窗口起点，未将批准转移到新诊断包，未生成物理片段视频。三分钟源同样保持真实 pending 状态；不是旧模拟批准 clip 包。

扩大样本包含 `0-u067` 与 `0-u068` 的《启示录》4:2–3直接引用。现有 `diagnostic_structural` 无 source-bound edition/group 逐句经文验收能力。声明 `contains_direct_quotations` 时预检按预期拒绝，exit=1、未创建 fixture、0 CLI/API 调用；即使错误声明无引文，新增 verse/John 引用引导检测也拒绝。不能把它计为10分钟在线性能或经文质量通过。下一轮补 source-bound 引文/版次/分组适配后，对这份固定样本运行实际线上对比，保留这个负例。

## 三分钟在线实录与新 finding

26 个独立 CLI 会话全部完成（无工具调用、无 API fallback），13 组源覆盖完整，translator/reviewer 实际 payload 已核验同份 modelRules。CLI 进程耗时之和 **336.421 s**，本次 accounting 工作流墙钟 **337.329 s**；输入 **443853**、缓存输入 **231296**、输出 **15911**（其中 reasoning **8388**，已包含在输出，不再相加）。角色会话输出吞吐约翻译 **38.06 tokens/s**、审核 **58.08 tokens/s**，合计约 **47.29 tokens/s**；纯生成 TPS 没有直接观测，仍为 null，也不含交互监督/开发消耗。

现有编辑式 semantic reviewer 13 组均 pass，但实际 plugin **12 pass／1 fail**：`fresh-g006` 的书名保留 `Super Bloom`，冻结的 pending 目标则是“超级花潮”。机器审核解释为避免把待核定译名当成正式书名；plugin 仍要求声明的目标表面出现，因而拒绝候选准入，exit=1、未产生候选。这证明新链补上的独立门禁实际生效，不能写成新候选链全绿，也不能仅凭此断言翻译质量差。

该目标来自本次诊断策略的待核定配置，不是已批准的项目书名。当前 modelRules 携带 term/status，但 pending 目标的试用约束与 plugin 精确表面要求尚需明确；应在新修订中冻结“待核定目标必须试用”或“保留原文”的实际约定，再运行对应译审，不能直接把此结果改 pass、删失败项、补人审或反写旧证据。正式政策继续拒绝 pending 术语。已把这条 finding 纳入原术语/prompt backlog。另一个具体消耗点是 plugin 位于全量译审之后：本例第6组失败直到26次完成后才停止。若在独立复核后逐组执行同版plugin，第6组即可停止剩余14次调用；这是待实现的早停/局部修订接线，不能凭本次恢复0调用声称已经具备。

同一身份恢复 **0.627 s**，复现同一 plugin 拒绝，**0 新调用**；159 个受保护的 CLI 返回/raw/evidence/规则身份文件 hash 未变。26 次新调用均进入账本与 credit 估算，reported complete coverage=26/26，**31.08960 purchased-credit equivalent**，实际 debit/额度未知。相较上一轮26次CLI的348.374 s，进程耗时约少 **3.43%**；估算26.04018→31.08960，约多 **19.39%**。本轮显式规则/策略和源身份不同，输入422198→443853、缓存268160→231296；该差异不能归因于单项代码提速，也不构成同政策质量非劣结论。阻塞阶段虽未产出候选，已执行调用的用量仍保留。

## 保留原书名后的修订复测

保留首轮失败包，新建 source/anchor 不变、policy 新版的隔离 fixture。待核定的书名目标改为有源证据的原文 `Super Bloom`，不猜正式中文译名；明确在同份 modelRules 的 registerRules 里冻结待核定表面试用约定。人审仍 pending，未补人审收据或把 pending 改成已批准。CLI 不跨run carry-forward，26次新调用独立执行，不让旧返回冒充新规则消费。

新版 **26/26 CLI完成、13/13 plugin通过**，当前候选准入函数独立读回通过，生成 `diagnostic-candidate.json`；人审／生产／发布资格均 false或pending。工作流墙钟 **317.065 s（5分17秒）**，CLI进程耗时和 **316.204 s**；输入 **494661**，缓存 **305408**，输出 **15396**（reasoning **7892**已包含），会话输出吞吐约 **48.69 tokens/s**，纯生成TPS未知。固定价卡估算 **28.93242 credits**，实际扣减／额度未知。

相对前一轮历史Sol61实测的348.374s，本版CLI区间少约 **9.23%**；credit相对26.04018多约 **11.11%**。仅比较所记同类CLI区间：源身份、显式规则和缓存情况改变，不能归因于单项修复或声称全制作流程同比提速。与本次首轮失败样本比较也不构成质量非劣证据。

同身份恢复 **0.771 s**、**0新模型调用**，216个受保护文件hash不变；再用本版精确payload/raw跑实际mock→plugin→诊断候选通过，未建立CLI transport、未计历史usage为新消耗。broker所有reservation已released。本次两份fresh样本共 **52真实CLI调用**，估算 **60.02202 credits**；不隐藏失败阶段费用，不含交互监督/开发消耗，未调用API或本地模型。

## 474 单元只读实录

旧 ES job 已有 source/window 批准与整句 anchor exception。初次未传例外收据时当前门禁正确拒绝；随后明确提供原绑定的 `anchor-exception-receipt-v2.json`，无需新批准。原 root 缺 formal lock，测试复制到新隔离目录再建立该副本自己的锁；没有修改原生产目录。

当前 exporter 完整覆盖 474 单元，用时 **16.573 s**；planner 用时 **42.150 s**，`reuse=0/revalidate=474/recompute=0/unknown=0`。模型调用、计划模型求值、缺项提交及批窗重放均为 0。原 **1910 文件**与隔离副本旧内容 SHA 全不变；未加载 torch/qwen。缺 owner 对账，474 全部 blocked；这是当前身份规划的正确分类，不等于缓存已获准复用、实际恢复或生产提速。历史输入的包装/实现不同，不能仅凭保留 WAV 宣称 exact reuse。

snapshot 保存 reactionLag/gap/maxEndLag/trackFormat，但这些不进入模型 intent。当前 planner 尚未比较 assembly 设置；改变它们需重建/验证同 locale 的排程、整轨、cue、听审/音频包与 release 绑定，不推导模型重算，不代表旧音频包匹配新设置。

## 验证范围

CLI/政策/候选相关 **167 项**回归通过（8.945 s，含新链11项）；Layer 3/exporter/批窗/旧 context/恢复相关100项回归通过（95.297 s），最终新模块12项通过，跨其两份日志去重101项。两组可能共享 fixture/测试依赖，不把它们当作模型或四层生产次数。结构 schema、定向 diff 与文档路径另外核验。

本轮没有重跑 Spark TTS/ASR、修正旧同步 lag、变更8秒门槛、发布 Dev/Beta 或验收真机。后续仍需直接经文/ko/es质量、strict正式CLI适配、owner对账、实际批次恢复、assembly参数比较、同步修复与完整四层新身份收据。
