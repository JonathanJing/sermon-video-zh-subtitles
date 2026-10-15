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

## 下一次只加三道检查

本轮已经验证局部续算和若干单点预检有效；统一检查入口尚未实现。下一步复用现有 run spec、阶段状态、哈希清单和预算账本，逐层做以下三件事：

1. **付费或远端派发前检查。** 调用即将执行的真实消费者已有的只读校验，核对当前已知的来源、政策、插件、语音授权、路径、请求长度与本阶段完整预算上界。列出下一步会新增的模型调用、Spark 作业或 Dev 写入；不合格就停止。尚未产出的下游输入标为 `deferred`，产出后再检查。
2. **续跑前对账。** 按哈希核对现有阶段收据和账本，列出“可复用、须新增、结果未知”三类。只补缺失调用；结果未知时先查清终态。已发布页面只续做缺失的 HTTP、浏览器或报告检查。
3. **翻译完成后、整段 TTS 前查时长。** 有同声线样本时估计每语音轨和句尾余量；缺样本就标记不确定，先测少量代表单元。没有足够余量时，换片段或准备经人工审核的口播稿。真实发音、语义和音频 QC 仍需实测。

先用四份保存的失败收据做无付费验收：L 的插件错绑应在模型前停下；AG 的音频校准预算不足应在新增调用前显示缺口；AJ→AK 的 551 笔已返回调用应只读复用；AB 已测得的韩语 245.44 秒与 194.66 秒容器冲突应挡住 AD 的同类整段重试。四例通过只能证明这些已知问题被挡下，不能宣称首次合成前就能准确预测韩语时长。现有 v1/v2 豁免及受保护否定词测试继续保留。

不要为验证上述检查重新执行本片段的三语付费 E2E。真实质量问题继续只测受影响的语言和单元；设备播放与现场验收仍分别记录。这三道检查是下次工作的最小验收范围，**尚未作为统一入口实现**。

## 本次收尾

本地没有正在运行的 `run_clip_real_e2e.py`、`run_spoken_condensation.py` 或 `clip_e2e_spark.py` 进程。失败产物、账本、原始音频和逐组韩语审稿材料保留在被忽略的 `artifacts/`，没有清理或改写。工作分支 `codex/opus-layer1-larger-clip` 上的局部代码修复已推送，**不能因此宣称已合入 Dev 或生产**。本复盘只归档事实与下次的预防要求，不授权新模型、Spark 或 Dev 派发。
