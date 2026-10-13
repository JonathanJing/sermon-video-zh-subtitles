# 复盘：20261012-pr360-pr362-offline-review-fixes

## 实际覆盖范围

本轮为 #360、#362 的离线软件修复和回归，L1–L4 真实内容生产、模型调用、Spark 运行、部署、通知、设备及现场验收均未执行。#360 使用合成媒体；#362 使用 fake synth/ASR 和本机 Unix socket。测试通过不代表新口播政策的真实语音质量或发布完成。

## 结果和结束信号

两个 run 的 outcome 均为通过、exit 0。#360 在修复 commit `14c318ed2ca6ab01fb2376d2af60666f0a7953df` 的单文件测试为 47 passed；随后仅正常合入 dev 报告基线，推送 head 为 `48a3af658cf8d79060c3ba7f5ee5a08dbc871ed5`，未额外重跑。

#362 在数字分隔符保护前的八文件回归为 178 tests、28 subtests passed；补数字间小数点/分隔符保护后的三文件复验为 86 tests、2 subtests passed，最终本地修复 commit `4bf72e641d5e32472a7c878208b55b76d9447591`。两个阶段范围和源码不同，不相加或宣称全部 178 项已在最终源码重跑。首次导出时 #362 尚待 #360 合入 dev 后同步基线并推送；本报告不称其已经 merge。

## 耗时

#360 pytest 自报 11.37 秒。#362 八文件 pytest 自报 67.64 秒，外层进程 wall 67.868 秒；最终数字分隔符三文件 pytest 自报 25.06 秒。范围不同，不作速度或性能提升结论；等待与计算未逐项拆分。

## 错误

#360 原 margin 数据允许 bool/string/nonfinite 等非法类型，可能让 NaN 绕过 clip 边界约束。修复在输入访问或素材创建前验证类型、有限值及可表示性，v1 对称迁移和原 spec hash 保留；相关负例和非对称/source binding 回归均通过。

#362 三条 review 均有效：普通照片/电影计数被误当 scripture counter；isalnum 删除百分号等可发声符号；连写章/节漏转章数。规则现仅匹配明确韩文 Bible 书名后的相邻章/节链，Psalm 另支持 편，裸章号和普通计数不推断上下文；连写 `3장16절` 两处均转换。等价比较保留可发声符号及数字间小数/分隔标点。注册规则升级 v2、三 adapter normalization hash 更新，旧实验身份不重标。

原 [CI run 38320455868](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/38320455868) 的 root-6 唯一错误为错误 peer UID 已被 server 提前拒绝关闭后，测试 client 仍 sendall 导致 BrokenPipeError。测试现直接读取具体拒绝响应，并验证 session status/require 准入检查未执行，生产拒绝逻辑未放宽。

本地初次测试收集还发现 regex format 把 `{1,3}` 误作占位符的开发错误；改为只替换 counter 占位符后离线回归通过。首次综合导出因 #360 timings 两列被误识别成失败阶段；规范为 stage/status/elapsedSeconds 后重新导出，没有重跑测试或修改测试结论。

## 占用资源之后才暴露的错误

无真实 Spark、模型或部署资源占用。边界与等价性问题已由离线负例覆盖，无需付费请求验证新增上下文规则。

## 遗留状态

仅保留忽略目录测试日志/摘要和初次 timing schema 错误导出；无新正式 run、job hold 或构建号。测试临时对象自行清理。未读取或改变线上 Dev 内容/运行状态。

## 外部可见的变化

首次导出时：#360 已推工作分支；#362 本地修复尚未推送，等待按 strict 分支保护顺序同步 dev。此报告是独立 docs-only draft PR，保持待复核，不代表代码已 merge。Firebase/TestFlight/设备/现场均 not_run。

## 后续

主 Agent 在 #360 required checks 通过后合并，再由 #362 修复 Agent 正常合入最新 dev、快验和 push，独立核对最终 head checks。#362 最终基线快验可另追加报告，不改写上述阶段收据。历史 #361/#363 真实音频证据属于旧规则身份，不外推新 v2 规则，也不由此报告授权重跑付费阶段。

## 最终 dev 基线追加快验

