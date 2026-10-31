import { expect, test, type Page } from "@playwright/test";
import { ADMIN_EMAIL as EMAIL, ADMIN_PASSWORD as PASSWORD } from "./scenario";

// Unique names so the spec can run again on a stack that already holds data.
const STAMP = Date.now().toString(36);
const FOLDER = `Clients ${STAMP}`;
const PROJECT = `Invoicing ${STAMP}`;

const html = (page: Page) => page.locator("html");

async function patchedMe(page: Page, action: () => Promise<void>) {
  const saved = page.waitForResponse(
    (r) => r.url().includes("/api/v1/auth/me") && r.request().method() === "PATCH",
  );
  await action();
  expect((await saved).ok()).toBe(true);
}

// The admin is activated (and that flow asserted) by auth.setup.ts; this spec starts logged in.
test("organize projects, switch language and theme, log out and back in", async ({ page }) => {
  // 1. Already signed in thanks to the setup project
  await page.goto("/");
  await expect(page.getByTestId("app-shell")).toBeVisible();
  await expect(page.getByTestId("new-project-button")).toHaveText("New project");

  // 2. Folder, then a project inside it
  await page.getByTestId("new-folder-button").click();
  await page.getByTestId("folder-name-input").fill(FOLDER);
  await page.getByTestId("folder-submit").click();
  const folder = page.getByTestId("folder-item").filter({ hasText: FOLDER });
  await expect(folder).toBeVisible();

  await page.getByTestId("new-project-button").click();
  await page.getByTestId("project-name-input").fill(PROJECT);
  await page.getByTestId("project-folder-select").selectOption({ label: FOLDER });
  await page.getByTestId("project-submit").click();
  await expect(folder.getByTestId("project-item").filter({ hasText: PROJECT })).toBeVisible();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
  await expect(page.getByTestId("project-page")).toBeVisible();

  // 3. Language and theme switch without any page reload
  await page.evaluate(() => {
    (window as unknown as { __marker: number }).__marker = 1;
  });
  const marker = () => page.evaluate(() => (window as unknown as { __marker?: number }).__marker);

  await patchedMe(page, () => page.getByTestId("lang-toggle").click());
  await expect(page.getByTestId("new-project-button")).toHaveText("Nouveau projet");
  await expect(html(page)).toHaveAttribute("lang", "fr");
  expect(await marker()).toBe(1);

  await patchedMe(page, () => page.getByTestId("lang-toggle").click());
  await expect(page.getByTestId("new-project-button")).toHaveText("New project");
  expect(await marker()).toBe(1);

  await expect(html(page)).not.toHaveClass(/\bdark\b/);
  await patchedMe(page, () => page.getByTestId("theme-toggle").click());
  await expect(html(page)).toHaveClass(/\bdark\b/);
  expect(await marker()).toBe(1);

  await patchedMe(page, () => page.getByTestId("theme-toggle").click());
  await expect(html(page)).not.toHaveClass(/\bdark\b/);
  await patchedMe(page, () => page.getByTestId("theme-toggle").click());
  await expect(html(page)).toHaveClass(/\bdark\b/);
  expect(await marker()).toBe(1);

  // End state before reload: French + dark
  await patchedMe(page, () => page.getByTestId("lang-toggle").click());
  await expect(page.getByTestId("new-project-button")).toHaveText("Nouveau projet");

  // 4. Preferences survive a reload
  await page.reload();
  await expect(page.getByTestId("app-shell")).toBeVisible();
  await expect(html(page)).toHaveAttribute("lang", "fr");
  await expect(html(page)).toHaveClass(/\bdark\b/);
  await expect(page.getByTestId("new-project-button")).toHaveText("Nouveau projet");

  // 5. Logout, then log back in: data and preferences come back
  await page.getByTestId("profile-menu").click();
  await page.getByTestId("logout-button").click();
  await expect(page).toHaveURL(/\/login$/);

  await page.getByTestId("login-email").fill(EMAIL);
  await page.getByTestId("login-password").fill(PASSWORD);
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("app-shell")).toBeVisible();
  await expect(
    page.getByTestId("folder-item").filter({ hasText: FOLDER }).getByTestId("project-item").filter({
      hasText: PROJECT,
    }),
  ).toBeVisible();
  await expect(html(page)).toHaveClass(/\bdark\b/);
  await expect(html(page)).toHaveAttribute("lang", "fr");
});
