# 本次交付路径的代码与运行演进

## 范围与起点

本分析只读本地 Git 对象和 `resi-69ba7a66` 的运行脚本／产物；不重跑模型、网络、发布或设备操作。重点是为何已具备四层组件，实际交付仍需补代码和运行桥接。审计脚本与安全结构化数据为同目录 `audit_delivery.py`、`delivery-metrics.json`。

最早明确生产冻结是 **2026-10-04 02:20:02 UTC 的 f446d8d**：dev `021725b` 加 PR237 `448df15`；02:46:03 UTC 改冻结 `efb774b`，记录修复 `092e61b`、`efb774b`。这比本地日期午夜更准确。`4f61a26^ = 4713b5e` 仅是后续交付补丁的父提交，不是开跑初始代码。

本次还存在独立冻结的远端配音运行代码（后期 `5b2c1ac`）与本地发布代码。不能因最后 Git HEAD 包含发布修复，就说较早已运行的 GPU 容器自动得到这些改动；运行计划/归档 SHA 与本地交付提交须分别保留。

## 开始时已有与缺失的能力

在 f446d8d 中已存在 `build_full_video_app_release.py`、`assemble_multilingual_v3_update.py` 和音频审核工具，具备三语资产准备→HTTP核验→封装发布包的主体流程；并非当天从零写了发布系统。

但初始代码的实际约束不覆盖当天最终交付路径：

| 初始实际行为 | 当天实际需求 | 后果／补足 |
|---|---|---|
| prepare循环固定LOCALES，manifest必须三语、资产数固定12 | 中文先发布，韩/西稍后独立完成人审 | 4f61只先加入中文单语；834再放开受支持语言非空子集 |
| 审核要求videoSync1x=approved及所有checks approved | 用户接受发布已听审音频，同时如实保留视频同步not_run | 新增精确track/locale/source/candidate/package绑定的例外版本；不能将未验收改为通过 |
| metadata审核要求三语同时批准；不能选单语言 | KO/ES各自metadata与音频批准后发布 | v2 selected-locales metadata审批契约及消费者同步升级 |
| 页面写死“31:31” | 本周媒体约32:22 | 834改由content.durationSeconds生成时长 |
| 原录制声纹offset被假定从0到clip时长 | sermon clip与完整原录制approvedWindow并存 | 5e8区分原录制sourceWindow与clip播放时间，保留真实来源哈希和offset |
| assembler禁止覆盖已有page ID | 中文已上线后，给同一page追加KO/ES | 本次使用ignored run-bound locale overlay；正式通用增量命令仍未覆盖此路径 |
| Release用prod，Debug/Beta用Dev，二者分开 | 用户期望Beta选择列表也立即出现本周中文 | prod成功不会更新Dev，需独立Dev快照增量发布；不是必须发布新iOS二进制 |

## 三个交付补丁到底改变了什么

### 4f61a26（作者时间09:02 PDT）

- `assemble_multilingual_v3_update.py` 加入 `single_zh_full_video_v1`（9项）与 `single_zh_bucket_video_v1`（8项），按profile核对语言集合、stage schema和文件数量；保留原三语契约。
- `build_full_video_app_release.py --locales zh-Hans` 可只交中文；资产数改为每locale四项，verify/seal按实际scope处理。
- `--source-date-label` 提供日期占位元数据路径。这个路径使已审内容先进入交付，但并非真实标题、系列、讲员、经文已完善的证明。
- 音频审核新增中文精确track的同步未验收发布例外，源锚点新增绑定唯一完整经文、source/anchor哈希的例外。不是全局放宽安全门槛，也不证明所有类似长句均获批准。

### 5e8cfb5（09:27 PDT）

- `build_full_video_app_release.py` 验证content.sourceWindow与source批准窗口、原媒体SHA一致。
- `published-weeks.mjs` 保留sourceFingerprintWindow；`fingerprint-ui.mjs` 使用正确原录制窗口，避免把原始录制窗口错误强制为0起点。
- 占位元数据补非空提示，仍是运行妥协；真实元数据随后另行修正。
- 这是序列化/客户端绑定修复，不是重新翻译或重新生成音频；代码测试通过也不代表实体设备或完整视频同步通过。

### 834dfe4（10:20 PDT）

