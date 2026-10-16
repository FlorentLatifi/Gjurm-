import { type Lang } from "@/shared/i18n";
import { usePreferences } from "@/stores/preferences";

// Each language is named in itself, so a reader who cannot read the current one finds theirs.
const NAME: Record<Lang, { full: string; short: string }> = {
  sq: { full: "Shqip", short: "SQ" },
  en: { full: "English", short: "EN" },
};

/** Switches the interface between Albanian and English (the news itself stays as published). */
export function LanguageToggle() {
  const lang = usePreferences((s) => s.lang);
  const setLang = usePreferences((s) => s.setLang);
  const other: Lang = lang === "sq" ? "en" : "sq";
  return (
    <button type="button" className="btn btn--ghost btn--sm" lang={other} onClick={() => setLang(other)}>
      <span className="site-header__label">{NAME[other].full}</span>
      <span className="site-header__short" aria-hidden="true">{NAME[other].short}</span>
    </button>
  );
}
