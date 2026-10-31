/// <reference types="vite/client" />
import { expect, test } from "vitest";

import css from "./style.css?raw";

/** The declarations of the rule whose selector is exactly `selector` ("" when there is none). */
function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`(?:^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`).exec(css);
  return match ? match[1] : "";
}

test("at a width of 375 px the page has no horizontal scroll", () => {
  expect(rule("*,\n*::before,\n*::after")).toContain("box-sizing: border-box");
  expect(rule("html,\nbody")).toContain("overflow-x: hidden");
  expect(rule(".todo-item label")).toContain("overflow-wrap: anywhere");
  expect(rule(".page")).toContain("max-width: 32rem");
});

test("buttons and checkboxes are at least 44 px tall", () => {
  expect(rule("button")).toContain("min-height: 44px");
  expect(rule('input[type="checkbox"]')).toContain("min-height: 44px");
  expect(rule('input[type="text"]')).toContain("min-height: 44px");
});

test("colours come from custom properties", () => {
  expect(rule(":root")).toContain("--bg:");
  expect(rule("body")).toContain("var(--bg)");
});
