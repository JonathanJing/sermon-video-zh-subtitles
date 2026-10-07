# L1/L2 实际运行与参数调整复盘

## 最重要的运行结论

1. 当天首个可核对生产 workflow 是 02:23:11 UTC 的 `sermon_pipeline`，实际 commit `f446d8d03b5672e93af48caedb936ef502c59766`，trackedWorkingTreeDirty=false。此 merge 在 02:18:34 UTC 已把 PR237 分支能力纳入冻结代码：L2 canonical 每语最多16 group workers、每 job_root 共享24 API slots。不能把主干22:22 PDT的后续 squash merge 时间当作现场首次启用时间，也不能把后面运行写成从3 workers临时提到16。
2. L1 英文审查确实有运行中并行试验：串行→22线程prewarm→24线程prefill。v3 prewarm缓存根传错，造成16组相同请求重复成功；v4修复缓存路径且避开并发canonical，汇总阶段零新请求。v6最终源稿审查又使用串行，说明并行能力没有固化为所有后续生产的默认路径。
3. L2所有有workload证据的实际模型run均16 workers；完整批次的API起止峰值重叠为16。修复group少时，峰值为1、2、3、4、5或8。没有证据显示24 slot被持续占满，也不能把16 workers×翻译/复核两角色解释为32并发：同group两角色依次调用。
4. 本次有价值的L2变化主要是把已存在的runner修订能力接入canonical controller、补齐模型实际消费的规则、做插件单独迁移，以及保留精确结果复用。不是反复调大并发。

## 时间线：代码已有、现场消费与结果

|时间 UTC|实际身份与改变|运行证据|结论|
|---|---|---|---|
|02:23–02:31|f446d8d clean；pipeline/PCM resume/英文judge-v1|executionIdentity；v1 28 API峰值1|生产起点已包含L2并发/缓存底座，L1 judge仍串行|
|02:48–03:12|efb774b clean；多从句anchor边界支持；judge-v2/v3|v2 28 API峰值1；v3 canonical 18 API峰值1|源锚修订与运行优化是不同轴|
|03:07|efb774b上的ignored helper，22线程并行prewarm；canonical仍在运行|失败尝试66条；成功尝试26条，峰值22；缓存reconciliation|错误cache根导致16重复成功，不能称成功提速|
|03:19–03:20|同efb774b，v4 helper改正确judge out，先prefill再canonical|28 API峰值24，53.196秒；canonical 0 API，0.451秒|证明正确缓存被消费。不同源/版本，不能由这些耗时给出无条件倍率|
|04:24–04:37|37322bb clean，policy-v4/source-bound支持；judge-v6|28 API峰值1，762.640秒|后续最终审查未复用并行调度方式；不代表未复用源文结果，源稿身份本身已变|
|05:13起|f61aa9c clean，L2 canonical|16 workers；完整ko 948 API，峰值16|初始生产L2已真实消费既有并发能力|
|05:42起|5edd643 clean，controller加入partialRepair lane|es-repair读取reuseFrom/brief；72角色结果复用、876新调用|runner原已有partial repair校验；当日补的是canonical可绑定入口|
|06:01–06:37|8f486e9 clean，proper-name边界匹配修复|zh-repair、v7-ko、ko定向修复实际加载|代码正确性变化；不能把耗时改变归于并发|
|06:57–07:20|ab420b7，dirty=true但所核对已加载模块匹配该commit|v8 model policy补引文/上下文，workers仍16|dirty不等于该次模型代码与commit不同；策略产物可独立变化|
|07:17–07:36|ignored plugin migration helper；后续6e1fdfe clean|三语各948结果验证复用，均0API；必要内容修复只6/2调用|实际启用精确payload迁移，不是重新翻译|
|08:30起|d190535；controller执行配置v2接入spokenRevision/cacheManifest|canonical-spoken native jobs，保留one-active/16group/24slot；大量carried_forward|原有runner revisionBrief能力通过新adapter纳入durable执行，不靠裸CLI绕过控制|
|12:46–12:57|formal timing只记录layer2_models；commit999fcb6 dirty|7次workflow；runner/semaphore加载SHA不等该commit，却等f446d8d/d190535的版本；workers16|混合代码来源需按loaded hash还原；没有足够launch证据证明canonical wrapper与共享slot包住实际caller|

`text-metrics.json` 保存每条workflow身份、选定模块loaded SHA与git blob SHA、每个根run及实际API重叠峰值、控制器job输入身份/命令hash/flag名。完整执行身份比对可结合本地审计输出 `execution-identities.json`；dirty标志和实际模块hash差异应分别报告。

## L1 并行预热的真实缺陷与修复

v3 helper传 `out=outdir.parent`，并从 `RUN/cache` 探测已有batch，而canonical使用 `RUN/english-source-judge-v3/cache`。它尝试预留两个batch避免竞争，却检查了错误缓存namespace；即使stage名相同，两个进程也没有共享实际命中。

