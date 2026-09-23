# 9 月 20 日三分钟片段四层 Dev 流程实测

状态：进行中。本文记录 2026-09-23 的真实片段尝试和门禁，不把机器候选、旧中文资产或 Dev POC 当作正式四层发布。

## 来源和选段

- 原始来源：Mariners 完整礼拜录像，`sourceId=7c193fd4-bc90-4f3b-aa00-37dfe8423aa0`，文件 SHA-256 `728f864e92ea08dbce249249369016e0fee47950ec4e6dcb60cd6d83185e8caf`，`ffprobe` 时长 4567.296067 秒；原人工证道范围为 29:49–1:02:09。
- 最终候选选段：原录像 **35:09.16–38:07.32**（证道相对 5:20.16–8:18.32），持续 178.16 秒。截取视频位于忽略目录 `artifacts/multilingual-clip-20260920/20260920-blocks9-14-178s/source-clip.mp4`，实测 178.178 秒，SHA-256 `c931d6f716bd30b9ba9b75ca6cbc9a4f4fd708b8bf8f8e3668187e67bac44c30`。
- 用户已在本对话确认该片段的精确窗口、英文完整性、词时间和句界；审核清单的“原录像时间”列曾多加 5:20.16，修正为 35:09.16–38:07.32 后，用户再次明确确认原批准仍适用。底层英文及 MFA 时间未改。窗口与英文收据分别位于忽略目录 `review/clip-window-approval.json`、`review/english-source-human-review.json`。

## 四层进度

| 层 | 已得到的实证 | 当前门禁 |
|---|---|---|
| Layer 1 | Spark MFA 对齐该连续片段，42 句、511 词；`clause_stable_v2` 生成 45 单元、0 个锚点结构问题。独立 GPT 机器裁判 42/42 句通过，`approved_for_layer2_shadow`；窗口和英文人工收据已绑定。 | 最新 English Source Package 为 `ready_for_translation`、`translationEligible=true`；JSON SHA-256 `4d645ff0aad0b55b2eb913fd0749ebcb3bed010ddfc037e89e1f8a98f44a227b`。这只放行 Layer 2，不授予下游审核。 |
| Layer 2 | `zh-Hans`、`ko`、`es` 已在正式 Layer 1 哈希 `4d645ff0…` 下重新生成三语 shadow，逐语言 45/45 单元独立机器语义复核通过；用户对三份逐句审稿页回复“批准”，内容审核分别绑定候选哈希。 | 正式语言策略、插件及分组 producer 尚未齐备；shadow 收据保留 `formalLayer2Admitted=false`，不能直接产生 `human_translation_approved`。 |
| Layer 3 | 尚无本片段同语言正式音频包。 | 用户要求三语音频全完成后才发布 Dev。只接受同 locale 已正式批准文字；韩／西语 voice 仍为 POC 能力，不得标为已审自然配音。 |
| Layer 4 | 尚未构建本片段 Release Package，也未发布 Dev 页面或取得 HTTP/设备证据。 | 同 locale 文字、Layer 3 包及页面审核状态必须先满足门禁。Dev POC 可单独标为机器预览，不能称四层正式完成。 |

## 发现的问题与处理

