// A small blocking script applies the saved palette before CSS paints the page.
// Keep it external so Hosting's script-src 'self' policy remains intact.
(() => {
  const key = "sermon-audio-theme";
  const root = document.documentElement;
  function apply(theme) {
    const dark = theme !== "light";
    root.dataset.theme = dark ? "dark" : "light";
    document.querySelector('meta[name="theme-color"]').content = dark ? "#111819" : "#f5f7f3";
    const button = document.getElementById("theme-toggle");
    if (button) {
      const action = dark ? "切换到浅色模式" : "切换到深色模式";
      document.getElementById("theme-label").textContent = dark ? "深色" : "浅色";
      button.setAttribute("aria-label", action);
      button.title = `当前${dark ? "深色" : "浅色"} · ${action}`;
    }
  }
  let saved = "dark";
  try { saved = localStorage.getItem(key); } catch { /* Dark also works without storage. */ }
  apply(saved);
  document.addEventListener("DOMContentLoaded", () => {
    apply(root.dataset.theme);
    document.getElementById("theme-toggle").addEventListener("click", () => {
      const theme = root.dataset.theme === "dark" ? "light" : "dark";
      apply(theme);
      try { localStorage.setItem(key, theme); } catch { /* The current page still switches. */ }
    });
  }, { once: true });
})();
