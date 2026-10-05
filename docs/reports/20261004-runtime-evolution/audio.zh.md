# Layer 3 运行实现与过程中调整

本专项只读既有本地脚本、launch receipts、queue snapshot、accounting与git历史；没有修改生产、调用模型或远端。安全结构指标 `audio-metrics.json` 仅保留RUN相对证据路径、hash、必要参数及统计。

## 初始代码与实际加载身份

正式运行冻结commit为 `5b2c1ac14575a0827b0e5ec0189cbc1f5f24a145`（2026-10-04 03:26:45 PDT），标题为 `fix: reuse canonical source readiness for formal audio`。8×8实现来自 `1e562a735108ff02dc7a4a2d04adbd70bf7165f2`，前置batch-resume身份修复为 `3fe82603aa07878fc012cbbed3293798dd5deaf0`。

10:28:03.325485 UTC staging receipt确认commit和code identity `07d7b413c0e32d766888f95d0afdb8be29b9ee8b1ed411c947f1039f915a75d2`。首轮snapshot/续跑replica runtime实际记录renderer SHA `948b3174bad368e8f80381beaca0d519299d16a927e50add934cb2111a90ebb2`、pool SHA `ccf79e4502fdb73074534171205ba9b8628456aa18c59b39a309ce3e2c4cc26e`。本地staged renderer/pool/scheduler/integrity四文件与git 5b2c1ac对应内容逐字节hash相同。scheduler SHA为 `351b60822173a438163506684d63383bc2c5a9b26b6e2fcb544fbf0a7e2f0ad4`；其hash未作为单独已加载字段记录，不能将本地匹配扩展为每模块执行证明。

后续临时launcher始终指定5b2c1ac；可见调整主要是派发、缓存、CPU/GPU资源及排程参数，没有证据证明当日这些attempt加载了更新producer代码。

## 参数/执行模式演化

| 实际消费时间 UTC | 参数或模式变化 | 实际证据与结果 | 性质 |
|---|---|---|---|
| 10:29–11:36 首轮 | 8 replicas×batch8、CUDA0/BF16/SDPA、seed42、24GiB连续reserve；reaction/gap各0.05秒、maxlag8秒、MP3；locale串行 | queue snapshot的rendererArgv、replicaRuntime；三语单句完整但8秒排程失败 | 初始实现 |
| 首轮之后，最迟12:27状态记录 | CPU静音压缩，中trailing+0.04秒padding、韩0.02秒；reaction/gap改0 | compact launch/measurement；文字/语速不变，仍失败 | 临时恢复，不是配音优化完成 |
| 修订attempt，最迟14:25报告 | `--reuse-from`明确旧cache、8×8/24GiB/8秒保持 | 中234/韩338/西288已复用；中韩生成完成但排程失败；西unit320内存guard失败 | 应固化的受控缓存恢复 |
| 14:34 中文、14:51 韩语 | maxlag由8→62秒；474缓存重组；韩采用CPU-only并发assembly launcher，不申请GPU lease/device | launcher argv虽仍cuda，实际events=474 reuse、0 synthesis；韩HostConfig要求无GPU、独立output/cache | 62秒是人工质量豁免；CPU调度是运行优化 |
| 17:19 西语同输出续跑 | 输出限定es-revision-v1；验证完整320前缀，备份旧runtime/launch；154缺项中122复用、32合成；8×8/24GiB原身份保留，maxlag62秒 | resume script/cache audit及accounting；474句完整但尾部溢出 | 临时特例恢复，应固化通用事务续跑 |
| 后续最终句首处理，精确dispatch时间缺失 | leading-only、padding0.06、RMS阈值0.01、10ms窗口、maxTrim0.75秒；不伸缩、不改当前译文 | final leading-silence receipts与schedule；韩裁150.96秒、西144.38秒，62秒policy pass | 音频后处理，另需质量/身份绑定 |

表中“最迟报告/状态时间”是观察边界，非脚本创建或完整执行起止。没有把8秒→62秒当性能提升，也没有把CPU-only称作MacBook failover。

## 代码路径与最值得固化的优化

### P0：receipt重复全量上下文校验是已定位热点

