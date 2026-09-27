# Mariners 周末 Resi 场次 UUID 观察

目的：以低频请求记录 [Weekend Live](https://www.marinerschurch.org/weekendlive/) 播放器在各场崇拜附近指向的 Resi 场次 UUID，用实际观察回答“不同时间是否切换场次”。这不是视频下载、证道窗口确认、翻译或发布流程。播放器的固定 `data-embed-id` 是频道 ID，`eventprofiles/latest` 返回的 `uuid` 才是当时的场次 ID；已有的[媒体下载说明](resi-live-download.zh.md)记录了这一区别。

## 时间和频率

[Mariners Online 官方页面](https://www.marinerschurch.org/online/)目前列出太平洋时间周六 16:00、17:30，周日 07:00、08:30、10:00、11:30。周日 07:00 也纳入观察，但该页面的排期并不证明 `weekendlive/` 对每场都切换 UUID；采集结果用来核实这一点。

在美西时间每周六 15:50、16:10–18:50 和周日 06:50、07:10–12:50，每隔 20 分钟查询一次。总计 **29 次 API 请求/周**，另在每天首次查询时请求一次页面以确认嵌入 ID。首个查询在开场前，最后一个查询在周日 11:30 场次开始 80 分钟后。Mac 睡眠或离线时会漏采，不补造观察；如需全天候覆盖，应迁到常开主机并沿用同一个一次性脚本。

每次只请求页面（每日首次）和 `https://webevents.resi.io/api/v1/eventprofiles/latest/<embed-id>`；不请求 HLS/DASH 清单、分片或视频文件。读取响应后只保存 UUID、场次名称、播放器 ID、观察时间、计划时间窗及成功／错误代码。`scheduledWindow` 表示观察时间落在哪个**计划**时间窗，不宣称 UUID 必然属于该场崇拜。同一 UUID 在不同窗出现，或同一窗出现两个 UUID，均原样保留。错误也记录，避免把未观察到误判为没有切换。

## 本地运行和查看

数据保存在 Git 忽略的 `artifacts/resi-uuid-inventory/`；每次查询追加一行到 `observations.jsonl`。`state.json` 仅缓存当日已核对的嵌入 ID，不保存媒体 URL。

```bash
python3 scripts/collect_resi_event_uuids.py
python3 scripts/collect_resi_event_uuids.py --report
python3 scripts/collect_resi_event_uuids.py --report 2026-09-26
```

第一条命令在观察窗外直接退出，不访问网站。仅为手工排障可加 `--force`，这次记录标为 `manual`，不纳入某个周末的自动比较。

## macOS 定时安装

本机系统时区须为 `America/Los_Angeles`，因为 `launchd` 的日历触发使用系统时区；脚本还会按美西时间检查窗口。将脚本复制到固定的本地目录，避免切换 Git 分支后定时任务找不到文件。脚本输出的 plist 包含当前 Python、固定副本和数据目录的绝对路径；仓库迁移或 Python 路径变化后需要重新生成。安装前检查没有同名任务，避免重复请求：

```bash
launchctl print "gui/$(id -u)/org.sermonvideo.resi-uuid-inventory"
```

在仓库根目录安装：

```bash
mkdir -p artifacts/resi-uuid-inventory "$HOME/Library/LaunchAgents"
cp scripts/collect_resi_event_uuids.py artifacts/resi-uuid-inventory/collector.py
python3 scripts/collect_resi_event_uuids.py --print-launchd-plist \
  --script-path "$PWD/artifacts/resi-uuid-inventory/collector.py" \
  > "$HOME/Library/LaunchAgents/org.sermonvideo.resi-uuid-inventory.plist"
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/org.sermonvideo.resi-uuid-inventory.plist"
launchctl print "gui/$(id -u)/org.sermonvideo.resi-uuid-inventory"
```

修改采集脚本后，重新复制 `collector.py`；若 Python 路径或日历计划改变，则先 `bootout`、重新生成 plist，再 `bootstrap`。

停用任务（不删除已收集数据）：

```bash
launchctl bootout "gui/$(id -u)/org.sermonvideo.resi-uuid-inventory"
```

`launchd.stdout.log` 和 `launchd.stderr.log` 也在 Git 忽略目录内。采集记录是网页当时公开接口的观察，不代表媒体文件可下载、整场完整、讲道内容或人工审核结论。场次是否相同必须按逐次 UUID 序列和实际画面另行核对。
