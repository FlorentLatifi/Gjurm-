import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.describe("GJURMË stories", () => {
  test("home lists stories with coverage bars and opens a story", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Top stories");
    const card = page.locator(".story-card").first();
    await expect(card.getByRole("img", { name: /^Coverage by perspective/ })).toBeVisible();
    await expect(card).toContainText(/\d+ outlets/);
    const title = (await card.locator(".story-card__title").textContent()) ?? "";
    await card.locator(".story-card__title a").click();
    await expect(page).toHaveURL(/\/stories\/\d+$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
    const original = page.locator(".headline a").first();
    await expect(original).toHaveAttribute("target", "_blank");
    await expect(original).toHaveAttribute("rel", "noopener noreferrer");
    await expect(page.getByText(/First reported by/)).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("going back to the feed restores where the reader was", async ({ page }) => {
    await page.goto("/");
    const card = page.locator(".story-card").nth(6);
    await card.scrollIntoViewIfNeeded();
    const before = await page.evaluate<number>("window.scrollY");
    expect(before).toBeGreaterThan(300);
    await card.locator(".story-card__title a").click();
    await expect(page).toHaveURL(/\/stories\/\d+$/);
    await page.goBack();
    await expect(page.locator(".story-card").nth(6)).toBeVisible();
    await expect.poll(() => page.evaluate<number>("window.scrollY")).toBeGreaterThan(before - 120);
  });

  test("coverage lens switches the bars and is remembered", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("group", { name: "Split coverage by" }).getByRole("button", { name: "Ownership" }).click();
    await expect(page.locator(".story-card").first().getByRole("img", { name: /^Coverage by ownership/ })).toBeVisible();
    await expect(page).toHaveURL(/lens=ownership/); // a shared link shows the same split
    await page.reload();
    await expect(page.getByRole("button", { name: "Ownership", pressed: true })).toBeVisible();
    await page.goto("/"); // no ?lens=: the reader's last choice
    await expect(page.getByRole("button", { name: "Ownership", pressed: true })).toBeVisible();
  });

  test("story feed filters are reflected in the URL", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "7 days" }).click();
    await expect(page).toHaveURL(/days=7/);
    await page.getByRole("button", { name: "Latest" }).click();
    await expect(page).toHaveURL(/sort=latest/);
    const more = page.getByRole("button", { name: /^Filter stories/ });
    if (await more.isVisible()) {
      await more.click(); // phones: the secondary filters are folded away
      await expect(more).toHaveAttribute("aria-expanded", "true");
    }
    await page.getByLabel("Covered by outlets from").selectOption("AL");
    if (await more.isVisible()) await expect(more).toHaveText("Filter stories (1)");
    await expect(page).toHaveURL(/country=AL/);
    await expect(page.locator(".story-card").first()).toBeVisible();
  });

  test("blindspot page groups stories by the side that missed them", async ({ page }) => {
    await page.goto("/blindspot");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Blindspot");
    await expect(page.getByRole("region", { name: /^For the left/ })).toBeVisible();
    await expect(page.locator(".badge--blindspot").first()).toBeVisible();
    await page.getByRole("button", { name: "Region", exact: true }).click();
    await expect(page).toHaveURL(/kind=region/);
    await expect(page.getByRole("region", { name: /^For the left/ })).toHaveCount(0);
  });

  test("source profile shows ratings and the stories it covered", async ({ page }) => {
    await page.goto("/sources");
    await page.getByRole("region", { name: "Outlet profiles" }).getByRole("link", { name: "Kronika Demo" }).click();
    await expect(page).toHaveURL(/\/sources\/demo-kronika/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Kronika Demo");
    await expect(page.locator(".stat", { hasText: "Perspective" })).toContainText("Center");
    await expect(page.getByRole("region", { name: "Recent stories" }).locator(".story-card").first()).toBeVisible();
  });

  test("my news bias counts the outlets of opened articles, only in this browser", async ({ page, context }) => {
    await page.goto("/my-news");
    await expect(page.getByRole("heading", { name: "Nothing read yet" })).toBeVisible();
    await page.goto("/");
    await page.locator(".story-card__title a").first().click();
    // demo links point to *.invalid hosts: let the new tab fail quietly
    await context.route("**/*.invalid/**", (route) => route.abort());
    const popup = context.waitForEvent("page");
    await page.locator(".headline a").first().click();
    await (await popup).close();
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "My bias" }).click();
    await expect(page.locator(".stat", { hasText: "Articles opened" })).toContainText("1");
    await page.getByRole("button", { name: "Clear my history" }).click();
    await expect(page.getByRole("heading", { name: "Nothing read yet" })).toBeVisible();
  });
});

