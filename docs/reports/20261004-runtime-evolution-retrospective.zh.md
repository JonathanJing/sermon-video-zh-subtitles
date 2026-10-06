# 2026-10-04 运行演进复盘：从冻结代码到临场调整

## 结论

本次最值得优化的运行问题，是**预检没有覆盖全部下游消费者、可复用结果仍有重复工作、恢复入口依赖本周临时脚本**。8×8 TTS和16组L2 worker在开跑冻结时已经存在；不能把全部耗时归因为并发不足，也不能再把这两项称为运行中才增加的提速。

新增的两个直接发现：

1. **L1英文复核确有重复成功请求**：v3并行预热传错缓存根目录，16组完全相同请求各成功两次，多出已知200,847 token。这部分已经包含在原24,947,374生产账本总量中，不再相加。此前“未发现相同payload重复成功”的结论仅适用于L2专项范围。
2. **L3缓存重组存在明确代码热点**：中文／韩语约21分钟重组，逐句receipt阶段分别占1156.86／1160.84秒（91.42%／92.47%）。renderer未使用已有的预验证job接口，逐句重复加载并验证整份上游输入。值得优先修，但尚无优化后的对照结果，不能宣称可节省同等比例。

15小时制作窗口要求生成、人审、恢复、发布与读回都在周日10:00前完成。运行策略应先减少可避免的重做和临场补接口，再做有测量依据的容量调整。此次只分析并记录改进，不更改生产参数、重新配音或部署。

## 1. 起始codebase的准确边界

本报告用RUN指 `artifacts/post-live-runs/2026-10-04/resi-69ba7a66`。时间主列采用洛杉矶当地PDT；提交作者时间、冻结收据时间和实际执行时间明确区分。

| 证据 | 时间／身份 | 能证明什么 |
|---|---|---|
| 第一份明确生产冻结 | 周六19:20:02，`f446d8d`，tree `090d1b5d…` | 合并dev `021725b`和PR237分支`448df15`；不是后来文档PR的起点 |
| 第二份冻结 | 周六19:46:03，`efb774b` | 在原冻结上加入`092e61b`、`efb774b`的源句／人工边界修复 |
| 正式TTS staging | 周日03:28:03收据，`5b2c1ac` | 正式GPU运行用另一个冻结代码包；首轮03:29启动 |
| 发布阶段本地补丁 | `4f61a26`→`5e8cfb5`→`834dfe4` | 分别扩展中文独立交付、原录制窗口、韩西独立交付；不代表早期GPU进程加载了这些修改 |

46份既有账本里有74条带executionIdentity的workflow观察（不是74个独立run）：40条working tree clean、30条dirty、4条缺状态。对记录的loadedProjectCodeSha256与各自Git对象逐文件比较，仅7条观察有已加载文件不等于其commit；其它dirty不自动表示运行模块变过。7条来自正式时长修订，涉及6个模块；仅报commit不足以复现实际代码。

现有 `sermon_accounting.execution_identity()` 记录的是workflow开始时已导入模块对应文件的hash，不能覆盖之后导入的代码、外部FFmpeg、容器或RUN桥接脚本。下一轮应绑定完整执行代码包、runtime镜像／工具、实际argv、policy与输入闭包，仍保留现有模块证据。

## 2. 过程中实际改变了哪些东西

