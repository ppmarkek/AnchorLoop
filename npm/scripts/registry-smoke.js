#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { assertPackageName, assertVersionConsistency } = require("./version.js");

const repositoryRoot = path.resolve(__dirname, "..", "..");

function usage() {
  console.log(`Usage: node npm/scripts/registry-smoke.js [--package <name>] [--version <version>]

Runs a clean, registry-backed AnchorLoop install and complete task lifecycle.
It keeps npm's cache outside the test project and removes all temporary files.`);
}

function parseArguments(args) {
  const release = assertVersionConsistency({ root: repositoryRoot });
  const result = { packageName: release.packageName, version: release.version };
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === "--help" || argument === "-h") {
      return null;
    }
    if (argument !== "--package" && argument !== "--version") {
      throw new Error(`Unsupported option: ${argument}`);
    }
    const value = args[index + 1];
    if (!value || value.startsWith("--")) {
      throw new Error(`${argument} requires a value.`);
    }
    if (argument === "--package") {
      result.packageName = value;
    } else {
      result.version = value;
    }
    index += 1;
  }
  assertPackageName(result.packageName);
  return result;
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd,
    env: options.env,
    encoding: "utf8",
    shell: false,
    windowsHide: true,
    stdio: options.capture ? "pipe" : "inherit",
  });
  if (result.error) {
    throw new Error(`${command} could not start: ${result.error.message}`);
  }
  if (result.status !== 0 && !options.allowFailure) {
    const detail = options.capture ? `\n${result.stderr || result.stdout}` : "";
    throw new Error(`${command} ${args.join(" ")} exited with ${result.status}.${detail}`);
  }
  return result;
}

function waitForRegistry(npm, packageSpec, environment) {
  const attempts = 24;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const result = run(npm, ["view", packageSpec, "version", "--json"], {
      env: environment,
      capture: true,
      allowFailure: true,
    });
    if (result.status === 0) {
      const registryVersion = JSON.parse(result.stdout);
      const requestedVersion = packageSpec.slice(packageSpec.lastIndexOf("@") + 1);
      if (registryVersion === requestedVersion) {
        return;
      }
    }
    if (attempt < attempts) {
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 5000);
    }
  }
  throw new Error(`${packageSpec} did not become readable from the npm registry within two minutes.`);
}

