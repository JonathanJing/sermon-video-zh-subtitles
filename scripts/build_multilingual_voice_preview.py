#!/usr/bin/env python3
"""Build an offline listening page from a verified multilingual voice demo delivery."""
from __future__ import annotations

import argparse
import hashlib
from html import escape
import json
from pathlib import Path
import subprocess
from typing import Any
from urllib.parse import quote


DELIVERY_SCHEMA = "sermon-multilingual-voice-demo-delivery-v1"
SCRIPT_SCHEMA = "sermon-multilingual-voice-demo-script-v1"
REGISTRY_SCHEMA = "sermon-speaker-voice-registry-v1"
LOCALE_ORDER = ("zh-Hans", "ko", "es", "vi")
LOCALE_LABELS = {"zh-Hans": "中文", "ko": "한국어 · 韩语",
                 "es": "Español · 西班牙语", "vi": "Tiếng Việt · 越南语"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def inside(root: Path, relative: str) -> Path:
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(),
            "Preview asset path must be relative")
    resolved = (root / relative).resolve()
    require(resolved.is_relative_to(root.resolve()),
            f"Preview asset escapes delivery directory: {relative}")
    return resolved


def snapshot_path(root: Path, name: str, repository_relative: str) -> Path:
    local = root / name
    if local.is_file():
        return local
    return Path(__file__).resolve().parents[1] / repository_relative


