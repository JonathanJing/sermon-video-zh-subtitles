# 七项日志契约实施对照（2026-09-30）

基于 #161 `7250a72` 的实现继续开发，不以旧 dev 覆盖 runtime。规范来自独立文档分支 `45cdc170e6120a525c4b7dcb68ff985208afade3` 的 [冻结合同](workflow-accounting-log-contract.zh.md)。七项均已有部分能力，不能整体标记完成。

| 类别 | 复用已有实现 | 本批新增 | 仍待实现/实跑 |
|---|---|---|---|
| LOGC-01 schema | v1–v3 reader、白名单、typed cache/local observations | 引入冻结合同作为测试边界 | opt-in closed JSON Schema2020-12、null reasons、未知profile隔离 |
| LOGC-02 顺序/重放 | event UUID、append lock、完整receipt冲突处理 | OTLP先共享receipt reconciliation，再选event代表；冲突不报可信token | producer sequence/outbox、重放冲突/缺口、并发恢复 |
| LOGC-03 时间 | 原有monotonic elapsed | process clockDomain、纳秒字符串；UTC跳变保留本地elapsed、wall未知；跨domain不假定同步；OTLP明确标记monotonic anchored估计端点 | profile约束、等待/队列时钟证据、完整跨进程路径 |
| LOGC-04 传播 | ContextVars、subprocess_environment、run/workflow/span | 保留既有机制 | workUnit/attempt/production关联、durable sidecar、async causal links/OTLP collision |
| LOGC-05 模型用量 | 原provider/SDK分栏、全局收据冲突、历史cache分栏 | OTLP与summary/Weekly共享去重规则，缺失token不填0，冲突总量缺省 | logical/modelCall/providerScope/billing identity、SDK覆盖、逐组内容verdict/重做链 |
| LOGC-06 状态 | stage completed/failed、jobs/reconciliation | 不把stage完成误当内容pass | 版本化logical step/attempt状态机、cancelled/outcome_unknown、合法转换 |
| LOGC-07可靠性 | fsync、append-only、私有权限、日志失败不重付、safe export | safe export保留新增时钟证据，回归重放一致 | 64KiB写前上限、symlink/路径防护、完整原子多报告快照一致性 |

本批回归覆盖同/不同eventId的等价/冲突provider收据、反序导入、UTC前跳/回拨、不同进程clock、伪造elapsed以及safe export再投影。不会把本批局部修复当作七项全部验收。

## 新180秒流程准备与预算门槛

已从本地2026-09-27素材的60–240秒重新剪辑；原媒体SHA `374662dc7c00993820360b2095e277ecd7ebf17bc4d873ccf7e2b76a6c7c7930`，新片段SHA `79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b`。音频180.000秒，容器180.013167秒（编码时间基），完整解码通过。此时只完成剪辑，freshInferenceRun=false；没有重放旧响应冒充新生成。

计划：OpenAI `gpt-transcribe`新转写、正式MFA/英文源检查、`gpt-6-astra`逐组初译和`gpt-6-sol`独立审核，三个locale；按真实结果记录每组pass/needs_rework及安全reason/私有证据hash。正式TTS走已有授权本地模型，仍须新译文人审；音轨须新听审。预算批准不代替这些门槛。MFA本地可执行文件尚未定位；既有Spark回退需按现有连接流程实际预检，不能先付费后发现正式对齐不可用。

拟请求付费上限 **USD25**，批准前不发请求：最多54个初始translator/reviewer对（每语≤18组），另≤6个明确失败组重做对；每次input≤8192、output≤4096（含reasoning），两次英文source模型检查各≤16384input/8192output，ASR最多两次180秒。按standard Astra10/50、Sol2/10美元每百万token及125%输入cache-write保守档，文字上界约23.35美元，ASR约0.027美元。实际组数/payload不能满足上限就暂停；未知已发送结果不盲重发。调用前预算预留与硬限制尚待实现，不声称当前producer已有此限额。

价格来源：[官方价格](https://developers.openai.com/api/docs/pricing?tab=suite)、[Sol模型页](https://developers.openai.com/api/docs/models/gpt-6-sol)，2026-09-30核验。这是拟议的bounded run预算，不是账单或已批准消费。数据为这份用户已有证道的180秒音频、对应英文和三语机器候选；无发布动作、无新凭证、无扩大访问权限。
