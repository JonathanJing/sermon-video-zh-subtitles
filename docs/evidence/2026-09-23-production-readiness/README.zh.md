# 四层多语言 Production 合并前核对

核对时间：2026-09-23（洛杉矶）。范围：代码和 2026-09-20 2:58 已审样片的**本地演练**；不构成本周新整篇发布批准。

## 可复核结果

- 起点：`origin/dev` 的 `ecad7ab`；核对时远端更新到 `e3eb8d6`，仅新增 iOS CI workflow。本分支另行吸收这一更新。
- 旧 Production：`weekly.json` 仍是 9 个中文周次，`multilingual-v2.json` 为 404；使用 registry head `rel_cbd3c91f6e220482fe00acbc` 的完整 `public` 重放。
- 候选：`/private/tmp/sermon-prod-overlay-rehearsal-v7`，状态 `validated_not_deployed`；`build-report.json` SHA-256 为 `eea22c48d94e4976b3fafd44313bd3233248afc7f2e9eb16c6282dc7efe3947a`。候选共 78 个公开文件；旧站点 58 个文件中 57 个原字节保留，仅 `index.html` 按首页切换意图修改。三语正式资源新增 12 个文件，另新增阅读器和旧页入口文件。旧 `weekly.json` 不变。
- 线上基线：2026-09-24 00:14:23 UTC，以 `verify_multilingual_hosting.py --preflight-baseline` 对 Production 逐个 GET、大小和 SHA-256 核对 58 个旧文件，全部匹配。此收据只有发布前短时效力，周六须对新的完整候选重新运行。
- 部署计划：`deploy_multilingual_hosting.py` 无 `--execute` 本地校验通过，目标固定为 `ai-for-god-caption-dev` 项目的 `ai-for-god-sermon-audio` Hosting site，状态 `validated_not_deployed`。没有向 Firebase 发布。
- Firebase Hosting 模拟器：`/` 显示三语阅读器；`/pages/2026-09-20-revelation-clip/ko` 和 `/es` 深链显示对应内容；韩语界面与音轨可播放，进度到 00:06；西语界面显示西语内容；`/legacy-reader.html` 可读 9 个旧中文周次和既有 PDF/MP3/SRT 下载入口。旧 `/?week=<legacy-id>` 转入旧页，新 `/?week=<four-layer-id>` 保持在三语阅读器，兼容周更海报链接。
- 定向测试：Python Hosting/部署/核验 13 项、Layer 3 渲染与 staging 24 项、JavaScript reader 与海报路由 14 项，合计 51 项通过；`git diff --check`、JS 语法及新 Python 脚本编译通过。POC 全套 334 项、根目录全套 1,529 项（5 项跳过）在允许本机测试端口的环境通过。

## 仍待生产验收

Firebase 模拟器对本地 WAV Range 请求返回 200，故 206/Content-Range 必须在正式 Hosting 域名部署后核对。当前 9 月 20 日样片只有 Dev 发布授权与收据，不能用这份演练候选直接覆盖 Production。本周新来源、三语全文人审、三轨完整听审与同步、正式许可署名、实际 Production 部署和 HTTP/手机验收均尚未发生。发布回退仍需沿用保留的旧发行快照并在窗口内演练；Firebase 站点没有原子 CAS。