- 发布builder允许唯一、非空、受支持的任意locale子集，不再强制中文或三语；所选metadata locales必须精确等于本次发布scope。
- metadata approval v2、audio human review v4、anchor exception v2保留旧版本语义，新版本绑定locale/source/candidate/audio/track，避免中文例外被无条件复用于其它语言。
- portable media audit、canonical inspection、delivery-intent binding和App delivery同时接受新receipt版本；否则生产者成功也会被后续旧消费者拒绝。
- 静态页时长由内容字段生成，消除复用9/27模板造成的31:31残留。

三次提交的作者时间不能替代真实部署时间；实际准备、HTTP读回及catalog发布仍是独立操作。

## 真正跑过的交付路径仍依赖运行桥接

以下是保存脚本的命令形状与对应产物，不把“脚本里有命令”当单独的执行证明；实际发生还依赖准备manifest、overlay、HTTP等回执。

1. **中文 sidecars**：`zh-publication-v1/generate_sidecars.py content|stage` 调用已检入的schema/page校验，手工绑定474组、原媒体window、浏览器视频SHA、声纹、英语参考和alignment；生成精确8项的bucket stage。它仍硬编码本周page/locale/source/candidate路径。
2. **正式中文**：prepared-client-window-v4 → stage-client-window-v4 → asset-first → HTTP资产验证 → sealed release → mutable catalog发布。保存的 `publication-http-final-v4.json` 证明实际正式中文HTTP完成；一条原生builder命令并未包办整个过程。
3. **Dev补齐可见性**：`ios-visibility-check-v1/prepare_dev_overlay_v1.py` 固定旧Dev catalog SHA，保留359项，新增8项和本周default；另复制公开视频redirect。`Release=prod/Beta=Dev` 从初始代码就存在，本次修复是交付环境覆盖不足而非突然产生客户端URL回归。
4. **元数据补修**：metadata-title-fix回执将日期占位改为真实标题、系列、讲员、经文，并声明audioAndCuesUnchanged。内容JSON、HTML、release及catalog等身份随显示元数据更新；不能只改网页标题而沿用旧hash。
5. **KO/ES准备**：`prepare_locale_app_v1.py --locale ko|es ...` 调用 `build_full_video_app_release.py prepare --locales <locale>`，固定绑定approved candidate、人审、screening与full-content。脚本在本次把同一已批准candidate赋给full/spoken两个参数；这必须是本次明确的内容决定，不能默认为未来所有run都可省略独立全文/口语策略。
6. **asset-first**：`prepare_asset_first_ko_es_v1.py` 将各4项资产叠加进两个环境旧快照，旧catalog不变；原始HTTP逐语言核对成功后再seal release。
7. **同page locale追加**：`merge_locale_release_v1.py` 检查同source identity、目标locale尚未存在、release和fingerprint哈希；仅更新catalog/english-reference/alignment三个共享文件，保留已有locale目标和无关文件。该脚本还专门兼容Dev已发布的legacy顶层defaultTargetLocale：验证投影删字段，但不改原服务目录其它值。
8. **CAS发布与读回**：`deploy_catalog_checked_v1.py --environment prod|dev --snapshot ...` 发布前下载catalog比对冻结baseline SHA，再运行 `firebase deploy --only hosting --project ... --config ... --non-interactive`。prod的project是 `ai-for-god-caption-dev`（hosting site仍为正式audio站），Dev project为 `ai-for-god-sermon-audio-dev`。项目名、hosting site、origin不是同一字段，不能靠名字猜目标。

所有这7份桥接脚本目前在ignored RUN内，不是一个已产品化、可用下一周参数直接复用的统一命令。部分保护确实存在（输出目录不覆盖、精确SHA、CAS、保留旧资源），但操作者仍承担阶段顺序、路径与环境的绑定。

## 运行参数与代码能力必须分开解释

- 首轮正式运行是8 replicas × batch8、reaction/gap各0.05、max-end-lag 8秒；随后CPU compact采用trailing、中文/西语padding40ms、韩语20ms、gap/reaction 0，并保留新目录。静音处理是已有native能力的run-level参数选择，不能描述成修改译文或速度。
- 保存的后续 `launch_formal_locale_reuse_timing62_v1.py` 明确改为 `--max-end-lag-seconds 62.0`。这是显式容差调整，不是“修复后达到原8秒目标”。音频复盘负责实际波形、单元替换和ASR证据，本分析不重复归因。
- `publicationException`与`anchor_exception_receipt`是在用户批准后增加的版本化接口；它们表达“批准这个已绑定例外”，与GPU/CPU运行参数不同。未来预检应先声明允许的例外模式，再决定能否继续，不能临场修改通用门槛来吞掉未知问题。
- 配音主机固定代码与发布脚本所导入的本地代码不同。最终receipt应记录两者，否则只给一个git commit不足以复现端到端结果。