| 阶段 | 当时问题／调整 | 运行判断 |
|---|---|---|
| L1媒体与MFA | 原AAC容器末端1942.2秒与批准窗口1942.123秒不一致；用sample-exact PCM恢复MFA，保留原ASR文字 | 有效的输入规范化；应产品化为固定decoder下的标准入口，不放宽窗口门槛 |
| L1锚点与源包 | `092e61b/efb774b`保留人审整句；后续允许已逐项审过的长句警告 | 修复跨层门禁不一致；不是将长句警告全部关掉 |
| L1机器复核 | v1/v2/v3 canonical为串行；v3并行预热cache root错误，v4改正；v6又出现串行路径 | 并行方式仍靠临时runner，没有成为统一、可恢复的正式入口 |
| L2策略／缓存 | source-bound policy、术语／引用上下文、partial repair和plugin-only迁移逐步补齐 | 模型输入和插件必须同版；已有结果迁移与定向修复应成为标准状态转移 |
| L3准入 | `9f6e932`声音授权、`d190535`口播修订／clip timeline v3、`5b2c1ac`复用canonical source readiness | 上游已批准的例外不被所有消费者识别，直到配音前仍在补接口 |
| L3首轮 | 固定8×8、24GiB reserve、8秒max lag；三语串行，单句生成全但排程失败 | 生成完成不是排程完成；需先隔离单句异常，再判断连续段文字预算 |
| L3恢复 | CPU静音处理、`--reuse-from`、中文／韩语474句全缓存重组、西语同输出续跑 | 保留正确cache与声音身份；特定目录／前缀／locale条件应改为通用恢复计划 |
| L3质量政策 | max-end-lag从8改62秒，最终韩西leading-only处理 | 62秒是明确批准的质量例外，不是性能优化或原8秒目标达成 |
| L4交付 | 中文先发、同page追加韩西、sourceWindow offset、metadata补修、Dev补齐 | 原有发布组件存在，但不完整支持当天需要的运行路径；临时桥接承担了最后一段 |

提交时间只是代码变化证据；每项实际消费以launch、workflow、runtime、产物及HTTP收据为准。没有据作者时间计算生产耗时。

## 3. 并发参数：哪些已生效，哪些不能继续盲调

### L1复核：应该改入口，不再手写预热

v3 helper给 `cached_call` 传了RUN而不是judge输出目录，形成 `RUN/cache` 与 `english-source-judge-v3/cache` 两个缓存空间。16组原始request逐一相同、request hash相同，每组两个不同responseId；32个responseId都可在46账本中找到对应成功usage。44次成功响应只覆盖28个唯一批次，其中重复的prewarm部分200,847 token已计入旧总量。66次失败的用量仍未知。

v4先以24并发prefill正确缓存，再由canonical流程汇总：观察到28调用／53.196秒，随后0调用／0.451秒。v1/v2/v3 canonical峰值1、v3 prewarm峰值22、v4峰值24、v6又回峰值1。这些是不同版本实际观察，不是同工作负载A/B提速比。

**调整建议**：正式judge入口支持有界并行；使用同一个规范化cache root和request key；对相同请求设置写入锁／single-flight，状态区分in-flight、完整成功、失败和未知。恢复先对账，不另开预热脚本。验收用同一批请求串／并行产生同样准入结果，并验证两个并发调用不会各付费生成一份。

### L2：16 workers不是batch16，24 slots不是全账户上限

初始冻结已经规定每locale最多16个group worker、共享API cap24；有workload记录的L2 run实际workers为16，完整新跑的单run峰值观察为16。定向小修的峰值更低，属于工作量限制，不能叫并发故障。controller初始每run只准入一个locale；提升group worker并不自动产生三语言并行。

本次部分实际路径只保存了 `layer2_models` 执行，没有完整canonical wrapper的dispatch记录。仅导入 `layer2_api_concurrency.py` 不能证明调用经过 `request_slot`；共享jobRoot信号量也不是跨任意run、独立CLI和主机的账户级限制。

**调整建议**：先统一controller/runner入口，记录每次请求的semaphore根、槽占用和实际峰值，再决定语言间并行。不要先从16改24或同时手开三套runner。语义、插件和人工批准仍分别处理；定向修复优先复用其余组，不能以并发掩盖重复全量翻译。

### L3：保持生成身份，再测容量

首轮实参：8 replicas、batch8、CUDA0/BF16/SDPA、seed42、reserve24GiB、reaction/gap各0.05秒、maxlag8秒。后续恢复仍使用原冻结renderer和pool；没有证据表明当日改了pool算法。

固定batch窗口包含缓存成员时，恢复仍可能按原窗口送入模型，只取缺失输出，以保持batch/seed声音身份。任意删成员、换batch或降replicas不是免费的等价恢复。8×8也不代表64句始终同时运行。只有在身份、质量与输出验收清楚的独立对照中，才能比较其它容量。

