# 中文听译反馈 API

Node.js 22 / Cloud Functions v2，导出 `sermonFeedback`（`us-west1`）。同域 Hosting 将 `/api/**` 重写到此函数。反馈独立于统计同意：客户端只有主动提交反馈或同意统计时才创建会话；服务端无法替用户确认统计同意，须通过浏览器验收验证这个入口。

## 配置与数据

发布脚本从同一份 App 目录生成 `catalog.json`（参见示例）；只收录周次、音轨、音频 SHA-256、时长与字幕位置，不包含机器中文或私人资料。`server-config.json` 设置 HTTPS 来源白名单、独立数据库与专用运行身份；两个生成文件放在忽略的发布目录。服务器启动时缺失配置立即失败。

使用独立 Firestore 数据库 `sermon-dubbing-feedback`，通过稳定的 `@google-cloud/firestore` 客户端连接。客户端无 Firestore SDK，安全规则全部拒绝直接访问；运行身份只获该库所需数据权限。不得使用默认数据库，不复用现有字幕身份权限。源站校验是浏览器隔离措施，并非机器人身份证明；匿名端点仍可能被脚本模拟。

| 集合 | 内容 | `expiresAt` TTL |
|---|---|---|
| `feedback` | 每会话一条赞踩、多个独立问题，处理状态及修复版本 | 最后更新后 365 天 |
| `listeningSessions` | 实际收听秒数、已播放区间、累计操作计数 | 最后更新后 30 天 |
| `usageSessions` | 秒级操作事件、页面日期会话、每日浏览器哈希 | 最后更新后 30 天 |
| `weeklyMetrics` | 每周/音轨/音频版本汇总，无会话标识与文本 | 长期保留 |
| `apiSessions` | 随机凭据的 SHA-256 索引、来源、序列号和速率窗口 | 创建后 24 小时 |
| `feedbackSequences` | 问题删除后防旧请求复活的序列号 | 会话到期后 24 小时 |
| `rateLimits` | 全局分钟/日创建配额，无个人标识 | 1–2 天 |

上述 TTL 需逐集合启用 Firestore TTL 策略；时间戳字段本身不会自动清理。TTL 为异步清理，不保证到期瞬间删除。TTL 删除不回减长期汇总，主动撤回会在同一事务内删除记录并减去该条汇总贡献。`feedback`、`listeningSessions` 无姓名、邮箱、IP、User-Agent、跨周用户 ID；反馈文本本身仍可能被用户填写私人内容，UI 应提示避免填写联系方式。每个音频版本凭据最多有效 24 小时，App 只在当前页面内存保留凭据与摘要；刷新、关闭页面或凭据到期后不能恢复撤回能力，历史反馈只能由管理员处理；此限制需对用户说明。

服务自身只写固定错误码到 Cloud Logging，不输出请求/令牌/正文或供应商错误对象。Google Cloud 平台默认请求日志可能另外保存 IP/UA，请按该函数服务配置日志排除或保留策略；不能声称平台默认不记录这些元数据。

## HTTP v1 合同

全部请求 `POST`、`Content-Type: application/json`、准确 `Origin`，上限 16 KiB。共同字段：

```json
{"schemaVersion":1,"week":"2026-08-30","trackId":"full","audioSha256":"64位小写十六进制","appVersion":"构建版本"}
```

`POST /api/session` 仅共同字段。返回 `{token, sessionId, expiresAt}`，后者为 ISO 字符串。App 的凭据只保留在当前页面内存，不写 `sessionStorage`、`localStorage` 或 URL；之后附 `Authorization: Bearer <token>`。扩展行为采集使用新的 v2 同意偏好，开启后才在 `localStorage` 保存当天随机浏览器 ID；按洛杉矶日期每天轮换，服务端只存其日期哈希，不连接跨日轨迹。

`POST /api/feedback`：

- 总体评价：共同字段加 `{kind:"vote",seq:1,vote:"up"|"down"|null}`。`null` 撤回；每会话只保留一个当前评价。
- 独立问题：加 `{kind:"issue",feedbackId:"UUIDv4",seq:1,action:"upsert",categories:[],comment:"",context:"home"|"venue"|"unspecified",positionSeconds:null,cueId:null,blockId:null}`。分类支持 `translation,pronunciation,fluency,voice,sync,volume,playback`；说明最多 1000 字符；至少有分类或非空文字。
- 问题删除：共同字段加 `{kind:"issue",feedbackId:"同一UUIDv4",seq:2,action:"delete"}`。不影响总体赞踩和其他问题。
- 时间点须在音频范围内；字幕索引、块 ID 必须出现在允许目录中，且字幕时间匹配（允许 0.5 秒边缘误差）。无字幕位置 `cueId` 与 `blockId` 都为 `null`。

`POST /api/events`：共同字段加 `{action:"upsert",seq:1,listenedSeconds:0,ranges:[],plays:0,pauses:0,seeks:0,nudges:0,outlineViews:0,downloadClicks:0,errors:{audio_load:0,audio_play:0}}`。累计快照，每 60 秒/暂停批量发一次。`ranges` 最多 256 个排序、已合并、不相接区间；已经上报的区间不可丢弃。客户端到达区间上限时忽略新分散区间，保守少计，不能填充未播放空隙。

HTTP 区间格式为 `[[start,end]]`；Firestore 记录格式为 `[{start,end}]`，因为 Firestore 不允许数组直接嵌套数组。服务端完成转换，HTTP v1 合同不变；初次线上接入尚无成功写入的旧区间记录，无须数据迁移。

退出统计：共同字段加 `{action:"delete",seq:更大序号}`，删除当前会话统计及其汇总贡献，保留反馈；重新同意后可用更大序号从零开始。不同动作序列应在客户端串行处理。已关闭的其他标签页/到期凭据记录不在当前会话撤回范围，依 TTL 到期。

