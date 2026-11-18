import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { appRoutes } from "@/app/router";
import { Shell } from "@/app/Shell";
import { PrivacyPage } from "@/features/system/pages/Privacy";
import { OPERATOR } from "@/features/system/pages/site";
import { WhoPage } from "@/features/system/pages/Who";
import { setLang } from "@/shared/i18n";
import { PREFERENCES_KEY } from "@/stores/preferences";
import { READING_KEY } from "@/stores/reading";

const page = (ui: React.ReactNode, path: string) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );

afterEach(() => setLang("en"));

describe("Who we are", () => {
  it.each([
    ["en", "Who we are", /no outside funding, no advertising/, /can be wrong/],
    ["sq", "Kush jemi", /pa financim të jashtëm, pa reklama/, /mund të gabojnë/],
  ] as const)("states the operator, funding, reply and automation in %s", (lang, h1, funding, automatic) => {
    setLang(lang);
    page(<WhoPage />, "/who-we-are");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(h1);
    expect(screen.getByText(new RegExp(OPERATOR.name.replace(/[[\]]/g, "\\$&")))).toBeInTheDocument();
    expect(screen.getByText(funding)).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent(automatic);
    expect(document.getElementById("reply")!.nextElementSibling).toHaveTextContent(OPERATOR.replyWithin[lang]);
    // the rating claims point at the methodology instead of repeating it
    const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(links).toContain("/about#ratings");
    expect(links).toContain("/privacy");
  });

  it("has a contact link and no more than one h1", () => {
    page(<WhoPage />, "/who-we-are");
    expect(document.getElementById("reply")!.nextElementSibling!.querySelectorAll("a[href^='mailto:'], a[href^='https://']")).toHaveLength(1);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });
});

describe("Privacy", () => {
  it.each(["en", "sq"] as const)("names every key the site writes to the browser, in %s", (lang) => {
    setLang(lang);
    page(<PrivacyPage />, "/privacy");
    const browser = document.getElementById("browser")!.parentElement!;
    expect(within(browser).getByText(PREFERENCES_KEY)).toBeInTheDocument();
    expect(within(browser).getByText(READING_KEY)).toBeInTheDocument();
    expect(within(browser).getByText("sessionStorage")).toBeInTheDocument();
    expect(document.getElementById("rights")!.nextElementSibling).toHaveTextContent(OPERATOR.replyWithin[lang]);
    expect(document.querySelectorAll("h2")).toHaveLength(4);
  });
});

describe("site integration", () => {
  it("routes both pages", () => {
    const paths = appRoutes.map((r) => r.path);
    expect(paths).toContain("/who-we-are");
    expect(paths).toContain("/privacy");
  });

  it("links both from the footer", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    page(<Shell />, "/");
    const footer = screen.getByRole("contentinfo");
    expect(within(footer).getByRole("link", { name: "Who we are" })).toHaveAttribute("href", "/who-we-are");
    expect(within(footer).getByRole("link", { name: "Privacy" })).toHaveAttribute("href", "/privacy");
    vi.unstubAllGlobals();
  });
});
