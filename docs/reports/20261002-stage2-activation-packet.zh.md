# 2026-10-02 第二轮启用包：可审查清单，尚未执行

本清单只冻结启用前要核对的对象、影响和回退。没有安装 unit，没有打开 `tts_experiment`，没有加载模型，也没有提交 trial。2026-10-02 已完成 root transient systemd `PrivateNetwork` 探针，host 与 unit 网络命名空间不同；此结果只验证隔离前提，不等于已安装或准入。

## 今天重新核对的身份

Spark 上既有 checkpoint 目录仍是 13 个普通文件、4,520,218,514 字节。

| 文件 | SHA-256 | 合同 |
|---|---|---|
| `model.safetensors` | `75d28ce6022b3df3a72df3dd6dbc01e53f584d685770d60ea04b341920968c9a` | 与授权值一致 |
| `config.json` | `9dd6cf2c1b1fdfb1c90dcee20ab81ee5367925bb7a8123b6046af9bce8b2941c` | 与授权值一致 |
| `speech_tokenizer/model.safetensors` | `836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258` | 合同只要求该键存在，没有单独钉死这个值 |

离线镜像 `sha256:9629b436aef8bd90147fd657137047aee94e7b81ada54c3f7209cbce1d24b490` 仍在本机 Docker 中。同日 `--network=none` 探针见[namespace 记录](20261002-stage2-namespace-probe.zh.md)。

截至 2026-10-03，Spark TTS venv `lib/python3.12/site-packages` 的 runtime 同口径清单已重算：4,924 个普通文件、166,214,042 字节；排除了 `__pycache__` 和 `.pyc`，与执行器校验逻辑一致。清单 SHA-256 为 `d38d583ac551082ed7354086e5011646b88a38762926ff6f8a7d29435dae98a2`，文件为 `artifacts/stage2/venv-files-20261003.json`。旧 9,261/259,682,636 清单包含不同范围的文件，不用于本次 manifest。

