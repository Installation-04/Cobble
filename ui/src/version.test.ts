import { describe, expect, it } from "vitest";
import { UI_VERSION } from "./version";

describe("version", () => {
  it("is set", () => {
    expect(UI_VERSION).toMatch(/^\d+\.\d+\.\d+/);
  });
});