function runSmoke({ packageName, version }) {
  const packageSpec = `${packageName}@${version}`;
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "anchorloop-registry-smoke-"));
  const project = path.join(workspace, "project");
  const npmCache = path.join(workspace, "npm-cache");
  const npm = process.platform === "win32" ? "npm.cmd" : "npm";
  const npx = process.platform === "win32" ? "npx.cmd" : "npx";
  const environment = {
    ...process.env,
    npm_config_cache: npmCache,
    npm_config_prefer_online: "true",
    npm_config_update_notifier: "false",
  };

  fs.mkdirSync(project);
  try {
    waitForRegistry(npm, packageSpec, environment);
    run("git", ["init", "--quiet"], { cwd: project, env: environment });

    const anchor = (...args) => run(
      npx,
      ["--yes", packageSpec, ...args],
      { cwd: project, env: environment },
    );

    anchor("install");
    const skillPath = path.join(project, ".codex", "skills", "anchorloop", "SKILL.md");
    assert.equal(fs.existsSync(skillPath), true, "registry install did not create the Codex skill");
    assert.match(fs.readFileSync(skillPath, "utf8"), new RegExp(`npx --yes ${packageName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}@${version} status`));

    anchor("add", "--apply");
    anchor("doctor", "--strict");
    for (const ignored of [
      "cache/example",
      ".cache/example",
      ".anchor/cache/example",
      ".npm/example",
      ".npm-cache/example",
      "graphify-out/example",
      "src/__pycache__/anchor.pyc",
      ".anchor/project.lock",
      ".anchor/transactions/example.json",
      ".anchor/outbox/example.json",
    ]) {
      const check = run("git", ["check-ignore", "--quiet", "--no-index", "--", ignored], {
        cwd: project,
        env: environment,
        capture: true,
        allowFailure: true,
      });
      assert.equal(check.status, 0, `${ignored} is not ignored after add --apply`);
    }
    anchor("rules", "approve", "baseline-code-quality-v1", "--by", "Registry smoke");
    anchor("rules", "approve", "baseline-security-v1", "--by", "Registry smoke");
    anchor("rules", "approve", "baseline-structure-v1", "--by", "Registry smoke");
    anchor("start", "Registry release lifecycle");
    anchor(
      "brief",
      "--by", "Registry smoke",
      "--outcome", "Exercise the published package end to end",
      "--scope", "Temporary registry smoke project only",
      "--constraints", "Leave no installed skill or project-local cache",
      "--invariant", "The pinned registry runner completes the lifecycle",
      "--uncertainty", "Registry propagation delay",
    );
    anchor(
      "plan",
      "--summary", "Run the empty-project lifecycle through the published runner.",
      "--mode", "STANDARD",
      "--task-type", "release-smoke",
      "--approach", "Exercise every guarded lifecycle transition with the published artifact.",
      "--alternative", "A launcher-only smoke was rejected because it would miss state transitions.",
      "--risk", "The registry artifact can diverge from the source checkout.",
      "--verification", "Complete the lifecycle and assert installation residue is absent.",
      "--human-artifact", "Recorded fixture: registry lifecycle reaches verified and closes.",
      "--comprehension", "Prediction: the registry runner owns no project dependency or cache.",
      "--by", "Registry smoke",
    );
    anchor("approve", "--by", "Registry smoke");
    anchor("implement");
    anchor("review");
    anchor("precommit");
    anchor(
      "verify",
      "--by", "Registry smoke",
      "--result", "pass",
      "--reason", "Published runner completed the recorded lifecycle.",
      "--recall", "The published runner kept state in .anchor and removed only its skill assets.",
    );
    const taskId = JSON.parse(
      fs.readFileSync(path.join(project, ".anchor", "tasks", "active.json"), "utf8"),
    ).id;
    anchor("close");
    anchor(
      "outcome",
      "--task", taskId,
      "--by", "Registry smoke",
      "--defects", "0",
      "--rollback", "no",
      "--corrective-refactor", "no",
      "--notes", "No post-completion issue in the registry smoke window.",
    );
    anchor("report", "--format", "json");
    anchor("doctor", "--strict");
    anchor("uninstall");
    anchor("doctor", "--strict");

    assert.equal(fs.existsSync(skillPath), false, "uninstall left the installed skill behind");
    assert.equal(fs.existsSync(path.join(project, ".anchor")), true, "workflow state disappeared during uninstall");
    for (const forbidden of [".agents", "node_modules", "cache", ".cache", ".npm", ".npm-cache", "__pycache__"]) {
      assert.equal(fs.existsSync(path.join(project, forbidden)), false, `${forbidden} leaked into the project`);
    }
    for (const relative of [".anchor/transactions/pending", ".anchor/outbox"]) {
      const directory = path.join(project, ...relative.split("/"));
      assert.equal(fs.existsSync(directory), true, `${relative} is missing after the lifecycle`);
      assert.deepEqual(fs.readdirSync(directory), [], `${relative} retained recovery residue`);
    }
    console.log(`${packageSpec}: clean registry lifecycle passed.`);
  } finally {
    fs.rmSync(workspace, { recursive: true, force: true });
  }
}

function main(args = process.argv.slice(2)) {
  try {
    const options = parseArguments(args);
    if (!options) {
      usage();
      return 0;
    }
    runSmoke(options);
    return 0;
  } catch (error) {
    console.error(`Registry smoke failed: ${error instanceof Error ? error.message : String(error)}`);
    return 1;
  }
}

if (require.main === module) {
  process.exitCode = main();
}

module.exports = {
  parseArguments,
  runSmoke,
};
