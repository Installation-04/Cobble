import { describe, expect, it } from "vitest";
import en from "../locales/en/errors.json";
import fr from "../locales/fr/errors.json";
import { KNOWN_ERROR_CODES } from "./errors";

describe("module error codes", () => {
  it("every refusal the modules API can send is a known, translated error code", () => {
    for (const messages of [en, fr] as Record<string, string>[]) {
      const refusals = Object.keys(messages).filter(
        (key) =>
          (key.startsWith("module_") && !key.startsWith("module_code_")) ||
          key === "invalid_request",
      );
      expect(refusals.length).toBeGreaterThan(8);
      for (const code of refusals) {
        expect(KNOWN_ERROR_CODES as readonly string[], code).toContain(code);
      }
    }
  });
});
