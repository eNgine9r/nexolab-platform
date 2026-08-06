import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import {
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const require = createRequire(import.meta.url);
const lintStagedEntry = require.resolve("lint-staged");
const lintStagedRoot = dirname(dirname(lintStagedEntry));
const lintStagedBin = join(lintStagedRoot, "bin", "lint-staged.js");
const nodeBinPath = join(repoRoot, "node_modules", ".bin");

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? repoRoot,
    encoding: "utf8",
    env: {
      ...process.env,
      FORCE_COLOR: "0",
      HUSKY: "0",
      PATH: `${nodeBinPath}${delimiter}${process.env.PATH ?? ""}`,
      ...options.env,
    },
  });

  if (!options.allowFailure && result.status !== 0) {
    throw new Error(
      [`Command failed (${result.status}): ${command} ${args.join(" ")}`, result.stdout, result.stderr]
        .filter(Boolean)
        .join("\n"),
    );
  }

  return result;
}

function git(cwd, args, options = {}) {
  return run("git", args, { ...options, cwd });
}

function gitOutput(cwd, args) {
  return git(cwd, args).stdout.replaceAll("\r\n", "\n");
}

function parseVersion(value) {
  const match = value.match(/(\d+)\.(\d+)\.(\d+)/u);
  assert(match, `Unable to parse version: ${value}`);
  return match.slice(1).map(Number);
}

function versionAtLeast(actual, minimum) {
  for (let index = 0; index < actual.length; index += 1) {
    if (actual[index] > minimum[index]) return true;
    if (actual[index] < minimum[index]) return false;
  }
  return true;
}

function assertRuntimeFloors() {
  const nodeVersion = parseVersion(process.versions.node);
  const supportedNode =
    (nodeVersion[0] === 22 && versionAtLeast(nodeVersion, [22, 22, 1])) || nodeVersion[0] === 24;
  assert(
    supportedNode,
    `Node ${process.versions.node} does not satisfy the NEXOLAB lint-staged v17 baseline`,
  );

  const gitVersionText = run("git", ["--version"]).stdout.trim();
  const gitVersion = parseVersion(gitVersionText);
  assert(
    versionAtLeast(gitVersion, [2, 32, 0]),
    `${gitVersionText} is below lint-staged v17 minimum Git 2.32.0`,
  );

  return { gitVersion: gitVersionText, nodeVersion: process.versions.node };
}

function assertRepositoryContract() {
  const manifest = JSON.parse(readFileSync(join(repoRoot, "package.json"), "utf8"));
  const packageMetadata = JSON.parse(readFileSync(join(lintStagedRoot, "package.json"), "utf8"));

  assert.equal(packageMetadata.version, "17.3.0");
  assert.equal(manifest.devDependencies["lint-staged"], "^17.3.0");
  assert.equal(manifest.engines.node, ">=22.22.1 <23 || >=24 <25");
  assert.deepEqual(manifest["lint-staged"], {
    "*.{js,jsx,ts,tsx,mjs,cjs}": ["eslint --fix", "prettier --write"],
    "*.{json,md,mdx,css,yml,yaml}": ["prettier --write"],
  });
  assert.equal(readFileSync(join(repoRoot, ".husky", "pre-commit"), "utf8"), "npx lint-staged\n");
  assert(existsSync(lintStagedBin), `Missing lint-staged CLI: ${lintStagedBin}`);

  return packageMetadata.version;
}

function initializeRepository(path) {
  mkdirSync(path, { recursive: true });
  git(path, ["init", "-q", "-b", "main"]);
  git(path, ["config", "user.email", "lint-staged@example.test"]);
  git(path, ["config", "user.name", "NEXOLAB lint-staged acceptance"]);
  git(path, ["config", "core.autocrlf", "false"]);
  writeFileSync(join(path, "sample.js"), "const value = 0;\n");
  git(path, ["add", "sample.js"]);
  git(path, ["-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-qm", "baseline"]);
}

function runLintStaged(cwd, configPath) {
  const args = [lintStagedBin, "--cwd", cwd, "--verbose"];
  if (configPath) args.push("--config", configPath);
  return run(process.execPath, args, { allowFailure: true, cwd });
}

function writeHarnessFiles(harnessDir) {
  mkdirSync(harnessDir, { recursive: true });

  const successTask = join(harnessDir, "success-task.mjs");
  writeFileSync(
    successTask,
    `import { readFileSync, writeFileSync } from "node:fs";\nfor (const file of process.argv.slice(2)) {\n  const content = readFileSync(file, "utf8");\n  if (content.includes("// unstaged")) {\n    throw new Error("Task received hidden unstaged content");\n  }\n  writeFileSync(file, content.trimEnd() + "\\n// formatted\\n");\n}\n`,
  );

  const failureTask = join(harnessDir, "failure-task.mjs");
  writeFileSync(
    failureTask,
    `import { appendFileSync } from "node:fs";\nfor (const file of process.argv.slice(2)) {\n  appendFileSync(file, "// should-rollback\\n");\n}\nprocess.exit(7);\n`,
  );

  const successConfig = join(harnessDir, "success-config.json");
  const failureConfig = join(harnessDir, "failure-config.json");
  writeFileSync(
    successConfig,
    `${JSON.stringify({ "*.js": `node ${JSON.stringify(successTask)}` }, null, 2)}\n`,
  );
  writeFileSync(
    failureConfig,
    `${JSON.stringify({ "*.js": `node ${JSON.stringify(failureTask)}` }, null, 2)}\n`,
  );

  return { failureConfig, successConfig };
}

