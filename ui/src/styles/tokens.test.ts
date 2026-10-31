import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { contrastRatio, parseTokens } from "./contrast";

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "tokens.css"), "utf-8");
const MIN_RATIO = 4.5; // WCAG AA, normal text

const PAIRS: [string, string][] = [
  ["foreground", "background"],
  ["primary-foreground", "primary"],
  ["muted-foreground", "background"],
  ["muted-foreground", "muted"],
  ["destructive", "background"],
  ["destructive-foreground", "destructive"],
  ["card-foreground", "card"],
  ["popover-foreground", "popover"],
  ["secondary-foreground", "secondary"],
  ["accent-foreground", "accent"],
  ["sidebar-foreground", "sidebar"],
  ["primary", "background"],
  ["success-foreground", "success"],
  ["success", "background"],
  ["success", "card"],
  ["warning-foreground", "warning"],
  ["warning", "background"],
  ["warning", "card"],
  ["destructive", "card"],
  ["muted-foreground", "card"],
  ["diff-added-foreground", "diff-added"],
  ["diff-removed-foreground", "diff-removed"],
  ["foreground", "muted"],
];

describe.each(["light", "dark"] as const)("WCAG AA contrast (%s)", (mode) => {
  const tokens = parseTokens(css, mode);
  it.each(PAIRS)("%s on %s is at least 4.5:1", (fg, bg) => {
    expect(tokens[fg], `missing token ${fg}`).toBeDefined();
    expect(tokens[bg], `missing token ${bg}`).toBeDefined();
    expect(contrastRatio(tokens[fg], tokens[bg])).toBeGreaterThanOrEqual(MIN_RATIO);
  });
});

describe("token parsing", () => {
  it("defines every token in both modes", () => {
    const light = Object.keys(parseTokens(css, "light")).sort();
    const dark = Object.keys(parseTokens(css, "dark")).sort();
    expect(dark).toEqual(light);
  });

  it("computes the extreme contrast ratio", () => {
    expect(contrastRatio([0, 0, 0], [255, 255, 255])).toBeCloseTo(21, 5);
  });
});
