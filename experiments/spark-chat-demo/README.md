# Spark chat demo (throwaway)

一次性演示：在 DGX Spark 上用 llama.cpp CUDA 跑 Qwen3.8，网页对话，演示完一条命令清干净。

## 文件

| 文件 | 作用 |
|---|---|
| `install.sh` | 建 `~/spark-chat-demo/`，编译 llama.cpp（CUDA），下载 GGUF 权重，写入 `state/install.json` |
| `run.sh` | 起 `llama-server`（127.0.0.1:8080）+ 网页代理（0.0.0.0:8088），写 `state/pids.json` |
| `serve.py` | 只用标准库的静态页 + SSE 代理，把 `/v1/chat/completions` 转发给 llama-server |
| `index.html` | 单页聊天界面，显示首 token 与总耗时 |
| `cleanup.sh` | 停进程、关端口、删模型和构建树，并验证已干净（`--keep-logs` 保留日志） |

## 用法

```sh
# 装机（约 10–20 分钟：编译 10 分钟 + 权重 16 GB）
HF_REPO=unsloth/Qwen3.8-27B-GGUF \
HF_FILE=Qwen3.8-27B-UD-Q4_K_M.gguf \
MODEL_NAME=qwen3.8-27b-ud-q4km \
bash install.sh

# 演示
bash ~/spark-chat-demo/scripts/run.sh
# 浏览器打开 http://<spark-ip>:8088/

# 演示完恢复干净
bash ~/spark-chat-demo/scripts/cleanup.sh
```

## 边界

- 不装系统包、不建 systemd unit、不用 docker；所有东西都在 `~/spark-chat-demo/` 下。
- 只绑定 8088 到局域网，8080 只在 loopback。
- 模型是一次性演示资产，`cleanup.sh` 默认连权重一起删；要留日志加 `--keep-logs`。
- 未做鉴权：同一局域网内任何人可访问，演示完请立刻清理。
