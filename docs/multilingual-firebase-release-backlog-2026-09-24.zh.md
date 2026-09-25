# 第二片段 POC 复盘与 Firebase Release Backlog

记录：2026-09-24。Firebase release 分支：`codex/release-firebase-2026-09-24`。目标是更新真实周日 Firebase App，保留旧中文九周；界面语言可选，未发布的旧周次内容语言置灰。iOS 等现有 review 有结果后再调整；本轮不把模拟器结果当作真机验收。

## 本次正式站范围（用户 2026-09-24 确认）

正式站**暂不展示** 9 月 20 日两个三语片段，只保留九个旧中文周次。它们的标题、大纲、字幕和音频固定使用已发布的中文资源；英文、韩文、西文内容入口标为未发布并禁用。界面语言独立切换中文、英文、韩文、西文；西文界面当前有英文低频文案回退，应继续补齐。两个已审核片段继续留在 Dev，不因通过审核而自动进入正式站。自 9 月 27 日周次起，按四层流程制作三语；目前没有可宣称已完成的新周三语发布包。

2026-09-25 已从远端 `main` 的 `d85ea24e4dd6b3ec934ad4ee1faefb162c3c8dde` 构建并发布 UI-only release `rel_afda7e194e8a52cb2dfc0e61`，`build-report.json` SHA-256 为 `7b7485ca34f8cda8444d00c6d50d3091e5c37d8211807da056a055a68c9da065`。先前的 `rel_35c2bfb63b0ca64d689ceb2b` 只是发布前预览候选；两个候选的 60 个公开文件逐字节相同，正式版本另有独立构建时间和收据。正式站地址为 <https://ai-for-god-sermon-audio.web.app/>。

发布前，线上原版 58 个文件逐一 HTTP/SHA 核对通过；发布后，新版 60 个文件及全部 MP3 Range 核对通过，registry head 更新到上述 release，generation 从 15 到 16。浏览器实测九个旧中文周次、四种界面语言、三种未发布内容语言禁用、8 月 30 日旧书签深链及中文音频开始／暂停。反馈函数路由对空 JSON 的 POST 返回 `400 invalid_payload`，证明路由和校验工作；未创建真实会话或提交反馈。证据在忽略目录 `artifacts/weekly-release/ui-refresh-2026-09-24-main-d85ea24/` 的 `deployment-receipt.json`、`http-verification.json`、`production-acceptance.json`，以及 registry 对应 release 快照。设备与现场验收仍为 `not_run`。

## 已解决并保留的证据

| 问题 | 本轮处理与验证 |
| --- | --- |
| 中文回转写将“老底嘉教会／《启示录》”连读，并把“三章十六节”误写为“三底十六分” | 第 01/02 组定向修订、全文重新听审并绑定新音轨和声纹索引；其余九组音频哈希不变。见[第二片段报告](reports/20260924-laodicea-second-clip-poc.zh.md)。 |
| 韩语第 07/08/11 组语速与时长不合，模型第 10 组出现空白差异 | 新候选仅重新处理变化组，旧组按请求哈希复用；新全文、音轨和同步分别获人审。保留失败和付费响应，未把旧批准继承给新哈希。 |
| Dev 发布后浏览器拒绝新增的 `sourceMediaSha256`、`audioFingerprint` 和 `alignment` 字段 | 修复正式目录 adapter，三语各 11 组浏览器可读；169 文件 GET/SHA、Range 与短时播放已核验。 |
| 同站点声音试听更新改变了 Dev 的三个 HTML | 以当前线上 154 文件重建完整基线，再发布 169 文件版本，未覆盖新增试听资源。 |
| 两个已审片段连续构建时，候选错误地把未上线的中间产物当作线上基线 | `assemble_multilingual_hosting.py` 现可多次传 `--staged`，最终报告绑定最初的完整 Production 快照；正式核验逐页查所有已发布 locale 的深链和 Range。定向 19 个 Python、9 个 Node 测试通过。 |
| Production 阅读器把正式目录当作可缺失的 Dev POC 资源，且同日两页选择标签完全相同 | 正式模式现在要求 v2 目录加载成功，审核标签按界面语言显示；同日页面以页面标识区分，已加载页面显示其审核标题。Dev POC 仍走可选目录。 |

## 未上线的三语 Firebase 候选

忽略目录 `artifacts/multilingual-production-candidates/2026-09-24-two-clips-v3/` 保留未部署的两片段三语候选及当时的部署计划；v1/v2 是较早的本地版本，不用于发布。它以旧 registry head `rel_cbd3c91f6e220482fe00acbc` 为基线，合并 `2026-09-20-revelation-clip` 与 `2026-09-20-laodicea-clip` 两个已审核页面；旧 `weekly.json` 保留九周。候选共 93 文件，旧 Production 基线 58 文件。其 2026-09-24 的预检已过期，且正式 registry 已推进到 generation 16；将来若决定发布三语片段，必须按新基线重建候选与预检。本次正式站没有部署该候选。

