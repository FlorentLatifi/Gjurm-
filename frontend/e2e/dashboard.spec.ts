import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.describe("GJURMË dashboard", () => {
  test("overview renders KPIs, charts and linked articles without errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("What the news is talking about");
    await expect(page.getByText("Articles today")).toBeVisible();
    await expect(page.getByRole("region", { name: "Publishing volume" }).locator("svg").first()).toBeVisible();
    const firstArticle = page.locator(".article__title").first();
    await expect(firstArticle).toHaveAttribute("rel", "noopener noreferrer");
    await expect(firstArticle).toHaveAttribute("href", /^https?:\/\//);
    expect(errors).toEqual([]);
  });

  test("time range filter updates the URL and the numbers", async ({ page }) => {
    await page.goto("/");
    const tile = page.locator(".stat", { hasText: "Articles, last" });
    await expect(tile).toContainText("last 30 days");
    await page.getByRole("button", { name: "7 days" }).click();
    await expect(page).toHaveURL(/days=7/);
    await expect(tile).toContainText("last 7 days");
  });

  test("chart has an accessible table view", async ({ page }) => {
    await page.goto("/");
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

  test("article detail shows AI analysis and a link to the original", async ({ page }) => {
    await page.goto("/articles");
    await page.getByRole("link", { name: /^Analysis details for/ }).first().click();
    await expect(page.getByRole("heading", { name: "AI analysis" })).toBeVisible();
    await expect(page.getByRole("link", { name: /Read the full article on/ })).toHaveAttribute("target", "_blank");
  });

  test("API failures show an error state with retry", async ({ page }) => {
    await page.route("**/api/v1/analytics/volume**", (route) =>
      route.fulfill({ status: 503, contentType: "application/json",
        body: JSON.stringify({ error: { code: "unavailable", message: "Service temporarily unavailable" } }) }));
    await page.goto("/");
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

  test("unknown routes show a 404 page", async ({ page }) => {
    await page.goto("/does-not-exist");
    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  });

  for (const path of ["/", "/trends", "/topics", "/entities", "/sources", "/articles", "/about", "/status"]) {
    test(`no serious accessibility violations on ${path}`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
      const serious = results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
      expect(serious.map((v) => `${v.id}: ${v.nodes.length} nodes — ${v.help}`)).toEqual([]);
    });
  }
});
