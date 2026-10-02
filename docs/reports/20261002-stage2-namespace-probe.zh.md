# 2026-10-02 第二轮：user-systemd 网络隔离探针

第二轮按既有协议开始，只做 CPU 可行性探针。没有提交 `tts_experiment`，没有加载语音模型，没有安装三项常驻 service 或 socket，没有修改 AppArmor、全局写入或 CPU gate，也没有用 legacy SSH 派发 GPU。

## 只读现状

2026-10-02 20:36 UTC 左右，经既有 Mac mini Hub 读取 Spark `job.v1` 能力表：`tts_experiment.available=false`，harness 已登记为 `1.0.3`；`cpu_smoke.available=true`。Spark 当前发布目录名对应已审 merge `abf9531287ac`，目录内已有 TTS supervisor、artifact collector、resource-control 源码和 guardian unit 模板。API 进程环境只有 `SPARK_CPU_SMOKE_ENABLED`，没有 `SPARK_TTS_EXPERIMENT_*` 或 `SPARK_JOB_WRITES_*`。

四个资源 unit（guardian、controller、native proxy service 和 socket）均为 `not-found`。llama 仍由既有进程监听 loopback 8000，对应 unit 的 `PrivateNetwork=no`，且该 unit 的 systemd active 状态是 inactive。ImageLab 与 Comfy 容器仍在原端口运行。GPU utilization 为 0。`MemAvailable` 约 39.34 GiB。`kernel.apparmor_restrict_unprivileged_userns=1`。

这修正 14:26 UTC“PR #11 尚未部署”的说法：源码树已经是当前发布目录，但启用开关和资源 unit 仍未打开。目录存在不是语音试验已运行。

## 探针

在 Spark 用户 systemd 中各跑一次临时 unit，命令结束后 unit 为 inactive，没有留下常驻服务。

| 检查 | 结果 |
|---|---|
| 当前用户直接 `unshare --net /bin/true` | 失败，`Operation not permitted` |
| `systemd-run --user --property=PrivateNetwork=yes /bin/true` | 进程退出 0 |
| 同一属性内读取 `/proc/self/ns/net` 与 `/proc/net/dev` | 网络命名空间与宿主相同，可见外部网卡 |

journal 原文：`PrivateNetwork=yes is configured, but the kernel does not support or we lack privileges for network namespace, proceeding without.`

因此 user-systemd 的 `PrivateNetwork` 目前会在缺少权限时继续跑在宿主网络里。`JoinsNamespaceOf` 没有可加入的私有命名空间，不能算通过。这个结果不允许把 18 个 cold/warm trial 标成已隔离执行。

## Docker 离线网络探针

语音 supervisor 固定使用已有镜像的 `docker run --network=none --read-only --cap-drop=ALL`。这次用同一镜像、同一网络参数跑了一个立即退出的 Python 进程，没有挂载模型、没有申请 GPU、没有提交 job。容器结束后没有留下 `tongxing.tts.owner` 容器。

| 观察 | 宿主 | `--network=none` 容器 |
|---|---|---|
| 网络命名空间 | `net:[4026531833]` | `net:[4026533140]` |
| 非 loopback 网卡 | 有 | 无 |
| `/proc/net/route` | 未作为对照读取 | 只有表头，没有路由项 |

这条隔离由 root dockerd 创建，不依赖当前用户的 `unshare`，也没有修改 AppArmor。它只证明容器网络命名空间可用，不证明 llama 后端已经迁入私有命名空间，也不证明 guardian 或 18 个 trial 已执行。当前账号 `sudo -n` 需要密码，因此不能在这次会话里安装 system unit 或迁移宿主 llama。

## 仍不能开始的部分

真实 batch 1/2/4 的速度、稳定性和音质仍是 0 次 GPU trial。user-systemd 不能当作隔离成功。Docker 容器网络隔离已经单独证实，但启用窗口仍要求 llama 进入私有命名空间、四生产者覆盖和 guardian/controller。这些步骤需要 Spark 上的 root，本次没有密码，不能改走旧 SSH 推理，也不能关闭 AppArmor。MacBook 接入和产物传输仍未验收。
