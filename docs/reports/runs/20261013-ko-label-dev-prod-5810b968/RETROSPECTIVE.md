# 韩语证道语言标签 Dev / Production 部署

- 实际范围：执行 commit 4938a7f23b4b5ac1b54629887224b0333a831c4c 的两个已准备 UI 候选，按 Dev → Production 顺序发布。仅 locales-ko.mjs 改动，使韩语页面品牌标题与 Media Session album 命名证道语言。未重跑 L1–L4 内容生产、翻译或音频。
- 结束结果：两次 guarded publisher 均退出 0、deployed，发布后租约释放。Dev bc4e94edeec02a88 → ae7dd119129a4680；Production a0b4d399c4d38e81 → 37421012eb737055。
- 耗时：Dev 收据 20:23:33.807852 至 20:24:32.365556 UTC，约 58.6 秒；Production 20:24:43.466411 至 20:24:59.457270 UTC，约 16.0 秒。未采集独立阶段计算/等待时长。
- 预检与回读：本地 Dev 731 public 文件，仅 1 文件变化、730 保留；Production 207 public 文件，仅 1 文件变化、206 保留。两侧 Hosting 配置保持原字节。线上完整 provider 清单另含 2 个 Firebase managed 文件，Dev 共 733、Production 共 209；无新增或删除，唯一变化 /locales-ko.mjs，candidate gzip hash 匹配。每站 locales-ko.mjs 与 v3/v4 catalog 全量 HTTP GET 原始 SHA-256 匹配，核验前后 live version 稳定。
- 错误：未观察到发布或回读错误，未重试。没有额外模型调用。
- 遗留状态：本机保留候选、发布及核验收据，未执行清理。来源仍为 codex/language-pickers；此次明确授权部署不代表 dev/main 代码晋升。
- 外部变化：仅上述两站 Hosting 韩语标签文件更新；未部署 API、媒体或 TestFlight。浏览器交互、Media Session 实际展示、真机播放与场地验收均 not_run。
- 后续：PR #377 跟踪代码晋升，浏览器/设备验收按需独立执行。本地执行者已填写报告，云端独立复盘待执行。
