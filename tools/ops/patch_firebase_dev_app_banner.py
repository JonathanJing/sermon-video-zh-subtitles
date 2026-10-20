#!/usr/bin/env python3
"""Keep the Dev App banner focused on its weekly selector."""

from __future__ import annotations

from pathlib import Path
import re

COPY = {
    "DEV 测试站 · 此页用于核验已审核的多语言内容；公开发布请以正式站点为准。":
        "DEV 测试站 · 正式周次与模拟演练同处 App 目录；演练片段不代表正式审核或发布。",
    "Dev test site · Reviewed multilingual content is shown here for verification. Check the public site for the released version.":
        "Dev test site · Formal weeks and simulations appear in the App catalog; a simulation is not a formal review or release.",
    "DEV 테스트 사이트 · 검토된 다국어 콘텐츠를 확인하는 페이지입니다. 공식 게시 여부는 공식 사이트에서 확인하세요.":
        "DEV 테스트 사이트 · 정식 주차와 모의 연습은 앱 목록에 함께 표시됩니다. 모의 연습은 정식 검토나 게시가 아닙니다.",
    "Sitio de pruebas DEV · Aquí se verifica contenido multilingüe revisado. Consulta el sitio público para la versión publicada.":
        "Sitio de pruebas DEV · Las semanas formales y las simulaciones aparecen en el catálogo de la app; una simulación no es una revisión ni publicación formal.",
}


def patch_public(public: Path) -> None:
    index = public / "index.html"
    text = index.read_text(encoding="utf-8")
    old = re.search(r' · <a id="devDryRunLink" href="[^"]+">[^<]+</a>', text)
    if old is None:
        raise ValueError("Expected known standalone Dev dry-run link")
    text = text[:old.start()] + text[old.end():]
    for before, after in COPY.items():
        if before in text:
            text = text.replace(before, after)
    index.unlink()  # complete snapshots may hardlink the source
    index.write_text(text, encoding="utf-8")
    label = public / "dev-preview-label.mjs"
    script = label.read_text(encoding="utf-8")
    for before, after in COPY.items():
        if script.count(before) != 1:
            raise ValueError(f"Dev banner copy no longer matches: {before}")
        script = script.replace(before, after)
    label.unlink()
    label.write_text(script, encoding="utf-8")
