# 和合本经文锁定与证道重译

入口为 `scripts/sermon_cuv_translation.py`。它从冻结的配音 `job.json` 读取完整英文，在新目录中重译全部段落；不修改英文、原 job、PDF、时间轴或音频，也不自动发布。经文取自 `scripts.cuv_scripture.CuvLibrary` 严格校验的和合本全文库，模型只能选择库中的原文片段。

## 执行与恢复

密钥仅从已有 `OPENAI_API_KEY` 环境变量读取；程序不读取 `.env`，不创建密钥或配置文件。缺少密钥且没有所需模型缓存时明确失败。`validate` 不需要密钥、网络或模型。

```bash
.venv/bin/python scripts/sermon_cuv_translation.py run \
  --parent-job /absolute/path/to/dubbing-v2/job.json \
  --out artifacts/cuv-scripture/new-translation

.venv/bin/python scripts/sermon_cuv_translation.py validate \
  --out artifacts/cuv-scripture/new-translation
```

可用 `--reference-map /absolute/path/to/reviewed-map.json` 提供独立审计的出处映射，省去自动识别调用；它不能跳过经文取文、独立覆盖审核或叙述审校。可显式指定 `--library`、`--provenance`；库仍须通过固定版本与内容哈希验证。`--batch-size` 默认为 6，支持 1–20。

修订映射后，用新输出目录并指定 `--reuse-from /absolute/path/to/previous-translation`，可以复用上一运行中完整请求 payload、阶段和版本完全相同的模型结果。父 job、库、来源元数据、父时间预算的哈希，以及模型、推理强度和批次大小都必须一致。输入改变的选择或审核会正常重新调用。复用收据保留真正执行过的原始 request 和 response，通过 `reuseFrom` 绑定旧收据及 manifest；新运行身份只记录为复用上下文，不伪造新请求。离线校验会递归验证这条来源链，因此旧证据目录须保留。

独立审核发现选文错误时，可在新运行加 `--repair-from /absolute/path/to/failed-translation`，并同时把它作为 `--reuse-from`。程序绑定且核验该运行唯一的全篇独立审核缓存、原始请求/响应和 manifest，只将被判失败段落的完整审核意见及旧选文作为 `repairContext` 传给对应的选文请求。未失败段落的 SELECT payload 不变，可继续复用。失败记录不会被改成通过，新选文仍须重新经过全篇审核。没有失败段落、缺少完整审核覆盖、来源不兼容、证据改变或无法定位到引用选文的问题均拒绝作为修复入口。

重复同一命令会复用以输入、完整提示、模型和请求哈希绑定的缓存。输出目录受进程锁保护；输入、映射、库或批次设置改变时必须选择新目录，不覆写已有运行。失败会保留已经收到的模型响应，包括未通过校验的响应；不把解析或审核失败自动变为再次付费的请求。网络层沿用 `chat_json` 原有重试行为，失败不代表服务端一定没有产生费用。

## 阶段与通过门槛

1. **识别来源**：Astra Medium 读取全部英文，识别直接引文及上下文出处。跨段引文按每段原文边界拆分。解释、间接引述、玩笑和讲员口误另行记录，不当作和合本正文替换。原文出现 `John chapter 1`、上下文实际引用启示录时，保留这句口述，实际引文出处另记证据。
2. **固定取文**：程序查询完整经节，将固定文本交给模型选择精确连续子串。引用范围之外的节、改写后的文本、歧义片段、逆序或重叠片段一律拒绝。完整相邻节和同节连续片段直接拼接，只有确实跳过字句时才加 `……`。不能用整节补齐讲员没有念的内容。英语译本与和合本的常规措辞差异记录为 `editionDifference`，不自动视为冲突。
3. **独立引文审核**：另一次模型调用检查全部英文中的直接引用覆盖、跨段边界、引用归属、漏读与增补。输入映射的每条问题及不确定项都必须有编号对应的明确消解证据；剩余问题阻止继续。
4. **叙述翻译与独立审校**：原文引文先替换为 opaque token；叙述翻译后再用独立请求审校。每个 token 必须保留一次且顺序一致。父 job 如有绑定有效的 `synchronization/report.json`，会提供逐段 `availableSeconds`；译文尽量自然精练，但不能为时长删去意思或缩写经文。
5. **程序注入**：程序将精确和合本文字放回 token 位置，记录中英文字符范围及原文哈希。仅在全部段落的四项审校、引文覆盖和问题清单均通过后输出通过报告与合成审校收据。

四项审校为 `completeMeaning`、`negationsNumbersNames`、`quotationAttribution`、`spokenChinese`。输出始终标记 `reviewType=model`、`humanApproval=false`。机器通过不代表人工逐句审核、实际听感、时间同步或现场验收。

翻译初稿允许保留待独立审校的问题及不确定项。进入审校前仍严格检查全段 ID/顺序、证据、问题列表形状和 token 的完整性；不能以“初稿”名义跳过引文锁定。独立审校收到完整初稿，涉及已分类旁白的批次还会收到对应 `caveatReview` 和真实收据绑定；它须解释问题如何处理，区分保留的未核实旁白背景与实际译文/直接引文缺陷。最终审校仍必须四项与引用覆盖全部通过，且无剩余翻译问题或不确定项。原初稿、原审核和旁白疑点保留在缓存及报告中，不因合成准入而清空。此门槛不改变初稿请求，因此可复用已有翻译缓存；增加的审校上下文由完整请求哈希绑定。

