// Open the current complete-video release from the Firebase App home URL.
// Keep it available in the legacy reader's week picker for returning visitors.
(() => {
  if (location.pathname !== "/" && location.pathname !== "/index.html") return;
  const pageId = "2026-09-27-weekend-sermon-drive-530";
  const pageUrl = `/pages/${pageId}/index.html`;
  if (!new URLSearchParams(location.search).has("week")) {
    location.replace(`${pageUrl}${location.search}${location.hash}`);
    return;
  }

  document.addEventListener("DOMContentLoaded", () => {
    const picker = document.getElementById("week-select");
    if (!picker) return;
    const addCurrentWeek = () => {
      if (Array.from(picker.options).some(option => option.value === pageId)) return;
      const selectedWeek = picker.value;
      const option = document.createElement("option");
      option.value = pageId;
      option.textContent = "2026.09.27 · 耶稣配得 · 完整 31:31 视频与三语配音";
      picker.prepend(option);
      if (selectedWeek) picker.value = selectedWeek;
    };
    picker.addEventListener("change", event => {
      if (picker.value !== pageId) return;
      event.stopImmediatePropagation();
      location.assign(pageUrl);
    }, true);
    new MutationObserver(addCurrentWeek).observe(picker, { childList: true });
    addCurrentWeek();
  });
})();
