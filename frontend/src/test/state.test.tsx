import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { applyTheme } from "@/app/preferences";
import { PREFERENCES_KEY, usePreferences } from "@/stores/preferences";
import { SearchField } from "@/ui/SearchField";

describe("SearchField", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  function Harness({ onCommit }: { onCommit: (v: string) => void }) {
    const [value, setValue] = useState("");
    return (
      <>
        <SearchField id="q" label="Search" value={value} onCommit={(v) => { onCommit(v); setValue(v); }} />
        <button type="button" onClick={() => setValue("")}>clear</button>
      </>
    );
  }

  it("commits once after typing pauses, not on every keystroke", async () => {
    const onCommit = vi.fn();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<Harness onCommit={onCommit} />);
    await user.type(screen.getByLabelText("Search"), "Prizren");
    expect(onCommit).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(400));
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith("Prizren");
  });

  it("ignores one-letter searches, commits on Enter, and follows an outside reset", async () => {
    const onCommit = vi.fn();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<Harness onCommit={onCommit} />);
    const box = screen.getByLabelText("Search");
    await user.type(box, "K");
    act(() => vi.advanceTimersByTime(400));
    expect(onCommit).not.toHaveBeenCalled();
    await user.type(box, "Q{Enter}");
    expect(onCommit).toHaveBeenLastCalledWith("KQ");
    await user.click(screen.getByRole("button", { name: "clear" }));
    expect(box).toHaveValue("");
  });
});

describe("preferences store", () => {
  beforeEach(() => {
    localStorage.clear();
    usePreferences.setState({ theme: "system", lens: null, lang: "sq" });
  });

  it("persists theme, lens and language under one key that theme.js can read", () => {
    act(() => usePreferences.getState().setTheme("dark"));
    act(() => usePreferences.getState().setLens("region"));
    act(() => usePreferences.getState().setLang("en"));
    const stored = JSON.parse(localStorage.getItem(PREFERENCES_KEY)!);
    expect(stored.state).toEqual({ theme: "dark", lens: "region", lang: "en" });
  });

  it("falls back to defaults for corrupted or hand-edited values", async () => {
    localStorage.setItem(PREFERENCES_KEY, JSON.stringify({ state: { theme: "neon", lens: "<x>", lang: "de" }, version: 1 }));
    await act(async () => usePreferences.persist.rehydrate());
    expect(usePreferences.getState().theme).toBe("system");
    expect(usePreferences.getState().lens).toBeNull();
    expect(usePreferences.getState().lang).toBe("sq");
  });

  it("applies the theme to the document, and removes it for 'system'", () => {
    applyTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    applyTheme("system");
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });
});
