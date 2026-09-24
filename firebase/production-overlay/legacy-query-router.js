// Existing posters and bookmarks use /?week=<legacy-page-id>.
const legacyWeekIds = new Set(__LEGACY_WEEK_IDS__);
if (location.pathname === "/" &&
    legacyWeekIds.has(new URLSearchParams(location.search).get("week"))) {
  location.replace(`/legacy-reader.html${location.search}${location.hash}`);
}
