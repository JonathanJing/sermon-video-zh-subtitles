# 正式三语 Dev 发布资源准备

`scripts/build_formal_dev_release_assets.py` 将已经人工批准的三语页面信息、同源的正式 Layer 2 候选和三份 `human_reviewed` Layer 3 音频包，组装成候选内容 JSON、WAV、字幕与 Release Package。它不会部署，也不会把 HTTP、设备或场地状态标为通过。用户已批准的 9 月 20 日页面信息在忽略目录 `artifacts/multilingual-clip-20260920/20260920-blocks9-14-178s/review/formal-dev-metadata.approved.json`；该文件保存提案 SHA、原文及批准记录，脚本核对每个显示字段仍在原提案中。

调用时为 `--candidate` 和 `--audio-package` 各提供 `zh-Hans=PATH`、`ko=PATH`、`es=PATH` 三次，并传入同一 `--source`、`--metadata`、`--metadata-proposal`、`--page-id`、`--date`、`--out`。输出目录必须尚不存在。脚本会先核对所有语言均已达到人审状态，再在临时目录生成文件，并以目录重命名提交最终结果。`review/content/<locale>.json` 只承载用户已批准的页面显示字段，逐组 cue 由已审 Layer 2 文字和 Layer 3 实测 schedule／captions 精确组装；任何一处文本、来源、时间或哈希不合即停止。

随后调用 `scripts/stage_formal_multilingual_dev.py`，使用上述 `assets/`、`releases/<locale>.json`、`review/content/<locale>.json`，再为每种语言传入 Layer 2 人审收据、Layer 3 人审收据和完整 ASR 筛查收据。staging 再次核对所有来源、locale、文件解码、cue 与音轨 SHA。只有三语全部通过才产出 `multilingual-v2.json` 和 `stage-receipt.json`；收据仍写 `deploymentStatus=not_deployed`。部署与逐文件 HTTP/Range 验证、App 实机验收分别执行并留证。
