#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const packageRoot = path.resolve(__dirname, "..", "..");
const packageMetadata = require(path.join(packageRoot, "package.json"));
const sourceRoot = path.join(packageRoot, "src");
const supportedPlatforms = new Set(["agents", "codex"]);

function printUsage() {
  console.log(`AnchorLoop ${packageMetadata.version}

Usage:
  npx anchorloop install [--platform codex|agents] [--global] [--preview] [--force]
  npx anchorloop uninstall [--platform codex|agents] [--global] [--preview] [--force]
  npx anchorloop <anchor-command> [arguments]

Quick start:
  npx anchorloop install

The quick install writes the Codex project skill to .codex/skills/anchorloop.
Every later npx command runs the bundled Python CLI without writing a cache in
the current project. Node.js 18+ and Python 3.11+ are required.`);
}

function fail(message) {
  console.error(`Error: ${message}`);
  return 2;
}

function candidatePythonRuntimes(environment = process.env) {
  if (environment.ANCHORLOOP_PYTHON) {
    return [{ command: environment.ANCHORLOOP_PYTHON, args: [] }];
  }
  if (process.platform === "win32") {
    return [
      { command: "py", args: ["-3"] },
      { command: "python", args: [] },
      { command: "python3", args: [] },
    ];
  }
  return [
    { command: "python3", args: [] },
    { command: "python", args: [] },
  ];
}

function findPython(environment = process.env) {
  const probe = "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')";
  for (const candidate of candidatePythonRuntimes(environment)) {
    const result = spawnSync(candidate.command, [...candidate.args, "-c", probe], {
      encoding: "utf8",
      shell: false,
      windowsHide: true,
    });
    if (result.error || result.status !== 0) {
      continue;
    }
    const match = /^(\d+)\.(\d+)$/.exec(result.stdout.trim());
    if (match && Number(match[1]) === 3 && Number(match[2]) >= 11) {
      return candidate;
    }
  }
  return null;
}

function optionValue(args, index, option) {
  const value = args[index + 1];
  if (!value || value.startsWith("--")) {
    throw new Error(`${option} requires a value.`);
  }
  return value;
}

function parseShortcutOptions(command, args) {
  let platform = "codex";
  let projectScoped = true;
  let apply = true;
  let force = false;
  let projectPath = null;

  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === "--platform") {
      platform = optionValue(args, index, argument);
      index += 1;
    } else if (argument === "--global") {
      projectScoped = false;
    } else if (argument === "--project") {
      projectScoped = true;
    } else if (argument === "--preview") {
      apply = false;
    } else if (argument === "--apply") {
      apply = true;
    } else if (argument === "--force") {
      force = true;
    } else if (argument === "--path") {
      projectPath = optionValue(args, index, argument);
      index += 1;
    } else {
      throw new Error(`Unsupported ${command} option: ${argument}`);
    }
  }

  if (!supportedPlatforms.has(platform)) {
    throw new Error("--platform must be either agents or codex.");
  }

  const backendArgs = [command];
  if (projectScoped) {
    backendArgs.push("--project");
  }
  backendArgs.push("--platform", platform);
  if (apply) {
    backendArgs.push("--apply");
  }
  if (force) {
    backendArgs.push("--force");
  }
  if (command === "install") {
    backendArgs.push(
      "--skill-runtime",
      "npx",
      "--npx-package",
      `${packageMetadata.name}@${packageMetadata.version}`,
    );
  }
  if (projectPath) {
    backendArgs.push("--path", projectPath);
  }
  return backendArgs;
}

function runAnchor(backendArgs, environment = process.env) {
  if (!fs.existsSync(sourceRoot)) {
    return fail("The npm package is missing its bundled Python source.");
  }
  const python = findPython(environment);
  if (!python) {
    return fail(
      "AnchorLoop requires Python 3.11 or newer. Install it, or set ANCHORLOOP_PYTHON to its executable path.",
    );
  }
  const pythonPath = environment.PYTHONPATH
    ? `${sourceRoot}${path.delimiter}${environment.PYTHONPATH}`
    : sourceRoot;
  const result = spawnSync(
    python.command,
    [...python.args, "-m", "anchorloop.cli", ...backendArgs],
    {
      cwd: process.cwd(),
      env: {
        ...environment,
        PYTHONPATH: pythonPath,
        PYTHONDONTWRITEBYTECODE: "1",
      },
      shell: false,
      stdio: "inherit",
      windowsHide: true,
    },
  );
  if (result.error) {
    return fail(`Could not start Python: ${result.error.message}`);
  }
  return typeof result.status === "number" ? result.status : 1;
}

function main(args = process.argv.slice(2)) {
  if (args.length === 0 || args[0] === "--help" || args[0] === "-h") {
    printUsage();
    return 0;
  }
  if (args[0] === "--version" || args[0] === "-v") {
    console.log(packageMetadata.version);
    return 0;
  }
  try {
    if (args[0] === "install" || args[0] === "uninstall") {
      if (args.includes("--help") || args.includes("-h")) {
        printUsage();
        return 0;
      }
      return runAnchor(parseShortcutOptions(args[0], args.slice(1)));
    }
    return runAnchor(args);
  } catch (error) {
    return fail(error instanceof Error ? error.message : String(error));
  }
}

if (require.main === module) {
  process.exitCode = main();
}

module.exports = {
  candidatePythonRuntimes,
  findPython,
  main,
  parseShortcutOptions,
};
