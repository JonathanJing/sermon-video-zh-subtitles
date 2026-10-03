# PR #231 修复与 #228–#231 联合检查

用户明确授权修复、写入 PR，并联合检查后合并 #228–#231。此前检查见[并行回执](20261003-pr231-parallel-checks.zh.md)；本报告记录随后修复的代码范围，不倒写为此前已完成。原件、线上目录、生产任务和其他分支的 tracker 修改保留；没有模型调用、账号／权限／限额配置、正式发布或通知。

## 修复与验证

| 路径 | 修复及实际验证 | 边界 |
| --- | --- | --- |
| Web／Swift 三语候选读取 | 冻结真实 Dev catalog→release→内容／字幕链可读；明确 Dev 才接纳 candidate，保留机器审核。Web 464 项通过。Core 实际 71 通过、6 跳过；Infrastructure 实际 42 通过、5 跳过。 | 原始 JSON／SHA 链与三语各 839 条字幕另有隔离探针；没有部署、真实播放或 seek 验收。 |
| 原生 Production 隔离 | 根据包的 hash 与 published/human 状态按 locale 投影可选内容，重选默认值；冷读取、候选负缓存、离线缓存均不能暴露候选。最多 4 路并发、30 秒截止；短 deadline 保留已通过 sibling。 | 兼容旧 wire 目录需额外查询发布包；没有代表性性能实测。 |
| Beta UI 选择 | Beta bundle＋精确 HTTPS Dev origin 才启用机器候选；AppModel 的真实三语选择／读取 2 项 XCTest 通过，显示 Dev／机器审核及未正式验收提示。播客不构造视频入口。未签名 Beta simulator build 通过。 | 未安装／启动实体设备或 TestFlight。编译与逻辑探针不等于设备视觉／播放验收。 |
| App durable producer | 显式配置接入 Supervisor、end_to_end 和 local production；消费已批准产物／双端收据，复制依赖并原子写 prepared_not_published 包。原目录不可用后仍能真实 CLI 消费复制包。 | 不生成四项内容，不代写人审，不执行双端正式 publisher／回退或通知；默认 dual_pdf 保留。 |
| App 恢复／独立状态 | 18 项新 workflow＋24 项准入通过；独立 reviewer 跑 127 项新旧 scope 套件通过。覆盖 PDF 独立失败／恢复、重启复用、旧批准拒绝、来源漂移、活／未知 owner、失败收据保留、目录祖先 fsync、固定配置路由及 JSON 非有限溢出拒绝。 | 127 包含新 workflow／准入，不能重复相加；夹具批准均为 synthetic，未运行真实新 App plan。正式端 pass/fail 观察不触发发布或虚报完成。 |
| 原生费用导入 | 新离线 envelope 消费原生 Costs 响应并输出既有归一化 v1；Decimal 合并 line-item 分区，拒绝重复／断链／缺日／错误类型／极限日期，未知归因不猜、空结果不补零。40 项相关测试及独立复核通过。 | 不调用 Costs API、读 key 或配置账号。原生响应不证明结算，输出固定 pending；实际映射、producer 归因与真实账单未验收。 |

独立审核关闭了目录祖先持久化、JSON 浮点溢出、截止时间丢失成功 sibling、候选／UI 状态、原生账单输入类型和日期溢出等问题；受审源码 hash 和详细日志在 ignored artifacts 中保存。新增共享 fixture 的 Web 测试已纳入 native CI 路由，24 项 CI 路由／文档／iOS 路由测试通过。原 renderer 与 #229 基线的字节仍一致，不扩大缓存兼容名单。

操作入口：[App producer](../app-delivery-workflow.zh.md)、[本地开发说明](../pr229-local-development.zh.md)。机器回执位于 ignored `artifacts/pr231-checks-20261003/` 的 `catalog-client/fix-summary.json`、`integration-recovery/app-workflow-summary.json`，以及 `artifacts/pr231-fixes-20261003/` 的 `final-code-review`、`cost-review`、`pr-stack-review`；不将原内容、私人审核信息或原日志复制进 Git。

## PR 联合检查与合并

1. #228 的页面输入命名、catalog 保留、HTTP／设备证据边界与 #229/#231 一致，可独立合并。
2. #229 保留九项稳定任务的完整定义、优先级／状态／验收／依赖，日期文档只展开细节；审计报告区分原只读调查与后续文档编辑、提交、push 和 PR 创建。两项远程审核意见已修复并独立复核。
3. #230 明确后续本地软件授权覆盖最初暂停措辞，其余模型／账号／设备／通知／部署实验保留前置；四个 ES／KO 范围链接直达本页锚点，不再循环跳转。远程链接意见修复并复核。
4. #229 合并后将 #231/#230 更新至 dev，按分支保护运行最终提交检查，采用 merge commit 保留栈的祖先关系。CI／合并的最终 SHA、状态和链接写入各 PR 与忽略的合并回执；不以旧 head 成功代替新 head 检查。

#232/#233 不在用户确认的本轮合并范围。只读核对 #232 的重叠：AppModel／ContentView／原测试补丁可组合；Core 音轨校验有文本冲突，但 #231 已覆盖其 v2 候选 WAV／M4A 兼容语义。后续合并 #232 仍需解决冲突并验证新组合，不能凭本轮核对自动合并。

真实新 App 四产物、双端人工批准、正式发布／回退、实际通知、设备和现场验收继续按各自证据记录；这些任务不因软件合并或 CI 通过而关闭。