## 可优先优化的发布预检与状态

| 优先级 | 具体改进 | 对应本次证据／验收方式 |
|---|---|---|
| P0 | 运行开始就做消费者契约预检：locale scope、receipt版本、approvedWindow偏移、同page增量、Dev/prod目标 | 用本周精确manifest在准备阶段执行所有下游读入校验；拒绝进入昂贵阶段后才发现接口不支持 |
| P0 | 单个声明式release intent列明page、locale、全文/口语身份、批准例外、目标origin/site/project与App channel | 每环境输出独立结果；中文发布不能误报Beta可见，dev状态缺失明确显示未发布 |
| P0 | 支持通用“新增page”和“已有page追加locale”两种不可混用命令 | 复用本次overlay的SHA/CAS/旧文件保留不变量；重复运行只复用相同hash产物 |
| P0 | metadata预检检查占位内容、动态时长、客户端必需字段、catalog/content/HTML一致性 | date-only应明确为降级模式；用户要求正式元数据时不能视为最终完成 |
| P0 | 对最终snapshot重新创建独立部署/HTTP收据，不copytree运行状态 | 本次两个bridge复制整个base目录会一并继承旧receipt；已有前次审计证明实际发生，不能把这些文件当新完成状态 |
| P1 | 将七份run-bound桥接收敛为仓库内带版本/参数schema的受测CLI | 仅用新run配置，不再编辑page ID、绝对路径、baseline SHA和locale常量；输出显示准确下一阶段 |
| P1 | 自动运行原生reader admission与网页读回，并区分缓存、网络、模拟器、真机 | 正式与Dev都用各自origin校验；UI证据绑定catalog与release SHA；真机不可用仍not_run |
| P1 | 输出多代码身份账本 | GPU archive commit/closure、native postprocess code、发布builder commit、run bridge SHA和实际argv分别存储 |

不需要因本周内容更新而自动重建、上传新App Store二进制；现有App能消费新目录时，正确动作是向它实际读取的环境发布并读回。也不应为元数据修正重做源稿、翻译或配音。

## 证据与复算

`delivery-metrics.json` 保存：最早两份冻结、5个提交元数据及patch SHA、24个精确Git版本文件内容SHA、7份运行桥接、24份运行证据SHA。没有复制私人审批原话或凭据。复算：

```sh
python3 audit_delivery.py --run-dir /path/to/run --out-dir /path/to/audit --repo-dir /path/to/repo
```

本次只补审计产物；上述优化尚未实现，不能称为已有自动化或性能提升。

### 关键运行输入 SHA

| RUN相对路径 | SHA-256 |
|---|---|
| `code-freeze-f446d8d.json` | `d53ea67c36b8861bf3de8092728391484b05231f094482550ec57d1a1a14344f` |
| `code-freeze.json` | `8d4c647697358ff2deab71f1de7327b386a6cf53eeab59d32a9dce94dba2125f` |
| `zh-publication-v1/generate_sidecars.py` | `02ee970bd9efd0f8a86384233de4a2b316a7a668c131b9b748f1a4fd956cea73` |
| `ios-visibility-check-v1/prepare_dev_overlay_v1.py` | `81cd2c618f8b963156fc7ba99d1de3030e01d744bc598678144a300456ab5e9a` |
| `multilingual-publication-v2/prepare_locale_app_v1.py` | `86fc9bdae89eb18b135f40843ab56a1590be43e7f0b396fa21f2b8d1e64f28ef` |
| `multilingual-publication-v2/prepare_asset_first_ko_es_v1.py` | `b74b5aac6c01a8205d92c186fa7df1707c5707dbff8b30ee0355576147c42b95` |
| `multilingual-publication-v2/merge_locale_release_v1.py` | `cda1c9fb9e9880133194f22b305cda1a5d78429a7264254814232fa0586d52e8` |
| `multilingual-publication-v2/deploy_catalog_checked_v1.py` | `695db3562a65c1872683bfb43a09063a77a631a67dac22c689c3bdd619e4bacc` |
| `multilingual-publication-v2/verify_final_ko_es_v1.py` | `9c64db569b1a15c55ac4249d188ac49bf3a0c2ce393af42792cb6f20ef4f1d73` |
