import { expect, test } from "@playwright/test";
import { BUILD_TIMEOUT, COMMENT_TEXT, DEMO_TODO_PATTERN } from "./scenario";
import { reachApprovedPlan } from "./helpers";

// The stack must run with COBBLE_PACK_MODE=fake: agents, CI, git and preview are in-memory fakes
// that go through the real scheduler states in seconds. Every wait below is generous anyway.
test("build loop: start, agents merge, demo, comment, validate, costs", async ({ page }) => {
  test.setTimeout(900_000);

  // 1. From an idea to an approved plan (same steps as plan.spec.ts)
  await reachApprovedPlan(page);

  // 2. Start building from the Plan tab
  await page.getByTestId("tab-plan").click();
  await page.getByTestId("start-building").click();
  await expect(page.getByTestId("plan-building")).toBeVisible({ timeout: BUILD_TIMEOUT });
  await expect(page.getByTestId("job-failed")).toHaveCount(0);
  await page.getByTestId("tab-chat").click();
  await expect(page.getByTestId("phase-step-building")).toHaveAttribute("data-state", "current");

  // 3. Agents tab: cards appear, tasks get merged, nothing needs attention
  await page.getByTestId("tab-agents").click();
  await expect(page.locator('[data-testid^="agent-card-"]').first()).toBeVisible({
    timeout: BUILD_TIMEOUT,
  });
  await expect(page.getByTestId("agents-col-merged").locator("li").first()).toBeVisible({
    timeout: BUILD_TIMEOUT,
  });
  await expect(page.getByTestId("agents-count-attention")).toHaveText("0");

  // 4. Demo tab: the first milestone becomes built
  await page.getByTestId("tab-demo").click();
  const milestone = page.getByTestId("milestone-card-M1");
  await expect(milestone).toHaveAttribute("data-status", "built", { timeout: BUILD_TIMEOUT });
  await expect(milestone.getByTestId("milestone-status")).toHaveText("Built");

  // 5. Open the demo (same-origin path) and check the seeded data is realistic
  const previewPath = await milestone.getByTestId("demo-open-M1").getAttribute("href");
  expect(previewPath).toMatch(/^\/demo\//);
  await page.goto(previewPath ?? "/");
  await expect(page.locator("body")).toContainText(DEMO_TODO_PATTERN, { timeout: 30_000 });
  const demoText = (await page.locator("body").innerText()).trim();
  expect(demoText.length).toBeGreaterThan(20);

  // 6. Back to the project (the tab is in the URL): comment on the milestone
  await page.goBack();
  await expect(page.getByTestId("demo-tab")).toBeVisible();
  await page.getByTestId("milestone-comment-M1").click();
  await page.getByTestId("comment-input").fill(COMMENT_TEXT);
  await page.getByTestId("comment-submit").click();
  await expect(page.getByTestId("comment-created")).toContainText("C-001");

  // 7. Step-8 acceptance: the comment became task C-001, visible in the Agents tab
  await page.getByTestId("tab-agents").click();
  const comment = page.getByTestId("agent-card-C-001");
  await expect(comment).toBeVisible();
  await expect(comment).toHaveAttribute(
    "data-state",
    /^(todo|writing_tests|implementing|ci|merged)$/,
  );

  // 8. The agents deliver it; the milestone is built again and can be validated
  await expect(comment).toHaveAttribute("data-state", "merged", { timeout: BUILD_TIMEOUT });
  await page.getByTestId("tab-demo").click();
  await expect(page.getByTestId("milestone-card-M1")).toHaveAttribute("data-status", "built", {
    timeout: BUILD_TIMEOUT,
  });
  await page.getByTestId("milestone-validate-M1").click();
  await expect(page.getByTestId("milestone-card-M1")).toHaveAttribute("data-status", "validated");

  // 9. Costs tab: some money and tokens were spent
  await page.getByTestId("tab-costs").click();
  await expect(page.getByTestId("costs-spent")).toHaveText(/\$\d/);
  await expect(page.getByTestId("costs-spent")).not.toHaveText(/^\$0\.00$/);
  await expect(page.getByTestId("costs-tokens-total")).toHaveText(/[1-9]/);
  await expect(page.getByTestId("costs-by-task-row").first()).toBeVisible();
});
