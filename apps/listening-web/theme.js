// A small blocking script applies the saved palette before CSS paints the page.
// Keep it external so Hosting's script-src 'self' policy remains intact.
(() => {
  const key = "sermon-audio-theme";
  const root = document.documentElement;
  function apply(theme) {
    const dark = theme !== "light";
    root.dataset.theme = dark ? "dark" : "light";
    const themeColor = document.querySelector('meta[name="theme-color"]');
    if (themeColor) themeColor.content = dark ? "#141b1a" : "#f5f3eb";
    // Pin the UA hint to the same scheme the CSS declares, so browser chrome and
    // native controls never disagree with the rendered page.
    const colorScheme = document.querySelector('meta[name="color-scheme"]');
    if (colorScheme) colorScheme.content = dark ? "dark" : "light";
    const icon = document.getElementById("brand-icon");
    if (icon) icon.src = dark ? "/brand-icon.svg" : "/brand-icon-light.svg";
    const button = document.getElementById("theme-toggle");
    if (button) {
      const label = document.getElementById("theme-label");
      label.setAttribute("data-i18n", dark ? "theme.dark" : "theme.light");
      button.setAttribute("data-i18n-aria-label", dark ? "theme.toLight" : "theme.toDark");
      button.setAttribute("data-i18n-title", dark ? "theme.darkTitle" : "theme.lightTitle");
      // Chinese fallback also works if the application module fails to load.
      const action = dark ? "切换到浅色模式" : "切换到深色模式";
      label.textContent = dark ? "深色" : "浅色";
      button.setAttribute("aria-label", action);
      button.title = `当前${dark ? "深色" : "浅色"} · ${action}`;
      document.dispatchEvent(new CustomEvent("sermon-theme-change"));
    }
  }
  let saved = "dark";
  try { saved = localStorage.getItem(key); } catch { /* Dark also works without storage. */ }
  apply(saved);
  function initializeControls() {
    // A toggle in another tab is the source of truth for this one; no value means
    // the stored override was removed, so fall back to the app's dark default.
    window.addEventListener("storage", event => {
      if (event.key !== key) return;
      apply(event.newValue === "light" ? "light" : "dark");
    });
    const button = document.getElementById("theme-toggle");
    if (!button) return;
    apply(root.dataset.theme);
    button.addEventListener("click", () => {
      const theme = root.dataset.theme === "dark" ? "light" : "dark";
      apply(theme);
      try { localStorage.setItem(key, theme); } catch { /* The current page still switches. */ }
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeControls, { once: true });
  } else {
    initializeControls();
  }
})();
