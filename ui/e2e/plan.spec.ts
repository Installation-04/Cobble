import { expect, test } from "@playwright/test";
import { PROJECT_NAME, USER_MESSAGES } from "./scenario";

// Worker jobs call the (fake) LLM through the queue: allow generous delays.
const JOB_TIMEOUT = 90_000;

test("interview, spec, plan: from an idea to an approved plan", async ({ page }) => {
  test.setTimeout(300_000);

  // 1. Create the project (the admin is already signed in by the setup project)
  await page.goto("/");
  await expect(page.getByTestId("app-shell")).toBeVisible();
  await page.getByTestId("new-project-button").click();
  await page.getByTestId("project-name-input").fill(`${PROJECT_NAME} ${Date.now().toString(36)}`);
  await page.getByTestId("project-submit").click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
  await expect(page.getByTestId("project-page")).toBeVisible();
  await expect(page.getByTestId("phase-step-interview")).toHaveAttribute("data-state", "current");
  await expect(page.getByTestId("chat-empty")).toBeVisible();
  await expect(page.getByTestId("spec-generate")).toHaveCount(0);

  // 2. Interview: send the scripted user messages, wait for each assistant reply
  const input = page.getByTestId("chat-input");
  for (const [index, text] of USER_MESSAGES.entries()) {
    await expect(input).toBeEnabled();
    await input.fill(text);
    await input.press("Enter");
    await expect(page.getByTestId("chat-message-user").nth(index)).toContainText(text);
    await expect(page.getByTestId("chat-message-assistant")).toHaveCount(index + 1, {
      timeout: JOB_TIMEOUT,
    });
    await expect(page.getByTestId("chat-typing")).toBeHidden();
    await expect(page.getByTestId("job-failed")).toHaveCount(0);
  }

  // 3. Spec
  await page.getByTestId("spec-generate").click();
  await expect(page.getByTestId("spec-panel")).toBeVisible({ timeout: JOB_TIMEOUT });
  await expect(page.getByTestId("spec-content")).not.toBeEmpty();
  await expect(page.getByTestId("spec-version")).toHaveText("Version 1");
  await expect(page.getByTestId("phase-step-spec_review")).toHaveAttribute("data-state", "current");
  await expect(page.getByTestId("chat-input")).toBeDisabled();

  await page.getByTestId("spec-approve").click();
  await expect(page.getByTestId("spec-status")).toHaveText("Approved");

  // 4. Plan
  await page.getByTestId("plan-generate").click();
  await page.getByTestId("tab-plan").click();
  await expect(page.getByTestId("milestone-M1")).toBeVisible({ timeout: JOB_TIMEOUT });
  await expect(page.getByTestId("job-failed")).toHaveCount(0);
  await expect(page.locator('[data-testid^="task-card-"]').first()).toBeVisible();
  await expect(page.getByTestId("estimate-total-cost")).toHaveText(/^\$\d/);
  await expect(page.getByTestId("estimate-total-tokens")).toContainText("tokens");
  await expect(page.getByTestId("plan-status")).toHaveText("Draft");

  // 5. Approve with the cost confirmation
  const total = (await page.getByTestId("estimate-total-cost").textContent()) ?? "";
  await page.getByTestId("plan-approve").click();
  const dialog = page.getByTestId("confirm-dialog");
  await expect(dialog).toContainText(total);
  await dialog.getByTestId("confirm-submit").click();
  await expect(dialog).toBeHidden();
  await expect(page.getByTestId("plan-approved")).toBeVisible();
  await expect(page.getByTestId("plan-status")).toHaveText("Approved");

  // 6. Phase Ready
  await page.getByTestId("tab-chat").click();
  await expect(page.getByTestId("phase-step-ready")).toHaveAttribute("data-state", "current");
  await expect(page.getByTestId("chat-input")).toBeDisabled();
});
