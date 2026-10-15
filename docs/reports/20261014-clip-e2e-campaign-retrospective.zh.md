# 2026-10-14 真实片段四层 E2E：失败复盘与防重跑方案

本次测试到此结束。以下按**运行身份**列出失败点；同一身份的失败证据保留原样，后续成功不改写它。证据来自各轮脱敏报告及本机终态收据。运行身份顺序不完全等于墙钟顺序，尤其 AC 与 AD 分别续测中文和韩语。

## 结论与证据边界

- 2026-10-11 的 16 单元先导片段最终有三语隔离 Dev 诊断页，见 [G 轮报告](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/435)。它证明该短片段在当时冻结的实现下走通四层，不证明下一片段自动可用。
- 2026-10-04 的约 174 秒、50 单元新片段，从 H 到 AK 建立了 **30 个运行身份**：26 个失败或中止，Y、AH、AK 分别完成西语、简体中文、西语的隔离 Dev 诊断页，AI 则按计划只完成当前实现的西语文字层。**三语合并有声页没有发布**。中文与西语在当前 QC 实现下各有独立 Dev 页；韩语音轨因时长无法放进片段容器。
- 最后一轮 AK 的 OpenAI 预算账本累计估算结算为 **US$21.405361 / US$30**，包含此前先导测试约 US$10.422771；新片段阶段增加约 US$10.982590。这是按已返回请求计算的估值，不是供应商发票。Claude CLI 订阅的列价等值另记，不能并入 OpenAI API 花费；P 轮被中断的 Opus 调用没有确认供应商侧结果，不能宣称零成本。
- Dev HTTP 文件哈希回读和浏览器渲染已验证的页面，不等于真机音频播放、现场验收、人工内容批准或生产发布。机器豁免均保持 `humanApproval=false`。

### 先导小片段：每次失败和恢复

