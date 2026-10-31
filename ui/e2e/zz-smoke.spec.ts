import { test, expect } from "@playwright/test";
test("smoke with mocked api", async ({ page }) => {
  let authed = false;
  const me = { id: "u", email: "a@b.co", role: "admin", lang: "en", theme: "system" };
  const folders: unknown[] = []; const projects: unknown[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request(); const p = new URL(req.url()).pathname.replace("/api/v1", "");
    const m = req.method(); const json = (s: number, b: unknown) => route.fulfill({ status: s, contentType: "application/json", body: JSON.stringify(b) });
    if (p === "/auth/me" && m === "GET") return authed ? json(200, me) : json(401, { error: { code: "unauthenticated", params: {} } });
    if (p === "/auth/me") return json(200, { ...me, ...req.postDataJSON() });
    if (p === "/auth/login") { authed = true; return json(200, me); }
    if (p === "/auth/logout") { authed = false; return route.fulfill({ status: 204 }); }
    if (p === "/folders" && m === "GET") return json(200, folders);
    if (p === "/projects" && m === "GET") return json(200, projects);
    if (p === "/folders") { const f = { id: "f1", name: req.postDataJSON().name, position: 0 }; folders.push(f); return json(201, f); }
    if (p === "/projects") { const b = req.postDataJSON(); const x = { id: "p1", name: b.name, folder_id: b.folder_id ?? null, created_at: "x" }; projects.push(x); return json(201, x); }
    return json(404, {});
  });
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByTestId("login-email").fill("a@b.co");
  await page.getByTestId("login-password").fill("xxxxxxxxxxx");
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("app-shell")).toBeVisible();
  await page.getByTestId("new-folder-button").click();
  await page.getByTestId("folder-name-input").fill("Clients");
  await page.getByTestId("folder-submit").click();
  await page.getByTestId("new-project-button").click();
  await page.getByTestId("project-name-input").fill("Invoicing");
  await page.getByTestId("project-folder-select").selectOption({ label: "Clients" });
  await page.getByTestId("project-submit").click();
  await expect(page.getByTestId("folder-item").getByTestId("project-item")).toBeVisible();
  await page.evaluate(() => ((window as any).__m = 1));
  await page.getByTestId("lang-toggle").click();
  await expect(page.getByTestId("new-project-button")).toHaveText("Nouveau projet");
  await page.getByTestId("theme-toggle").click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  expect(await page.evaluate(() => (window as any).__m)).toBe(1);
  await page.screenshot({ path: process.env.SHOT! });
  await page.getByTestId("settings-button").click();
  await page.getByTestId("settings-tab-appearance").click();
  await expect(page.getByTestId("settings-theme-select")).toHaveValue("dark");
  await page.keyboard.press("Escape");
  await page.getByTestId("profile-menu").click();
  await page.getByTestId("logout-button").click();
  await expect(page).toHaveURL(/\/login$/);
});
