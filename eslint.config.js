import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["frontend/src/**/*.{ts,js}", "**/frontend/src/**/*.{ts,js}"],
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_"
        }
      ],
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-array-constructor": "error",
      "no-console": ["warn", { allow: ["warn", "error", "info", "log"] }],
      "no-debugger": "error",
      "no-duplicate-imports": "error",
      "eqeqeq": ["error", "always", { null: "ignore" }],
      // Google TypeScript Style Guide enforcement (https://google.github.io/styleguide/tsguide.html)
      "prefer-const": "error",
      "no-var": "error",
      "curly": ["error", "multi-line"],
      "default-case-last": "error",
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-wrappers": "error",
      "no-caller": "error",
      "no-throw-literal": "error",
      "prefer-rest-params": "error",
      "prefer-spread": "error"
    }
  },
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      "test-results/**",
      "playwright-report/**",
      "**/*.config.*"
    ]
  }
);