#360 已通过 required checks 并合入 dev。#362 正常合入 dev `6fc1368224341b4154071001e3818514758f30ac`，最终工作分支 head `d58c140b7ef2554689295ce4d8a7e1a8cf347d5f`，无冲突。针对 Korean spoken numerals 和 gateway 的两个文件快验为 55 passed，pytest 自报 0.86 秒；diff check 通过。未重复八文件 178 项回归，未调用模型、Spark 或部署。最终 head 已正常推送，CI 结果另由 GitHub checks 核对；本报告保持 draft，不表示 #362 已合并。

## 引用范围终点追加修复

最终基线 CI 13 项成功后，新增 review 指出 `부터`／`에서` 范围终点数字未转换。修复 commit `1df273e3` 仅扩展既有书名锚定的相邻引用链，不跨普通正文；普通照片/电影 counter 仍不转换。两个正例和普通 counter／跨正文负例定向测试所在 numeral 文件 50 passed in 0.23 秒，diff check 通过。正常 push 后由新 head CI 再判断可合并性；此前 13 项成功不代表新 head 已通过。没有调用模型或部署，报告保持 draft。

## 生成到 ASR 评分全链范围追加修复

前一 head CI 13 项成功后，新增 review 发现重复 counter 横线范围漏终点，以及单 counter 范围首端无法折回数字。commit `81773fee` 增加三种横线连接，并以 scoring v5 按书名锚定完整引用链折叠；同时修复连写章/节和无空格书名，Psalm `편` 走同一链。v4/v3 收据仍按原语义评分，普通词内保护不放宽。口播规则仍为本 PR 未合并的 v2，normalization policy hash 不另改；ASR runtime scoring 和实现 hash 单独绑定。

最终三文件合同回归 138 tests、34 subtests passed，0.83 秒；覆盖生成→fold→score、单/重复 counter、三种横线、particles、单/多音节端点、空格/连写/Psalm，以及错误数字和固有词拒绝。diff check 通过；独立只读审阅未发现新增具体阻塞。初步两文件阶段 120 tests、22 subtests passed，0.71 秒，不与最终统计相加。未重跑模型、音频或部署；旧 #361/#363 的真实 QC 不验证新折叠实现或校准。正常 push 后等待新 head required CI，报告保持 draft。

## Counter 词边界与数字范围结构追加修复

新增两条有效 review：counter 前缀词如 `3장면`／`2편지` 被误改；字符级评分可能把 `12-3` 与 `1-23` 摊平为相同数字串。commit `bce69bd8` 为 generator 采用词边界、相邻引用或列明完整助词；`편의점`／`장도리`／`장만두` 也不转换。新 v5 只在书名锚定引用 span 内比较数字串分段、范围标记、counter 和紧接的范围终结助词，拒端点重分段、横线插删、末尾까지插删及 counter 变换；无书名引用的既有 generic folding 行为不改，v4/v3 重评分语义保持。

初次新增边界测试有三项开发中失败（Sino 相邻范围前瞻不完整以及一个负例预期），均修正后重新测试；独立审阅进一步指出无空格连接词的 digits/Sino 边界差异及末尾范围标记遗漏，也已加回归。最终三文件 189 tests、34 subtests passed，0.95 秒；diff check 通过。各中间阶段不相加，不宣称一次全量回归。复用未合并规则 v2 normalization hash，v5/runtime 实现身份单独绑定；旧 #361/#363 真实 QC 不证明新实现。没有模型调用、Spark、部署、设备或现场验证；报告保持 draft，最终 head 仍须独立 CI 通过后合并。

## 范围结束助词的空格与复合形式

在 `bce69bd8` 的独立复核中发现，范围末尾空格 `4장 까지` 和复合 `4장까지는` 的删除未受引用结构保护。追加 commits `5e36f34f`、`4efc566f` 纳入带空格的完整范围 marker+suffix（는/만/도）；只标准化空白，保留 suffix 语义，单删 suffix 也被拒绝。最终工作分支 head `4efc566f9c53f2326e62347ee37e6ce008662dc1`，三文件 193 tests、34 subtests passed，0.97 秒，diff check 通过。此前 189 项阶段为历史快照，不与此相加。未执行模型、Spark、部署或真实音频 QC；保持 draft，等待最终 head CI。

## 当前 v5 依赖闭包与计划冻结

