"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const test = require("node:test");

const repositoryRoot = path.resolve(__dirname, "..", "..");
const launcher = path.join(repositoryRoot, "npm", "bin", "anchorloop.js");
const packageMetadata = require(path.join(repositoryRoot, "package.json"));

function runLauncher(args, cwd) {
  return spawnSync(process.execPath, [launcher, ...args], {
    cwd,
    encoding: "utf8",
    shell: false,
    windowsHide: true,
  });
}

test("the shortcut installs a Codex skill that keeps an npx command runner", () => {
  const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), "anchorloop-npx-"));
  const project = path.join(temporaryRoot, "O'Reilly project");
  fs.mkdirSync(project);
  try {
    const installation = runLauncher(["install"], project);
    assert.equal(installation.status, 0, installation.stderr);

    const skillPath = path.join(project, ".codex", "skills", "anchorloop", "SKILL.md");
    const markerPath = path.join(project, ".codex", "skills", "anchorloop", ".anchorloop-skill.json");
    assert.equal(fs.existsSync(skillPath), true);
    assert.equal(fs.existsSync(markerPath), true);
    assert.equal(fs.existsSync(path.join(project, ".anchor")), false);
    assert.equal(fs.existsSync(path.join(project, "cache")), false);
    assert.match(
      fs.readFileSync(skillPath, "utf8"),
      new RegExp(`npx --yes ${packageMetadata.name}@${packageMetadata.version} status`),
    );

    const setup = runLauncher(["add", "--apply"], project);
    assert.equal(setup.status, 0, setup.stderr);
    const status = runLauncher(["status"], project);
    assert.equal(status.status, 0, status.stderr);
    assert.match(status.stdout, /"active_task": null/);
  } finally {
    fs.rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("the package manifest allowlists the runner and its Python skill assets", () => {
  const pyproject = fs.readFileSync(path.join(repositoryRoot, "pyproject.toml"), "utf8");
  const pythonVersion = /^version = "([^"]+)"$/m.exec(pyproject)?.[1];

  assert.equal(packageMetadata.name, "anchorloop");
  assert.equal(packageMetadata.version, pythonVersion);
  assert.equal(packageMetadata.bin.anchorloop, "npm/bin/anchorloop.js");
  assert(packageMetadata.files.includes("npm/bin/anchorloop.js"));
  assert(packageMetadata.files.includes("src/anchorloop/cli.py"));
  assert(packageMetadata.files.includes("src/anchorloop/safe_fs.py"));
  assert(packageMetadata.files.includes("src/anchorloop/skills/"));
  assert.equal(fs.existsSync(path.join(repositoryRoot, "src", "anchorloop", "skills", "anchorloop", "SKILL.md")), true);
  assert.equal(fs.existsSync(path.join(repositoryRoot, "src", "anchorloop", "skills", "anchorloop", "references", "workflow.md")), true);
  assert.equal(packageMetadata.files.some((file) => /(?:^|\/)(?:cache|\.cache|node_modules)(?:\/|$)/.test(file)), false);
});