本次对reconciliation列出的全部16组直接重读两套原始cache，逐一核实：request对象完全相同、规范化requestSha256一致、payload hash一致、两个responseId不同、response对象SHA正确、两份responseId都能在原46账本API terminal事件找到，原始usage与accounting一致。多出的prewarm成功响应为 **200,847 token**。这部分**已经在全生产24,947,374中，不得相加**。

v3同一账本内：canonical18成功 + parallel26成功 = 44成功，对应28个唯一batch，恰好多16；另66条prewarm失败用量缺失。66失败和26成功均已纳入既有索引；没有发现待补入的遗漏账本。reconciliation称66失败发生连接前；费用未据供应商账单核验。10份有效并行结果迁回canonical缓存，源收据保留。

v4 helper改 `out=out`，按同一manifest/hash构造payload；运行前确认canonical不并发，并核对源与锚点批准绑定。实测28批并行预填后canonical仅做验证汇总。现有证据证明该次结果复用正确，不证明v4相较所有源版本可获得固定加速倍率。L1最终v6又回到串行，显示优化只是现场helper，没有默认进入canonical judge。

## 并发控制的真实作用域

冻结代码 `layer2_api_concurrency.py` 用flock，24 slot位于 `job_root.parent / ('.'+job_root.name+'.layer2-api-slots')`。因此它在使用同一job_root的进程之间共享，不是任意不同job_root、不同机器的全局24上限。canonical还有每个production run一个active locale的门控；新revision切换前审计父job terminal，承担跨root不重叠的流程约束。

初始runner已有：batchSize=1、canonical workers1..16、source-order结果合并、每组Astra→Sol、线程context传播、精确payload/model验证、完整raw响应恢复，以及started marker阻止未知请求自动重试。standalone CLI仍限定workers1..3；不能把canonical的16-worker运行当作普通裸CLI默认能力。

本次实测最多16重叠API与配置一致。24是安全容量上限，不能写成实际24并发生产吞吐。峰值用api_attempt_started→api_attempt结束事件计算；包括客户端调用时间，不能等同服务端同时执行数或GPU利用率。小修复的峰值低是工作量较少，不是并发机制退化。

## 上下文、策略与缓存的调整

初始f446d8d的 `surrounding_context` 已提供前3/后2个source unit；整个L2期间run_target_language_models加载hash仍为 `286c7bd76c3aa37426e6b4772bebdbe0dfc44f9eac9b05a4ba2984d6e9379e86`。没有证据显示当天把上下文窗口从小调大。u018所需卡车/限速先行内容在u014，u026的指代先行内容也更远；既有短窗并不保证足够语义背景。实际修复通过源绑定brief或policy明确这些关系，不能描述为单纯“开了context”。

中文批准经文映射最初只在插件中，模型policy遗漏；韩文出现未口述编辑式经文编号，后补模型规则。这是model-facing规则完整性缺陷。模型/提示版本标签没变，实际payload变了。人审收据、模型输入、确定性插件是不同消费者，仅在某处存有规则不证明其他消费者使用。

插件-only变更曾改变policy总hash，但helper通过逐组精确payload与raw收据验证后复用。中文旧插件20拒→0、韩文4拒→2；真实语境错误保留。helper-v2还验证partial-repair bootstrap，回归中文/韩文各474组零API；正式三语迁移各948模型角色结果零API。此处实际优化是正确区分模型输入变化和仅验收器变化。

5edd643把partialRepair接到controller：读取旧request/brief，绑定job输入，调用现存runner定向重译。d190535再把spokenRevision的proposal/cacheManifest接入canonical配置v2。早期spoken execution-plan明确记录“旧controller仅partialRepair、无lane revisionBrief；裸runner会绕过durable admission和shared slots”，之后native job确实使用新adapter。必须区分“能力在runner已有”和“生产入口已可用”。

## 尚不能下结论的部分与改进定位

- 实际L2并发参数未在本日从3逐轮升到16；16能力在起点已存在并全程使用。若要再调并发，先记录slot等待/请求延迟与吞吐对照；本证据无法证明上调能缩短总交付。
- L1 parallel helper的cache-root/并发canonical错误是确认的运行缺陷；修复已在v4消费，但并行调度尚未贯穿最终v6。适合纳入统一judge入口，避免人工prewarm旁路。
- formal timing的loaded semaphore文件存在不证明request_slot被调用；缺launch/caller封装证据，不给它补写canonical执行证明。
- dirty=true不自动代表每次代码变化。formal timing七次的runner/semaphore加载内容彼此相同且与既有版本一致，变的是git归属背景；可靠冻结需同时保留commit、加载模块hash和helper hash。
- 未测固定源/固定policy的串行与并行对照，不给出速度提升百分比；未测provider排队、共享slot等待和CPU瓶颈，不把API峰值当最优吞吐。
- 统一持久化调度、自动fallback、全局跨root semaphore等若未见调用证据，仍是提案，不是本次已兑现能力。

复算入口与证据索引见本目录 [README](README.md)。原始正文、prompt及response未导出。
