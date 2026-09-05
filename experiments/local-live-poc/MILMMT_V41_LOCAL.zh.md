# v4.1 后训练模型接入本地 POC

沿用 [Sunday Live Captions.command](Sunday%20Live%20Captions.command) 启动 POC，打开 [v4.1 本机页面](http://127.0.0.1:4173/?translationProvider=milmmt-v41-mlx)。普通入口默认仍选择原 MiLMMT Q8；带参数的链接只预选实验模型。

1. 开始前选择「v4.1 Q5 · 实验候选」。若模型未运行，点击「启动 v4.1 模型」，等待就绪。
2. 选择麦克风，点击「开始录音与字幕」。当前英文 ASR final 经 Gateway 发给 v4.1，中文在原有大字字幕区显示。
3. 点击「停止并保存」。模型选择在录音期间锁定；如需换模型，保存后开始新会话。

v4.1 仍未通过神学质量门，译文未经人工确认。实验会话只在本机显示和保存，Gateway 禁止 LAN/Firebase 发布，也不使用 Saturday context。此接入不构成 Sunday 现场、手机端或人工语义验收。

已完成的实机接入检查见 [2026-09-05 验证报告](benchmarks/MILMMT_V41_POC_INTEGRATION_20260905.zh.md)。

## 运行与恢复

Gateway 仍使用 `127.0.0.1:8766` REST 和 `127.0.0.1:8767` WebSocket。它将实验翻译路由至 `127.0.0.1:18771` 的独立单 worker MLX 服务；浏览器不直接连接模型。录音和 PCM 持久化沿用原流程，模型不可用时显示错误并保留录音，不自动切换到默认模型。

模型目录为 `~/Models/milmmt-sermon-v41-experimental-mlx-q5`，解释器为 `~/.local/share/uv/tools/mlx-lm/bin/python`。启动时校验冻结模型包和依赖版本；没有就绪环境时给出失败原因，不下载或替换环境。翻译采用冻结 A0、无上下文、greedy、最多 512 tokens、`add_special_tokens=false`、EOS `[1,106]`，每次新建 cache。仅完整正常终止的输出可成为 translation final。

首次更新代码后使用「重启后台」载入 Gateway。网页校验会话绑定及 `stream.ready`；旧 Gateway 或协议不匹配时不发送 PCM 给模型，独立录音仍继续。断线后使用「恢复字幕与保存」恢复同一会话；已有字幕缺口保留在日志中。

模型服务按需启动并保持加载，不随录音结束退出。先停止并保存所有使用它的任务，再从仓库根目录执行：

```bash
~/.local/share/uv/tools/mlx-lm/bin/python scripts/serve_milmmt_v41_local.py status
~/.local/share/uv/tools/mlx-lm/bin/python scripts/serve_milmmt_v41_local.py stop
```

`stop` 校验 PID 与实例身份；不会按端口任意杀进程。模型日志和状态保存在 `~/Library/Caches/sermon-video-zh-subtitles/milmmt-v41-local/`；启动入口不设置登录自启。原 POC 停止入口不负责此独立服务。

## 会话与兼容性

新会话 metadata 使用 `translationSelectionSchema=local-live-translation-selection-v1`，固定 `translationProvider`，resume 不允许改变。默认/历史会话维持 `local-live-runtime-identity-v1`；实验会话使用 `local-live-runtime-identity-v2`，记录 MLX 模型权重/包 SHA、量化和解码参数及禁止发布标记。历史 manifest 无需重写，缺省 provider 按原 Ollama 解释；不得将历史会话重新标记成 v4.1。

录音进行中或 WebSocket 正在创建会话时，后台拒绝启动模型；模型启动期间拒绝新字幕连接。启动结束或失败后释放占用。多标签页共享一个模型 worker，忙碌时显式报错。

验证要求见 [AGENTS.md](AGENTS.md)：跨层测试使用 `npm test`，实机证据须区分文件 PCM 回放、浏览器真实录音及现场输入。回放可以显式选择模型：

```bash
.venv/bin/python scripts/replay-audio-e2e.py /absolute/path/original-16k-mono.wav \
  --translation-provider milmmt-v41-mlx --context-policy none \
  --duration-seconds 45 --output artifacts/benchmarks/new-v41-replay.json
```

回放报告记录 provider 与实际 translation final 的模型哈希；身份不符的运行保留为 incomplete。
