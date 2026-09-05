# v4.1 本地实验翻译服务

日常试用入口是 [本地 POC 麦克风与字幕流程](../local-live-poc/MILMMT_V41_LOCAL.zh.md)。此目录的 `index.html` 是模型服务附带的纯文本诊断页面，不包含麦克风或 ASR。

在仓库根目录可独立启动：

```bash
~/.local/share/uv/tools/mlx-lm/bin/python scripts/serve_milmmt_v41_local.py start --open
```

使用固定模型 `~/Models/milmmt-sermon-v41-experimental-mlx-q5` 和本机端口 18771；启动会验证冻结模型包、依赖及模型输出。模型仍为未经人工确认、未通过神学质量门的实验候选。
