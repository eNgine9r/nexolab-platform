import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: [
      "src/components/refrigeration/equipment-lifecycle-panel.tsx",
      "src/components/refrigeration/refrigeration-detail-screen.tsx",
      "src/components/refrigeration/refrigeration-equipment-dialogs.tsx",
    ],
    rules: {
      // These components intentionally reset controlled dialog/page state at explicit
      // equipment, node and visibility boundaries. The effects also subscribe to
      // browser/session resources, so replacing them with render-time mutations would
      // make focus and cancellation semantics less deterministic.
      "react-hooks/set-state-in-effect": "off",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
