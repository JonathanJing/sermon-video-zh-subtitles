# 复盘：2026-10-14 每周海报模板 v2

数据见同目录 INDEX.md、manifest.json 和脱敏 summary.json。

## 结论先行

- 高置信结论：模板 `tongxing-dual-qr-v2` 的中、韩、西三语海报及手机预览共 6 张 PNG 均与已确认预览哈希一致，二维码验证通过，22 项定向测试通过。
- 证据边界：本轮状态是 `validated_not_published`，`productionSiteChanged=false`；没有线上替换、真机扫码、设备播放或场地验收证据。
- 处置建议：本报告可在同步最新 `dev` 并确认检查保持绿色后转 Ready／合并；任何实际发布须另行运行并留证。

## 实际覆盖范围

本轮只验证 2026-10-11 页面 `resi-20261011-54475d42` 的固定海报模板。它使用已有发布包、原主视觉和官方徽章重渲染中、韩、西三语海报及手机预览；没有重新执行 L1–L3 内容生产，也没有改动生产站点。模板身份为 `tongxing-dual-qr-v2`，被测提交记录为 `70cbefa6601e271dfcb2ab7edf3e980097b894f9`。

## 结果和结束信号

`summary.json` 的最终状态为 `validated_not_published`。三个 locale 各有海报和手机预览，共 6 张 PNG；每个 locale 的 `qrValidation=pass`，每张图与已确认预览的 SHA-256 一致，`matchesApprovedPreview=true`。定向海报测试 22 项通过。报告没有 `outcome.json` 或进程退出码，因此不能补写未导出的结束信号。

渲染器使用 AppKit 系统字体，标题 bold、正文 regular；CJK／Latin 字形回退记录在 summary.json。官方 App Store 徽章沿用 Apple SVG，未重绘。海报底部的 AI 内容和独立项目免责声明仍保留；本轮没有改变发布包与页面的机器质检状态。

## 耗时

本报告没有导出 `timings.tsv`、journal 或起止时间，无法可靠给出总耗时、阶段耗时、等待时间或与上一轮的性能比较。不得从 22 项测试通过推断渲染速度改善。

## 错误

已导出的 summary 没有记录渲染、二维码或定向测试失败；最终状态为 `validated_not_published`。原复盘记录 `git diff --check` 通过。报告没有导出原始日志，因此只能确认已汇总检查通过，不能断言未导出的环节从未出现过错误。

## 占用资源之后才暴露的错误

本轮证据只记录本地海报重渲染和代码验证，并明确没有新的模型调用。由于没有阶段 journal 或资源占用记录，无法进一步拆分预检、渲染和测试的资源时间；已导出 evidence 中没有资源占用后才暴露的错误。

## 遗留状态

manifest 记录源运行目录中有 6 个 JSON 和 6 个 PNG 未复制，公开报告只保留脱敏 summary 及哈希。`productionSiteChanged=false`，没有由本轮产生的生产站点变更。报告没有导出远端 job、构建号或清理收据，所以这些项目除本轮明确未执行的发布外均不作额外完成声明。

## 外部可见的变化

生产站点变更为 `false`，本轮没有再次上传海报或执行生产部署。真机扫码、设备播放、TestFlight 和场地验收均为 `not_run`；用户确认本地固定模板不等于这些外部验收已完成。`humanApproval` 未由 summary 单独记录，本报告不把模板确认扩展为内容人工批准。

## 后续

维护者在 PR #405 跟踪模板代码评审。若决定实际替换线上海报，应以新的发布运行单独记录上传、HTTP 读回、实际 App 显示和真机扫码；不得把本地哈希与二维码验证直接写成已发布。
