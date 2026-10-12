# 复盘：20261012-pr360-pr362-offline-review-fixes

## 实际覆盖范围

本轮为 #360、#362 的离线软件修复和回归，L1–L4 真实内容生产、模型调用、Spark 运行、部署、通知、设备及现场验收均未执行。#360 使用合成媒体；#362 使用 fake synth/ASR 和本机 Unix socket。测试通过不代表新口播政策的真实语音质量或发布完成。

## 结果和结束信号

两个 run 的 outcome 均为通过、exit 0。#360 在修复 commit `14c318ed2ca6ab01fb2376d2af60666f0a7953df` 的单文件测试为 47 passed；随后仅正常合入 dev 报告基线，推送 head 为 `48a3af658cf8d79060c3ba7f5ee5a08dbc871ed5`，未额外重跑。

#362 在数字分隔符保护前的八文件回归为 178 tests、28 subtests passed；补数字间小数点/分隔符保护后的三文件复验为 86 tests、2 subtests passed，最终本地修复 commit `4bf72e641d5e32472a7c878208b55b76d9447591`。两个阶段范围和源码不同，不相加或宣称全部 178 项已在最终源码重跑。当前 #362 尚待 #360 合入 dev 后同步基线并推送；本报告不称其已经 merge。

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

#360 已推工作分支；#362 本地修复尚未推送，等待按 strict 分支保护顺序同步 dev。此报告是独立 docs-only draft PR，保持待复核，不代表代码已 merge。Firebase/TestFlight/设备/现场均 not_run。

## 后续

主 Agent 在 #360 required checks 通过后合并，再由 #362 修复 Agent 正常合入最新 dev、快验和 push，独立核对最终 head checks。#362 最终基线快验可另追加报告，不改写上述阶段收据。历史 #361/#363 真实音频证据属于旧规则身份，不外推新 v2 规则，也不由此报告授权重跑付费阶段。