没有明确经节的叙述性典故可以保留为讲员旁白，并明确记录其候选出处尚未核实；不得把候选变成已核实经节，也不替讲员纠正叙述事实。独立审核必须确认这种分类符合实际英文。直接引文的出处或范围不明仍然阻止通过。

若全篇审核已经逐段 `quoteCoverage=pass`、`issues=[]`，且全部输入问题均已明确消解，但 `uncertainty` 中仍保留旁白疑点，程序会执行独立的 `audit-narration-caveats` 分类关口。它把每条疑点原文、段落 ID、段内编号、完整对应英文、锁定引用和原审核收据交给模型，要求逐条返回有证据的 `narration_only` 或 `quotation_unresolved`。只有全部为前者才能继续；缺项、重复、身份或原文不符、无证据，以及任何直接引文疑点都阻断。原审核与疑点不清空，报告 `caveatReview` 保留完整输入和真实分类结果，只声明直接引文已经审核，旁白候选出处与事实仍未核实。离线校验会重放该关口并检查缓存、报告和原审核的绑定。

上述分类是新增阶段，不改变既有引文审核提示、manifest 或请求 payload。使用原参数、原输出目录恢复即可复用已完成的选文与全篇审核，只新增分类和未完成的翻译/审校调用。若分类仍不能通过，保留失败缓存，不自动删证据或重试付费。

## 独立映射格式

`blocks` 必须与父 job 的 ID 和顺序完全一致，包括没有经文的段落。

```json
{
  "schemaVersion": "sermon-cuv-reference-map-v1",
  "parentJobSha256": "父 job 文件的 SHA-256",
  "issues": [],
  "blocks": [{
    "id": 0,
    "quotes": [{
      "quoteId": "q001",
      "sourceText": "I am Alpha and Omega.",
      "reference": "REV 1:8",
      "evidence": "直接引文及上下文出处的证据说明",
      "uncertainty": []
    }],
    "speakerReferences": [],
    "uncertainty": []
  }]
}
```

重复出现的英文子串须指定 `start`、`end`，按 Python Unicode 字符偏移、左闭右开计算。跨段引用可用相同 `groupId`，但每个 `quoteId` 全局唯一。`speakerReferences` 的每项包含精确 `sourceText`、`kind`（`explanation`、`allusion`、`joke`、`misquotation`）、`evidence` 与 `uncertainty`。这些范围不得与锁定引文重叠。

映射可提供 `parts`、`selectionEvidence` 提示，模型仍须独立选择和审核。输入问题会保留在原映射中；报告的 `quotationAudit.resolutions` 记录如何逐项消解，而不是删除历史不确定性。

## 输出与下游

- `cuv-manifest.json`：父 job、和合本库、来源元数据、可选映射和父时间预算的路径及哈希。
- `cache/`、`accounting/`：请求/响应缓存与已有费用记录流程；不包含密钥。
- `reference-map.json`：精确源范围绑定的识别映射。
- `blocks.json`：全部英文原样保留、新中文、模板、锁定经文及注入范围。作为新阅读稿/PDF 的依据时应保留这些来源绑定。
- `report.json`：全部引文覆盖审核、叙述审校及模型证据；如存在旁白疑点，另保留 `caveatReview`，不改原 `quotationAudit`。
- `spoken-review.json`：兼容 `apply_spoken_review.py` 的全段机器审校收据，绑定报告及 manifest。

下游可调用 `validate_spoken_review(parent_job_or_directory, review_path)`。该函数在本地重新验证输入哈希、模型请求缓存、引用选择与注入、全部英文、最终中文和审校状态；不能仅检查经文字串“出现过”就放行。任何文件变动或缺失都必须重新审查，不得直接修改哈希掩盖变化。

```bash
.venv/bin/python experiments/sermon-dubbing-poc/apply_spoken_review.py \
  --parent /absolute/path/to/dubbing-v2 \
  --out /absolute/path/to/new-dubbing \
  --review artifacts/cuv-scripture/new-translation/spoken-review.json
```

新 job 仍需自己的配音、逐段回听、时间预算、同步装配与发布证据。旧 PDF 不会由此脚本自动更新；新中文 PDF、字幕、同步音轨、完整视频时间轴下载、指纹音轨绑定和反馈目录须在后续明确重建。保留旧版本用于恢复，页面来源身份及用户确认窗口不变时可继续复用其有效来源批准。

## 开发验证

```bash
python3 -m unittest tests.test_sermon_cuv_translation -q
git diff --check
```

测试使用真实固定经文库和模拟模型响应，覆盖 67 段完整流程、自动识别入口、续跑、离线验证、问题消解、篡改拒绝、未通过审校不得生成批准，以及连续/省略片段。测试不调用付费模型，不证明实际机器译文质量。
