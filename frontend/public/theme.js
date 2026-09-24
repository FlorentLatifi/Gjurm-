// Apply the stored colour theme before first paint (no flash). External file so the site's
// Content-Security-Policy can forbid inline scripts entirely. Storage may be unavailable.
try {
  var t = localStorage.getItem("gjurme-theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch (_) {}