commit `cc353091b501f3cd32df5a2c169d4e8fdde779aa` 添加合法完整助词 이／이라고，并把 screen、Korean helper、auto_qc_text_common、common 纳入当前 v5 实现身份。缓存、ASR settings、primary runtime 和 rescore 消费者拒绝过期闭包；QC/calibration/waiver 的实现身份也纳入 helper。Korean normalization-v2 或显式 unit-instructions-v2 的 unified audio plan 绑定新增依赖，修改依赖后 execute 在 dispatch 前拒绝。旧 exact-text v1 声音身份及 v4/v3 评分路径保持，旧 single-file experimental v5 收据需显式重评分。fixture 只更正 current v5 hash，没有放宽阈值、预期结果或旧 v4 测试。

初次六文件测试因旧 dummy/self-only fixtures 得到 22 failed、270 passed、69 subtests（159.03 秒），识别身份预期过期后中止，保留失败证据。更新 fixture 后，四文件快速合同 210 passed／46 subtests（9.98 秒），独立 waiver 依赖变异回归 1 passed（0.09 秒）；最终完整四文件 consumer/fake-calibration 矩阵在冻结 `cc353091` 上 131 passed／64 subtests（920.76 秒），退出码 0。各阶段不相加；快速阶段早于显式 v2 指令 plan 补充测试，完整 consumer 包含该路径。全部使用离线 fake 数据，没有模型、Spark、部署或真实音频 QC。旧 #361/#363 真实 QC 不能验证新 folding／依赖闭包或当前 calibration。

## 引用替代连接词与共享语法

最终代码 head `471fd2c5` 针对新 review 的 이나，并统一已有完整 citation connector：이나／이든／에서부터／부터는／부터만／부터도 与原连接词，在 generator、ASR 边界和引用链共用语法。不扩大一般助词或跨正文上下文。数字折叠先消费完整连接词再处理 reference numeric atoms，避免把连接词的 이／만 当数词。

开发阶段依次发现 connector syllable 误折、无空格 부터만 吞 syllable、一次移动 import 后的作用域 NameError（134 failed），均保留日志与统计。修正后最终三文件合同 219 passed／34 subtests（1.01 秒），diff check 通过；覆盖生成→fold→score、无空格／空格替代和 compound 范围、错误端点拒绝、普通 counter 与跨正文负例。该结果绑定 `471fd2c5`；此前完整 consumer 131／64 只绑定 `cc353091`，本次 connector-only followup 没有重跑其十五分钟矩阵。GitHub CI 按最终 head 独立核对；报告继续 draft，不表示代码已合并或真实 QC／设备／现场通过。

## 导出日志副本规范化

补交日志后发现 pytest traceback 副本含行末空白，默认 diff gate 会拒绝。仅清理报告日志副本的行末空白；manifest 的 sha256／bytes 保留原来源身份，新增 exportedCopy 绑定规范化副本的 hash、字节数与处理方式。原运行日志未修改，未重跑模型或测试。默认 git diff --check 和 exporter 脱敏验证通过。

## 引用连接词语义与分隔式 Sino 数词

新 review 指出 과／이나 的语义替换可能在相似度门槛下通过，以及 `시편 백 십구 편` 未整体折为 119。commit `ca535487` 让书名锚定结构保留所有 lexical citation connector 与 range marker，拒替换、删除、插入；新增 book-scope 分隔式 Sino 折叠，并要求去空白拼写为 canonical korean_sino(value)，拒重复／升序 unit 与端点合并。初轮 246／34（1.11 秒），严格拼写补例 249／34（1.10 秒），插入矩阵后 264／34（1.11 秒）均通过，分别为开发阶段，不能相加。

父审裁定逗号沿既有停顿标点可忽略政策。追加 commit `2165db49` 仅从结构签名排除 comma，保留 lexical connector／dash；测试加入 comma 插删通过与 lexical 插删拒绝对照。最终三文件 263 passed／34 subtests（1.12 秒），默认 diff check 通过。完整 consumer 131／64 仍只绑定 cc353091，没有重跑十五分钟矩阵；v4/v3 旧评分路径未变。两条已实质修复线程已 resolve，无评论。脱敏日志实际入 Git，规范化副本记录 exportedCopy；没有模型、Spark、部署或真实音频 QC。新 head CI 独立判断合并，报告仍 draft。

