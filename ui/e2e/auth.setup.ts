import { expect, test as setup } from "@playwright/test";
import { activationPath, ADMIN_EMAIL, ADMIN_PASSWORD, STORAGE_STATE } from "./scenario";

const HEADERS = { "X-Requested-With": "cobble" };

/**
 * Runs once before the other specs. On a fresh stack it activates the admin through the UI
 * (the activation flow is asserted here); on an already initialized stack it just logs in.
 * Either way it saves the logged-in state and resets the preferences to English / system theme.
 */
setup("activate the admin (or log in) and save the session", async ({ page, request }) => {
  const login = await request.post("/api/v1/auth/login", {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    headers: HEADERS,
  });

  if (login.ok()) {
    const reset = await request.patch("/api/v1/auth/me", {
      data: { lang: "en", theme: "system" },
      headers: HEADERS,
    });
    expect(reset.ok()).toBe(true);
    await request.storageState({ path: STORAGE_STATE });
    return;
  }

  await page.goto(activationPath());
  await page.getByTestId("activate-email").fill(ADMIN_EMAIL);
  await page.getByTestId("activate-password").fill(ADMIN_PASSWORD);
  await page.getByTestId("activate-lang").selectOption("en");
  await page.getByTestId("activate-submit").click();
  await expect(page.getByTestId("app-shell")).toBeVisible();
  await expect(page.getByTestId("new-project-button")).toHaveText("New project");
  await page.context().storageState({ path: STORAGE_STATE });
});
