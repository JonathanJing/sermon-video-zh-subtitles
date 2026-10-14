# iOS 页面类别由 Firebase 目录驱动

本变更将日期下方的类别作为目录页面的可选展示元数据。它不是内容审核状态，也不改变音频、字幕、来源、发布包及其 SHA-256。新增嵌套版本 `sermon-page-display-category-v1`；外层目录继续使用 `sermon-multilingual-catalog-v2`、`v3` 或 `v4`，不改变现有播放器和生产层契约。

## 数据契约

权威定义：[sermon-page-display-category-v1.schema.json](../schemas/sermon-page-display-category-v1.schema.json)。v2/v3/v4 schema 内嵌相同定义，以兼容现有无需外部 resolver 的校验器；定向测试保证定义一致。

在目录 `pages[]` 内添加可选 `displayCategory`：

```json
{
  "schemaVersion": "sermon-page-display-category-v1",
  "labels": {
    "zh-Hans": "正式播放版",
    "en": "Archive"
  }
}
```

`labels` 有 1–16 个语言键，键遵循目录 locale 格式，必须提供 `en` 兜底。每个标签为 1–48 个 Unicode 码点的单行纯文本，不能全为空白、包含控制字符或换行分隔符。标签作为原生文本显示，不解释 HTML。对象不接受额外字段。无需定义新的类别枚举；新增类别直接提供标签。

| 页面类型 | `zh-Hans` | `en` |
| --- | --- | --- |
| 证道正式音频 | 正式播放版 | Archive |
| YouTube 来源版本 | YouTube 版 | YouTube |
| 播客 | 播客 | Podcast |
| 新的自定义类型示例 | 研读材料 | Study material |

App 按界面语言选择标签：精确 locale → 简体中文 `zh-CN` / `zh-Hans` / `zh-SG` 等价匹配 → 基础语言 → `en`。缺少该字段时继续使用既有兼容显示规则；旧 App 忽略新增可选字段。因此此能力需要先发布一次支持该字段的新版 App，此后修改类别数据并刷新目录即可，无需为每个类别重新构建。旧版 App 不会因此获得新类别显示能力。

## 离线准备目录

先从已核实的 Firebase Hosting 目录准备输入快照；本工具不下载、不部署、不修改审批，不读取或重写发布包。创建以页面 ID 为键的更新 JSON，例如：

```json
{
  "resi-20261004-69ba7a66": {
    "schemaVersion": "sermon-page-display-category-v1",
    "labels": {"zh-Hans": "正式播放版", "en": "Archive"}
  },
  "if-i-had-more-time-jesus-is-worthy": {
    "schemaVersion": "sermon-page-display-category-v1",
    "labels": {"zh-Hans": "播客", "en": "Podcast"}
  }
}
```

从仓库根目录执行（使用已安装 `requirements.txt` 的 Python 环境）：

```sh
python scripts/update_catalog_display_categories.py \
  --catalog artifacts/catalog-input.json \
  --updates artifacts/category-updates.json \
  --output artifacts/catalog-category-candidate.json
python -m unittest discover -s tests -p test_update_catalog_display_categories.py -v
```

工具校验输入和输出 v2/v3/v4 schema，拒绝未知页面、重复 JSON 键、非有限数值（NaN/Infinity）、重复页面 ID、无效默认页面、无效标签以及已存在的输出文件。仅更新指定页面的 `displayCategory`，包括 `generatedAt`、页面顺序、targets 与所有哈希在内的其他数据保持不变；输出的目录文件 SHA-256 因展示元数据变化而改变。stdout 回执记录输入/输出哈希、页面 ID 和 `deployed: false`，不表示 Firebase 发布完成。

工具每次只处理一个目录文件，不自动生成或同步其他版本投影。部署同时存在 v4/v3 时，App 优先读取 v4；仅改 v3 不会更新有效 v4 的类别。应分别对当前 v4 和人审 v3 投影的共同页面使用相同类别更新（每份 updates 仅包含该目录已有页面），核对共同页面的类别一致、各自非类别数据与发布包哈希保持，再将两份候选纳入同一 Hosting 发布快照。v4 独有的机检页面不应加入人审 v3 投影。

确认候选目录差异后，通过现有 Hosting 发布流程更新目录，并单独核实 HTTP 读取内容、缓存刷新和 App 显示。不要为标签变化重新生成证道或重签发布包。该 PR 不自动部署到 Dev 或 Production。

回滚时以 `"页面ID": null` 生成新的候选目录，移除可选字段，使新版 App 回到兼容显示规则；这不是强制隐藏旧版类别。原始输入快照保留，工具不覆盖它。

## Beta 验证

1. 安装含本能力的 Beta，刷新目录，打开选篇列表。分别检查正式播放版、YouTube 版、播客和自定义类型；标签在日期/讲员下面。页面主标题处类别应一致。
2. 用同一 Beta 读取第二份目录快照，仅将自定义标签改为“研读材料（更新）”，刷新后确认新文本出现，App 版本和 build 不变。记录两份目录哈希、Beta 版本/build 和截图，证明变化来自数据。
3. 中文界面检查 `zh-Hans` 标签；英文界面检查 `en`。缺少其他语言时应显示英文兜底，不影响内容语言选择、播放或字幕。
4. 不带 `displayCategory` 的旧目录继续可读；移除字段后回到兼容显示。未知新类型只需新标签，不能伪造审核或离线可用状态。
5. 验证切换页面、播放/暂停和离线缓存；类别刷新不能改变当前播放位置或已有内容/音频身份。离线时使用最近缓存目录，联网刷新后再验更新。

合成 UI fixture、Xcode build、模拟器交互、Firebase HTTP 读取与真机 Beta 验收分别记录。截图不替代真机播放或后台验收。网页布局本次 `not_applicable`；本次修改的是原生 App 消费的目录展示字段。