test.describe("GJURMË dashboard", () => {
  test("overview renders KPIs, charts and linked articles without errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("What the news is talking about");
    await expect(page.getByText("Articles today")).toBeVisible();
    await expect(page.getByRole("region", { name: "Publishing volume" }).locator("svg").first()).toBeVisible();
    const firstArticle = page.locator(".article__title").first();
    await expect(firstArticle).toHaveAttribute("rel", "noopener noreferrer");
    await expect(firstArticle).toHaveAttribute("href", /^https?:\/\//);
    expect(errors).toEqual([]);
  });

  test("time range filter updates the URL and the numbers", async ({ page }) => {
    await page.goto("/dashboard");
    const tile = page.locator(".stat", { hasText: "Articles, last" });
    await expect(tile).toContainText("last 30 days");
    await page.getByRole("button", { name: "7 days" }).click();
    await expect(page).toHaveURL(/days=7/);
    await expect(tile).toContainText("last 7 days");
  });

  test("chart has an accessible table view", async ({ page }) => {
    await page.goto("/dashboard");
    const card = page.getByRole("region", { name: "Publishing volume" });
    await card.getByRole("button", { name: "Table" }).click();
    await expect(card.getByRole("table")).toBeVisible();
    await expect(card.getByRole("columnheader", { name: "Articles" })).toBeVisible();
  });

  test("topic drill-down", async ({ page }) => {
    await page.goto("/topics");
    await page.getByRole("link", { name: "Elections" }).first().click();
    await expect(page).toHaveURL(/\/topics\/elections/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Elections");
    await expect(page.getByRole("region", { name: "Articles per day" })).toBeVisible();
  });

  test("article search with filters is reflected in the URL", async ({ page }) => {
    await page.goto("/articles");
    await page.getByLabel("Keyword in headline").fill("Prizren");
    await expect(page).toHaveURL(/q=Prizren/);
    await expect(page.locator(".article").first()).toContainText(/Prizren/i);
    await page.getByLabel("Tone").selectOption("negative");
    await expect(page).toHaveURL(/sentiment=negative/);
    await expect(page.getByRole("heading", { level: 2 }).first()).toContainText("articles");
  });

  test("people search is part of the URL", async ({ page }) => {
    await page.goto("/entities");
    await page.getByLabel("Search names").fill("Kurti");
    await expect(page).toHaveURL(/q=Kurti/);
    await page.reload();
    await expect(page.getByLabel("Search names")).toHaveValue("Kurti");
  });

  test("entity drill-down from the people list", async ({ page }) => {
    await page.goto("/entities");
    await page.getByRole("button", { name: "People", exact: true }).click();
    await expect(page).toHaveURL(/type=person/);
    // wait until the refetch for the new filter has replaced the previous (placeholder) rows
    await expect(page.locator(".card--refetching")).toHaveCount(0);
    await expect(page.locator("tbody .rank-meta").first()).toHaveText("Person");
    const first = page.getByRole("region", { name: "Most mentioned" }).getByRole("link").first();
    const name = await first.textContent();
    await first.click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(name ?? "");
    await expect(page.getByRole("region", { name: "Mentions per day" })).toBeVisible();
  });

  test("article detail discloses how it was analysed and links to the original", async ({ page }) => {
    await page.goto("/articles");
    await page.getByRole("link", { name: /^Analysis details for/ }).first().click();
    // The demo dataset is analysed by keyword rules, not an LLM, and the page must say so.
    await expect(page.getByRole("heading", { name: "Rule-based analysis" })).toBeVisible();
    await expect(page.getByText(/Assigned by keyword rules, not by an AI model/)).toBeVisible();
    await expect(page.getByRole("link", { name: /Read the full article on/ })).toHaveAttribute("target", "_blank");
  });

  test("API failures show an error state with retry", async ({ page }) => {
    await page.route("**/api/v1/analytics/volume**", (route) =>
      route.fulfill({ status: 503, contentType: "application/json",
        body: JSON.stringify({ error: { code: "unavailable", message: "Service temporarily unavailable" } }) }));
    await page.goto("/dashboard");
    const card = page.getByRole("region", { name: "Publishing volume" });
    await expect(card.getByRole("alert")).toContainText("Service temporarily unavailable");
    await expect(card.getByRole("button", { name: "Try again" })).toBeVisible();
  });

  test("theme toggle persists the chosen theme", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /Colour theme/ }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  });

  test("keyboard: skip link is the first stop and jumps to the content", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible(); // app rendered
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to content" });
    await expect(skip).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("main")).toBeFocused();
  });

  test("keyboard: client-side navigation moves focus to the new page", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Topics" }).click();
    await expect(page.locator("main")).toBeFocused();
    await expect(page).toHaveTitle(/Topics · GJURMË/);
  });

  test("no serious accessibility violations on a story page", async ({ page }) => {
    await page.goto("/");
    await page.locator(".story-card__title a").first().click();
    await expect(page.locator(".headline").first()).toBeVisible();
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    const serious = results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
    expect(serious.map((v) => `${v.id}: ${v.nodes.length} nodes — ${v.help}`)).toEqual([]);
  });

  test("a page whose code fails to load reloads once, then explains, with the site still usable", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Top stories");
    await page.route(/\/assets\/Trends-[^/]+\.js$/, (route) => route.abort());
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Trends" }).click();
    await expect(page.getByRole("alert")).toContainText("This page could not be loaded");
    await expect(page).toHaveURL(/\/trends$/);
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  });

  test("the edge never answers a missing build file with the app shell", async ({ request }) => {
    const missing = await request.get("/assets/does-not-exist-0000.js");
    expect(missing.status()).toBe(404);
    expect(missing.headers()["cache-control"]).toBe("no-store");
    const deepLink = await request.get("/stories/1");
    expect(deepLink.headers()["cache-control"]).toBe("no-cache");
  });

  test("unknown routes show a 404 page", async ({ page }) => {
    await page.goto("/does-not-exist");
    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  });

  for (const path of [
    "/", "/blindspot", "/my-news", "/sources/demo-tirana", "/dashboard", "/trends", "/topics", "/entities",
    "/sources", "/articles", "/about", "/status",
  ]) {
    test(`no serious accessibility violations on ${path}`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
      const serious = results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
      expect(serious.map((v) => `${v.id}: ${v.nodes.length} nodes — ${v.help}`)).toEqual([]);
    });
  }
});
