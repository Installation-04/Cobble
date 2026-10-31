import js from "@eslint/js";
import globals from "globals";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

// User-visible attributes must never be string literals: they go through t().
const VISIBLE_ATTRS = "aria-label|aria-description|aria-placeholder|title|placeholder|alt|label";

export default tseslint.config(
  { ignores: ["dist", "coverage", "node_modules", "test-results", "playwright-report"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  { languageOptions: { globals: { ...globals.browser, ...globals.node } } },
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/**/*.test.{ts,tsx}", "src/test/**"],
    plugins: { react, "react-hooks": reactHooks },
    settings: { react: { version: "19" } },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react/jsx-no-literals": ["error", { noStrings: true, ignoreProps: true }],
      "no-restricted-syntax": [
        "error",
        {
          selector: `JSXAttribute[name.name=/^(${VISIBLE_ATTRS})$/] > Literal`,
          message: "User-visible attributes must use t(), not string literals.",
        },
        {
          selector: `JSXAttribute[name.name=/^(${VISIBLE_ATTRS})$/] > JSXExpressionContainer > Literal`,
          message: "User-visible attributes must use t(), not string literals.",
        },
      ],
    },
  },
);
