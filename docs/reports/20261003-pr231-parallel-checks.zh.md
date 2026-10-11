# PR #231 并行检查回执

业务代码基线 `384b79cc5dfcbd56b72642b741dda78841431380`；后续 `86355d5f98228681e1e5f525cfda78bb4cc4a05f` 只增加当前工作分支的 CI push 触发，不改变被检查的业务代码。用户要求并行执行真实产物、目录、流程集成、双端条件、费用与恢复检查。本次保留原件及用户其他分支的修改，没有模型调用、账号配置、远程发布／回退或实际通知发送。

## 本轮执行结果

| 检查 | 实际证据 | 结论及范围 |
| --- | --- | --- |
| 真实来源／西语产物 | 9/27 完整来源 420 单元、完整译文与独立口播稿各 420 组；来源、翻译及原始独立人审、音频／ASR 判定绑定通过 | 原件适用于新检查器的对应 fragment validator；未提供完整新 App plan，整体 App inspect 未运行 |
| 真实音频及原媒体 | 整轨加 420 单元共 421 份交付音频完整解码；整轨 1891.677333 秒。971172781 字节原媒体 SHA 和完整音频解码通过 | 439 份原件 hash 与检查前后不变；未全量解码原视频画面，未做新的听感／现场验收 |
| 真实 Dev 目录导航 | 冻结线上 JSON，以当前 reader／导航读取 14 条：10 正式／旧期次、3 诊断、1 演练；同名不同 ID、韩／西语音轨选择及深链刷新通过。Production 离线过滤保留 10 条，隐藏开发深链回退 | 本地当前代码及实际数据验证；线上仍是不同版本的 reader，不将本地分组说成已部署。实际播放／seek 未运行 |
| 音轨 HTTP | 两个诊断×三种语言共六条音轨的 4096 字节 Range 均返回 206 | 只证明这些 URL 的部分字节读取；不能代替播放、完整 hash 或音频内容验收 |
| iOS 实际 decoder | 当前 Core 原代码与真实冻结 v3 的临时 Swift package：全目录失败；诊断用已审 9/27 子集通过，两个探针测试通过 | 复现目录协议不兼容；未改线上目录／原客户端／cache，不等同设备实际失败 |
| 新检查器离线恢复 | 7 个独立 CLI 进程、12 项断言通过：无 PDF、PDF 损坏→有效 PDF、重启只读、旧 capability／旧批准拒绝、两端观察分列 | 人审和发布观察均为合成 fixture；不是 producer integration 或实际发布／回退 |
| 既有恢复守卫 | 16 项定向回归通过，包括 guardian 真实 owner／child／grandchild 死亡清理、两个 controller 唯一 durable attempt、旧 PDF resume／latch、catalog 回退资料和通知状态去重 | 证明所选已有路径；未接入新 App scope，未产生付费模型调用或真实通知 |
| 费用既有日志 | 10/1 原始 ledger 的 164 个生命周期事件为 82 start＋82 completed terminal，一一匹配；82 terminal 有 usage 对象，81 个有既有 responseId。两个导出快照的 API 记录与原始 ledger 完全相同，未相加 | 所检记录没有新合同的环境、Project／key、pricingVersion 绑定；历史日志不是本轮账单，不能猜测归因。独立只读复核通过 |

原件、冻结目录、详细机器回执、CLI 进程记录、临时 Swift package 及截图保留在 ignored `artifacts/pr231-checks-20261003/` 的 `real-products`、`catalog-client`、`integration-recovery`、`cost-ci` 四个目录；正文、私有审核者信息与原始日志不复制进 Git。

## 已确认缺口

1. **Dev 播客候选协议兼容。** 线上新 reader 已支持较晚的 Dev 候选扩展，当前分支 reader 不支持。当前 Swift `PageTarget.validate` 要求已人审 target，真实 Dev v3 的机器候选使整个 fresh catalog 解码失败。相关 reader／decoder 与 #229 基线字节相同，这不是新增导航引入的回归。需先冻结候选与正式内容的兼容／隔离合同，再补真实 client 回归；不直接复制线上脚本或过滤／覆盖正式目录。
2. **新 App producer 接线。** `app_delivery_readiness` 尚未被 producer、Supervisor、completion latch 或通知消费；旧 `page_release` 仍等待 PDF 上游，`deferred_until_release` 仍要求旧 PDF/GCS completion。新 App producer integration 执行次数为 0；恢复检查不能关闭完整交付验收。
3. **产物与双端证据。** 旧正文含四项大纲，无默想字段；不等于新增 study sidecar／独立审批。缺新 plan、默想产品及 iOS Beta／Firebase Dev 的对应能力与候选批准。物理 iPhone 当前不可用，已有模拟器安装身份不证明与本提交一致；真实双端查看、播放与人工批准为 `not_run`。
4. **真实费用接线。** 新模块只有本地归一化证据入口，provider 原生 Costs adapter、实际环境／用途／Project／key 映射及 producer 接线尚缺。凭据值未读取，真实账单测试 `not_run`，不能根据旧 usage 反推 Project/key 或已结算实际费用。
5. **双端发布恢复。** 新检查器只保存供应观察；没有新候选的双端 publisher／rollback adapter。本轮远程 publication、rollback、recipient receipt 均为 0／`not_run`。

下一轮优先修复 Dev 候选的客户端兼容／目录隔离，再接新 App producer 和独立 completion scope。随后以真实完整产物和双端批准做集成及发布演练；费用 adapter 与用途映射可独立推进。

## CI

已确认 #231 原 base 为 #229 工作分支，既有 Python workflow 只监听 dev／main，因而此前没有远程检查。新增当前工作分支 push 触发后，24 项 CI 路由／文档／iOS route 本地测试通过。

`86355d5` 的[完整 Python CI](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/37140372316) 终态为 **success**，`changes`、两个 `test-group` 和 required `unittest` 均通过。root-0 汇报 1705 项／1453.098 秒（跳过 3 项），root-1 汇报 1943 项／1531.132 秒（跳过 17 项），合计 3648 项，其中执行通过 3628 项、跳过 20 项。另有配音流程 399 项、Web 458 项、反馈接口 61 项通过。`native_contracts` 按 full scope 路由跳过，本轮的两个 Swift decoder 探针为本地独立执行。

远程 timing artifacts、两分片日志及最终 job metadata 保存于 `cost-ci/`；CI 通过不改变上述真实客户端、生产接线、账单及发布的验收状态。
