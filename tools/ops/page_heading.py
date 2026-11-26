"""Header lines of a published sermon or podcast page, shared by every surface.

Web (`headingLines` in apps/listening-web/catalog.mjs), iOS (`SermonHeading.displayedSeries`)
and the static page written by experiments/sentence-first-agent/sfa_publish.py show the same
lines in the same order: series, title, date · speaker, scripture. The series is shown once:

- a title ending in " · <series>" drops that suffix from the title line;
- a title starting with "<series> · " (the approved podcast format) keeps its published
  wording, and the separate series line is left out.
"""
from __future__ import annotations

SEPARATOR = " · "


def heading_lines(title: str | None, series: str | None) -> tuple[str, str]:
    """Return (title line, series line); an empty series line means it is not shown."""
    value = (title or "").strip()
    name = (series or "").strip()
    if not value or not name:
        return value, name
    if value.endswith(SEPARATOR + name) and len(value) > len(name) + len(SEPARATOR):
        return value[: -(len(name) + len(SEPARATOR))].strip(), name
    if value.startswith(name + SEPARATOR):
        return value, ""
    return value, name


def details_line(date: str | None, speaker: str | None) -> str:
    return SEPARATOR.join(part for part in ((date or "").strip(), (speaker or "").strip()) if part)
