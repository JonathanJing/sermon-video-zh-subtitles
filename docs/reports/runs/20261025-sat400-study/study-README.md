# 2026-10-25 周：大纲与默想（四产品）

- 页面：`revelation-jesus-wins-20261025`（耶稣得胜 · 启示录 12–13 章）
- 语言：zh-Hans / ko / es
- 来源：已批准的英文来源包（`20261024-sat400-v2-english`，sha256 `199e4b86…`）与已发布的三种译文
- 生产：`experiments/sentence-first-agent/build_study.py`（文本、artifact、review、元数据/窗口批准、products.json）
- 发布：`experiments/sentence-first-agent/publish_study.py`（页面学习段 + `/study/<pageId>/<locale>/` + release v3 四产品 + 目录）
- 文本：大纲 7 节、默想 4 节，均给出 `sourceUnitIds`（本页 447 个 `asr-u…` 单元）

## 授权与审核记录（照实写）

- 2026-10-25 08:09 PDT 用户指示：「本周的大纲和默想，也制作并发布。大纲和默想的制作也一并在agent里写出。生产的时候一并做完。」
- 这份发布是在该指示下完成的；`sermon-study-review-v1` 的三项检查（faithfulness / scriptureIntegrity / localeReadability）由代理对照英文全文与当周译文完成，`humanApproval` 记录的是这次发布授权。
- 用户尚未逐句读过这三份文本；如需修改，按 `AGENTS.md` §10.5 的改内容路径重建并重发（分钟级）。

## 产物

- `artifacts/<locale>/{outline,meditation}.json`：`sermon-study-artifact-v1`，已通过 schema 与 `ingest_review`
- `reviews/<locale>/<kind>-review.json`：`sermon-study-review-v1`
- `metadata-proposal.json` / `metadata-approval.json`：页面信息（系列、标题、讲员、经文、摘要、大纲标题）
- `assets/public/study/…`：公开的 `/study/<pageId>/<locale>/{outline,meditation,products}.json`
- `study-hashes.json`：元数据批准、来源、窗口收据、每语的 artifact/review 哈希
- 发布快照：`../20261024-sat400-v2-study-publish/`
