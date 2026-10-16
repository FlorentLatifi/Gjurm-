import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { LanguageRoot } from "@/app/LanguageRoot";
import { installPreferences } from "@/app/preferences";
import { Shell } from "@/app/Shell";
import { getLang } from "@/shared/i18n";
import { usePreferences } from "@/stores/preferences";

function app() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <LanguageRoot>
          <Shell />
        </LanguageRoot>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("interface language", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    localStorage.clear();
    usePreferences.setState({ lang: "sq" });
    installPreferences();
  });
  afterEach(() => {
    act(() => usePreferences.getState().setLang("en"));
    vi.unstubAllGlobals();
  });

  it("is Albanian by default, and English is one click away and remembered", async () => {
    app();
    const nav = screen.getByRole("navigation", { name: "Kryesore" });
    expect(nav).toHaveTextContent("Lajmet");
    expect(document.documentElement.lang).toBe("sq");

    await userEvent.click(screen.getByRole("button", { name: "English" }));
    expect(getLang()).toBe("en");
    expect(document.documentElement.lang).toBe("en");
    expect(screen.getByRole("navigation", { name: "Main" })).toHaveTextContent("Stories");
    expect(JSON.parse(localStorage.getItem("gjurme-prefs")!).state.lang).toBe("en");

    await userEvent.click(screen.getByRole("button", { name: "Shqip" }));
    expect(screen.getByRole("navigation", { name: "Kryesore" })).toBeInTheDocument();
  });
});
