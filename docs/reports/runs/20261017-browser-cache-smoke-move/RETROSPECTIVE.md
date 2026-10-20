# 复盘：20261017-browser-cache-smoke-move

数据见同目录 `INDEX.md`、`manifest.json` 和脱敏的 `outcome.json`。

## 结论先行

交付类型为本地浏览器代码测试。迁移前旧脚本、迁移后 `tools/development/` 新入口及旧 `scripts/` facade 均使用一次性 Chrome profile、loopback synthetic index 完成，三份结果 JSON 完全相同且 `status=pass`。仅证明指纹索引缓存的冷读、暖读和损坏离线拒绝流程，不证明整个 App 离线可用。

## 总时间

三次命令各约 1–2 秒；没有阶段 journal，不能拆分浏览器启动与执行耗时，也没有性能比较结论。

## 各层模型、耗时与速度

真实 L1–L4 模型调用均为 `not_run`；没有音频或 API 请求。模型、token、费用与速度不适用。

## 错误

三次命令退出码均为 0。结果显示 `microphoneRequested=false`、`indexRouteRequests=2`、损坏缓存被拒绝。未发现输出差异。

## 可以改进的地方

保留旧脚本入口直到文档与外部调用者完成迁移；日后若移除 facade，须先核对调用清单。

## 实际覆盖范围

执行：合成索引、真实本机 Chrome 缓存存储、断网索引路由、损坏缓存拒绝、外部工作目录 CLI 与导入对象身份。合并新的 `dev` 后，`apps/listening-web/` 与两个脚本路径在基线到合并基线之间无差异；无需重跑相同浏览器输入。未执行真实页面发布、麦克风识别或设备验收。

## 遗留状态

代码 PR #741 待检查与合并；浏览器日志留在忽略的本地 `artifacts/`，未入 Git。

## 外部可见的变化

只有 PR 和脱敏测试收据；没有网站发布或用户内容改变。
