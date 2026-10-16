// Apply the stored colour theme and interface language before first paint (no flash). External file so the site's
// Content-Security-Policy can forbid inline scripts entirely. Storage may be unavailable.
// Reads the preferences store (src/stores/preferences.ts), then the key used before it existed.
try {
  var t = null;
  var prefs = localStorage.getItem("gjurme-prefs");
  var state = prefs ? JSON.parse(prefs).state || {} : {};
  t = prefs ? state.theme : localStorage.getItem("gjurme-theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  if (state.lang === "en") document.documentElement.lang = "en";
} catch (_) {}