Hosting 模拟器在 v1/v2 上实际打开两段的中文、韩语和西语示例页；页面选择器可切换同日两片段，第二段韩语音轨播放进度达到 00:05。最终 v3 又打开第二段西语页并切到第一段中文页。旧九周阅读器仍显示 9 个周次及 PDF/MP3/SRT 下载入口，旧 `/?week=` 转至旧页，新片段 `/?week=` 打开三语页。模拟器的反馈 `/api/session` 返回 403，因此不能据此宣称反馈后端已通过；此项要在正式发布前用适当的真实后端环境验证。韩／西文已批准字幕在若干句号后仍缺空格，修改需走新的语言 revision。

候选 `build-report.json` SHA-256：`0f706571148cb2b2cb4c67a320ce25e235cca4bafc1e177317926a51102f8ede`；线上基线收据 SHA-256：`0f6d14d69363b8f1ed7015d02bc80af7ecc0f31fe0242c8fd8ac293e477596ca`；未执行部署计划 SHA-256：`3345b05f1de8ad7b03c4ea8dbbdb28c0780ae8e9ed56744938af3e0d45b5a9d8`。这些哈希只定位本机文件，不能代替将来发布时的实时预检。

## 未完成的 Release Backlog

| 优先级 | 工作 | 完成条件 |
| --- | --- | --- |
| P0 | **周更发行与多语言首页共存**：legacy 部署入口现探测正式站 v2，发现后拒绝覆盖；显式回退要单独传参。但 registry/周更构建尚不能从多语言站点叠加新中文周次。 | 合成 fixture 证明新中文周次、两段三语页面、旧九周、`/?week=`、下载及反馈路由同时保留；其他旧式发布入口也不能静默删除 v2。 |
| 已决 | **正式内容范围**：两页合计只是 9 月 20 日的两个片段。 | 用户已确认本次 Production 只展示九个旧中文周次；两段留在 Dev。新周次按四层流程另行发布。 |
| P1 | **正式站恢复演练**：本次从 `main` 发布、实时基线、逐文件/Range 和浏览器检查已完成，旧完整 release 已保留；尚未实际执行回退。 | 在不影响周日使用的受控窗口演练回退及重新发布，分别保留 Firebase 与 HTTP 收据。 |
| P1 | **反馈真实会话回归**：Hosting rewrite 和函数输入校验已通过；尚未完成生产会话创建与反馈提交。 | 用专门标识的测试数据完成会话、反馈、查询与清理，核对 Firestore 实际写入及权限；不要把 `400` 校验回执当作完整后端验收。 |
| P1 | **西语界面文案补齐**：目前常用导航和状态已译，少用诊断和隐私长文暂用英文回退。 | 完整西语界面文案人审，静态键与运行时状态全覆盖；不得把旧中文周次伪装成西语内容。 |
| P1 | **跨页导航标题**：未打开的页面以 ID 词组区分；没有按界面语言显示已批准的完整标题。 | 从哈希绑定的页面信息生成各界面语言的导航标题；同日多页无重复、缺失时有明确回退。 |
| P1 | **单语言修订/撤回**：同 page ID 被安全拒绝覆盖，但缺版本化替换与独立回滚。 | 新 revision 与旧包并存，按 `pageId + locale` CAS 切换；只使该 locale 下游哈希失效，其他语言和页面不动。 |
| P1 | **计时与并行性**：Tracker 46/46 中只有 25 步有实测执行，21 步无执行计时。 | 每个生产任务记录开始、结束、重试、等待与共享操作，独立语言并行时能重建墙钟关键路径；不以文件时间推算。 |
| P1 | **已批准韩／西文字的排版问题**：部分标点空格仍需独立检查。 | 若改变已批准字节，创建新的 Layer 2 revision，并重做该 locale 所需的 Layer 3/4 绑定与审核；不原位改发布包。 |
| 待 review | **iOS 实机与原生阅读器**：模拟器已读三语 Dev 页并播放韩语，但阅读页与播放器尚分开；真机麦克风、噪声、耳机、锁屏、来电未验。 | 等当前 review 结果后确定范围，再单独测真机与现场；不以 Web 或模拟器结果代替。 |

## Release 分支边界

隔离工作树 `/Users/jonathan_jing/.codex/worktrees/release-firebase-2026-09-24/sermon-video-zh-subtitles` 从 `dev` 的 `74309ee` 创建 `codex/release-firebase-2026-09-24`。先带入 Web、生产脚本、Tracker、schema、测试和文档改动，没有从原始工作区复制未提交的 iOS 工作；之后合入当前 `dev`，解决 Tracker 和并行生产代码的冲突。原始工作区 `codex/release-2026-09-20-second-clip` 的未提交工作仍独立保留。

2026-09-25，release 分支的 [PR #76](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/76) 已 squash 合并到 `dev`（`aa715ac`）。进入 `main` 的 [PR #77](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/77) 经用户批准纳入 `dev` 中已有的 iOS 代码。自动评审指出 release merge 旁路和 iOS 试听未校验音频的问题；修复经 [PR #79](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/79) 进入 `dev` 后，#77 的 Python、晋升策略与完整 iOS 模拟器门禁通过，squash 合并为 `d85ea24`。随后 [PR #80](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/80) 用无文件差异的 merge commit `8393598` 将正式 `main` tip 回同步至 `dev`，并验证两者代码树一致。候选媒体、`.env` 和发布收据保留在 Git 忽略目录。两个已审核片段仍只在 Dev，iOS 上架及真机验收继续等待独立 review 和测试。
