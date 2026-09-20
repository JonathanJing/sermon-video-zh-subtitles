# 界面语言与讲员音色

顶部语言按钮切换中文／英文界面，保存到当前浏览器的 `sermon-audio-locale`。字幕卡保留独立的双语对照按钮。切换界面只刷新文字，不重载音轨、不跳转、不清空反馈表单，也不重建声音定位会话。

中文模式按现有中文 cue 显示；英文模式使用同一来源已冻结的英文段落，全文按关联 block ID 合并，时间按钮指向这一段首条中文 cue。英文可能来自自动转写，按中文音频的段落提供参考，不是逐词对齐。缺少来源英文时明确提示，全文保留相应中文，而不从中文回译冒充原文。

## 语言文件

- `web/i18n.mjs`：语言注册、浏览器偏好、插值、缺键回退和变更通知。
- `web/locales-interface.mjs`：导航、按钮、弹窗和无障碍标签。
- `web/locales-app.mjs`：播放、恢复位置、音色等动态提示。
- `web/locales-feedback.mjs`：反馈、匿名统计和声音定位状态。
- `web/content-locales.mjs`：当前八期标题、摘要、大纲、反思及来源说明的英文呈现，使用精确原文字串匹配。英文摘要等明确标为 AI 译文；不改变 canonical ID、音轨、时间轴、审核状态或原英文 transcript。

新增语言时，在三份界面字典注册相同 locale 和稳定 key，补齐内容 sidecar，并将顶部两语言按钮扩展为语言菜单。缺少 key 回退中文，缺少内容译文保留原文并记录 `contentLocalization.fallbackPaths`。配音语言、界面语言、字幕对照是独立能力；新增界面语言不会自动生成该语言音频。

## 音色示例

页面用简短说明介绍“授权英文参考 → AI 合成中文 → 检查与试听”，详细步骤可展开。每位讲员分别有英文原声和中文 AI 示例，标注示例时长与已有试听状态。Eric 使用独立文稿，其余五位使用同一篇文稿，不作同文案比较的假设。

2026-09-14 检查发现当前公开目录缺少 `voiceBank`；历史素材仍在。六位讲员的恢复输入为本地忽略产物 `artifacts/sermon-dubbing/voice-bank-recovery-20260914/speaker-bank-six.json`，导出的 12 个 MP3 及 catalog 对象位于其 `exported/`。中文样片复用已接受哈希；Eric 英文仅由现有 WAV 转码，未重新合成。

构建继续使用显式 `--voice-bank` 输入。正常周次合并会保留已有基线音色库；恢复缺失基线需显式音色库更新，不放宽周次合并的声音素材保护。

2026-09-14 按用户授权发布到现有 [Firebase 站点](https://ai-for-god-sermon-audio.web.app/)，Hosting 版本为 `4dad2d0ac6e4d5b8`。保留原有八个讲道页面、媒体、下载和定位索引；恢复六位讲员的十二段试听，并将已核验 API 运行源码保持不变，只同步讲员允许列表和原有来源兼容。发布包及证据保存在忽略目录 `artifacts/sermon-dubbing/2026-09-14-ui-english-voices-release/`：`http-verification.json` 核验全部 51 个文件和 MP3 Range，`api-source-verification.json` 核验实际部署源码及六位讲员列表。已登记新的周次发布基线，后续周次更新可保留这次界面与音色库。

## 验证

```sh
node --test experiments/sermon-dubbing-poc/web/*.test.mjs
.venv/bin/python -m unittest discover -s experiments/sermon-dubbing-poc -p 'test_build_weekly_app.py' -q
.venv/bin/python -m unittest discover -s experiments/sermon-dubbing-poc -p 'test_weekly_release.py' -q
git diff --check
```

网页测试覆盖播放位置、异步加载、分组时间关联、偏好存储、主题加载时序、反馈状态和采集中切换语言。浏览器另查中文／英文、主题、历史周次、大纲及 12 个音色媒体的加载。手机宽度检查不等同真实设备或场地验收。

发布后在 Chrome 实际播放约 13 秒，确认播放中切换语言没有重置或暂停，十二段试听均加载成功；本次没有重做真实手机后台播放或现场声学定位验收。
