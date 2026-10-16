import { useEffect, useId, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

/**
 * The masthead's story search: a button that opens a search box under the header. Searching
 * goes to the story feed's own keyword filter, so results, paging and the shareable URL are the
 * feed's. The box closes on search, on Escape and when the reader goes to another page.
 */
export function SiteSearch() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const [at, setAt] = useState(location.key);
  if (location.key !== at) {
    setAt(location.key);
    setOpen(false);
  }
  const panelId = useId();
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  function close() {
    setOpen(false);
    button.current?.focus();
  }

  return (
    <>
      <button
        ref={button}
        type="button"
        className="btn btn--ghost btn--sm"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => (open ? close() : setOpen(true))}
      >
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" aria-hidden>
          <circle cx="7" cy="7" r="4.5" />
          <path d="m10.5 10.5 3.5 3.5" />
        </svg>
        <span className="site-header__label">Search</span>
      </button>
      <div id={panelId} className="site-search" hidden={!open}>
        <form
          role="search"
          className="site-search__form"
          onSubmit={(e) => {
            e.preventDefault();
            const q = input.current?.value.trim() ?? "";
            if (q.length < 2) return;
            navigate(`/?q=${encodeURIComponent(q)}`);
          }}
        >
          <div className="field field--grow">
            <label htmlFor={inputId} className="visually-hidden">Search stories</label>
            <input
              ref={input}
              id={inputId}
              type="search"
              name="q"
              placeholder="Search stories, e.g. Prizren"
              minLength={2}
              maxLength={120}
              required
              onKeyDown={(e) => {
                if (e.key === "Escape") close();
              }}
            />
          </div>
          <button type="submit" className="btn">Search</button>
        </form>
      </div>
    </>
  );
}