1. **MFA 缓存链接上传失败（已修复代码）**：Spark tar worker 只接收普通文件；本地缓存音频为符号链接时，传输把链接本身写入 tar，远端报 `Unexpected transport member`。`mfa_spark.py` 现对上传文件先解析真实路径，定向测试覆盖链接输入；真实 MFA 重跑成功。
2. **首选开场片段安全切点不足（已换选段）**：29:49–33:05.16 的 196.16 秒连续候选有 2 个长单元，分别为 13.17 和 10.52 秒，均无现行 ≥0.35 秒或标点支持的内部安全切点，故 Layer 1 `waiting_anchor_review`。证据保留在 `artifacts/multilingual-clip-20260920/20260920-opening-196s/`；未调大阈值绕过门禁。
3. **片段 POC 语言集合原先固定四语（已修复 Layer 2 入口）**：`generate_multilingual_fragment_poc.py` 现可重复传入 `--target-locale`，本次仅选中文、韩语和西班牙语；默认四语保持兼容。该脚本仍是机器 shadow，不是通用正式 producer。
4. **西班牙语策略原先缺失（已建立 pending 草案）**：新增 `config/target-language-policies/es.json`，冻结译者／复核者、术语来源、语言检查和断句规则的身份；用户后续选定 `RVR1960` 和中性拉美语体，引用许可、术语译名及插件实现仍 pending，`productionPolicyReady=false`。
5. **历史中文 cue 不能直接复用（待新排程）**：所选六个区块中，旧中文 cue 末尾相对最后英文词全部提前超过 2 秒，3 个区块超过 5 秒。这是对旧页面的诊断，不能推断新音频已经失败；Layer 3 必须以批准的完整译文和自然语速重新测量、排程、听审。
6. **Dev 演示页原先固定单页及六句音频（部分修复）**：`firebase/dev/public/app.js` 原先把路由固定到 `2026-09-20-lion-of-judah-poc`，只读取默认页；现按 catalog 的 pageId 路由、切换周次，若音轨缺席会清空旧音频并隐藏播放器。`weekly.json` 和 fragment 打包器仍假设各语言有 MP3；本次用户要求三语音频齐备后发布，不能靠替换旧六句 POC 覆盖旧页。
7. **中文语义复核失败（修正规则并重跑）**：首轮 `block-10-u009` 把英文 “away from the Word” 写成“偏离真道”，独立复核判 `completeMeaning=fail`，指出应明确“神的话语”；韩／西语首轮机器复核通过。首轮候选和收据保留在 `layer2-shadow/`；v2 翻译政策明确该指向，逐单元机器复核 sidecar 记录失败 ID 和原因，输出使用新目录。机器通过仍不等于人工文字批准。
8. **审核清单时间基准偏移（已修正并复核批准）**：英文锚点用证道相对时间，初版审核表将该时间再加到片段绝对起点，导致首句错误显示为 40:29.32。审核表现正确显示 35:09.16；末句 38:03.75–38:07.32。用户复核并确认原人工批准适用于更正表。以后生成审核表须用 `原录像时间 = 29:49 + 证道相对时间`，或 `片段时间 = 证道相对时间 - 5:20.16`。新增 `verify_clip_review_timeline.py` 并对真实 45 行通过检查，测试覆盖旧错误值。
9. **Layer 1 shadow 收据的人审状态滞后（已修复代码）**：正式 English Source Package 已记人工批准，但外层 shadow 收据原写死 `humanReview=pending`；现从包内审批字段派生，重建后为 `approved`。
10. **Layer 4 纯文字包门禁不一致（已修复代码）**：先前 catalog 构建器只接受 `audio_unavailable` 时音频包哈希为 null，无法承载正式四层所需的同 locale Layer 3 包；现在验证该包的来源、候选、locale 与无音频资产状态，旧 null 路径必须显式打开迁移开关。iOS Core 同步接受已绑定的哈希。
11. **Layer 1 包路径敏感（待合同修订）**：外层 shadow 脚本的代码 SHA 改变会改变其输出目录，进而改变英文包中 anchor artifact 的绝对路径和英文包 JSON 哈希，尽管锚点内容哈希未变。本次在修正外层 `humanReview` 后以最终 `4d645ff0…` 身份重新生成三语草稿；通用生产应将稳定逻辑身份与临时运行路径分开，避免无意义的跨语言失效。
12. **正式 Layer 2 与 Dev 消费端仍缺迁移（待实现）**：已生成的三语片段 shadow 使用 POC policy 和单个 45 单元组；正式候选验证实际拒绝三语，首个错误均为 `Target text differs from utterances`，因为该版以空格连接 45 单元，而正式合同要求组内文本与 utterance 精确相合。已修正后续 shadow producer 为每源单元独立 group，保留西语词界及逐单元机器复核证据；现有三个候选及用户对其内容的审批哈希不改、不重标。正式策略、语言插件和逐组人工收据仍须重建；Dev Web 的 demo catalog 与正式 v2 catalog 不同，亦需适配后发布。
13. **经文版本授权（待凭证核对）**：用户选定韩语 `개역개정`、西语 `RVR1960` 和中性拉美语体，并说明持有两版使用许可、稍后提供凭证。韩国圣书公会[版权 FAQ](https://bskorea.or.kr/bbs/board.php?bo_table=copyright_faq&wr_id=8)称即使非商业、只引用少量经文也须申请批准；美国圣经公会的 [RVR60 权利说明](https://www.americanbible.org/rights-and-permissions/)对 App 电子使用及音频使用要求书面许可。收到凭证后须核对权利主体、App／音频范围、署名及期限，并绑定到策略；此前不能以口头持有代替可审计凭证放行逐字经文。
14. **Dev POC 多页／无音轨路径（已修复本地代码，未发布）**：Web 路由改为按 catalog 的 `pageId` 选择页面，周次选择可切页；无音轨时清空旧音频、隐藏播放器并明确显示仅文字状态。本地 HTTP 浏览器 fixture 验证了从旧页切到第二个 `pageId`、URL 和标题更新、播放器隐藏；同时发现并修正了仍写“字幕随当前音频更新”的误导提示。fixture 只验证交互，不含本片段正式文本或音频。新片段仍须等正式上游及三语音频验收后才能发布。
15. **三语音色的正式能力不足（待听审）**：现有 Speaker Voice Registry 中 Eric 的用途只有 `chinese_dubbing` 与 `multilingual_voice_demo`；韩语、西语 locale 状态为 `unverified_poc`、机器筛查通过而非母语听审。正式 speech-job 对韩／西语还要求 `multilingual_dubbing` 授权用途和 `human_reviewed` 能力。用户已选继续审核 Eric 克隆音色的韩语、西语能力；未因该选择就改写注册表能力或正式用途。
16. **正式 Layer 2 producer 缺口（已建入口，待真实运行）**：新增 `produce_target_language_candidate.py`，从 `ready_for_translation` 英文包和正式单语言策略冻结完整源单元请求，随后只接受独立翻译、机器复核与 locale 插件逐组证据，输出仍为 `machine_review_pass_human_review_pending`；人工批准仍走独立 worksheet。三语当前策略均未 ready，因此该入口在本片段 fail closed，尚无正式候选。
17. **Eric 韩／西语长句探针（机器问题待人耳判定）**：用户已批准既有 v2 短样音，收据绑定两条 MP3 哈希，但未升级正式能力。另从本片段四个已审、非逐字经文单元生成韩语 19.20 秒、西语 18.56 秒的克隆音色探针；两条 WAV 哈希相符、单音轨且完整解码。Qwen3-ASR 回转写相似度韩语 `0.939759`、西语 `0.982759`，分别把 `씨름하는` 识别为 `실험하는`、`Éfeso` 识别为 `Efsol`。需人耳判断是发音还是识别错误，长句听审页位于忽略目录 `review/voice-capability/index.html`；探针状态是 `not_release`，不能充作正式 Layer 3 音轨。
18. **中文直接经文边界（人工批准）**：固定 CUV 库为启示录 2:4 和 3:4 提供精确短句节选，已与本片段英文单元建立建议映射并记录库哈希；3:4 引文跨数个英语单元。用户批准两处边界与改文，重复解释句暂按讲员重述处理。忽略目录 `review/layer2/zh-Hans-scripture-boundary-approval.json` 以提案与正式 Layer 1 的规范化 JSON 哈希绑定该批准；逐单元差异稿 `review/layer2/zh-Hans-scripture-revision-draft.json` 保留原 shadow 身份并把 3:4 精确节选分配到 `block-14-u002`–`u003`。原提案的 `humanBoundaryReview=pending` 保留历史状态。该批准不等于修改后的整篇中文候选获批，也不覆写原 shadow 文本。
19. **Firebase Dev 新页面深链（已修复本地配置，未部署）**：本地 HTTP fixture 从首页切换新 `pageId` 成功，但对新 URL 直接 GET 返回 404；检查发现 `firebase/dev/firebase.json` 的 Hosting rewrite 只匹配旧六句 POC。已改为 `/pages/** → /index.html` 并加配置测试。Firebase 上实际深链加载仍需部署后的 HTTP 检查，静态配置测试不能代替。
20. **远端 Dev 基线变化与集成（待合并）**：核对远端 `dev=22adda5`，比原基线 `8ec18e6` 新增播放器完整性与移动端导航 PR #41。已在该版 Dev 的独立工作树 `/private/tmp/sermon-sep20-dev-ready` 移植通用 pageId 路由、无音频界面、`/pages/**` rewrite，同时保留下载 SHA 校验、对象 URL 与播放记忆；修正旧测试对重构前代码位置的断言，并要求无音频内容状态与 release 匹配。定向 Python 测试 59/59、Node 完整性测试 4/4、Swift catalog 测试 5/5 通过；具备本机权限的完整 Python 套件 1390 项通过、3 项跳过。另以占位第二页的本地 HTTP fixture 直开 `/pages/<new-id>/ko` 得到 200，浏览器实际显示韩语内容和“仅文字 · 无此语言音频”，播放器未出现；这不代表本片段已上 Dev。尚未运行线上 HTTP／设备验收，正式 v2 发布包到 Dev demo v1 的适配仍缺。先前提交因缺明确授权被自动审批拒绝；用户随后明确授权提交、合入 Dev 并继续到三语音频齐备后的页面发布。本报告写入时尚无本轮 commit、push、PR 或 Dev 部署。

## 下一步验收

1. 将已审三语 shadow 内容经正式策略、语言插件及分组 producer 重建为可逐组批准的候选；待经文使用方式确定并取得所需许可或改用独立转述。现有内容批准绑定原候选，重建后不得自动移植批准状态。
2. 对三语言生成正式同 locale Audio Package；完整解码、回转录筛查、全文听审和同视频同步检查均须留证。用户要求三语音频齐备后再发布 Dev。
3. 构建逐 locale Release Package，发布到 Dev，逐文件 GET/SHA、音频 Range、App 目录和真实设备播放分别留证。

## 本轮验证

- 本地浏览器通过 HTTP fixture 切换两个 `pageId`，在第二页观察到 URL／标题更新、无音轨播放器隐藏和纯文字提示。fixture 使用旧 POC 文本占位，未验证真实片段发布。
- 最新 Dev 基线的 Python 定向测试 59/59、Node 完整性测试 4/4、Swift catalog 测试 5/5 通过；`git diff --check` 通过。完整 Python 套件在沙箱内因 `ps` 与 loopback 权限报错；使用本机测试权限重跑后 1390 项通过、3 项跳过，日志在 `/private/tmp/sermon-sep20-dev-ready-full-tests.log`。
- Eric 长句探针实跑：Spark 使用已登记 checkpoint SHA `75d28ce6…`，输出两条 WAV；本地 SHA、`ffprobe` 单音轨／时长及 `ffmpeg` 完整解码通过。ASR 只作机器筛查，重点差异已交付人耳复核。`screen_multilingual_voice_demos.py` 改为允许只有选定 locale 的 manifest，避免对非越南语短探针强制要求 `vietnamese-manifest.json`。
- 已检查代码和本地页面，尚无本片段正式音频、Release Package、Dev HTTP 或实体设备验收证据。
