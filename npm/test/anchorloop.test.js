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
const { readCanonicalVersion } = require(path.join(repositoryRoot, "npm", "scripts", "version.js"));
const { parseShortcutOptions, shouldOpenGuidedInstaller } = require(launcher);

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
    const expectedRunner = `npx --yes ${packageMetadata.name}@${packageMetadata.version}`;
    const nextAction = fs.readFileSync(
      path.join(project, ".anchor", "next-action.md"),
      "utf8",
    );
    assert.equal(nextAction.includes(`${expectedRunner} start`), true, nextAction);
    assert.equal(nextAction.includes("{command}"), false, nextAction);

    const help = runLauncher(["help"], project);
    assert.equal(help.status, 0, help.stderr);
    assert.equal(help.stdout.includes(`${expectedRunner} add --apply`), true, help.stdout);

    const shadowPackage = path.join(project, "anchorloop");
    fs.mkdirSync(shadowPackage);
    fs.writeFileSync(path.join(shadowPackage, "__init__.py"), "", "utf8");
    fs.writeFileSync(
      path.join(shadowPackage, "cli.py"),
      "from pathlib import Path\nPath('foreign-python-source-ran').write_text('unsafe')\n",
      "utf8",
    );
    const status = runLauncher(["status"], project);
    assert.equal(status.status, 0, status.stderr);
    assert.match(status.stdout, /"active_task": null/);
    assert.equal(fs.existsSync(path.join(project, "foreign-python-source-ran")), false);
  } finally {
    fs.rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("the terminal shortcut routes to the guided installer and global all-agent setup", () => {
  assert.equal(
    shouldOpenGuidedInstaller(["install"], { isTTY: true }, { isTTY: true }),
    true,
  );
  assert.equal(
    shouldOpenGuidedInstaller(["install", "--global"], { isTTY: true }, { isTTY: true }),
    true,
  );
  assert.equal(
    shouldOpenGuidedInstaller(["install", "--platform", "codex"], { isTTY: true }, { isTTY: true }),
    false,
  );

  assert.deepEqual(
    parseShortcutOptions("install", [], { interactive: true }),
    [
      "install",
      "--interactive",
      "--apply",
      "--skill-runtime",
      "npx",
      "--npx-package",
      `${packageMetadata.name}@${packageMetadata.version}`,
    ],
  );
  assert.deepEqual(
    parseShortcutOptions("install", ["--global", "--all"]),
    [
      "install",
      "--global",
      "--all",
      "--apply",
      "--skill-runtime",
      "npx",
      "--npx-package",
      `${packageMetadata.name}@${packageMetadata.version}`,
    ],
  );
  assert.throws(
    () => parseShortcutOptions("install", ["--project", "--all"]),
    /--all is available only for a global installation/,
  );
});

test("npm preview prints a copy-pasteable command without Python-only flags", () => {
  const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), "anchorloop-preview-"));
  try {
    const preview = runLauncher(["install", "--global", "--all", "--preview"], temporaryRoot);
    assert.equal(preview.status, 0, preview.stderr);
    assert.match(
      preview.stdout,
      new RegExp(`npx --yes ${packageMetadata.name}@${packageMetadata.version} install --global --all --apply`),
    );
    assert.doesNotMatch(preview.stdout, /--skill-runtime|--npx-package/);
  } finally {
    fs.rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

test("the package manifest allowlists the runner and its Python skill assets", () => {
  const pyproject = fs.readFileSync(path.join(repositoryRoot, "pyproject.toml"), "utf8");
  const launcherSource = fs.readFileSync(launcher, "utf8");
  const canonicalVersion = readCanonicalVersion(repositoryRoot);

  assert.equal(packageMetadata.name, "anchorloop");
  assert.equal(packageMetadata.version, canonicalVersion);
  assert.match(pyproject, /^dynamic = \["version"\]$/m);
  assert.match(pyproject, /^version = \{ attr = "anchorloop\.version\.VERSION" \}$/m);
  assert.equal(packageMetadata.bin.anchorloop, "npm/bin/anchorloop.js");
  assert.match(launcherSource, /\.\.\.python\.args, "-I", "-B", "-c"/);
  assert(packageMetadata.files.includes("npm/bin/anchorloop.js"));
  assert(packageMetadata.files.includes("npm/scripts/version.js"));
  assert(packageMetadata.files.includes("npm/scripts/registry-smoke.js"));
  assert(packageMetadata.files.includes("src/anchorloop/command.py"));
  assert(packageMetadata.files.includes("src/anchorloop/cli.py"));
  assert(packageMetadata.files.includes("src/anchorloop/project_lock.py"));
  assert(packageMetadata.files.includes("src/anchorloop/safe_fs.py"));
  assert(packageMetadata.files.includes("src/anchorloop/transaction.py"));
  assert(packageMetadata.files.includes("src/anchorloop/version.py"));
  assert(packageMetadata.files.includes("src/anchorloop/skills/"));
  assert(packageMetadata.files.includes("CONTEXT.md"));
  assert(packageMetadata.files.includes("CONTRIBUTING.md"));
  assert(packageMetadata.files.includes("SECURITY.md"));
  assert(packageMetadata.files.includes("docs/"));
  assert.equal(fs.existsSync(path.join(repositoryRoot, "src", "anchorloop", "skills", "anchorloop", "SKILL.md")), true);
  assert.equal(fs.existsSync(path.join(repositoryRoot, "src", "anchorloop", "skills", "anchorloop", "references", "workflow.md")), true);
  assert.equal(packageMetadata.files.some((file) => /(?:^|\/)(?:cache|\.cache|node_modules)(?:\/|$)/.test(file)), false);
  const readme = fs.readFileSync(path.join(repositoryRoot, "README.md"), "utf8");
  assert.match(
    readme,
    /https:\/\/raw\.githubusercontent\.com\/ppmarkek\/AnchorLoop\/main\/docs\/assets\/anchorloop-delivery-loop\.svg/,
  );
  assert.match(
    readme,
    /https:\/\/raw\.githubusercontent\.com\/ppmarkek\/AnchorLoop\/main\/docs\/assets\/anchorloop-evidence-integrity\.svg/,
  );
});
