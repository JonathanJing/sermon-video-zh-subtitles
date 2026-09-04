# Real PDF Page Examples

These PNG files are page-1 renders from the real 2026-08-30 post-live outputs. They are checked in only as README examples; the complete per-run PDFs remain outside Git.

| Example | Source artifact | Source SHA-256 | PDF QA |
|---|---|---|---|
| `sermon-zh-en-reading-real-page-1.png` | `sermon_zh_en_reading.pdf`, page 1 | `d2434df157ff79ad338f01fe0fde186665bb40544a0dcd38842f074afe6b5987` | `pass` |
| `sermon-interpretation-zh-real-page-1.png` | `sermon_interpretation_zh.pdf`, page 1 | `2fcf4adb7ddf8be61c8209c396a24793fc2ba9d5764ae4fa5b1f9e6d84e553f4` | `pass` |

Rendering contract:

- Source run: `artifacts/post-live-runs/2026-08-30/sermon_-BeFX5G2oAw/`
- Renderer: Poppler `pdftoppm`, page 1, 110 DPI; final images resized to 1100 px high.
- Reading-text QA, reading-PDF QA, and interpretation-PDF QA all report `pass`.
- The source run's top-level `run-status.json` remains `running`; these screenshots demonstrate the two rendered outputs and their individual QA, not whole-run completion.
- Do not replace these examples with another run unless both canonical PDFs and their individual QA reports are present and visually inspected.
