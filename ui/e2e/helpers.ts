import { expect, type Page } from "@playwright/test";
import { PROJECT_NAME, USER_MESSAGES } from "./scenario";

// Worker jobs call the (fake) LLM through the queue: allow generous delays.
export const JOB_TIMEOUT = 90_000;

/** Create a project from the sidebar and land on its page. */
export async function createProject(page: Page): Promise<void> {
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
}

/** Send the scripted user messages and wait for each assistant reply. */
export async function runInterview(page: Page): Promise<void> {
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
}

/** Generate the spec, check it, approve it. */
export async function generateAndApproveSpec(page: Page): Promise<void> {
  await page.getByTestId("spec-generate").click();
  await expect(page.getByTestId("spec-panel")).toBeVisible({ timeout: JOB_TIMEOUT });
  await expect(page.getByTestId("spec-content")).not.toBeEmpty();
  await expect(page.getByTestId("spec-version")).toHaveText("Version 1");
  await expect(page.getByTestId("phase-step-spec_review")).toHaveAttribute("data-state", "current");
  await expect(page.getByTestId("chat-input")).toBeDisabled();

  await page.getByTestId("spec-approve").click();
  await expect(page.getByTestId("spec-status")).toHaveText("Approved");
}

/** Generate the plan and check it is shown with its estimate. */
export async function generatePlan(page: Page): Promise<void> {
  await page.getByTestId("plan-generate").click();
  await page.getByTestId("tab-plan").click();
  await expect(page.getByTestId("milestone-M1")).toBeVisible({ timeout: JOB_TIMEOUT });
  await expect(page.getByTestId("job-failed")).toHaveCount(0);
  await expect(page.locator('[data-testid^="task-card-"]').first()).toBeVisible();
  await expect(page.getByTestId("estimate-total-cost")).toHaveText(/^\$\d/);
  await expect(page.getByTestId("estimate-total-tokens")).toContainText("tokens");
  await expect(page.getByTestId("plan-status")).toHaveText("Draft");
}

/** Approve the plan through the cost confirmation dialog. */
export async function approvePlan(page: Page): Promise<void> {
  const total = (await page.getByTestId("estimate-total-cost").textContent()) ?? "";
  await page.getByTestId("plan-approve").click();
  const dialog = page.getByTestId("confirm-dialog");
  await expect(dialog).toContainText(total);
  await dialog.getByTestId("confirm-submit").click();
  await expect(dialog).toBeHidden();
  await expect(page.getByTestId("plan-approved")).toBeVisible();
  await expect(page.getByTestId("plan-status")).toHaveText("Approved");
}

/** The stepper (Chat tab) shows the phase "ready" and the chat is closed. */
export async function expectReady(page: Page): Promise<void> {
  await page.getByTestId("tab-chat").click();
  await expect(page.getByTestId("phase-step-ready")).toHaveAttribute("data-state", "current");
  await expect(page.getByTestId("chat-input")).toBeDisabled();
}

/** Whole scripted flow: new project, interview, spec, plan, approval, phase ready. */
export async function reachApprovedPlan(page: Page): Promise<void> {
  await createProject(page);
  await runInterview(page);
  await generateAndApproveSpec(page);
  await generatePlan(page);
  await approvePlan(page);
  await expectReady(page);
}