## 已知书名内部 ASR 空格

新增 review 指出 `요한 복음 삼-사장` 因书名空格而失去锚点，范围首端无法折回数字。commit `306d57ba` 仅在 ASR folding 的已知圣经书名模式内允许内部空白，并只 canonicalize 匹配的书名，不全局删除空格。书名后仍需有明确相邻引用；普通照片词、书名后缀、词内前缀与跨正文引用不获得该解释。新增复合书名、Psalm、错误端点及普通字符串负例。最终三文件 273 passed／34 subtests（1.17 秒），默认 diff check 通过；这次没有重跑完整 consumer 或模型／Spark／部署。此前阶段不是此 head 的全量验证，最终 GitHub CI 单独核对。报告保持 draft。

## 完整系词结尾、复合连接词空格及前导零

commit `4d8cc087` 扩展明确列举的完整 copular endings（인데／이고／이지만／이라서及이에요／이죠／이네요／이어서／이니까等），仍要求完整后缀边界，장면／편지普通词不转换。ASR 的已注册复合引用连接词内部空白局部 canonicalize；terminal marker 的 suffix 空格也绑定结构，保留连接词替换、删除、插入保护。03장／03-04장／016절仅在书名引用内按数值规范化，不全局修改普通数字。

首轮 293／34 通过（1.33 秒）；扩展 terminal 矩阵暴露 4 个失败（detached 만／suffix），修正后剩 2 个 suffix 删除误过，进一步纳入完整 marker+suffix。最终三文件 312 passed／34 subtests（1.29 秒），所有失败阶段日志保留，不把中间统计相加。

实际 GitHub root-1 CI 在 head 306d57ba 记录 3 failed、78 passed、3 errors、5 subtests（批次24.25秒）：machine-checked delivery fixture 使用 dummy d*64 screening hash，被 current v5 closure gate 正确拒绝。本次仅改 fixture 使用实际 implementation_sha256，不放宽生产校验、阈值或结果断言。完整该测试文件离线 8 passed（3.30 秒）。CI 脱敏摘录已附，最终 head CI 独立核对。完整 consumer 131／64 仍属于 cc353091，没有重跑；没有模型／Spark／部署。报告继续 draft，默认 diff check 与脱敏验证通过，副本规范化保留 source hash 并绑定 exportedCopy。

## 校准 TTS 消费冻结口播策略

commit `f08720bf` 修复 Qwen 校准 transport 对变异文本直接合成 Arabic 数字、与正式 v2 Sino 路径不一致的问题。调用在合成及缓存 lookup 前使用 formal.policy_spoken_forms 与 job 冻结 normalization hash；v1 保留 raw，v2 request／record 绑定实际 spokenTextSha256，缓存读回核对 approved text／spoken binding。不存在的校准 unit 用独立合成单元查询同一策略，不把变异文本误当原 job 固定句。

离线注入 Synth 的定向 transport 测试最终 2 passed、12 deselected（0.32 秒）：验证 v1 raw、v2 Sino、cache reuse、规则派生文本变化 cache miss 和 spoken hash 篡改拒绝，以及 primary ASR 合同。首轮单测 1 passed／13 deselected（0.18 秒），不相加。没有模型／Spark／部署或真实重新校准，完整 consumer 未重跑，旧真实校准不能外推新口播实现。新 head CI 单独核对，报告仍 draft。

## 完整系词与校准调用闭包

commit `57cb5840` 补齐明确枚举的现在／过去／将来／条件 copular endings（含이다／이었다及常用conjugations），保持完整后缀边界，普通词前缀不放开。校准／waiver implementation identity 纳入实际 driver→transport→formal spoken policy 调用路径，以及 policy activation 使用的 sermon_sentence_interpretation.json_sha256；ko helper／terminology／common 已在闭包。未把无关 batch／recovery imports 扩入整个仓库。每个新增文件 mutation 后 hash 改变、旧 calibration receipt 被拒，恢复字节后旧收据重新有效。

开发首轮 1 failed、338 passed／34 subtests（1.49秒），原因是负例拼接后变成已支持的合法이라면；改为普通词尾상점。最终含activation helper闭包的三文件 339 passed／34 subtests（1.47秒），transport合同 2 passed／12 deselected（0.33秒），分别记录，不相加。此前339／34（1.67秒）为未加activation helper的中间阶段。全部离线，无模型／Spark／部署或真实重新校准；完整 consumer 未重跑，最终 CI 独立核验。报告保持 draft，默认diff check／脱敏验证通过。

