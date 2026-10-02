# 2026-10-02 第二轮启用包：可审查清单，尚未执行

本清单只冻结启用前要核对的对象、影响和回退。没有安装 unit，没有打开 `tts_experiment`，没有加载模型，也没有提交 18 个 trial。root 探针仍待在 Spark 上由操作者执行。

## 今天重新核对的身份

Spark 上既有 checkpoint 目录仍是 13 个普通文件、4,520,218,514 字节。

| 文件 | SHA-256 | 合同 |
|---|---|---|
| `model.safetensors` | `75d28ce6022b3df3a72df3dd6dbc01e53f584d685770d60ea04b341920968c9a` | 与授权值一致 |
| `config.json` | `9dd6cf2c1b1fdfb1c90dcee20ab81ee5367925bb7a8123b6046af9bce8b2941c` | 与授权值一致 |
| `speech_tokenizer/model.safetensors` | `836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258` | 合同只要求该键存在，没有单独钉死这个值 |

离线镜像 `sha256:9629b436aef8bd90147fd657137047aee94e7b81ada54c3f7209cbce1d24b490` 仍在本机 Docker 中。同日 `--network=none` 探针见[namespace 记录](20261002-stage2-namespace-probe.zh.md)。

`lib/python3.12/site-packages` 下当前普通文件为 9,261 个、259,682,636 字节。这和 13:44 UTC 记录的 4,924 个文件、166,214,042 字节不是同一份清单。启用 manifest 的 `venv_files` 必须按当天字节重算，不能沿用旧计数。

选择哈希仍是合同里的 `e23ca743106e4c291f43563221f94fc42549e9053d113db351b56be69a34f9d4`。本次在 Spark 的当前发布树和语音结果目录没有找到含该哈希的 sample/manifest JSON。10 月 2 日的样本字节核验不能当成文件今天还在。

## 启用时要动的对象

只在 root 探针证明系统级 `PrivateNetwork` 真正换了网络命名空间之后才能做。用户级 systemd 已证明会退回宿主网络，不能用来安装这些 unit。

| 对象 | 动作 | 影响 |
|---|---|---|
| `llama-server.service` | 迁入只有 loopback 的私有网络，后端改听 `127.0.0.1:18000` | 维护重启，权重可能重载；宿主 `:8000` 在迁移完成前不可用 |
| `spark-resource-native-proxy.service` 与 `.socket` | 安装并只让它占用原来的宿主 `127.0.0.1:8000` | 不能和现有 `:8000` 监听同时绑定 |
| `spark-resource-guardian.service` | 安装，旗标先保持 0 | 只拥有 TTS 容器的创建和停止 |
| `spark-resource-controller.service` | 安装，旗标先保持 0 | 窗口内拒绝 llama、ImageLab、Comfy 的新 GPU 请求；不卸载已驻留模型 |
| Hub `SPARK_JOB_WRITES_ENABLED` | 保持 0 | 不打开全局写入 |
| `SPARK_CPU_SMOKE_*` | 保持原值 | 不扩大 CPU gate |
| `SPARK_TTS_EXPERIMENT_ENABLED` 及 Hub 对应写入旗标 | 最后、并且只对同一个 manifest SHA 和同一个不超过 2 小时的 UTC 截止时间打开 | 幂等键固定为 `tts-exp:<manifest-sha256>` |

ImageLab `:7862` 与 Comfy `:8188` 的容器保持运行。窗口只挡住新的 GPU 请求。容器 ID 和 PID 必须在动手时重读，本清单不引用更早的进程号。

## 窗口与停止条件

一次窗口最多 2 小时。cold session 600 秒，warm session 1800 秒，整个 job 7200 秒。可用内存低于 24 GiB、容器 OOM、超时、产物字节缺失或网络命名空间不再成立时停。已完成的 session 保留，不自动重跑。先做 1 个 admitted trial 并收齐退出与字节收据，再决定是否继续其余 17 个。

## 回退

1. 先关掉 Hub 与 Spark 的 TTS 旗标。
2. 确认本次拥有的 TTS 容器已停止；停不干净就保持 intake hold，不猜测成功。
3. 恢复这次窗口改过的 proxy 与 llama 监听，确认宿主 `:8000` 回到迁移前的服务。
4. 不停止 ImageLab 或 Comfy 的常驻容器，不删 Job DB，不关 AppArmor。
5. 产物和账本留下。缺字节或未知退出不授权再推理。

## 仍缺的动作

Spark 上的 root 探针还没有输出。样本 JSON 还没有按今天的字节重新定位。`venv_files`、producer PID 和 logging release 都要在启用当时重读。MacBook 路径仍未验收。
