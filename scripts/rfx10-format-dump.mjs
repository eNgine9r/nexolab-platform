import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const files = [
  "e2e/refrigeration-layout.production.e2e.ts",
  "src/components/refrigeration/refrigeration-circuit-configuration-workspace.tsx",
  "src/components/refrigeration/refrigeration-circuit-configuration-workspace.test.tsx",
  "src/features/refrigeration/circuit-configuration-repository.ts",
  "src/features/refrigeration/circuit-configuration-repository.test.ts",
];

execFileSync("npx", ["prettier", "--write", ...files], { stdio: "inherit" });

for (const file of files) {
  const encoded = Buffer.from(readFileSync(file, "utf8"), "utf8").toString("base64");
  console.log(`RFX10_FORMAT_BEGIN ${file}`);
  console.log(encoded);
  console.log(`RFX10_FORMAT_END ${file}`);
}

process.exitCode = 1;