既有 18-trial 合同仍绑定选择哈希 `e23ca743106e4c291f43563221f94fc42549e9053d113db351b56be69a34f9d4`。它不是本播客样本的准入。按已批准的 Layer 2 候选，已生成 41 个连续中文单元的源样本，byte SHA `52b0827211251e7923b507c885c0c7159f3ac14664d36ddb81b4798786602d76`，另生成校验器格式样本，SHA `936b58eb29eca1cb5b75a1d797e91a8ac286ae024fe120e44db00ac301fe88f3`；后者含 908 个目标文字，绑定当前 source、anchor、candidate 和 speaker route。样本覆盖源音频 5.74–139.23 秒，属于原 0–180 秒摘录；其余摘录内容不在 41 单元样本内。2026-10-03 已将候选与样本复制到 Spark 隔离目录并通过 CPU 校验，但没有部署或接入活跃服务。

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
| `SPARK_TTS_EXPERIMENT_ENABLED` 及 Hub 对应写入旗标 | 最后打开，且只绑定[下面单独准入的单 trial manifest](#第一份准入必须是单独的单-trial-manifest) 的 SHA 和同一个不超过 2 小时的 UTC 截止时间 | 幂等键固定为 `tts-exp:<该单 trial manifest 的 sha256>`；不对 18-trial SHA 打开 |

ImageLab `:7862` 与 Comfy `:8188` 的容器保持运行。窗口只挡住新的 GPU 请求。容器 ID 和 PID 必须在动手时重读，本清单不引用更早的进程号。

## 窗口与停止条件

一次窗口最多 2 小时。cold session 600 秒，warm session 1800 秒，整个 job 7200 秒。可用内存低于 24 GiB、容器 OOM、超时、产物字节缺失或网络命名空间不再成立时停。已完成的 session 保留，不自动重跑。

## 第一份准入必须是单独的单 trial manifest

[backlog](../backlog.zh.md) 里的首轮矩阵是一份完整的 18-trial manifest。唯一 task 参数是 manifest SHA，batch 由这份冻结矩阵决定；没有正式 warm/preload 公共 API，也没有同一 job 的暂停或续跑参数。提交这份 18-trial SHA 就会按矩阵跑完其余 trial，不能靠“先做一个再看收据”停住。现有 collector 只在 exact succeeded、attempt 1、且 12 个 owned session 都已退出确认时才导出字节收据，所以它也不是第 1 个 trial 之后的中途闸门。

本清单因此不准入 18-trial SHA。第一份 job 必须是另一份只冻结 1 个 trial 的 manifest：

| 条件 | 要求 |
|---|---|
| 身份 | 自己的 SHA，幂等键 `tts-exp:<该 SHA>`，与 18-trial 矩阵的 SHA 不同 |
| 旗标 | TTS 旗标只对这一份 SHA 和同一个不超过 2 小时的 UTC 截止时间打开 |
| 禁止 | 同一窗口不提交、不打开 18-trial SHA；已完成的单 trial session 不是其余 17 个的 resume |
| 下一份 | 这一份 job 到达终态并留下退出证据之后，才可另行审查其余矩阵。其余矩阵是新 manifest、新 SHA、新窗口 |

这份单 trial manifest 还没有冻结，也还没有证明 runtime 会按 1-trial 矩阵执行。在它被单独审查并准入之前，不得打开 TTS 旗标。

## 回退

1. 先关掉 Hub 与 Spark 的 TTS 旗标。
2. 确认本次拥有的 TTS 容器已停止；停不干净就保持 intake hold，不猜测成功。
3. 恢复这次窗口改过的 proxy 与 llama 监听，确认宿主 `:8000` 回到迁移前的服务。
4. 不停止 ImageLab 或 Comfy 的常驻容器，不删 Job DB，不关 AppArmor。
5. 产物和账本留下。缺字节或未知退出不授权再推理。

## 2026-10-03 候选验证补充

隔离候选目录为 `/home/achillesjing/dgx-spark-benchmark/podcast-runs/if-i-had-more-time-jesus-is-worthy-20261003/stage2-candidate-v3`。候选压缩包 SHA-256 为 `c0d1e7eee1650dac45c79c7af80a4896c76712bc6ed8e46f3bc36ae0eac53c59`，解包后的 297 文件树清单 SHA-256 为 `0438ded452de63567bf522ef099d65238873745420fd18392271835817c03b13`。候选 harness 为 1.0.4，runtime profile 为 1.0.3；v3 合同固定一个 cold batch=2 trial 和 41 单元样本，旧 18-trial 合同保留。

本机测试 161 项通过、1 项跳过；Spark Python 3.12 候选测试 140 项通过。测试覆盖样本字节与源选择、版本化 harness 锁、一次加载、20 个双单元批次加一个末批单元、单试验收据校验、资源门控以及旧合同回归。Spark 检查时 GPU 利用率为 0%，可用内存约 43 GiB。候选没有调用模型，没有安装 unit 或更改当前 symlink；现有 ImageLab 与 Comfy 容器仍运行。root PrivateNetwork 探针已通过，但 `spark-resource-controller.service` 和 `spark-resource-guardian.service` 尚未安装，正式 intake hooks 尚未启用。

**本候选不等于 TTS 运行或生产准入。** 单 trial manifest SHA、私有资源窗口与 lease、logging release 身份、生产 hooks 的确切安装/回退包和 idempotency key 仍待就绪。按 Spark 准入合同，在提交前须审查确切 manifest SHA、UTC 窗口和幂等键；安装 controller/四个生产入口 hooks 也须单独审查。现有 18-trial SHA 不得用于本次单试验。

## 仍缺的动作

root `PrivateNetwork` 探针已完成；样本与候选已放入隔离目录，但活跃 validator 没有改变。单 trial manifest 候选已生成并通过上下文预检；正式部署、安装审查、lease 窗口和 TTS 提交均未完成。producer 身份、可用资源、logging release 与服务状态必须在实际启用时重读。MacBook 路径仍未验收。

### 2026-10-03 canonical context 复核

首份 podcast 单 trial manifest 现绑定 SHA-256 `ba115214ed2903186ed546bc1aebc8f2ac782f8dd09fd3ff7caf522a79c18aed`，幂等键为 `tts-exp:ba115214ed2903186ed546bc1aebc8f2ac782f8dd09fd3ff7caf522a79c18aed`。它只冻结一个 cold batch=2 trial，样本 SHA 仍为 `936b58eb29eca1cb5b75a1d797e91a8ac286ae024fe120e44db00ac301fe88f3`。本机候选 validator 与 Spark 隔离候选均通过 manifest、sample 和已安装 canonical logging release 的上下文预检。失败原因是 `missingReasons` 原先为空；修订后按会计合同明确记录不适用或未观测字段。原 SHA `7511848e…` 作废，不可用于提交。

这只关闭 manifest 上下文形状问题。本次逐项重验了该 SHA 绑定的 20 个实现文件、4,924 个 venv 文件和 13 个 checkpoint 文件，Spark 上均与 manifest 哈希一致；样本和 logging 上下文预检也通过。候选仍未部署。controller、guardian、native proxy/socket 与生产 intake hooks 仍未安装，TTS 未提交。按本报告的启用边界，仍须针对此确切 SHA 审查安装包、UTC 窗口和回退；提交前重读 producer 身份、资源与 outstanding jobs。用户要求在后续页面生成阶段暂缓 Spark 新任务接入并排队。这项要求仅适用于页面生成窗口；到该阶段时需确认控制器能只拦截新准入、让既有任务 drain，并恢复排队任务，不终止正在运行的任务或卸载常驻模型。当前不宣称队列暂停已安装或生效。