## 配对引用括号、叠加范围助词与口播长度集成

commit `daadac90` 让范围 marker 共用已注册完整系词 grammar，覆盖까지입니다／까지였어요／까지라고／까지의／까지를等，counter 普通词边界不放宽。明确书名可紧接配对半角／全角括号，引用链完整处于同一对 delimiter 内；未闭合／错配／普通照片词／跨正文负例不转换。ASR 在相同 book scope 内折叠并保护端点、connector 和完整 marker+suffix。

并行独立修复语速拟合／预测／预算与音频时长QC：使用 job-bound formal.policy_spoken_forms，QC driver实际传 speech_job，CLI提供--speech-job；无job或v1保留原文计数。ASR／text hashes继续绑定批准文本。新增实际消费依赖 schedule／audio_qc／formal／driver／ko／terminology／activation helper 均已在当前waiver闭包，无需whole-repo扩张。

开发阶段refactor错误删除book与citation之间空格，85 failed／254 passed／34 subtests（1.93秒），修复后terminal内部空格8 failed／350 passed／34 subtests（1.79秒），均保留日志。grammar阶段358／34（1.71秒）、完整共享copula stacks364／34（1.79秒）通过。最终统一集成390 passed／49 subtests（14.55秒），范围为grammar三文件、新spoken-length实际WAV screen例、原PredictedScheduleTests／AudioQcTests、machine_checked_delivery。独立shadow报告两阶段17 passed／53 deselected／15 subtests（11.32秒）以及5 passed／13 deselected（47.61秒，含真实fake driver入口），与集成阶段重叠，不能相加，shadow确认两阶段stdout仅保存在工具输出、未保存原始文件；作为agent-observed报告记录，不冒充已附原始日志，也不为补日志重跑。未重跑完整consumer或模型／Spark／部署；最终head CI独立核验，三线程resolve，无评论，报告仍draft。

## 独立QC真实job绑定与压缩预算同口径

commit `0ef25fe0` 修复独立unit QC默认无job而raw计数的问题：CLI必须显式--speech-job或--legacy-raw-text，成品QCreceipt记录durationNormalization的job JSON hash与policy hash。canonical v2试听豁免拒缺失、legacy或foreign-job绑定；旧v1无字段收据保持历史raw语义。实际CLI运行验证缺输入拒绝、job绑定输出及显式legacy路径，waiver入口验证v2拒绝无绑定或其他job。

压缩请求从既有budget.rate.synthesisIdentity传递完整冻结身份，预算相等校验、输出长度、omission计量、recordspokenSpeechUnits与bindfinalSpeechUnits均复用相同policy_texts，原frozen rebuild proof未放宽。独立shadow回归22 passed／26 subtests（0.41秒），已保存日志与两份fixture开发失败证据，本报告实际导出入Git。

沿实际校准入口额外发现clean／seeded audio QC仍raw计数，已从renderIdentity.synthesis.normalizationPolicySha256传入显式calibration_policy_context；不伪造完整jobhash，该内部收据不能支持真实v2job豁免。新增测试调用实际seeded.calibrate与fake WAV／render，验证clean边界不误报、多个实际seeded QC都消费同上下文、且不被当成成品job绑定。

定向QC13项（3.35秒）、追加waiver拒绝后14项（3.43秒），校准修复前集成62 passed／38 subtests（4.29秒），最终含校准的集成63 passed／38 subtests（5.74秒），各阶段重叠不能相加。最终范围：实际QC CLI、AudioWaiverTests、machine_checked_delivery与condensation三个文件。全部离线，无模型／Spark／部署或真实重新校准；完整consumer未重跑。默认整PRdiffcheck、脱敏verify通过，日志forceadd／副本规范化保留sourcehash，报告仍draft，最终CI独立核验。

## 人接受收据不能绕过时长身份与旧显式口播拒绝