def validate(root: Path, *, decode: bool = True) -> tuple[dict[str, Any],
                                                           dict[str, Any], dict[str, Any], Path, Path,
                                                           list[str]]:
    root = root.resolve()
    delivery_path = root / "delivery-manifest.json"
    delivery = read_json(delivery_path)
    script_path = snapshot_path(root, "demo-script.json",
                                "experiments/sermon-dubbing-poc/multilingual-voice-demo-script-v1.json")
    registry_path = snapshot_path(root, "registry.json", "config/speaker-voice-registry.json")
    script = read_json(script_path)
    registry = read_json(registry_path)
    require(delivery.get("schemaVersion") == DELIVERY_SCHEMA
            and delivery.get("status") == "encoded_and_fully_decoded"
            and delivery.get("scope") == "voice_capability_audition_not_sermon_translation"
            and delivery.get("fullDecodeCoverage") == 1,
            "Delivery is not a fully decoded voice audition package")
    require(script.get("schemaVersion") == SCRIPT_SCHEMA
            and script.get("scope") == delivery["scope"]
            and registry.get("schemaVersion") == REGISTRY_SCHEMA,
            "Voice audition script or registry differs from delivery scope")
    require(delivery.get("registry", {}).get("sha256") == sha256(registry_path),
            "Delivery registry snapshot hash changed")
    sources = delivery.get("sourceManifests")
    require(isinstance(sources, list) and len(sources) == 2,
            "Expected both Qwen and Vietnamese voice manifests")
    source_tracks: dict[tuple[str, str], dict[str, Any]] = {}
    source_registry_hashes = set()
    for record in sources:
        source_path = inside(root, record["path"])
        require(source_path.is_file() and sha256(source_path) == record["sha256"],
                f"Voice source manifest changed: {record['path']}")
        source = read_json(source_path)
        require(source.get("scriptJsonSha256") == json_sha256(script),
                "Voice source manifest uses another audition script")
        require(isinstance(source.get("registryJsonSha256"), str),
                "Voice source manifest lacks registry provenance")
        source_registry_hashes.add(source["registryJsonSha256"])
        for track in source.get("tracks", []):
            key = (track.get("speakerId"), track.get("targetLocale"))
            require(key not in source_tracks, "Duplicate source voice track")
            source_tracks[key] = track
    locale_rows = script.get("locales")
    require(isinstance(locale_rows, list)
            and {row.get("targetLocale") for row in locale_rows} == set(LOCALE_ORDER)
            and len(locale_rows) == len(LOCALE_ORDER)
            and all(isinstance(row.get("text"), str) and row["text"].strip()
                    for row in locale_rows),
            "Voice audition script does not cover four languages")
    speakers = registry.get("speakers")
    require(isinstance(speakers, list) and len(speakers) == 6,
            "Voice registry does not contain six speakers")
    expected = {(speaker["speakerId"], locale) for speaker in speakers
                for locale in LOCALE_ORDER}
    rows = delivery.get("tracks")
    require(isinstance(rows, list) and len(rows) == 24
            and delivery.get("trackCount") == 24
            and delivery.get("speakerCount") == 6
            and set(delivery.get("targetLocales", [])) == set(LOCALE_ORDER),
            "Voice delivery does not contain a complete 6 × 4 matrix")
    actual = [(row.get("speakerId"), row.get("targetLocale")) for row in rows]
    require(len(set(actual)) == 24 and set(actual) == expected,
            "Voice delivery has duplicate or missing speaker-language pairs")
    speaker_index = {speaker["speakerId"]: speaker for speaker in speakers}
    locale_text = {row["targetLocale"]: row["text"] for row in locale_rows}
    for row in rows:
        speaker = speaker_index[row["speakerId"]]
        key = (row["speakerId"], row["targetLocale"])
        generated = source_tracks.get(key)
        require(generated is not None, f"Missing source voice track: {key}")
        capability = next((item for item in speaker["localeCapabilities"]
                           if item["targetLocale"] == row["targetLocale"]), None)
        require(capability is not None
                and row.get("displayName") == speaker["displayName"]
                and row.get("capabilityStatus") == capability["status"]
                and row.get("displayName") == generated.get("displayName")
                and row.get("capabilityStatus") == generated.get("capabilityStatus")
                and row.get("humanListeningStatus") == generated.get("humanListeningStatus")
                and row.get("sourceWav", {}).get("path") == generated.get("file")
                and row.get("sourceWav", {}).get("sha256") == generated.get("audioSha256")
                and generated.get("textSha256") == hashlib.sha256(
                    locale_text[row["targetLocale"]].encode("utf-8")).hexdigest(),
                "Voice delivery differs from registered speaker capability")
        if row["targetLocale"] == "vi":
            adapter = capability.get("adapterOverride", {})
            require(row.get("adapter") == generated.get("adapter") == adapter.get("adapter")
                    and generated.get("model") == adapter.get("model")
                    and generated.get("modelRevision") == adapter.get("revision")
                    and generated.get("conditioningRef") == adapter.get("conditioningRef")
                    and generated.get("referenceAudioSha256") ==
                    adapter.get("conditioningRef", "").rsplit("/", 1)[-1],
                    f"Vietnamese voice identity differs from registry: {key}")
        else:
            checkpoint = speaker["checkpoint"]
            require(row.get("adapter") == "qwen3_tts_sft"
                    and generated.get("speakerKey") == speaker["speakerKey"]
                    and generated.get("checkpointRef") == checkpoint["checkpointRef"]
                    and generated.get("checkpointSha256") == checkpoint["checkpointSha256"]
                    and generated.get("modelLanguage") == capability["modelLanguage"],
                    f"Qwen voice identity differs from registry: {key}")
        mp3 = row.get("mp3", {})
        wav = row.get("sourceWav", {})
        path = inside(root, mp3.get("path", ""))
        source = inside(root, wav.get("path", ""))
        require(path.suffix == ".mp3" and path.is_file()
                and sha256(path) == mp3.get("sha256")
                and source.is_file() and sha256(source) == wav.get("sha256")
                and mp3.get("fullDecode") == "pass"
                and isinstance(mp3.get("durationSeconds"), (int, float))
                and mp3["durationSeconds"] > 0,
                f"Voice audio missing, changed or invalid: {row['speakerId']}/{row['targetLocale']}")
        if decode:
            result = subprocess.run(
                ["ffmpeg", "-nostdin", "-xerror", "-v", "error", "-i", str(path),
                 "-map", "0:a:0", "-f", "null", "-"],
                capture_output=True, text=True, check=False)
            require(result.returncode == 0,
                    f"Voice MP3 cannot be fully decoded: {row['speakerId']}/{row['targetLocale']}")
    require(len(source_tracks) == len(rows), "Source voice track matrix differs from delivery")
    return delivery, script, registry, script_path, registry_path, sorted(source_registry_hashes)


