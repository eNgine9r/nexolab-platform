import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const file = ".project/BLOCKERS.md";
execFileSync(process.execPath, ["node_modules/prettier/bin/prettier.cjs", "--write", file], {
  stdio: "inherit",
});
console.log("BLOCKERS_FORMAT_BEGIN");
console.log(readFileSync(file).toString("base64"));
console.log("BLOCKERS_FORMAT_END");