变更成功返回 `{ok:true,accepted:true}`，旧序号或重复请求 `{ok:true,accepted:false,lastSeq:当前服务器序号}`。每种总体评价、每个问题、每份统计各有独立递增序号。传输重试必须复用同一序号和内容；反馈和统计写入与汇总均使用 Firestore 事务，防止请求重试重复计数。客户端不得把旧请求的 `accepted:false` 当成新版本数据被接受，可同步本地序号后由用户重新提交。编辑反馈会重新进入待处理状态。

## 统计与防滥用边界

### 操作时间线 `/api/usage`

此新增路由保持已有反馈/收听 HTTP v1 合同兼容。详情见[行为采集与私有报表](../../../docs/sermon-app-usage.zh.md)。每个页面日期及同意阶段使用独立内存凭据，可复用公开目录中首个有效音轨作为凭据来源；事件自身记录当前周次/页面，因此查看音色或无配音周次也能记录。

追加请求为共同字段加 `{action:"append",seq:1,day:"YYYY-MM-DD",browserId:"UUIDv4或null",events:[],droppedEvents:0}`。`browserId` 实际为 JSON 字符串或 `null`；每天轮换，只存 SHA-256(day + 分隔符 + UUID)。每个事件必须准确包含 `{at:epochMilliseconds,action,panel,week,trackId,positionSeconds,speakerId}`；后三类位置/身份字段无对应值时填 `null`。`at` 到秒，服务端另存 `receivedAt`。允许动作/页面分别由 `usage-core.mjs` 的 `USAGE_ACTIONS`（46 项）与 `USAGE_PANELS`（6 项）定义，不接受任意文字。

现场界面扩展新增固定动作 `seek_undo`（撤销跳转）、`position_restore`（继续上次收听）、`position_restart`（从头开始）、`transcript_current`（定位当前字幕）、`more_open`（展开更多功能）、`precision_open`（展开精细调整）、`feedback_section_open`（展开反馈区域）。原有 39 项动作仍接受，HTTP v1 字段和存储格式不变，无数据迁移或新增自由文本字段；私有报表同步显示中文名称。

每批最多 30 条，连续 `seq` 从 1 开始；同序号且同内容的最后批次重试返回 `accepted:true,replayed:true`，不重复追加。序号缺口或冲突返回 409。响应含 `lastSeq,totalEvents,droppedEvents,closed`；累计最多 500 条，`closed:true` 后客户端停止采集此会话。声明丢弃数是该批新增数量，重放不重复累加。

事件与 `day` 必须同属洛杉矶日期；时间须在服务器当前时间前 24 小时以内、不早于凭据创建前 5 分钟、不晚于当前时间后 5 分钟。首次离线等待较久时，客户端舍弃未发送且已超准入时间窗的旧事件，并记录可上报的丢弃数量；已经发出的不确定批次保持原样重试。跨午夜创建新凭据。目录新增的可选 `weekIds`、`voiceIds` 严格绑定同一发布的公开目录，兼容旧目录未提供这些字段的情况。

撤回请求为共同字段加 `{action:"delete"}`，不需要 `seq`。服务端删除使用记录，并在 `apiSessions` 保存终止标记；后到的追加返回 410，重复删除成功，重新同意必须创建新凭据。此路由不修改 `feedback`、`listeningSessions` 或 `weeklyMetrics`。

完成定义为覆盖当前音轨时长至少 90%；跳到结尾不算听完。服务器校验覆盖区间、累计单调增长、收听秒数不超会话墙钟时间，并以最高 3 倍播放速率约束覆盖量。但它仍然是浏览器自报统计，不是防作弊计量或真实人数；下载统计仅表示点击，不表示文件保存成功或离线播放。

默认全局创建配额每分钟 100、每天 3000，每凭据每分钟 30 次写入，最多 50 个独立问题；可在配置里降低。进程内用随机 HMAC 盐对 IP 做临时索引（每分钟每来源 20 次建会话或 120 次写入），有大小上限且不持久化 IP。进程限流不能跨实例独立识别人，全局 Firestore 计数对各实例共同生效。固定最多 2 个实例、并发 20、15 秒超时；预算告警仍需云端另设，配额不是账单上限。

## 验证与管理

```sh
npm ci --ignore-scripts
npm test
```

测试用事务适配器验证写后再读约束、赞踩替换/撤回、独立问题、重试/乱序、统计覆盖和撤回、来源/正文/时间校验、限流；不冒充线上 Firestore 或浏览器端到端证明。依赖固定版本；`uuid` 覆盖到 11.1.1 修复传递依赖审计问题（上游只用兼容的 `v4()` API）。

管理员使用 ADC/IAM 权限运行，不提供公网管理路由：

```sh
GOOGLE_CLOUD_PROJECT=ai-for-god-caption-dev node admin.mjs list 2026-08-30
GOOGLE_CLOUD_PROJECT=ai-for-god-caption-dev node admin.mjs metrics 2026-08-30
GOOGLE_CLOUD_PROJECT=ai-for-god-caption-dev node admin.mjs status RECORD_ID confirmed
GOOGLE_CLOUD_PROJECT=ai-for-god-caption-dev node admin.mjs status RECORD_ID fixed AUDIO_VERSION
GOOGLE_CLOUD_PROJECT=ai-for-god-caption-dev node admin.mjs usage --from 2026-09-05 --to 2026-09-05 --out /PRIVATE/NEW_REPORT_DIRECTORY
```

`list` 一次最多显示 100 条反馈，输出为私人审阅资料，不写入 Git、公共 App 或公开日志。