def render(root: Path, delivery: dict[str, Any], script: dict[str, Any],
           registry: dict[str, Any]) -> str:
    locale_text = {row["targetLocale"]: row["text"] for row in script["locales"]}
    tracks = {(row["speakerId"], row["targetLocale"]): row
              for row in delivery["tracks"]}
    cards = []
    for speaker in registry["speakers"]:
        speaker_id = speaker["speakerId"]
        name = escape(speaker["displayName"])
        rows = []
        for locale in LOCALE_ORDER:
            track = tracks[(speaker_id, locale)]
            audio = track["mp3"]
            src = quote(audio["path"], safe="/-._~")
            status = ("本次样音已听审" if track["humanListeningStatus"] == "approved"
                      else "本次样音待听审")
            capability_note = ("旧中文样片已有能力认可" if track["capabilityStatus"] == "human_reviewed"
                               else "语言能力尚未晋升")
            priority = track.get("asrScreening") or {}
            priority_html = ('<span class="chip caution">机器复核优先</span>'
                             if priority.get("reviewPriority") else "")
            score = priority.get("similarity")
            score_text = (f"ASR 文本相似度 {score:.2f} · 仅辅助定位" if isinstance(score, (int, float))
                          else "未记录 ASR 文本相似度")
            rows.append(f'''<section class="sample" data-locale="{escape(locale)}">
              <div class="sample-top"><div><span class="locale">{LOCALE_LABELS[locale]}</span>
              <span class="duration">{audio["durationSeconds"]:.1f} 秒</span></div>
              <div class="badges"><span class="chip">{status}</span>{priority_html}</div></div>
              <audio controls preload="none" src="{escape(src, quote=True)}"
                     aria-label="{name} {LOCALE_LABELS[locale]}音色试听"></audio>
              <details><summary>查看试听文稿</summary><p lang="{escape(locale)}">{escape(locale_text[locale])}</p></details>
              <p class="sample-note">{escape(capability_note)} · {escape(score_text)}</p>
            </section>''')
        initials = "".join(part[0] for part in speaker["displayName"].split()[:2]).upper()
        cards.append(f'''<article class="speaker-card" data-speaker="{escape(speaker_id)}"
              data-name="{escape(speaker["displayName"].lower(), quote=True)}">
          <header class="speaker-head"><span class="avatar" aria-hidden="true">{escape(initials)}</span>
          <div><h2>{name}</h2><p>同一讲员的四种语言样音</p></div></header>
          <div class="samples">{"".join(rows)}</div>
        </article>''')
    return '''<!doctype html>
<html lang="zh-Hans"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>多语音色试听室 · 六位讲员</title>
<style>
:root{font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#182e35;background:#f5f5f0}
*{box-sizing:border-box}body{margin:0}button,input{font:inherit}button{cursor:pointer}
.hero{background:#15383d;color:#f5f8f4;padding:54px max(24px,calc((100vw - 1180px)/2)) 44px}
.eyebrow{letter-spacing:.15em;text-transform:uppercase;font-size:.73rem;font-weight:800;color:#9ed2c8}
h1{font-size:clamp(2rem,5vw,3.6rem);line-height:1.1;letter-spacing:-.035em;margin:12px 0 14px}
.hero p{max-width:730px;color:#d2e3df;line-height:1.65;margin:0}
.metrics{display:flex;flex-wrap:wrap;gap:10px;margin-top:27px}.metric{border:1px solid #527174;border-radius:999px;padding:8px 13px;font-size:.9rem}
main{max-width:1228px;margin:auto;padding:30px 24px 72px}
.notice{border:1px solid #d1d8ce;background:#fff;padding:17px 20px;border-radius:14px;line-height:1.6;color:#36515a}
.toolbar{display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:18px;margin:28px 0 22px}
.toolbar h2{font-size:1.3rem;margin:0 0 4px}.toolbar p{margin:0;color:#617379;font-size:.88rem}
.filters{display:flex;gap:7px;flex-wrap:wrap}.filters button{border:1px solid #cad4cf;background:#fff;color:#315257;border-radius:999px;padding:9px 14px}
.filters button[aria-pressed="true"]{background:#1e6a62;color:#fff;border-color:#1e6a62}
.search{border:1px solid #cad4cf;border-radius:10px;background:#fff;padding:10px 13px;min-width:190px;max-width:100%}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.speaker-card{border:1px solid #d9dfd8;border-radius:20px;background:#fff;box-shadow:0 5px 24px #123b3110;overflow:hidden}
.speaker-head{display:flex;align-items:center;gap:15px;padding:22px 23px;border-bottom:1px solid #e7ebe5;background:#fbfcf9}
.speaker-head h2{margin:0 0 4px;font-size:1.2rem}.speaker-head p{margin:0;color:#718183;font-size:.84rem}
.avatar{display:grid;place-items:center;width:48px;height:48px;border-radius:14px;background:#dceee8;color:#1d665e;font-weight:800}
.samples{padding:6px 22px 20px}.sample{padding:17px 0;border-bottom:1px solid #e8ece8}.sample:last-child{border-bottom:0}
.sample-top{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}
.locale{font-weight:750}.duration{font-size:.82rem;color:#7b898b;margin-left:8px}.badges{display:flex;gap:6px;flex-wrap:wrap}
.chip{font-size:.73rem;border-radius:999px;padding:4px 8px;background:#eef2ef;color:#53706a}.chip.caution{background:#fff1dc;color:#90621d}
audio{display:block;width:100%;height:38px}details{font-size:.87rem;color:#496065;margin-top:10px}summary{cursor:pointer;color:#1c6e64;font-weight:650}details p{margin:9px 0 0;line-height:1.6}
.sample-note{font-size:.76rem;color:#839190;margin:8px 0 0}.empty{padding:28px;text-align:center;color:#687d7e}
footer{max-width:1228px;margin:auto;padding:0 24px 40px;color:#768789;font-size:.8rem}
@media(max-width:850px){.grid{grid-template-columns:1fr}.hero{padding-top:40px}.toolbar{align-items:flex-start}}
</style></head><body>
<header class="hero"><div class="eyebrow">VOICE LIBRARY · LOCAL REVIEW</div>
<h1>多语音色试听室</h1>
<p>统一预览六位讲员已固定选用的多语言音色配置。每条样音使用同一段意思的对应语言文稿，便于比较声音表现；它们不是证道原话或正式整篇音轨。</p>
<div class="metrics"><span class="metric">6 位讲员</span><span class="metric">4 种语言</span><span class="metric">24 条完整解码样音</span></div></header>
<main><div class="notice"><strong>审核范围：</strong>这是一页本地试听资料。音色选用、语言能力登记与每篇新音轨的听审是不同记录；页面状态直接来自 v2 交付清单。越南语样音使用另一种 reference-clone adapter，机器转写已标为优先复听。播放本页不会改变任何正式生产或发布状态。</div>
<div class="toolbar"><div><h2>按讲员试听</h2><p id="count" aria-live="polite">显示 24 条样音</p></div>
<div class="filters" role="group" aria-label="语言筛选"><button type="button" data-filter="all" aria-pressed="true">全部</button>
<button type="button" data-filter="zh-Hans" aria-pressed="false">中文</button>
<button type="button" data-filter="ko" aria-pressed="false">韩语</button>
<button type="button" data-filter="es" aria-pressed="false">西语</button>
<button type="button" data-filter="vi" aria-pressed="false">越南语</button></div>
<input class="search" id="search" type="search" placeholder="搜索讲员" aria-label="搜索讲员"></div>
<div class="grid" id="grid">''' + "".join(cards) + '''</div><p class="empty" id="empty" hidden>没有符合条件的讲员。</p></main>
<footer>资料来源：2026-09-21 v2 多语言声音样音；页面生成前逐文件核对哈希和完整解码。仅供本地试听。</footer>
<script>
const buttons=[...document.querySelectorAll('[data-filter]')];
const cards=[...document.querySelectorAll('.speaker-card')];
const search=document.getElementById('search');let filter='all';
function update(){let shown=0,visibleCards=0;const q=search.value.trim().toLowerCase();
  for(const card of cards){const matches=card.dataset.name.includes(q);let cardShown=0;
    for(const sample of card.querySelectorAll('.sample')){const visible=matches&&(filter==='all'||sample.dataset.locale===filter);sample.hidden=!visible;if(visible)cardShown++}
    card.hidden=cardShown===0;shown+=cardShown;if(cardShown)visibleCards++}
  document.getElementById('count').textContent=`显示 ${shown} 条样音 · ${visibleCards} 位讲员`;
  document.getElementById('empty').hidden=visibleCards!==0}
for(const button of buttons)button.addEventListener('click',()=>{filter=button.dataset.filter;
  for(const item of buttons)item.setAttribute('aria-pressed',String(item===button));update()});
search.addEventListener('input',update);
for(const player of document.querySelectorAll('audio'))player.addEventListener('play',()=>{
  for(const other of document.querySelectorAll('audio'))if(other!==player)other.pause()});
update();
</script></body></html>'''


