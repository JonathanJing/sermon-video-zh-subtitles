# 现场采集与日志检查（2026-09-04）

本轮验证采集与留证，不替代现场音频或字幕质量验收。

## 已验证

- 浏览器以 1× 回放公开证道 WAV，经真实 MediaRecorder、AudioWorklet、Qwen ASR、MiLMMT 和 Gateway。
- 会话 `20260905T004812.210Z-6e294036` 持续 39,449 ms：39 个 WebM 块、125 个事件、12 条 ASR final、12 条 translation final、8 次持续健康采样。
- `completed`，worker drain 确认；ASR/翻译失败及音频 gap 均为 0。计数不代表翻译正确。
- WebM 与 WAV 经 ffmpeg 完整解码成功；WebM、PCM、WAV 的 SHA-256 与 manifest 一致。浏览器恢复录音副本与磁盘 WebM 字节数及 SHA-256 相同。
- WebM SHA-256：`fe0cd0bb1b9e79723cb0d022efa40aea29e7b3abe1589b6115d8a02b74f50e0d`。
- 启动日志目录 `20260905T004709Z-TK9Io2` 中 supervisor、Gateway、MLX Audio、frontend 四个日志均非空，文件权限 0600，并由会话 metadata 关联。
- `npm test` 通过（前端 32、后端 120、集成 23、Firebase rules 5）及生产构建；随后新增的服务端日志位置防伪测试所在模块 8 项通过。
- `bash -n scripts/run-local.sh`、`git diff --check` 通过。

## 使用与边界

录音、PCM/WAV、events.jsonl 和 manifest 位于 `artifacts/sessions/<session>/`。运行日志位于 `artifacts/runtime/<launch>/`，具体路径见 manifest 的 `metadata.runtimeLogDirectory`。保持页面和启动终端运行，结束时等待页面显示“本地保存：已完成”，保留整个会话目录及关联运行日志目录。

新增健康采样记录磁盘余量、模型可用性、队列深度与发布失败数；浏览器挂起或 Gateway 写入故障仍可能造成采样缺失。机器掉电或浏览器崩溃时尚未上传的数据无无损保证。当前启动器不收集共享 Ollama 或外部已有 MLX 进程的 stdout，也不自动持续采样 RSS/swap。手机没有逐字幕显示回执。

回放页面已清理；回放音频没有经过物理麦克风。现场调音台、选定麦克风、收音电平、长时间资源趋势、手机可读性与人工语义质量仍须分别验证。原始日志和录音留在本机并被 Git 忽略。
