import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ME, mockFetch, renderApp } from "../test/utils";
import { SettingsDialog } from "./SettingsDialog";

afterEach(() => vi.unstubAllGlobals());

async function open(role: string) {
  mockFetch({
    "GET /auth/me": () => ({ body: { ...ME, role } }),
    "GET /models": () => ({ body: { models: [], default: null, configured_default: "demo" } }),
  });
  await renderApp(<SettingsDialog open onOpenChange={() => {}} />);
}

describe("SettingsDialog models tab", () => {
  it("is offered to administrators", async () => {
    await open("admin");
    expect(await screen.findByTestId("settings-tab-models")).toBeInTheDocument();
  });

  it("is hidden from other users", async () => {
    await open("user");
    await screen.findByTestId("settings-tab-about");
    expect(screen.queryByTestId("settings-tab-models")).toBeNull();
  });
});
