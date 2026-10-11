import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { isChunkLoadError, reloadOnce } from "../lib/chunkReload";
import { RouteError } from "./RouteError";

function Boom({ error }: { error: Error }): never {
  throw error;
}

describe("chunk load recovery", () => {
  afterEach(() => sessionStorage.clear());

  it("recognises chunk load failures from every major browser", () => {
    expect(isChunkLoadError(new TypeError("Failed to fetch dynamically imported module: https://x/assets/a.js"))).toBe(true);
    expect(isChunkLoadError(new TypeError("error loading dynamically imported module"))).toBe(true);
    expect(isChunkLoadError(new TypeError("Importing a module script failed."))).toBe(true);
    expect(isChunkLoadError(new Error("Unable to preload CSS for /assets/a.css"))).toBe(true);
    expect(isChunkLoadError(new Error("Cannot read properties of undefined"))).toBe(false);
    expect(isChunkLoadError(undefined)).toBe(false);
  });

  it("reloads once, then not again within the guard window", () => {
    const reload = vi.fn();
    expect(reloadOnce(reload, 1_000_000)).toBe(true);
    expect(reloadOnce(reload, 1_005_000)).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(reloadOnce(reload, 1_020_000)).toBe(true);
    expect(reload).toHaveBeenCalledTimes(2);
  });
});

describe("RouteError", () => {
  it("contains a render error and offers a reload", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <RouteError>
        <Boom error={new Error("bad data")} />
      </RouteError>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong on this page");
    expect(screen.getByRole("button", { name: "Reload page" })).toBeVisible();
    vi.restoreAllMocks();
  });

  it("explains a page whose code could not be loaded when it already reloaded once", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    sessionStorage.setItem("gjurme-chunk-reload", String(Date.now()));
    render(
      <RouteError>
        <Boom error={new TypeError("Failed to fetch dynamically imported module: /assets/Trends.js")} />
      </RouteError>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("This page could not be loaded");
    vi.restoreAllMocks();
    sessionStorage.clear();
  });
});
