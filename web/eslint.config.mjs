import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Pas de popup native du navigateur (« localhost indique… ») : useConfirm() de components/confirm.tsx,
  // useToast() pour une information ou une erreur.
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/**/*.test.ts"],
    rules: {
      "no-alert": "error",
      "no-restricted-globals": [
        "error",
        { name: "alert", message: "Popup native interdite : useToast() de components/toast.tsx." },
        { name: "confirm", message: "Popup native interdite : useConfirm() de components/confirm.tsx." },
        { name: "prompt", message: "Popup native interdite : une Modal avec un champ." },
      ],
      "no-restricted-properties": [
        "error",
        { object: "window", property: "alert", message: "Popup native interdite : useToast() de components/toast.tsx." },
        { object: "window", property: "confirm", message: "Popup native interdite : useConfirm() de components/confirm.tsx." },
        { object: "window", property: "prompt", message: "Popup native interdite : une Modal avec un champ." },
      ],
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
