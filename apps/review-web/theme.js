// Blocking script: applies the saved palette before CSS paints. External on purpose,
// so the page works under script-src 'self' (docs/web-frontend-modernization-policy.zh.md).
// Dark is the default; light is the reviewer's override and does not follow the system.
(() => {
  const key = "sermon-review-theme";
  const root = document.documentElement;
  function apply(theme) {
    const dark = theme !== "light";
    root.dataset.theme = dark ? "dark" : "light";
    const themeColor = document.querySelector('meta[name="theme-color"]');
    if (themeColor) themeColor.content = dark ? "#141b1a" : "#f5f3eb";
    const colorScheme = document.querySelector('meta[name="color-scheme"]');
    if (colorScheme) colorScheme.content = dark ? "dark" : "light";
    const button = document.getElementById("theme-toggle");
    if (button) {
      button.textContent = dark ? "深色" : "浅色";
      button.setAttribute("aria-label", dark ? "切换到浅色模式" : "切换到深色模式");
    }
  }
  let saved = "dark";
  try { saved = localStorage.getItem(key); } catch { /* dark also works without storage */ }
  apply(saved);
  document.addEventListener("DOMContentLoaded", () => {
    apply(root.dataset.theme);
    window.addEventListener("storage", event => {
      if (event.key === key) apply(event.newValue === "light" ? "light" : "dark");
    });
    const button = document.getElementById("theme-toggle");
    if (!button) return;
    button.addEventListener("click", () => {
      const theme = root.dataset.theme === "dark" ? "light" : "dark";
      try { localStorage.setItem(key, theme); } catch { /* still switches for this page */ }
      apply(theme);
    });
  });
})();
