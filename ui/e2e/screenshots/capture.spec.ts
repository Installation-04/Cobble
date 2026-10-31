import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import {
  activationPath,
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  BUILD_TIMEOUT,
  USER_MESSAGES,
} from "../scenario";

const OUT = fileURLToPath(new URL("../../../docs/images/", import.meta.url));
const JOB = 90_000;

async function shot(page: Page, name: string): Promise<void> {
  // Let transitions finish so the image is stable.
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}${name}.png` });
}

test("documentation screenshots of the whole journey", async ({ page }) => {
  // Account activation
  await page.goto(activationPath());
  await page.getByTestId("activate-email").fill(ADMIN_EMAIL);
  await page.getByTestId("activate-password").fill(ADMIN_PASSWORD);
  await page.getByTestId("activate-lang").selectOption("en");
  await shot(page, "01-activate");
  await page.getByTestId("activate-submit").click();
  await expect(page.getByTestId("app-shell")).toBeVisible();
  await shot(page, "02-home");

  // A folder and a project inside it
  await page.getByTestId("new-folder-button").click();
  await page.getByTestId("folder-name-input").fill("Personal");
  await page.getByTestId("folder-submit").click();
  await page.getByTestId("new-project-button").click();
  await page.getByTestId("project-name-input").fill("Todo list");
  await page.getByTestId("project-folder-select").selectOption({ label: "Personal" });
  await page.getByTestId("project-submit").click();
  await expect(page.getByTestId("project-page")).toBeVisible();
  await shot(page, "03-new-project");

  // Interview
  const input = page.getByTestId("chat-input");
  for (const [index, text] of USER_MESSAGES.entries()) {
    await expect(input).toBeEnabled();
    await input.fill(text);
    await input.press("Enter");
    await expect(page.getByTestId("chat-message-assistant")).toHaveCount(index + 1, {
      timeout: JOB,
    });
    await expect(page.getByTestId("chat-typing")).toBeHidden();
  }
  await shot(page, "04-interview");

  // Spec
  await page.getByTestId("spec-generate").click();
  await expect(page.getByTestId("spec-panel")).toBeVisible({ timeout: JOB });
  await shot(page, "05-spec");
  await page.getByTestId("spec-approve").click();
  await expect(page.getByTestId("spec-status")).toHaveText("Approved");

  // Plan and cost estimate
  await page.getByTestId("plan-generate").click();
  await page.getByTestId("tab-plan").click();
  await expect(page.getByTestId("milestone-M1")).toBeVisible({ timeout: JOB });
  await shot(page, "06-plan");
  await page.getByTestId("plan-approve").click();
  await expect(page.getByTestId("confirm-dialog")).toBeVisible();
  await shot(page, "07-plan-approve");
  await page.getByTestId("confirm-dialog").getByTestId("confirm-submit").click();
  await expect(page.getByTestId("plan-approved")).toBeVisible();

  // Build: agents at work
  await page.getByTestId("start-building").click();
  await expect(page.getByTestId("plan-building")).toBeVisible({ timeout: BUILD_TIMEOUT });
  await page.getByTestId("tab-agents").click();
  await expect(page.locator('[data-testid^="agent-card-"]').first()).toBeVisible({
    timeout: BUILD_TIMEOUT,
  });
  await shot(page, "08-agents-running");

  // Wait for the whole backlog (three milestones) to be delivered.
  await page.getByTestId("tab-demo").click();
  for (const ref of ["M1", "M2", "M3"]) {
    await expect(page.getByTestId(`milestone-card-${ref}`)).toHaveAttribute(
      "data-status",
      /built|validated/,
      { timeout: BUILD_TIMEOUT },
    );
  }

  // Task detail with log and diff
  await page.getByTestId("tab-agents").click();
  await expect(page.getByTestId("agents-count-attention")).toHaveText("0");
  await shot(page, "09-agents-done");
  await page.getByTestId("agent-card-T-003").click();
  await expect(page.getByTestId("task-drawer")).toBeVisible();
  await shot(page, "10-task-log");
  await page.getByTestId("drawer-tab-diff").click();
  await expect(page.getByTestId("diff-view")).toBeVisible();
  await shot(page, "11-task-diff");
  await page.getByTestId("sheet-close").click();

  // Demo
  await page.getByTestId("tab-demo").click();
  await page.getByTestId("demo-toggle-M1").click();
  await expect(page.getByTestId("demo-frame-M1")).toBeVisible();
  await page.waitForTimeout(800);
  await shot(page, "12-demo");
  const previewPath = await page.getByTestId("demo-open-M1").getAttribute("href");

  // The generated app itself (before commenting: a comment reopens the milestone)
  await page.goto(previewPath ?? "/");
  await shot(page, "14-generated-app");
  await page.goBack();
  await expect(page.getByTestId("demo-tab")).toBeVisible();

  await page.getByTestId("milestone-comment-M1").click();
  await page.getByTestId("comment-input").fill("Please add a due date to each task");
  await shot(page, "13-demo-comment");
  await page.getByTestId("comment-submit").click();
  await expect(page.getByTestId("comment-created")).toBeVisible();

  // Costs
  await page.getByTestId("tab-costs").click();
  await expect(page.getByTestId("costs-spent")).toHaveText(/\$\d/);
  await shot(page, "15-costs");

  // Dark mode and French
  await page.getByTestId("tab-agents").click();
  await page.getByTestId("theme-toggle").click();
  await shot(page, "16-agents-dark");
  await page.getByTestId("lang-toggle").click();
  await shot(page, "17-agents-fr");
});