西语失败直接证据是主机MemAvailable reserve guard。保留24GiB保护；先记录失败瞬间内存、worker RSS、未消费波形字节和队列深度。现有代码的按序消费、父进程波形缓存和Pipe传输值得测量，但不能直接认定为该次失败根因。

## 4. 最具体的性能热点：缓存重组的收据路径

| 同一locale缓存重组 | 完整run | receipt子阶段合计 | 音频validation | reuse复制 |
|---|---:|---:|---:|---:|
| 中文474句 | 1265.50秒 | 1156.86秒 | 21.30秒 | 4.71秒 |
| 韩语474句 | 1255.33秒 | 1160.84秒 | 21.06秒 | 4.75秒 |

两个run均0新synthesis。receipt占比91.42%／92.47%，不能再描述成21分钟又做了一遍GPU配音。unit是父span，不能与receipt等子span重复相加。

代码证据：运行版本 [renderer的receipt循环](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/5b2c1ac14575a0827b0e5ec0189cbc1f5f24a145/scripts/render_formal_target_language_speech.py#L899) 每句调用integrity而没有传 `validated_job`；[integrity接口](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/5b2c1ac14575a0827b0e5ec0189cbc1f5f24a145/scripts/validate_target_language_audio_unit.py#L148) 已支持它，否则 `_load_job` 重新校验完整job、inputs与candidate。已有另一处cache admission路径使用预验证接口，说明不是必须完全重写验证器。

**应修调用方式，而不是删除校验**：attempt开始完成一次严格admission并冻结依赖；逐句保留audio完整解码、文字／locale／job绑定和receipt验证；依赖改变时必须拒绝旧上下文。只读容器mount不能单独保证宿主文件不被外部修改。先实现可验证快照或内容寻址输入，再安全复用上下文。

验收以相同474句cache做前后对照：输出与收据身份一致，坏音频、错receipt、运行中输入变更仍被拒绝，leaf阶段耗时明显变化。当前只定位热点，未证明整个receipt耗时都来自 `_load_job`，也未得到可承诺的节省分钟数。

## 5. 把临时恢复收敛为正式运行模式

| 今天的临时方式 | 应固化的接口／不变量 |
|---|---|
| KO CPU-only launcher要求某个ZH容器正在运行、两份输出不同 | 通用assembly-only：预检必须全部cache hit；一项需合成就拒绝CPU路径；独立lease/output，按CPU和I/O容量调度 |
| ES专用脚本验证正好320句前缀并固定目录名 | 通用resume plan：逐项核对intent、commit、WAV、生成身份；未知远端状态先reconcile；保存旧attempt证据 |
| 每次从完整renderer重新走到排程 | 明确分开合成、完整校验、排程、拼接、ASR和打包，按各自输入hash复用已完成阶段 |
| 整轨8秒排程失败后修多组文字 | 先报告异常单句、局部lag跳升和后续传播；保存旧WAV；再判断TTS定向修复还是L2内容修订 |
| AAC在不同主机到较晚阶段才出现采样数不一致 | 在正式预检固定兼容FFmpeg/ffprobe，检查真实PCM采样与批准窗口；encoder能力一并检查 |

AAC例子不是放宽时长容差的理由：同一媒体在6.1.1与9.0.1解码相差759 samples，源于末包discard padding处理；已有诊断保留窗口、map和±1 sample门槛。临场构建兼容工具可救本次运行，但应移到周六19:00前的运行时准备。

## 6. 发布准备应该在配音前验证

初始代码并非没有发布系统，但其路径默认三语齐全、同步检查通过、新page写入。当天需要中文先交付、韩西之后追加、批准的同步例外和完整录制offset，这些在运行中才打通。

- `4f61a26`（作者时间周日09:02）补中文单语scope、绑定例外和source-date占位metadata。
- `5e8cfb5`（09:27）修原录制sourceWindow／声纹offset，不能把完整录制窗口当从0开始的clip。
- `834dfe4`（10:20，已过截止）推广任意受支持locale子集及receipt消费者版本，页面时长由写死31:31改为内容字段。
- 仍靠7份ignored RUN桥接执行sidecar、Dev overlay、locale准备、asset-first、追加locale、CAS deploy和最终验证。这些桥接已有hash、旧资产保留等保护，但还不能仅换下周manifest就安全复用。

正式站发布成功不等于Beta可见：Release读prod，Debug/Beta读Dev从初始代码就存在。下一轮release intent须明确App channel、environment、project、hosting site、origin，并分别读回。元数据修正只更新相关内容和发布身份，不重做源稿／音频。已有page追加locale应采用带baseline SHA的增量命令，不能用强制覆盖绕过保护。

需要在实际源包和scope就绪后做全消费者dry-run；同时在周六19:00前用代表性fixture演练中文先发布、韩西追加、例外receipt、非零sourceWindow和双环境路由。fixture证明接口覆盖，不替代本周人审及真实发布验证。

## 7. 15小时窗口下的实施顺序

| 优先级 | 优化项 | 对本次运行的价值 | 完成验收 |
|---|---|---|---|
| P0 | 发布／音频消费者全链预检与冻结runtime | 把临场补接口和工具安装移出制作窗口 | 代表性fixture通过；实际输入admission通过；所有代码／工具／schema身份留存 |
| P0 | 修L1缓存根与统一并行入口 | 避免已经证实的16组重复成功调用 | 同payload并发只能得到一份新成功；恢复不产生第二份付费结果 |
| P0 | 优化L3 receipt重复上下文验证 | 针对已测到的主要CPU热点 | 同474句cache前后对照；保持音频与身份错误拒绝；记录实测节省 |
| P0 | 单句异常先定位，阶段级续跑 | 防止一处异常扩散成大范围不必要返工 | 异常WAV保留；changed set与重跑范围可解释；排程独立重算 |
| P1 | 正式assembly-only与事务resume | 去掉专用容器／320前缀等操作条件 | 任意有效前缀和稀疏完整项可对账；无GPU模式不能误派合成 |
| P1 | 统一L2并发所有权和实际槽计量 | 防止旁路限流，避免无证据加worker | 正式入口记录槽根和峰值；多locale配置不会超出授权范围 |
| P1 | 参数、资源及版本变更登记 | 避免一个commit遮盖多段不同代码 | 每attempt绑定代码闭包、实际argv、缓存身份、状态和变更理由 |
| P1 | 通用单语／增量发布与独立收据 | 降低最后一小时手工绑定和复制旧receipt风险 | 双环境CAS、已有locale保留、收据新建且hash闭合 |
| P2 | 固定质量基线后的8×8容量／长尾实验 | 再决定replicas、batch与worker预算 | 完整资源与延迟分布；同验收目标，不混入缓存和质量豁免 |

周六19:00前可准备的是代码、runtime、fixture和发布路由，不能预先替本周内容批准。15小时内应只做内容特定生成、审核与受控恢复。当前尚无证据保证完成以上优化后必定达标；下一次用真实完整scope记录截止前完成率、各阶段关键路径与余量，不用孤立模型速度推导端到端保证。

## 8. 证据与限制

本次读取历史Git对象、冻结/staging/launch receipts、原始cache、46账本和RUN脚本；没有运行模型、远端任务、部署或媒体听审。提交作者时间不冒充执行时间，参数默认值不冒充实际消费。

[证据目录](20261004-runtime-evolution/README.md) 提供文本、音频与交付专项、离线复算入口及相对路径／SHA索引。与 [完整制作复盘](20261004-full-production-retrospective.zh.md) 共用原始账本；新发现的L1重复请求已经包含在旧费用总量里。原始对话、媒体、审批正文、模型prompt及response未提交。

验证：三份离线复算脚本均执行完成；L1全部16组原始cache／账本绑定、输入SHA、workflow代码比对及receipt耗时闭合通过。Python语法、相关Markdown链接和diff空白检查通过。没有做优化实现后的性能测试。
