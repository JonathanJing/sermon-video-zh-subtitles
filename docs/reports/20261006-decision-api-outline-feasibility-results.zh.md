# 大纲来源支持：第四轮机器可行性实测

日期：2026-10-06。状态：machine_feasibility_completed_human_quality_unproven。24次Decisions请求完成，未执行人工A/B或生产审核。

## 实际范围

用户明确选择“暂时只有我：先做机器可行性测试”。因此执行独立的[机器子阶段](../../config/decision-api-outline-machine-feasibility-v1.json)，不把它算成[原48项人审方案](../decision-api-outline-support-validation.zh.md)已执行。

库存核实只有四个合适的新来源各至少六个完整小节，未找到六来源各八节的材料。采用四来源×六个不同底稿，共24项：8条未改写真实大纲、4条忠实意译、12条真实来源上的语义变体。来源为公开YouTube的ZDQwL3K-A44、-BeFX5G2oAw、8JYwTq1xcBE、l8ucqF9uA9A，均未用于上一轮E06六来源；发布复制件和模拟fixture不计新来源。

每个底稿只保留一个形式。引用ID全部有效、英文非空，提供原引用切片的完整segmentEvidence，中文仅辅助阅读。不把空字段、错误状态或非法引用当额外语义判断能力。本轮不测上下文缺失／补证据流程，也没有用完整讲道证明“整篇从未支持此主张”。

十二条变体覆盖限定放大、引语错归、必要对照移除、应用越界、关系反转及整体重点偏移，每类两项。其中十条直接改变主张，两条保留局部可支持语句但删除原论证关键对照。它们仍是作者构造挑战，不代表生产错误发生率，四源也不是随机来源样本。

## 题目与证据

逐原文标题／完整point做支持分类，整小节另做支持分类及framing判断；最后从给定sourceUnitIds选候选定位。候选ID合法仅证明导航可用，尚未证明定位语义正确或节省人审时间。

作者预期、变体family和来源准备状态不进入Decisions输入／盲复核包，作者预期单独冻结hash。来源身份、源文件、底稿、样本、payload、代码依赖、累计预算及receipt绑定；两类“机器读过即批准”均未发生。程序承担身份、引用和格式检查；没有付费Sol分类臂，也不把程序预检称为内容质量A。

使用已有dev环境及隔离[执行器](../../scripts/experiments/decision_outline_feasibility.py)，沿用[累计ledger](../../scripts/experiments/decision_api_weekly_ab.py)。收费按[官方Decisions说明](https://developers.openai.com/api/docs/guides/decisions)的输入计价，runner保留地区费用余量；费用为usage估算，非账单或provider硬限额。

## 在线结果

| 材料 | Decisions结果 | 可解释范围 |
|---|---|---|
| 8条真实原稿 | 8/8 supported、faithful | 未建立人工真值，不能称准确率 |
| 4条忠实改写 | 3条supported；1条unsupported，四条framing均faithful | 有一项可能误报，需核对标题支持 |
| 10条直接语义变体 | 10条均被整体分类为contradiction，framing均misleading | 都有问题提示；不代表细分类正确或真实错误召回 |
| 2条局部有据的重点偏移变体 | 均supported；framing一条misleading、一条faithful | 支持分类本身抓不到整体偏移，额外framing也存在边界分歧 |

十二条变体的四分类与作者预期一致8/12，framing一致11/12；忠实改写作者预期符合3/4。四个四分类分歧均为作者预期unsupported、Decisions选择contradiction，不能据此直接把四条当漏检。构造题的符合率不充当人工准确率。

24/24响应均通过格式和身份校验，无timeout、refusal、invalid或未知结果。每次一小节、中位数0.286秒、p95为1.956秒；串行观测跨度11.712秒。仅一次观测，p95受三次长尾影响；不与前轮批量Sol延迟换算生产提速。

本轮估算增量$0.015657，累计$3.011306／$20；四轮累计508次网络请求。完整预检上界$0.063247，阶段上限$2／最多24次请求；未结算0。实际恢复24项全部restored，网络请求仍24、增量消费0。

## 独立Agent盲复核：诊断而非人工gold

盲复核只读同一来源／大纲和rubric，不读取模型结果或作者标签。与Decisions四分类一致20/24、framing一致23/24。它支持检查以下边界，但不是human gold：

- outline-6ad3880a8b8d01ef95ce：忠实改写的原始标题被Decisions判unsupported，正文points均supported；盲复核找到第一章宣读及耶稣得胜的来源，判supported。提示标题可能误报，不能把这一项记作已证实人工误报。
- outline-b50f013e4276a2147709：只保留末世不同观点与学习资源，省去“不要因细节错过耶稣”的中心对照；Decisions判faithful，盲复核倾向misleading。
- outline-99524ad32c4bf823eb60：自我形象／梦想的局部语句有据，却省去降服神及反映耶稣的关键对照；Decisions与盲复核均判supported＋misleading。
- 后两项framing的盲复核把握仅中等。合理分节摘要也允许省略；相邻大纲是否承接中心对照，可能改变全篇判断。本轮未把该争议裁成确定严重错误。
- 另三项分歧为unsupported与contradiction边界：新增“本周内解决全部不公”、禁止专业帮助／分享、要求政治行动。盲复核认为未被来源明确否定的新增断言应保留unsupported；不因来源没说就断言矛盾。
- outline-c5628865ab445bbadbba还出现整体contradiction、全部逐claim却为supported或unsupported的内部不一致。保留原响应作为诊断，不后处理成“正确”。

作者首项“立即消除痛楚”的预期为unsupported，盲复核与Decisions均判contradiction，并发现来源明确说痛楚可能再次来临。说明作者细分类也可能有问题；预期不改写，观察与诊断分别保留。

## 判断与尚未验证的部分

本轮显示Decisions能以低延迟给直接语义错误提示，并能在一项案例区分“单句有依据”和“整段重点偏移”。同时出现标题支持分歧、整体重点漏提示争议、unsupported／contradiction混用及整体／逐claim不一致。

结论为继续研究人工辅助筛查；不据此自动放行大纲、替代人审或宣布优于现有完整流程。没有独立人工gold、最终修订、人工active分钟、返工、定位准确率或新来源误报率。本轮四新来源现在属于已用开发材料，后续正式留出必须排除它们及之前六源。

[离线人审协议工具](../../scripts/experiments/decision_outline_review_protocol.py)支持显式人员配置、同来源角色隔离、双人gold与独立裁定、精确来源span和完整claim覆盖、计时与未完成项保留；不验证人员身份，也不证明最终交付质量。实际24项空gold预检返回incomplete、completeCases=0；没有虚构人员、gold或计时结果。

## 验证与保存

51项定向离线测试通过，包括新来源排除、身份／底稿变化拒绝、原英文缺失拒绝、作者标签隔离、cache不重发、gold角色／来源span／完整claim覆盖及计时边界，原预算／unknown保护测试继续通过。实际24项缓存恢复无网络调用。

[安全聚合](../evidence/decision-api-weekly-ab/20261006-outline-feasibility-summary.json)保存标签、时间、预算和身份hash。原始正文、作者patch／预期、原响应、盲审包和ledger仅保留ignored artifacts/decision-api-weekly-ab/20261006-outline-04。没有remote CI、生产批准、发布或设备验收结论。
