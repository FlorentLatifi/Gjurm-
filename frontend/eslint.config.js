import js from "@eslint/js";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

/**
 * Layer boundaries (docs/architecture/frontend_system.md §1): app → features → ui / shared /
 * stores → design. Cross-folder imports use the @/ alias so these patterns can see the layer.
 * Flat config replaces a rule's options per block, so every block lists the shared pattern.
 */
const LEAVE_FOLDER = { group: ["../../*"], message: "Cross into another folder through the @/ alias." };
const restrict = (patterns, paths = []) => ({
  "no-restricted-imports": ["error", { patterns: [LEAVE_FOLDER, ...patterns], paths }],
});
const NO_FRAMEWORK = {
  group: ["react", "react-dom", "react-router-dom", "@tanstack/*", "zustand", "zustand/*"],
  message: "shared/api, shared/lib and shared/model are plain TypeScript.",
};
const ROUTER_HOOKS = {
  name: "react-router-dom",
  importNames: ["useSearchParams", "useLocation", "useNavigate", "useParams", "useLoaderData"],
  message: "ui/ is pure: read router state in a feature and pass it in as props.",
};
const TESTS = ["src/test/**", "src/**/*.test.{ts,tsx}"];
const boundaries = [
  { files: ["src/app/**/*.{ts,tsx}"], rules: restrict([]) },
  {
    files: ["src/features/**/*.{ts,tsx}"],
    rules: restrict([
      { group: ["@/app/*"], message: "features/ never import the app shell." },
      { group: ["@/features/*/*"], message: "Import another feature through its index: @/features/<name>." },
    ]),
  },
  {
    files: ["src/ui/**/*.{ts,tsx}"],
    rules: restrict(
      [
        { group: ["@/features", "@/features/*", "@/stores/*", "@/app/*"], message: "ui/ may import shared/ and design/ only." },
        { group: ["@tanstack/*", "zustand", "zustand/*"], message: "ui/ is pure: pass data and callbacks in." },
      ],
      [ROUTER_HOOKS],
    ),
  },
  {
    files: ["src/stores/**/*.{ts,tsx}"],
    rules: restrict([{ group: ["@/features", "@/features/*", "@/ui/*", "@/app/*"], message: "stores/ may import shared/ only." }]),
  },
  {
    files: ["src/shared/**/*.{ts,tsx}"],
    rules: restrict([{ group: ["@/features", "@/features/*", "@/ui/*", "@/stores/*", "@/app/*"], message: "shared/ is the bottom layer." }]),
  },
  {
    files: ["src/shared/{api,lib,model}/**/*.{ts,tsx}"],
    rules: restrict([
      { group: ["@/features", "@/features/*", "@/ui/*", "@/stores/*", "@/app/*"], message: "shared/ is the bottom layer." },
      NO_FRAMEWORK,
    ]),
  },
].map((block) => ({ ...block, ignores: TESTS }));

export default tseslint.config(
  { ignores: ["dist", "coverage", "playwright-report", "test-results", "src/shared/api/schema.gen.ts"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended, jsxA11y.flatConfigs.strict],
    files: ["**/*.{ts,tsx}"],
    languageOptions: { ecmaVersion: 2022, globals: { ...globals.browser, ...globals.node } },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
          message: "Never inject HTML: article data is untrusted.",
        },
      ],
    },
  },
  ...boundaries,
);