| 运行/证据 | 失败出现处 | 实际问题与防复发点 |
|---|---|---|
| 10 月 11 日 u101–u116 首轮，[报告 #409](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/409) | 中文、韩语文字 QC 后的 Layer 2 修订 | 预算授权哈希混入模型传输缓存身份；修订换授权即无法核实同一模型请求。传输身份与预算授权分离，修订路径须在首轮付费 QC 前做合同演练。 |
| 同片段第二轮，[报告 #414](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/414) | Spark 镜像、音频压缩、韩中音频校准 | 远端父目录不存在；西语末尾容器不足；韩中 `dropped_key_word` 校准未达门槛。目录和排期容量在 TTS 前查；音频校准属于真实内容关口，失败收据保留。 |
| u216–u231 的 C 轮，[报告 #417](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/417) | 中文 Gate 4 修订 | 修订沿用初译预算账本根却换了 authority，正确触发 `budget_authority_changed`。预算根按执行授权隔离，未来修订配置与已有账本一起预检。 |
| u216–u231 的 D 轮及修复，[初次 #422](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/422)、[最终 #427](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/427) | 韩语音频 QC、发布后浏览器冒烟 | 章号读法 `8장` 被 TTS 读错；新种子 43 仍失败，绑定发音说明的种子 44 才通过。已发布的页面在 4 秒检查时仍显示旧内容，15 秒稳定等待后完整三语检查通过。发音问题须真实音频验证；发布成功后只续跑浏览器检查，不能重发部署。 |
| Opus E，[报告 #431](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/431) | 韩语音频 QC、中文校准 | 韩语仍需定向修复；中文注错器把普通词“一起”的“一”当数量词删除，生成无效试验，使校准 8/9 低于 90%。先验证注错样本的语义适用性，再做昂贵音频校准。 |
| Opus F，[报告 #433](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/433) | 中文文字 QC 后的 CLI 修订 | 预算授权再次进入 CLI 缓存指纹，修订未派发即失败。修复缓存身份并用两份不同授权的同一请求回归；冻结失败轮不原地改写。 |
| Opus G，[报告 #435](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/435) | 韩语音频修复、发布后的报告阶段 | 韩语按种子 44 与绑定发音说明通过；Dev 发布及浏览器通过后，报告阶段因重复参数及同名报告恢复问题中断，修复后只续报告，没有再次发布。报告和发布都需幂等恢复测试。 |

### 新片段 H–Q：来源、预算与缓存

| 轮次/报告 | 停在何处 | 失败点及可提前发现的信号 |
|---|---|---|
| [H #438](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/438) | Layer 1/2 交界 | Opus 三轮结构化返回超过旧两轮解析上限，已从同请求终态恢复；选中的片段没有多词专名，术语收据要求非空而政策冻结失败。返回 schema 与片段术语适用性都应在选片/冻结前演练。 |
| [I #439](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/439) | Layer 1 Opus 审核 | 人工旧锚点在 u163/u164 切开从句，Opus 正确拒绝高风险边界。保留整句和源审核，不以下游翻译补救；选片先排除已知有争议边界。 |
| [J #440](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/440) | Layer 2 预算规划 | 50 组的 100 次初译/复核最坏预留超出旧每语 US$8 Claude 列价等值上限，未派发。组数、输入/输出上界与批准额度须在运行规格冻结前一起计算。 |
| [K #441](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/441) | Layer 2 开工复核 | 用户已批准的每语 US$20 覆盖值通过规划，但开工检查又读取周更配置的旧 US$8。规划、开工与 worker 必须消费同一冻结授权。 |
| [L #442](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/442) | Layer 2 派发前 | 韩中插件仍绑定完整周次来源，西语插件与冻结政策哈希不符。将来源、锚点、语言插件和政策组成完整身份图，三语规则预检必须全绿后才付费。 |
| [M #443](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/443) | Layer 2 首次实际派发 | 西中请求超过输入长度；韩语 100 次返回后一个组不合语言规则，CLI 局部修复路径被拒。按实际完整 prompt 检查输入上界，修订路径也纳入首轮预检；已返回调用按指纹复用。 |
| [N #444](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/444) | Layer 2 缓存导入/预算预留 | 韩语导入缺原运行身份；西中部分调用已返回后，共用账本触及文件大小上限。8 个 `started` 标记经账本核对无预留、发生在 CLI 派发前，不能一概视为未知付费结果。复用应带身份文件，账本按语言分片，状态按“标记→预留→调用”顺序对账。 |
| [O #445](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/445) | 三语首次付费文字 QC 之后 | 三语候选完成，但 QC 修订写到独立 lane，CLI 同作业路径保护拒绝；阶段字段还留 `running`。先验证完整修订目录形状，再付首次 QC；异常须写终态。 |
| [P #446](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/446) | 新轮输入准备 | 未先复制已完成的 J 轮 Layer 1 输入，驱动启动新的 Opus 审核，操作者中断。供应商结果未确认，不能声称无成本或盲目再派发。运行开始前强制展示“复用清单／新增调用清单”。 |
| [Q #447](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/447) | 冻结策略/韩语局部修复 | 新术语收据中的本轮文字时间改变政策哈希，旧缓存不能复用；重建旧冻结政策后，韩语两次新 CLI 修订仍不合插件。策略需内容寻址；模型修订可能不确定，已通过的精确响应应优先按身份复用，不把重试当修复。 |

### 新片段 R–Z：质检、语音与发布

| 轮次/报告 | 停在何处 | 失败点及可提前发现的信号 |
|---|---|---|
| [R #448](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/448) | 三语文字 QC | 韩中修订触及冻结支出上限；西语 `swapped_quantity` 唯一注错位置会先被章节表面规则挡下，0 个有效校准试验。拟复用 O 的 QC 收据却写入非权威 `summary.json`，驱动实际重复付费 QC。预算与注错适用性预检、正式阶段状态导入均缺。 |
| [S #449](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/449) | 三语首次付费文字 QC 之后 | 单语 revision 配置错误携带韩中两语修订额度映射，planner 正确拒绝未注册语言。先从最终单语配置构造并验证 child plan，再开始 QC。 |
| [T #450](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/450) | 韩中修订/西语语音授权 | 韩语内容修订两轮仍不收敛；中文 30% 最坏预留不够下一组；西语拿正式整窗声明当 clip 语音授权而被 schema 拒绝。内容问题须逐组裁定，预算须先算下一完整轮，clip 权利凭据须先做来源绑定转换。 |
| [U #451](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/451) | 西语 Spark 渲染/压缩 | Eric 的适配器和 checkpoint 已核对，但全局音频操作策略仍带另一声音的规范化哈希。操作策略、adapter、job、checkpoint 与 speaker 应在 Spark 派发前同图验证。 |
| [V #452](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/452) | 西语音频校准 | 音频包完成，549 次 QC 请求已返回；US$5.525 阶段最坏预留上限不足，校准未完。保留返回调用，新预算只补缺口；“预留耗尽”不等于实际花掉上限。 |
| [W #453](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/453) | Spark 音频 QC 同步 | 镜像已有，新的 `aqc/es` 子目录未建，上传 checkpoint 映射前失败；没有新 QC API 派发。远端目录创建和可写性应在独占会话及镜像前检查。 |
| [X #454](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/454) | 西语 Layer 4 部署前 | 西语音频豁免签发，发布脚本却仍硬要求三语，隔离的单语诊断页被拒。发布计划的 locale join 规则要在准备阶段和最终 publisher 用同一合同验证。 |
| [Y #455](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/455) | 成功检查点 | 西语单语机器质检 Dev 页发布，HTTP 与浏览器通过；未验证真机播放或三语合并。此轮保留为成功证据，不当作韩中放行。 |
| [Z #456](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/456) | 韩中文本校准 | 用户逐组接受 3+5 组原译文，但两语校准各在 511 个已返回调用后触及阶段预留上限；无未知请求。逐组人审不能代替完整机器校准，续跑只补缺失调用。 |

### 新片段 AA–AK：真实音频及当前实现

| 轮次/报告 | 停在何处 | 失败点及可提前发现的信号 |
|---|---|---|
| [AA #457](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/457) | 韩语语音任务预检 | 韩中当前文本豁免均签发，但冻结规格缺韩语已审声纹能力复用凭据；TTS 未派发。声纹能力链应纳入跨层输入清单。 |
| [AB #458](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/458) | 韩语压缩、中文音频校准 | 韩语 50 单元去静音后 245.44 秒，容器 194.66 秒，1 倍速调度拒绝；中文包完成但 514 个已返回 QC 请求后预留耗尽。时长是内容/片段选择问题，不能靠加 API 预算或同类种子重试；中文只补缺失校准。 |
| [AC #460](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/460) | 中文音频豁免 | 签发器只认 v1 文字豁免，拒绝带逐组接受证据的合法 v2；离线进一步发现 `dropped_key_word` 仅 6/7，一级 ASR 已听到否定词缺失，二级 ASR 的正常化结果掩盖它。schema 兼容测试须覆盖真实 v2；受保护否定/数字差异不应被二级意见无条件覆盖。 |
| [AD #459](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/459) | 韩语再次压缩 | 保持译文，换种子及绑定的较快朗读提示后仍为 245.79 秒，未改善 AB 的 245.44 秒。停止同类种子试验，转向片段选择或经人工审核的口播稿。 |
| [AE #461](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/461) | 当前 QC 实现的中文文字校准 | 修复音频 detector 改变统一 QC 实现哈希，旧文字豁免因此失效；重跑文字校准在 511 个返回后预留耗尽。安全地拒绝旧豁免，但整体哈希过粗导致无关层重算；将来应细分版本化依赖闭包。 |
| [AF #462](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/462) | 中文 TTS 本地构建前 | 文字续算 24 个请求后放行，新目录却缺 `clip-timeline-map.json`。跨运行复用须由 manifest 枚举所有下游依赖，而非手工只复制显眼收据。 |
| [AG #463](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/463) | 当前实现的中文音频校准 | 中文新音频、包与主 QC 通过，校准在 514 个已返回请求后再次用尽原阶段预留。预算规划要以**剩余完整校准矩阵**算上界，复用旧调用只补缺失。 |
| [AH #464](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/464) | 成功检查点 | 中文续算 63 个请求，校准 376/376 检出，单语 Dev 发布、HTTP 哈希回读和浏览器检查通过。机器豁免不等于人审、设备或现场。 |
| [AI #465](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/465) | 计划内文字层终点 | 西语旧实现的豁免不沿用；当前实现文字校准 218/218 并签发新豁免。`--through qc.es` 是有意停止，不计失败。 |
| [AJ #466](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/466) | 当前实现的西语音频校准 | 新音频包与主 QC 通过，551 个已返回请求后原阶段预留耗尽。保留本轮音频和响应，不能重新合成或重买校准。 |
| [AK #467](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/467) | 成功检查点 | 西语续算后校准 369/371 检出，单语 Dev 发布、HTTP 哈希回读和浏览器检查通过；三语合并仍未完成。 |
| [韩语口播试验 #468](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/468) | 新 Layer 2 草稿前 | 按同声线 50 个去静音单元拟合，8 秒句尾延迟预算要求 24 组共缩短约 524/1479 韩语音节。44 次本机 CLI 返回中，19 组只通过长度/确定性检查，5 组失败；部分“通过”草稿明显漏义。试验退出 1，未生成可配音的口播候选，没有新 Spark 或 Dev 发布。 |

## 泛化：一套防重跑门禁，而非再加一次“全程试跑”

| 类别 | 跨轮共同原因 | 下一次需要的工程关口 | 本次状态 |
|---|---|---|---|
| 跨层身份与缺失依赖 | L、N、P、Q、T、U、AA、AF 在来源、政策、插件、缓存、语音权利或时间线的**实际消费者**处才发现不匹配 | 运行规格冻结时导出不可变依赖图：每个消费者读取的文件、schema、哈希、实现、模型/声音/运行时身份及复用来源。先用真实消费者的只读校验路径跑完所有可构造的子计划；缺项直接拒绝派发。 | 单点修复已在工作分支，统一依赖图未实现 |
| 预算与调用容量 | J/K、M/N、R/S/T、V/Z/AB/AE/AG/AJ 分别暴露额度来源不一、输入过长、账本容量和校准最坏预留不足 | 派发前计算**实际请求数、完整 prompt token 上界、各语各阶段校准矩阵、单轮修订最坏预留、剩余总额与账本容量**；规划、开工、worker 消费同一版本授权。不足时先停在一次具体预算决策。 | 分片及续算代码已有；端到端容量预估仍缺 |
| 运行恢复 | O/P/Q/R 等靠人工复制，甚至曾把复用状态写到非权威摘要；已返回请求可能被重买 | 由驱动读取哈希清单并导入**权威 stage state**。分清未预留标记、已预留未派发、已返回、未知；未知先对账，完整返回只读复用，变更身份只失效受影响的 locale/层。发布成功后只续浏览器和报告。 | 若干手工导入与局部恢复已验证；统一恢复入口未实现 |
| 质检样本有效性与 schema | E/R 的注错样本无效；AC 的 v2 waiver/schema 错配和真实否定词漏检被先后发现 | 注错前先判适用性，保证每类有有效试验；waiver 消费者以真实 v1/v2 收据做合同测试。一级 ASR 的否定、数字等受保护差异须有独立阻断证据，再作全量校准。 | 样本适用性、v2 验证、一级受保护差异已修；需守住后续校准 |
| 片段与语速 | 101–116 西语、AB/AD 韩语以及口播草稿表明源片段时长不等于多语音轨可容纳时长 | 选片前用**当前声线、规范化策略、已测单元**拟合每语保守时长，核对完整句边界、尾部余量和 8 秒句尾延迟；只读筛选不当成 TTS 证明。难容纳的片段改选，不能靠随机种子、裁断、变速或降低 QC 门槛。 | 本次 50 句片段不满足韩语；只读候选筛选已做，未再开始测试 |
| 发布与状态诚实 | D 冷启动旧内容、G 报告异常、O/R `running` 残留、X 单语发布冲突 | Layer 4 计划与 publisher 共用 locale join；部署收据、HTTP 哈希回读、浏览器渲染各写独立终态。报告阶段可在已发布状态幂等恢复，异常总写 failed/blocked。 | 多项局部修复已有；完整恢复与真机播放未验收 |

### 优先实施顺序与验收标准（均为建议，测试已停止）

1. **P0：离线全路径预检。** 针对冻结 run spec 生成所有可推导的 Layer 1–4 子计划，使用与正式派发相同的 schema/身份/路径/预算校验器，输出“将新增的模型调用、Spark 作业、Dev 写入”清单；没有付费和远端副作用。用本报告中的确定性失败规格回放，要求 H 的术语、J/K 的额度、L 的插件、M 的输入、N 的账本、O/S 的修订路径、T/U/AA/AF 的语音与时间线、W 的远端目录前置要求、X 的发布 join **在相应消费者派发前**被捕获。无法在源数据产生前检查的条件标为 `deferred`，不能虚报通过。
2. **P0：内容寻址恢复计划。** 自动列出可复用的 Layer 1–4 产物和每一笔已返回调用，验证原运行身份与当前消费者；生成新 authority 时只对缺失调用预留，未知结果严格阻止新派发。用 N/P/R/AB/AJ 的保存状态做无模型恢复演练，证明不会重复请求、合成或部署。
3. **P0：选片及额度双重可行性。** 在任何三语真实模型调用前，给出完整句边界、来源审核状态、按同声线估计的每语音轨余量，以及三语文字/音频校准的最坏上界和剩余总预算。估计不足是**选片/授权决定**，不进入“先花一部分再发现不够”的运行。
4. **P1：版本化 QC 依赖闭包与消费者兼容。** 区分文字、音频和共同 schema 的实现身份，明确迁移规则；只有确实受影响的 waiver 失效。用 v1/v2 与受保护否定词/数字的真实形状夹具验证消费者，保留已冻结旧实现的历史语义。
5. **P1：状态机与发布恢复。** 所有异常写终态，部署、HTTP、浏览器、报告分别可恢复；测试“部署已成功但浏览器/报告失败”只重试后两者。真正的设备播放和场地验收单独记录，不能由浏览器冒烟替代。

下次真实派发前应只有一份明确的 **go/no-go 收据**，至少列出：冻结源与完整句边界、三语实际消费者身份及依赖哈希、预计音轨余量、各阶段最坏预留与总额余额、已返回/未知调用的复用结果、拟新增模型/Spark/Dev 操作，以及尚无法预检的真实质量风险。任一确定性条件不通过就不派发；质量风险则用受影响语言的最小真实单元先验证，再决定是否扩展，不重新运行整条三语链。

这也限定了预检的能力：Opus 对复杂句界的判断、TTS 章号读法、ASR 对否定词的实际听辨及译文核心语义，不能由静态配置检查证明通过。防重跑的做法是**保留已完成层的身份和收据，并把真实试验缩到风险所在的层、语言和单元**；不是把所有失败都改称基础设施故障后自动重试。

不要为检验这些改进再执行本片段的三语全量付费 E2E。先离线回放失败规格和收据，再选择**一个**身份冻结、语速与预算均有余量的新片段做有界真实验证；质量失败只修对应语言和层。此处是下次工作的验收要求，并非已实现或已验证的功能。

## 本次收尾

本地没有正在运行的 `run_clip_real_e2e.py`、`run_spoken_condensation.py` 或 `clip_e2e_spark.py` 进程。失败产物、账本、原始音频和逐组韩语审稿材料保留在被忽略的 `artifacts/`，没有清理或改写。工作分支 `codex/opus-layer1-larger-clip` 上的局部代码修复已推送，**不能因此宣称已合入 Dev 或生产**。本复盘只归档事实与下次的预防要求，不授权新模型、Spark 或 Dev 派发。
