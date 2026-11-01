import { expect, test, type Page } from "@playwright/test";

const entry = (id: string, over: Record<string, unknown> = {}) => ({
  id,
  name: id.charAt(0).toUpperCase() + id.slice(1),
  version: "1.0.0",
  category: "git",
  description: { en: `${id} in English`, fr: `${id} en français` },
  license: "MIT",
  provides: [],
  requires: [],
  exclusive: [],
  variants: [],
  web_ui: null,
  secrets: [],
  host_access: [],
  offline: false,
  hardware: { ok: true, variant: null, problems: [] },
  installed: null,
  ...over,
});

/** The browser's view of a module-manager: three modules, one that does not fit. */
async function mockModules(page: Page) {
  let installed = false;
  let polls = 0;
  const modules = () => [
    entry("forgejo", {
      provides: ["git"],
      installed: installed
        ? { state: "running", explicit: true, variant: null, version: "1.0.0", error: null }
        : null,
    }),
    entry("woodpecker", { category: "ci", provides: ["ci"], requires: ["git"] }),
    entry("ollama", {
      category: "llm",
      hardware: {
        ok: false,
        variant: null,
        problems: [{ code: "ram", needed: "8192", have: "4096" }],
      },
    }),
  ];
  const json = (route: { fulfill: (o: object) => Promise<void> }, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

  await page.route("**/api/v1/modules/stream", (route) => route.abort());
  await page.route("**/api/v1/modules", (route) =>
    json(route, { modules: modules(), hardware: { ram_mb: 4096, gpu: "none" } }),
  );
  await page.route("**/api/v1/modules/packs", (route) =>
    json(route, {
      packs: [
        {
          id: "api-only",
          name: { en: "API only", fr: "API seulement" },
          description: {
            en: "Git and CI, models from a service.",
            fr: "Git et CI, modèles d'un service.",
          },
          modules: ["forgejo", "woodpecker"],
          hardware: { min_ram_mb: 4096, gpu: "none" },
          priority: 10,
          fit: { ok: true, problems: [] },
          recommended: true,
          installed: installed,
          installed_modules: installed ? ["forgejo"] : [],
        },
      ],
      problems: {},
      recommended: "api-only",
    }),
  );
  await page.route("**/api/v1/modules/plan", (route) =>
    json(route, {
      steps: [{ action: "install", module: "forgejo" }],
      explicit: ["forgejo"],
      installed: ["forgejo"],
      auto_added: [],
      cascade: [],
      replaced: [],
      auto_removed: [],
      links_added: [],
      links_removed: [],
    }),
  );
  await page.route("**/api/v1/modules/operations", (route) =>
    json(route, { operation_id: "op1" }, 202),
  );
  await page.route("**/api/v1/modules/operations/op1", (route) => {
    polls += 1;
    if (polls >= 2) installed = true;
    return json(route, {
      id: "op1",
      action: "install",
      modules: ["forgejo"],
      state: polls >= 2 ? "done" : "running",
      plan: null,
      error: null,
    });
  });
  await page.route("**/api/v1/modules/forgejo/secrets", (route) => json(route, {}));
}

test("the Store lists, filters, explains and installs modules", async ({ page }) => {
  await mockModules(page);
  await page.goto("/");
  await page.getByTestId("nav-store").click();
  await expect(page.getByTestId("view-store")).toBeVisible();
  await expect(page.getByTestId("store-grid").getByRole("listitem")).toHaveCount(3);

  // the starter pack proposed for this machine comes first
  await expect(page.getByTestId("pack-card-api-only")).toHaveAttribute("data-recommended", "true");
  await expect(page.getByTestId("pack-card-api-only")).toContainText(
    "Recommended for this machine",
  );

  // filter by category, then by search
  await page.getByTestId("store-category").selectOption("ci");
  await expect(page.getByTestId("store-grid").getByRole("listitem")).toHaveCount(1);
  await page.getByTestId("store-category").selectOption("");
  await page.getByTestId("store-search").fill("forgejo");
  await expect(page.getByTestId("module-card-forgejo")).toBeVisible();
  await expect(page.getByTestId("module-card-woodpecker")).toHaveCount(0);
  await page.getByTestId("store-search").fill("");

  // a module that does not fit says why and cannot be installed
  await expect(page.getByTestId("module-card-ollama")).toHaveAttribute("data-fits", "false");
  await expect(page.getByTestId("module-reason-ollama")).toContainText("needs 8192 MB");
  await page.getByTestId("module-card-ollama").click();
  await expect(page.getByTestId("module-install")).toBeDisabled();
  await page.getByTestId("sheet-close").click();

  // install: plan, confirm, follow, done, the card flips
  await page.getByTestId("module-card-forgejo").click();
  await page.getByTestId("module-install").click();
  await expect(page.getByTestId("flow-steps")).toContainText("Install forgejo");
  await page.getByTestId("flow-start").click();
  await expect(page.getByTestId("flow-done")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("sheet-close").click();
  await expect(page.getByTestId("module-state-forgejo")).toHaveText("Installed");
});