function assertProductionTasks(root) {
  const cloneDir = join(root, "production-config");
  git(root, ["clone", "--quiet", "--no-hardlinks", repoRoot, cloneDir]);

  symlinkSync(
    join(repoRoot, "node_modules"),
    join(cloneDir, "node_modules"),
    process.platform === "win32" ? "junction" : "dir",
  );

  const fixturePath = join(cloneDir, "src", "__lint_staged_v17_fixture__.ts");
  writeFileSync(fixturePath, "export const lintStagedFixture={value:1}\n");
  git(cloneDir, ["add", "src/__lint_staged_v17_fixture__.ts"]);

  const result = runLintStaged(cloneDir);
  assert.equal(result.status, 0, `Production lint-staged tasks failed:\n${result.stdout}\n${result.stderr}`);

  const staged = gitOutput(cloneDir, ["show", ":src/__lint_staged_v17_fixture__.ts"]);
  assert.equal(staged, "export const lintStagedFixture = { value: 1 };\n");
  assert.equal(gitOutput(cloneDir, ["diff"]), "");
  git(cloneDir, ["diff", "--cached", "--check"]);
}

function assertPartialStageSuccess(repoDir, successConfig) {
  writeFileSync(join(repoDir, "sample.js"), "const value = 1;\n");
  git(repoDir, ["add", "sample.js"]);
  writeFileSync(join(repoDir, "sample.js"), "const value = 1;\n// unstaged\n");

  const result = runLintStaged(repoDir, successConfig);
  assert.equal(result.status, 0, `Partial-stage success case failed:\n${result.stdout}\n${result.stderr}`);

  const staged = gitOutput(repoDir, ["show", ":sample.js"]);
  const working = readFileSync(join(repoDir, "sample.js"), "utf8");
  assert(staged.includes("// formatted"));
  assert(!staged.includes("// unstaged"));
  assert(working.includes("// formatted"));
  assert(working.includes("// unstaged"));
  assert.equal(gitOutput(repoDir, ["stash", "list"]), "");
}

function assertFailureRollback(repoDir, failureConfig) {
  git(repoDir, ["reset", "--hard", "-q", "HEAD"]);
  writeFileSync(join(repoDir, "sample.js"), "const value = 2;\n");
  git(repoDir, ["add", "sample.js"]);
  writeFileSync(join(repoDir, "sample.js"), "const value = 2;\n// unstaged\n");

  const cachedBefore = gitOutput(repoDir, ["diff", "--cached", "--binary"]);
  const workingBefore = gitOutput(repoDir, ["diff", "--binary"]);
  const stashBefore = gitOutput(repoDir, ["stash", "list"]);

  const result = runLintStaged(repoDir, failureConfig);
  assert.notEqual(result.status, 0, "Failure case unexpectedly succeeded");
  assert.equal(gitOutput(repoDir, ["diff", "--cached", "--binary"]), cachedBefore);
  assert.equal(gitOutput(repoDir, ["diff", "--binary"]), workingBefore);
  assert.equal(gitOutput(repoDir, ["stash", "list"]), stashBefore);
  assert(!readFileSync(join(repoDir, "sample.js"), "utf8").includes("should-rollback"));
}

function assertEmptyStage(repoDir, successConfig) {
  git(repoDir, ["reset", "--hard", "-q", "HEAD"]);
  const result = runLintStaged(repoDir, successConfig);
  assert.equal(result.status, 0, `Empty staged-file case failed:\n${result.stdout}\n${result.stderr}`);
  assert.equal(gitOutput(repoDir, ["status", "--porcelain"]), "");
}

const runtime = assertRuntimeFloors();
const lintStagedVersion = assertRepositoryContract();
const root = mkdtempSync(join(tmpdir(), "nexolab-lint-staged-v17-"));

try {
  const harnessDir = join(root, "harness");
  const repoDir = join(root, "isolated-repository");
  const { failureConfig, successConfig } = writeHarnessFiles(harnessDir);
  initializeRepository(repoDir);
  assertProductionTasks(root);
  assertPartialStageSuccess(repoDir, successConfig);
  assertFailureRollback(repoDir, failureConfig);
  assertEmptyStage(repoDir, successConfig);

  console.log(
    JSON.stringify(
      {
        git: runtime.gitVersion,
        lintStaged: lintStagedVersion,
        node: runtime.nodeVersion,
        verified: [
          "production-eslint-prettier-order",
          "partial-stage-success",
          "failure-rollback",
          "empty-stage",
        ],
      },
      null,
      2,
    ),
  );
} finally {
  rmSync(root, { force: true, recursive: true });
}