中文缓存重组run1265.50秒，其中474个 `layer3.receipt.*` 合计1156.86秒（91.42%）；韩语run1255.33秒，receipt1160.84秒（92.47%）。逐句decode validation合计只有21.30/21.06秒，复制reuse合计4.71/4.75秒。unit父span包含receipt，不能与子span再相加。

运行时renderer在每句receipt调用 `integrity.build_receipt/validate_receipt`，不传已验证上下文。integrity `_load_job` 因而每句重读job/schema，遍历所有inputs文件hash/JSON身份与候选全部groups/声音政策。已有API支持 `validated_job`、`validated_job_file_sha256`，但该producer调用方未使用。

应固化：每attempt完整admission一次，构建可验证的冻结上下文；receipt只做该unit的文本/job/audio绑定、完整decode与receipt匹配。保留job与依赖输入身份变更检测、严格rubric、跨窗口前后校验及失败关闭。不能仅传一个可能过期的dict跳过上游输入变化：只读mount也不能单独保证宿主外部不改文件。验收应使用相同474句cache，对照完整输出SHA、拒绝输入中途变更/坏audio/错receipt并比较leaf elapsed。

目前证据证明receipt热点及重复代码路径；未跑fast path对照，不能直接宣称能节省91–92%或具体分钟。

### P1：把assembly-only声明变成producer可验证的模式

临时CPU并发launcher写死“必须已有zh容器运行”“必须KO locale”“两个output/cache不同”，并检查无DeviceRequests；实际成功避免新GPU模型调用。应改为通用的all-cache-hit preflight和明确assembly-only模式：只要一项需要synthesis就拒绝该CPU路径；每locale独立锁/output，按CPU/I/O预算并发。无需GPU lease；实际compute字段不要因argv遗留cuda而误标GPU。

这是有运行证据的优化方向，但中文/韩同时约21分钟主要卡receipt，增加更多并发未必解决根本热点，也没有CPU/磁盘负载对照证明无限并发更快。

### P1：续跑与batch声音身份保持统一

resume脚本已严格验证320个commit/intents/WAV hash、拒绝孤立partial、保存旧launch/runtime，以同job/runtime身份恢复。应把精确320前缀和特定目录名变成通用reconciliation计划，保留逐单元事务和未知远端结果占用。

`_BatchedUnitSynthesizer` 按完整固定窗口调用batch，再只返回缺失波形；这可能让同窗口已缓存成员重新进入模型输入，但它保持batch/seed声音意图，不应当作能任意删除的浪费。改变batch大小、窗口成员或seed进入新生成身份，不能混用旧cache却仍声称同身份。future sparse-batch优化需独立质量验证和身份契约。

### P1：pool计量与受控容量选择

pool使用spawn，8个worker各加载模型；outstanding windows最多8，scheduler按窗口顺序消费再补位。较晚窗口提前完成也会留在父进程 `_outputs`，并且波形通过Pipe反序列化；代码明确一次recv可能超过poll间隔。长尾窗口、波形缓存和主机内存压力是合理待测风险，现有tail日志不证明它们是这次reserve失败根因。

应记录guard触发available/reserve、pending/output数量、波形字节、worker RSS、提交/返回/消费时间与exit reason。容量变化需显式profile身份和授权；先用固定质量/窗口对照8×8与其他容量，不能凭一次内存失败直接宣布降低replicas会更快。pool早停保护保留，不应放低24GiB门槛掩盖失败。

## 临时处置、固化与质量豁免分开

- 临时处置：特定目录/前缀的ES恢复，KO依赖特定zh容器的CPU并发，单次静音裁切方案。
- 应固化：可验证冻结上下文复用、通用assembly-only资源调度、事务cache reconciliation、完整pool/guard计量、真实阶段code/参数消费收据。
- 质量豁免：maxlag62秒及已批准锚点例外。它们不证明运行更快，不应成为未获新授权的默认同步目标。

61秒异常单句应先留WAV和输入身份并定位，再决定定向修复或L2修订；不应因完整排程失败自动整批重翻。旧u172声学原因缺证据，不能宣称该程序优化已修复TTS幻觉。
