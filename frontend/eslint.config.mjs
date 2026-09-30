import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const compat = new FlatCompat({ baseDirectory: __dirname });

const eslintConfig = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  { ignores: [".next/**", "node_modules/**", "out/**", "scripts/**", "next-env.d.ts"] },
  {
    rules: {
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      "@typescript-eslint/no-explicit-any": "off",
      "react-hooks/exhaustive-deps": "warn",
      // A component declared inside another component is a new type on every render, so
      // React remounts its subtree: inputs lose focus after a single keystroke. This cost
      // the profile form its cursor once - never again silently.
      "react/no-unstable-nested-components": ["error", { allowAsProps: true }],
      // Icons come from the project's icon package, never from the library directly: one
      // place decides what a board or a food category looks like (components/icons).
      "no-restricted-imports": ["error", { paths: [
        { name: "lucide-react", message: "Import icons from @/components/icons." },
        { name: "lucide", message: "Import icons from @/components/icons." },
        { name: "react-icons", message: "Import icons from @/components/icons." },
      ], patterns: ["react-icons/*"] }],
    },
  },
  { files: ["components/icons/**"], rules: { "no-restricted-imports": "off" } },
];

export default eslintConfig;
