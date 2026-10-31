import { test } from "@playwright/test";
import {
  approvePlan,
  createProject,
  expectReady,
  generateAndApproveSpec,
  generatePlan,
  runInterview,
} from "./helpers";

test("interview, spec, plan: from an idea to an approved plan", async ({ page }) => {
  test.setTimeout(300_000);

  // 1. Create the project (the admin is already signed in by the setup project)
  await createProject(page);

  // 2. Interview: send the scripted user messages, wait for each assistant reply
  await runInterview(page);

  // 3. Spec
  await generateAndApproveSpec(page);

  // 4. Plan
  await generatePlan(page);

  // 5. Approve with the cost confirmation
  await approvePlan(page);

  // 6. Phase Ready
  await expectReady(page);
});
