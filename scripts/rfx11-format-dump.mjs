import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const files = [
  "e2e/refrigeration-layout.production.e2e.ts",
  "src/components/instrumentation/instrumentation-registry-screen.tsx",
  "src/components/instrumentation/instrumentation-registry-workspace.test.tsx",
  "src/components/instrumentation/instrumentation-registry-workspace.tsx",
  "src/features/instrumentation/instrumentation-repository.test.ts",
  "src/features/instrumentation/instrumentation-repository.ts",
];

execFileSync(
  process.execPath,
  ["node_modules/prettier/bin/prettier.cjs", "--write", ...files],
  { stdio: "inherit" },
);

for (const file of files) {
  const encoded = readFileSync(file).toString("base64");
  console.log(`RFX11_FORMAT_BEGIN ${file}`);
  console.log(encoded);
  console.log(`RFX11_FORMAT_END ${file}`);
}