def build(root: Path, out: Path, *, decode: bool = True) -> dict[str, Any]:
    delivery, script, registry, script_path, registry_path, source_hashes = validate(
        root, decode=decode)
    page = render(root, delivery, script, registry)
    root = root.resolve()
    out = out.resolve()
    require(out.parent == root and out.suffix == ".html",
            "Preview page must be an HTML file in the delivery directory")
    out.write_text(page, encoding="utf-8")
    receipt = {
        "schemaVersion": "sermon-multilingual-voice-preview-verification-v1",
        "deliveryManifestSha256": sha256(root / "delivery-manifest.json"),
        "demoScriptSha256": sha256(script_path),
        "registrySha256": sha256(registry_path),
        "sourceRegistryJsonSha256": source_hashes,
        "sourceRegistrySnapshotMatch": source_hashes == [json_sha256(registry)],
        "voiceIdentityBinding": "per_track_checkpoint_or_adapter",
        "speakerCount": delivery["speakerCount"],
        "trackCount": delivery["trackCount"],
        "mp3HashCoverage": 1,
        "mp3FullDecodeCoverage": 1 if decode else None,
        "pageSha256": sha256(out),
    }
    (root / "preview-verification.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"page": str(out), "verification": str(root / "preview-verification.json"),
            "speakerCount": delivery["speakerCount"], "trackCount": delivery["trackCount"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, help="Defaults to <root>/index.html")
    args = parser.parse_args()
    root = args.root.resolve()
    result = build(root, args.out or root / "index.html")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
