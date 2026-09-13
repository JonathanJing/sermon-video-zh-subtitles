# 同行 App 品牌与视觉统一

品牌名称为“同行”，功能说明为“证道中文听译”，介绍用语为“一起听懂，一路同行。”。页面内的大纲统一叫“证道大纲”，避免与产品名混淆。

## 已选设计

用户选择第3款书页“同”字图标，并采用第1款无衬线字体风格。Logo 由内置 ImageGen 按选定设计图生成独立 PNG；网站使用真实图片资源，文字继续作为可访问、可选择的 HTML 文本。品牌、正文、控件共享系统无衬线字族（Apple system/PingFang SC/Noto Sans SC/sans-serif），按平台已有字体回退；没有新增字体下载。

[图标资源](../experiments/sermon-dubbing-poc/web/brand-icon.png) 用于页头、浏览器 favicon 和 Apple touch icon。源文件1254×1254像素、923395字节。墨绿、鼠尾草绿与暖白应用于图标与界面；深色页面保留暗室阅读对比，浅色底为暖白。实际手机主屏幕图标呈现仍需在对应设备检查。

页头采用图标、品牌名、副标题两行组合；手机下仍显示功能说明，主题按钮保留44像素触控区域及完整无障碍标签。页头高度68像素，正文与固定播放控件延续现场收听布局。

## 产物与验证

选定设计预览：`artifacts/sermon-dubbing/2026-09-05-tongxing-logo-options/tongxing-logo-selected-v1.png`。

本轮发布目录：`artifacts/sermon-dubbing/2026-09-05-weekly-app-v12-brand/`，appVersion `dbadc933f8bd0940`。品牌资产纳入构建哈希、上传白名单及静态服务路由；沿用现有同源图片 CSP，不扩大权限。

定向构建测试11项通过，JS语法与差异检查通过。桌面Chrome分别检查390×844深色、320×667浅色、1024×768桌面；验证图标加载、品牌字体、副标题、无横向溢出、底部控件、大纲标题、刷新恢复60秒后播放/暂停及音色页标题。截图和操作结果在本轮发布目录，视觉复核见 [design-qa.md](../experiments/sermon-dubbing-poc/design-qa.md)。

音频、周次数据与反馈API目录相对v11逐字节一致；浏览器恢复键和匿名统计偏好沿用原值。此轮不新增音频或现场同步验收结论。

2026-09-05 已部署线上并回读验证29个文件共54066641字节，全部与发布目录一致。图标响应为 `image/png`，音频 Range 返回206，CSP保持原值。线上390×844浏览器再次验证图标、标题、播放/暂停及大纲；控制台错误日志为空。收据为发布目录中的 `http-verification.json` 与 `live-gui-verification.json`。

## 作者署名（2026-09-05）

页面页脚使用现有淡色文字显示 `© 2026 Jonathan Jing · 应用设计与开发`，姓名与仓库 LICENSE 一致。HTML 同时包含 `author`、`copyright` 元数据和文件头作者注释；版权说明区分应用代码与原始证道/媒体。

署名发布目录：`artifacts/sermon-dubbing/2026-09-05-weekly-app-v14-author/`，appVersion `4402af8cb076be64`。仅 HTML 和版本标识变化。线上 HTML、版本、播放器代码与样式哈希已核对；390px Chrome 页面检查署名可见、无横向溢出、无播放器遮挡。
