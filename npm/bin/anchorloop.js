#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { assertBundledVersionConsistency } = require("../scripts/version.js");

const packageRoot = path.resolve(__dirname, "..", "..");
const sourceRoot = path.join(packageRoot, "src");
const supportedPlatforms = new Set(["agents", "codex", "cursor", "gemini", "claude", "opencode"]);
const isolatedPythonEntry = [
  "import runpy, sys",
  "source_root = sys.argv.pop(1)",
  "sys.path.insert(0, source_root)",
  "sys.argv[0] = 'anchorloop'",
  "runpy.run_module('anchorloop.cli', run_name='__main__')",
].join("; ");

function bundledRelease() {
  return assertBundledVersionConsistency({ root: packageRoot });
}

function printUsage() {
  const { version } = bundledRelease();
  console.log(`AnchorLoop ${version}

Usage:
  npx anchorloop install [--project|--global] [--platform <agent>|--all] [--preview] [--force]
  npx anchorloop uninstall [--project|--global] [--platform <agent>|--all] [--preview] [--force]
  npx anchorloop <anchor-command> [arguments]

Quick start:
  npx anchorloop install

In an interactive terminal, quick start opens a guided project/global installer.
Global setup can target Codex, Cursor, Gemini CLI, Claude Code, OpenCode, the
Agent Skills standard, or every native agent. Explicit flags stay scriptable.
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

function parseShortcutOptions(command, args, { interactive = false } = {}) {
  const release = bundledRelease();
  let platform = "codex";
  let platformSelected = false;
  let allPlatforms = false;
  let scope = null;
  let apply = true;
  let force = false;
  let projectPath = null;

  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === "--platform") {
      platform = optionValue(args, index, argument);
      platformSelected = true;
      index += 1;
    } else if (argument === "--global") {
      if (scope === "project") {
        throw new Error("--global cannot be combined with --project.");
      }
      scope = "global";
    } else if (argument === "--project") {
      if (scope === "global") {
        throw new Error("--project cannot be combined with --global.");
      }
      scope = "project";
    } else if (argument === "--all") {
      allPlatforms = true;
    } else if (argument === "--interactive") {
      interactive = true;
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

  if (allPlatforms && platformSelected) {
    throw new Error("--all cannot be combined with --platform.");
  }
  if (allPlatforms && scope === "project") {
    throw new Error("--all is available only for a global installation.");
  }
  if (!allPlatforms && !supportedPlatforms.has(platform)) {
    throw new Error("--platform must be one of: agents, codex, cursor, gemini, claude, opencode.");
  }
  if (interactive && command !== "install") {
    throw new Error("--interactive is available only for install.");
  }
  if (interactive && (platformSelected || allPlatforms)) {
    throw new Error("--interactive chooses the destination; do not combine it with --platform or --all.");
  }

  const backendArgs = [command];
  if (scope === "project" || (!interactive && scope !== "global" && !allPlatforms)) {
    backendArgs.push("--project");
  } else if (scope === "global" || allPlatforms) {
    backendArgs.push("--global");
  }
  if (interactive) {
    backendArgs.push("--interactive");
  }
  if (allPlatforms) {
    backendArgs.push("--all");
  } else if (!interactive) {
    backendArgs.push("--platform", platform);
  }
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
      `${release.packageName}@${release.version}`,
    );
  }
  if (projectPath) {
    backendArgs.push("--path", projectPath);
  }
  return backendArgs;
}

function shouldOpenGuidedInstaller(args, input = process.stdin, output = process.stdout) {
  if (args[0] !== "install" || !input.isTTY || !output.isTTY) {
    return false;
  }
  const options = new Set(args.slice(1));
  return !["--platform", "--all", "--apply", "--preview", "--force", "--path"].some((option) => options.has(option));
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
  const { packageName, version } = bundledRelease();
  const result = spawnSync(
    python.command,
    [...python.args, "-I", "-B", "-c", isolatedPythonEntry, sourceRoot, ...backendArgs],
    {
      cwd: process.cwd(),
      env: {
        ...environment,
        ANCHORLOOP_BUNDLED_VERSION: version,
        ANCHORLOOP_COMMAND: `npx --yes ${packageName}@${version}`,
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
  try {
    const release = bundledRelease();
    if (args.length === 0 || args[0] === "--help" || args[0] === "-h") {
      printUsage();
      return 0;
    }
    if (args[0] === "--version" || args[0] === "-v") {
      console.log(release.version);
      return 0;
    }
    if (args[0] === "install" || args[0] === "uninstall") {
      if (args.includes("--help") || args.includes("-h")) {
        printUsage();
        return 0;
      }
      return runAnchor(
        parseShortcutOptions(args[0], args.slice(1), {
          interactive: shouldOpenGuidedInstaller(args),
        }),
      );
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
  shouldOpenGuidedInstaller,
};