最终 commit `01bb67a4` 为human-accepted audio waiver v3接上与普通v2相同的duration_binding_problems。负例先构造并验证真正有效的人接受收据，再调用实际v3build：无绑定、legacy raw、calibrationcontext或另一个job绑定均拒绝；有效jobbinding会进入独立human-acceptance gate。两处生产build_audio_waiver入口均已核对，真实QC driver及calibration调用分别使用actualjob与显式calibrationcontext。

另一项legacy normalization-v1＋显式韩文spokenText没有可冻结口播长度身份，按父裁定在renderer指令校验和adapter planfreeze／dispatch前拒绝，要求冻结新registered-v2job。只拒该组合；旧v1 raw／instruction-only、其他语言既有角色及registered-v2匹配指令保留。docs与body旧兼容声明已纠正；历史阶段对旧组合的测试不能冒充最终仍支持。

最终字节整合39 passed／12 subtests（5.26秒），范围为新human gate、AudioWaiverTests、job-boundQC与delivery；独立完整renderer＋adapter44 passed／14 subtests（34.28秒），原日志已导出入Git。先前两次human gate24／12（0.93／0.90秒）为重叠阶段，后者包含valid人接受负例，不能相加。没有模型／Spark／部署或完整consumer重跑。默认整PRdiffcheck／脱敏verify通过，日志forceadd并保留来源hash，报告仍draft，最终head CI独立判断合并。

## 实际CI旧record兼容错误及版本化rate身份

实际head01bb67a4的root-0／root-6 CI分别跑650／685 tests（384.376／438.417秒），各有1error、3skipped，均因SpokenModeTests的手造legacy condensationrecord没有synthesisIdentity而KeyError；两个原始CI日志已脱敏摘录入Git。本次`e173a663`将新producer记录升级recordv2，必须valid冻结synthesisIdentity；legacyrecordv1缺字段仅保留raw长度，有身份时仍验证并消费。revisionbrief／bind读两版本，候选hash、source、omission、预算proof未放宽。两个旧fixture显式标legacyv1，不伪装新v2。新增v2删除／损坏身份拒绝、legacy缺字段raw绑定回归。

初轮33passed／26subtests加1个macOS路径别名失败（/private/var对/var），实际spokenwaiver已经签发；仅将路径断言两边resolve后，完整SpokenModeTests＋condensation相关文件34passed／26subtests（0.97秒）。普通production路径未改。

同轮formalpast范围结尾由完整copula family作 contraction（이었습니다→였습니다，이었습니까→였습니까），不是逐词allowlist补丁；15个family正负例，grammar三文件379passed／34subtests（1.96秒）。

Fitted rate新v2要求rateImplementationSha256，闭包六文件含计数schedule、formal、ko、terminology、common与policyactivationhelper；predict／budget／max_units_for共用校验。旧ratev1只兼容raw策略，registeredspoken-v2必须refit，不能把旧系数配新规则。静态旧rawfixture明确v1，新v2fixture绑定currenthash。独立rate矩阵53passed／53deselected／41subtests（11.71秒）；先前broad78passed／41subtests（96.67秒）因不必要慢校准中断，保留日志但不声明完整pass。

最终冻结字节统一443passed／75subtests（15.51秒），包含grammar三文件、完整SpokenMode、condensation三文件、rateidentity、spokenlength和原PredictedSchedule／AudioQc类。阶段重叠不能相加；没有模型／Spark／部署或完整consumer重跑。默认整PRdiffcheck／脱敏verify通过，报告保持draft，最终head CI独立核验。

## 最终代码合并终态

GitHub当前核对：#362最终代码head `e173a663c26cf7a28c5ab32eb9c2c5b90f2a8ce9` 的CI为18 SUCCESS、2 SKIPPED，无未解决review线程（主Agent已核验）。PR状态MERGED，mergedAt `2026-10-13T03:42:44Z`，mergeCommit `c1719208edd37073201efd3c827e1afd7e4cc62a`；远端dev的ls-remote同为该commit，主Agent的fetch核验一致。其余本次请求PR #360／#359／#361／#363已由主Agent核验合并。

这次只补终态文档，没有重跑代码测试、模型、Spark、部署或真实重新校准。代码合并及CI是代码证据，不表示新规则真实音频、当前生产calibration、Firebase／App、设备或现场验收通过。#364保持独立docs-only draft，未合并。此前各阶段失败／通过证据按各自head保留，不改写为一次最终全套本地测试。
