// Open the current complete-video release from the Firebase App home URL.
// Explicit week links continue to open the legacy weekly reader.
(() => {
  if (location.pathname !== "/" && location.pathname !== "/index.html") return;
  if (new URLSearchParams(location.search).has("week")) return;
  location.replace(
    `/pages/2026-09-27-weekend-sermon-drive-530/index.html${location.search}${location.hash}`,
  );
})();
