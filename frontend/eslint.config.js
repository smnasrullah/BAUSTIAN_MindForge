import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import { defineConfig, globalIgnores } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig([
  globalIgnores(["dist", "coverage"]),
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
    rules: { "@typescript-eslint/no-explicit-any": "error" },
  },
  // Type-aware promise rules: an unhandled promise hides failures (no error state, no retry).
  // App code only: in tests a synchronous act() returns a thenable that does not need awaiting.
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/**/*.test.{ts,tsx}", "src/test/**"],
    languageOptions: { parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname } },
    rules: {
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": "error",
    },
  },
  // Feature boundaries: agent and admin code never import each other; shared helpers live in src/lib.
  {
    files: ["src/features/agent/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": ["error", { patterns: [{ group: ["**/admin/**"], message: "Agent code must not import admin code. Move shared helpers to src/lib." }] }],
    },
  },
  {
    files: ["src/features/admin/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": ["error", { patterns: [{ group: ["**/agent/**"], message: "Admin code must not import agent code. Move shared helpers to src/lib." }] }],
    },
  },
  {
    // Bangla shaping: a vowel sign or hasanta rendered on its own shows a dotted circle (◌).
    // Never split display text per character; use digitRuns() from src/lib/textRuns.ts.
    files: ["src/**/*.tsx"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "CallExpression[callee.property.name='map'][callee.object.type='ArrayExpression'][callee.object.elements.length=1][callee.object.elements.0.type='SpreadElement']",
          message: "Do not render text per character ([...text].map): it breaks Bangla glyph clusters. Use digitRuns() from lib/textRuns.",
        },
        {
          selector: "CallExpression[callee.property.name='map'][callee.object.callee.object.name='Array'][callee.object.callee.property.name='from'][callee.object.arguments.length=1]",
          message: "Do not render text per character (Array.from(text).map): it breaks Bangla glyph clusters. Use digitRuns() from lib/textRuns.",
        },
        {
          selector: "CallExpression[callee.property.name='split'][arguments.length=1][arguments.0.value='']",
          message: "Do not split text per character (.split('')): it breaks Bangla glyph clusters. Use digitRuns() from lib/textRuns.",
        },
      ],
    },
  },
]);
