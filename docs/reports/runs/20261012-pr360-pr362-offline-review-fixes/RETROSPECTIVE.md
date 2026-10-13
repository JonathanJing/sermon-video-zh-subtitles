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
