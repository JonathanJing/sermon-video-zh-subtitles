# Firebase 目录类别与 Beta 测试准备

本轮接续 PR #261，将仅有两个旧页面 ID 的类别兼容显示扩展为 Firebase 目录可选 `displayCategory`。类别使用独立嵌套版本 v1 和多语言 labels；外层目录 v2/v3 保持兼容，不占用另一个 PR 的 v4 协议。以后新增类别只需目录数据，新能力仍须先进入一次原生 Beta 构建。

## 已验证

- `abc51167`：Xcode 27.1（27A9269）TongxingBeta / BetaDebug，iPhone 18 Pro / iOS 27.0；1 项 hosted App 测试与 3 项 UI 测试全部通过，0 failures。测试分别覆盖未选篇缓存类别更新/移除、旧目录三项分类、四种新页面类型中英文显示和同进程目录刷新保留暂停状态/位置。UI 夹具使用未知页面 ID，避免已知 ID 规则掩盖远程字段缺失；内容和音频是合成静音数据，不代表实际证道或真机听感。
- 最新 Core 定向测试 18 项通过：两条目录投影都保留类别；未知新类别、语言 fallback、来源/targets 哈希保持、无效版本/控制字符/超长标签/缺少 en 被拒绝，模拟内容不被类别声明晋升。最后补充 zh-SG→zh-CN 显示兼容断言。
- Python 新工具 8 项 + 既有目录构建 4 项通过。最后将输入读取改为一次读取，SHA 回执与实际使用字节相同；未安装额外依赖。
- 通用 Simulator build 完成；最后的 zh-SG alias 补充再次 build 验证，具体退出状态见下述独立运行证据。UI 测试对应 abc51167，之后只有上述 alias/定向断言、工具一次读取及文档差异，未改变已测 UI 路径。
- 独立只读审核 abc51167 的 12 个文件未发现 blocker，最终增量另行复核。机器结果不代替人工截图或真机验收。

## 证据

本地证据保留，不上传凭据或运行输出到 Git：

- 首次 build：`/tmp/tongxing-remote-category/20261006T223708-build-52f09e06/`
- 正式交互与 hosted 测试：`/tmp/tongxing-remote-category-final/20261006T224006-test-d189ed07/test.xcresult`
- 最新 build 与 status：`/tmp/tongxing-remote-category-final/` 内唯一后续 build 运行目录
- 中文四种类别、英文四种类别、同构建刷新前后截图：`artifacts/tongxing-ios/20261006-remote-categories/screenshots/`
- 原始 Dev v3 目录 SHA：`7388b9cd6ff65fc77c871715f3cf691a8ff308a569fabaa21ec900b8271d7fd1`
- 类别候选目录 SHA：`b776c2c4ddc68870af2284ea0e476e66354d08747a79afadbc4935816743b3b1`，仅为最近两篇证道和播客添加类别；其余字段、顺序、generatedAt、sources、targets/发布包哈希不变。候选及工具回执保留于同一忽略目录，`deployed:false`。

## Beta 与发布边界

已准备 [数据契约、更新命令及 Beta 测试步骤](../ios-page-display-categories.zh.md)。四类为正式播放版、YouTube 版、播客和自定义类别。关键验收是在同一 Beta 版本/build 中更新目录，再刷新看到类别变化；同时保持暂停位置、字幕与音轨语言。旧字段缺省与离线使用最近缓存也要在真机验收。

本轮未部署 Firebase、未上传新 TestFlight、未合并 PR，当前已安装 Beta 仍没有新字段读取能力。真实 Dev 候选与四类模拟器数据分开记录，不把模拟器夹具发布成正式内容。网页布局 `not_applicable`；若后续采用 v4，须在对应 schema 和投影中保留该展示字段，再做那一协议的验证。
