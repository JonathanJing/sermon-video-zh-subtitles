# v4.1 本地网页接入验证 · 2026-09-05

v4.1 Q5 已接入原 POC 的模型选择、启动、麦克风会话和字幕链路。使用 [实验入口](http://127.0.0.1:4173/?translationProvider=milmmt-v41-mlx)，具体操作与停服命令见 [运行说明](../MILMMT_V41_LOCAL.zh.md)。此报告描述本次运行，不保证未来服务健康。

## 代码与模型

开始时核对了实际监听进程、所有本地 worktree、最新远端分支和 POC 提交；实际服务来自主仓库 `experiments/local-live-poc`，不是旧 iOS 设计 worktree。开始基线为 `main@1e7b480`；验证期间其他工作将 main 更新至 `0a9c5d4`（工作流日志 PR #16），该提交不修改 POC。以下实机证据采自当时尚未提交的工作区；发布准备将相同实现复制到独立分支，并核对文件哈希。后续代码合并不扩大本报告的验收范围。

原 ASR 与 Vite 进程保持运行，Gateway 在无活动会话时由现有 supervisor 重载。网页按钮已真实启动主仓库的独立 MLX 进程，替代此前指向 iOS worktree 的实验服务入口；原 Q8 仍为普通页面默认项。

- 模型：`milmmt-sermon-v41-experimental-mlx-q5`。
- 权重 SHA-256：`6057e793922b8aa0c30c5180b490d8e5cac14a3dcd1a000b1b906d0da8fa6987`。
- 冻结包清单 SHA-256：`5f313eadf8951eb3251056686fee965feae3d189b2a6cbe844118982d0d27179`。
- MLX 0.32.2 / mlx-lm 0.31.3；固定 A0、无上下文、greedy、512 tokens、无 special-token 编码、EOS `[1,106]`。

模型权重、已冻结评估数据和默认模型配置均未变更。实验会话持久化 provider 与 runtime identity v2，禁止 LAN/Firebase 发布；旧 Gateway、伪造绑定和不匹配握手不能放行实验 PCM。模型失败不会停止独立录音，也不会自动换成 Q8。

## 本次验证

| 路径 | 实际结果 |
|---|---|
| 完整 `npm test` | 43 项前端、164 项后端单测、24 项集成、5 项 Firebase 本地规则测试及 Vite build 全部通过 |
| 独立模型服务测试 | 21 项通过，使用 fake engine；真实模型启动另由网页验证 |
| Gateway → 实际模型 | `God loves us, and he calls us to love one another.` 返回「神爱我们，也呼召我们彼此相爱。」；响应模型与权重哈希正确 |
| 原始证道文件 PCM → ASR → v4.1 | 1 倍速 45 秒、450 帧，17 条 ASR final / 17 条 translation final / 17 条 caption.display；无失败事件、队列排空，所有录音/PCM/WAV 哈希检查通过 |
| Chrome 实际麦克风控制流程 | 内置麦克风录音 17.55 秒、18 个恢复音频块、174 帧 PCM；录音时模型锁定，停止后 completed，录音/PCM/WAV 哈希均匹配，WebM 可解码 |
| 网页模型切换与布局 | 从网页启动 v4.1；停止后可切回 Q8，再选 v4.1；默认窗口与 900px 窗口布局检查通过，900px 无横向溢出；临时窗口尺寸已恢复 |

文件回放来源为直接下载的 [2026-08-09 证道](https://www.youtube.com/watch?v=0SMeXJXsqKM)，原片 1906–1951 秒，位于已有人工批准的 1876–3866 秒证道窗内。原始 M4A SHA-256 为 `5af241408951b17c1c97532b4f8a4aaefe5b84e155fb970fddad00362e024c72`；本次 16kHz mono PCM16 WAV SHA-256 为 `2ba2651b0ce6e38bb25541a58c98442da426238de9085c615d83ac0263579c22`。

原声回放会话为 `20260905T195914.428Z-58a557b2`。回放接收的 `stream.ready` 确认实验 provider 与空分享地址，17 条翻译 final 均带候选模型身份。浏览器会话为 `20260905T200010.646Z-a8779c67`，安静环境下没有语音 final；这轮验证只证明真实录音、协议握手和保存控制，不证明麦克风语音翻译质量或实际中文渲染。

本地详细证据保留在 `artifacts/benchmarks/v41-poc-integration-20260905/`：`source/` 来源转换收据、`npm-test.log`、`gateway-translation.json`、`original-file-replay.json` 及事件、`browser-verification.json`、`final-health.json`、`delivery-verification.json`。录音与完整日志保持 Git ignored。

## 验收边界

v4.1 神学质量门仍未通过，不能因这次运行成功转为生产模型。本轮没有重复训练或打开 sealed final，没有进行现场、手机、真实声学播放或人工语义验收。文件回放的 `caption.display` 是 Gateway 事件；不能当作浏览器已显示该条中文的证据。
