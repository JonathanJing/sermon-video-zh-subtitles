# PR #242：统一执行实现与验收

日期：2026-10-04。对应[DEV-R242-001—024](../backlog.zh.md#pr242-remaining-backlog)。本报告区分代码、离线验证、真实媒体和后续生产验收；并非三语／双端正式完成收据。

## 实现范围

| Backlog | 本次软件交付 | 仍需的实际证据 |
|---|---|---|
| 001 | 全消费者能力配置、实际输入/代码/runtime冻结、嵌套绑定、固定PCM及原窗口批准桥接 | 新来源声音授权、实际目标配置及相应执行输入 |
| 002 | L1 judge共用不可变cache、single-flight、1—8 workers、prewarm/unknown恢复 | 新来源真实模型运行 |
| 003 | receipt上下文复用、运行中依赖变更拒绝、逐WAV完整解码 | 已完成相同474句cache阶段实测，见下 |
| 004 | duration/lag诊断、异常旧WAV保留、稀疏恢复与独立排程 | 新篇修复效果及原8秒同步；不补造u172缺失旧WAV |
| 005 | 模型实际payload/policy预览、精确零API迁移、失败/unknown拒绝 | 真实prompt行为实验独立归023 |
| 006—007 | 元数据/环境路由、每次发布attempt、live版本及资产/HTTP闭合 | 新目标Hosting发布读回 |
| 008—010 | v2 CLI、只读查询、单owner、CAS、intent/预算、恢复、drain/取消、增量revision | 已做真实CLI/后台owner离线验收 |
| 011 | 正式L2 controller同账本接线、逐locale准入、请求硬限、输入闭包 | 新篇真实L2调用与账单核销 |
| 012 | Source ASR/MFA/anchor/judge；音频固定配方、assembly-only、正式候选与输出闭包验证 | 新来源模型/GPU和人审 |
| 013 | 大纲/默想独立producer及审核、source unit核验、四产物汇合 | 新篇两份学习产物实际审核 |
| 014 | 增量locale合并、siblings保护、回滚、远端lease和基线版本检查 | 授权目标实际发布/回滚演练 |
| 015 | Beta/Dev/正式iOS/正式Web端点读回、locale×endpoint覆盖与实际播放证据验证 | 四端真实人工审核和三语播放 |
| 016—017 | owner事件、既有provider/job日志接线、截止余量、未知保持空值、代码/runtime/内存/预算账本 | 新篇真实provider叶、GPU峰值、账单；历史缺测仍未知 |
| 018 | 当前WAV/track/text绑定的可选逐项裁决，旧整体批准兼容，逐项真值统计 | 新样本实际裁决 |
| 019 | 真实CLI、脱离聊天的owner、100次转移与故障回归 | 离线验收已通过；不代替内容验收 |
| 020 | 实际测试媒体已接新CLI；可按审核后的scope逐层续跑 | 短片→10分钟→全片、冷/热和15小时完整范围 |
| 021 | 固定质量、声音与输入的容量计划/结果准入，8×8及24GiB保护保留 | 有授权的真实容量矩阵 |
| 022 | 同源/政策/质量协议、冷/热六组盲标签比较、bounded context packet、费用域分列 | 实际workflow/Agent对照及账单 |
| 023 | 复用paired A/B，冻结完整payload、样本、预算、盲评/非劣门槛及批准 | 获批候选的真实调用和人工盲评 |
| 024 | 同pump/同账本Temporal、显式scheduler转交、人工等待signal、一次activity尝试 | 本机隔离native server验收已通过；未迁移生产 |

实现入口：[CLI与恢复](../unified-cli-runtime.zh.md)、[全消费者能力](../unified-consumer-capabilities.zh.md)、[Source](../unified-source-preparation.zh.md)、[L2预算/迁移](../canonical-layer2-budget-and-migration.zh.md)、[音频](../unified-audio-adapter.zh.md)、[STE实验准入](../ste-paired-admission.zh.md)。

## 已运行的验证

- 跨Source、L2、L3、交付和统一状态机的第一轮集成：89项通过。
- L3/听审/STE定向回归：88项及4个subtests通过。
- Temporal SDK人工等待/未知结果唤醒：2项通过。
- 集中回归：unittest 319项通过；pytest **347项、41个subtests通过**。后续owner/CAS/闭包定向回归41项、42项通过，最后修订缓存计量与owner组合56项通过；新增CI专用pytest合同28项通过；受影响legacy发布测试3＋32＋18项通过。命令和日志保存在`artifacts/pr242-integrated-validation/`。
- CI已安装独立`requirements-test.txt`并显式运行pytest风格的合同测试，避免unittest导入却不执行这些函数测试。
- 这些数字含部分测试类继承和重叠，不相加成唯一测试总数。

### 真实CLI和后台owner

证据：`artifacts/pr242-unified-cli-acceptance-closed-runtime/acceptance.json`。

- 100次带前置依赖的持久转移，99次可测交接；最终代码闭包含legacy发布脚本与网页资源，总耗时42.710秒。
- 交接p95 **0.224645秒**，低于2秒阈值。
- 新付费请求0；运行时Codex turn 0；生产资格false。
- 这是离线fixture返回与真实CLI/owner，不是模型速度或三语内容通过。

### 474句真实cache收据校验

同一474句中文cache，基线与复用路径均逐WAV完整解码，没有修改原生产产物。

| 路径 | 秒 |
|---|---:|
| 原完整receipt校验 | 800.787065 |
| 当前严格快照复用 | 48.098803 |
| 减少 | 752.688262（约94%） |

仅衡量该收据校验阶段，不推断GPU合成或全流程加速。证据`artifacts/pr242-layer3-validation/receipt-benchmark.json`，文件SHA-256 `e21d48b1d6988221d10b77768ceba5c2173376bcab550935cefee75e96a53aae`。

### Temporal原生环境

证据：`artifacts/pr242-temporal-unified-acceptance-1/acceptance.json`。

独立临时本机端口、独立SQLite、真实SDK/native server → 项目Python → 原pump：观察持久暂停，signal后完成，再转回canonical；只有一对dispatch开始/结束事件，未重复派发，零模型请求。测试服务器已停止，数据库保留用于核验。版本为CLI1.8.3 / Server1.31.2。未启动或迁移生产owner，不声称高可用。

## 用户指定视频实际测试

来源：[If I Had More Time | Jesus Judges and Keeps](https://www.youtube.com/watch?v=Ihf2FfYx8-M)，发布者Mariners Church。下载metadata与音频保留在`artifacts/unified-cli-acceptance/Ihf2FfYx8-M/`，不入Git。

新CLI已经完成：媒体SHA绑定、ffprobe、**整段音频解码**和窗口上界核验。

- 音频时长：4606.221秒（76分46秒）。
- 媒体SHA-256：`ee46fa3b9298725f5c8ffdbf538fe54c012863c3ab8c0928f5424399960989b4`。
- `media-result-v2.json`：`runRevision=2`、`completionScope=media_verified`，`outcome=succeeded`；`productionEligible=false`。
- 实际预算预留0，未启动付费ASR/翻译、Spark配音或发布。

发布者说明含多人讨论。机器speaker标签不会自动映射真人，也不能将多人轮次压成单一声音。下一阶段仍待本视频范围/窗口、API硬上限和声音方案明确，才能生成绑定授权及全消费者能力配置。当前媒体测试使用独立实验窗口，不是正常周六19:00—周日10:00的整周验收。

## 发现后修复的关键回归

- 首次远端CI发现冷进程首次模型调用懒加载迁移模块改变代码身份，现改为冻结前加载，仍保留身份变化拒绝。
- 严格准入识别新增政策预览文件，并核验政策、payload、对应cache哈希和非人工批准状态；新增篡改拒绝回归。
- 嵌套测试先注册清理再初始化，异常也恢复全局临时目录；音频旧夹具补齐快照依赖，缓存fsync测试精确区分预览写入和请求标记写入。
- activeScope按阶段产物限制派发，媒体验收不会进入ASR，翻译审核目标不会触发TTS。
- 消费者嵌套文件、原窗口URL、当前locale和政策均重新核验，配置JSON本身的SHA不能替代这些输入。
- 旧response缺失/变更不复用；连续revision保留最初返回来源和历史预算，当前revision单独计缓存验证时间，不重复累计原合成耗时。
- 失去owner的running转unknown；取消与在途返回分开；对账保留CAS。后台owner在人工等待期间保持运行，避免审核提交恰好撞上owner退出而漏掉续跑。
- 三语言最终状态按每个locale的每个端点检查。
- 学习产物读取canonical `sourceUnits`；Temporal在人工等待时保持可唤醒，不提前结束后卡死。

## 关闭规则

上述工作在本PR接受审阅、合并后，代码交付可记录对应合并commit。涉及真实模型、发布、设备、容量和质量实验的条目继续保留其实际验收状态；不把软件通过改写成这些实际证据。

## 逐层审计后的补齐（2026-10-04）

先前软件入口验收未覆盖从空输出物化后续配置、实际学习产物生成和原生阅读页。逐层审计明确了这些缺口；本次补齐不把旧组件测试当成完整四层实际生产验收。

| 缺口 | 本次修复 | 本轮证据边界 |
|---|---|---|
| 后续配置依赖尚不存在的文件 | 冻结受限 continuation recipe、typed output ports、原始审核证据槽；owner 在同一账本中 CAS 追加 revision，并同时保存物化收据 | 从不存在的 source 输出开始，离线 ASR/judge → 审核配置 → 独立人审包 → canonical source inspection；owner CAS、预算/原 owner 保留及证据导入另有回归。完整真实四层仍需正式 producer 输入与人工决定 |
| 大纲和默想只有 supplied sections | Study v2 独立模型生成、完整翻译组分批、术语/policy/prompt/code 身份、独立请求预算、原始响应缓存、unknown 阻断及保留结果重建 | 注入离线 provider；实际 API 调用未运行，机器产物仍为 human_pending |
| 四产物只汇合在私有目录 | release v3 公开 outline、meditation、products；静态 HTML 完整正文、随版本封存的 Web reader、HTTP/端点资源核验 | 真实本地 builder → seal → Web Node loader；合成上游审核证据，不是 Hosting 发布或真人内容批准 |
| 原生客户端未消费学习产物 | iOS v3 验证来源/候选/资源 hash；实际 SwiftUI 文稿区显示大纲与默想，切换清除旧资源；独立 HTML 阅读及离线缓存均重验 | Python 真实 builder 产物 → Swift 原生文稿/学习资源/HTML → 离线 → 缓存篡改拒绝；iPhone 模拟器完成正文与语言选择交互、保存前后截图。不是新视频真机验收 |
| 跨配置来源身份只绑定媒体 | Source 绑定 run/URL/duration/window approval；Audio/Delivery 全来源与 page 绑定；下游生成、canonical inspection、审核导入及审核复用均核对所选英文修订包 SHA | 同媒体同窗口的另一文本修订拒绝；保留原源码/媒体/cache，不在下游修源 |

### 验证记录

- Python 集成批次：`/private/tmp/pr242-final-complete-targeted.log`，167 passed、2 skipped、17 subtests；新增 Unicode/单引号 fixture 后一项 Web 对照仍写着旧正文，修正为完整 fixture 正文后，`/private/tmp/pr242-public-encoding-final.log` 的 5 项复验通过。其他测试未因这项失败被跳过。
- 新 review/所选源包/owner/capability 定向：`/private/tmp/pr242-review-binding-final.log`，54 passed、5 subtests。与上述批次有重叠，不累计为独立数量。
- Web 三个相关测试文件：`/private/tmp/pr242-web-final-tests.log`，33 passed。
- iOS 实际 Python 产物互操作、完整正文及篡改拒绝：`/private/tmp/pr242-study-real-builder-ios.log`，3 项通过。fixture 含单引号、韩文、斜线和多行正文。
- Core 旧目录兼容：`/private/tmp/pr242-core-compatibility-final.log`，15 项通过。
- 原生 UI：`artifacts/tongxing-ios/2026-10-04/cli/20261004T165424-test-77d00deb/test.xcresult`，1 项通过；同设备、同韩文样本的前后截图在 `artifacts/pr242-four-product-repair/native-ui-attachments/manifest.json`。中途失败揭示实际 SwiftUI 阅读分支未接资源，已修复并复验。
- 上一提交 b744 的远程 root-0 CI 因 strict Layer 3 测试缺少新增 checkpoint 夹具失败；本次补齐真实 map/operation policy，并让负例明确匹配 rubric 错误。41 项相关测试、3 subtests 通过。新提交的 CI 需另行核对，不用该局部结果冒称远程全部通过。

### 版本与接续

详见 [continuation](../unified-continuation.zh.md)、[Study v2](../unified-study-generation.zh.md)、[四产物公开交付](../layer4-four-product-public-delivery.zh.md)。consumer capabilities v2 指向 release v3；旧 v1/v2 包保留其原范围，不赋予四产物资格。代码身份或输入已改变时需新 revision/绑定，不能直接沿用旧执行的成功声明。

本视频仍只保留已验证完整媒体的实际收据。没有新增付费 ASR/TTS、Hosting 发布、TestFlight 上传或真人听审。新来源的窗口决定、API 硬预算和五人声音方案仍是实际生产输入；不能从旧证据或离线合成批准继承。
