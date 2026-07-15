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
const { buildGlobalPlatformPlan } = require(path.join(repositoryRoot, "npm", "scripts", "registry-smoke.js"));
const { parseShortcutOptions, shouldOpenGuidedInstaller } = require(launcher);

function runLauncher(args, cwd) {
  return spawnSync(process.execPath, [launcher, ...args], {
    cwd,
    encoding: "utf8",
    shell: false,
    windowsHide: true,
  });
}

test("registry smoke isolates all six global platform destinations", () => {
  const workspace = path.join("release-smoke", "workspace");
  const plan = buildGlobalPlatformPlan(workspace);

  assert.deepEqual(plan.map(({ platform }) => platform), [
    "agents",
    "codex",
    "cursor",
    "gemini",
    "claude",
    "opencode",
  ]);
  assert.deepEqual(
    plan.map(({ platform, home, project, destination }) => ({
      platform,
      home: path.relative(workspace, home).split(path.sep).join("/"),
      project: path.relative(workspace, project).split(path.sep).join("/"),
      destination: path.relative(home, destination).split(path.sep).join("/"),
    })),
    [
      { platform: "agents", home: "home-agents", project: "project-agents", destination: ".agents/skills/anchorloop" },
      { platform: "codex", home: "home-codex", project: "project-codex", destination: ".codex/skills/anchorloop" },
      { platform: "cursor", home: "home-cursor", project: "project-cursor", destination: ".cursor/skills/anchorloop" },
      { platform: "gemini", home: "home-gemini", project: "project-gemini", destination: ".gemini/skills/anchorloop" },
      { platform: "claude", home: "home-claude", project: "project-claude", destination: ".claude/skills/anchorloop" },
      { platform: "opencode", home: "home-opencode", project: "project-opencode", destination: ".config/opencode/skills/anchorloop" },
    ],
  );
  assert.equal(new Set(plan.map(({ home }) => home)).size, plan.length);
  assert.equal(new Set(plan.map(({ project }) => project)).size, plan.length);
});

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

test("the actual npm tarball contains only release runtime and documentation files", { timeout: 60_000 }, () => {
  const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), "anchorloop-pack-"));
  const npmCache = path.join(temporaryRoot, "npm-cache");
  try {
    const npmArguments = ["pack", "--pack-destination", temporaryRoot, "--json"];
    const npmExecutable = process.env.npm_execpath;
    const pack = npmExecutable
      ? spawnSync(process.execPath, [npmExecutable, ...npmArguments], {
          cwd: repositoryRoot,
          encoding: "utf8",
          shell: false,
          windowsHide: true,
          env: { ...process.env, npm_config_cache: npmCache },
        })
      : spawnSync(process.platform === "win32" ? "npm.cmd" : "npm", npmArguments, {
          cwd: repositoryRoot,
          encoding: "utf8",
          shell: process.platform === "win32",
          windowsHide: true,
          env: { ...process.env, npm_config_cache: npmCache },
        });
    assert.equal(pack.status, 0, `${pack.stdout}\n${pack.stderr}`);
    const jsonStart = pack.stdout.indexOf("[");
    const jsonEnd = pack.stdout.lastIndexOf("]");
    assert(jsonStart >= 0 && jsonEnd > jsonStart, `npm pack did not return JSON:\n${pack.stdout}`);
    const metadata = JSON.parse(pack.stdout.slice(jsonStart, jsonEnd + 1));
    assert.equal(metadata.length, 1, "npm pack must create exactly one archive");
    const archives = fs.readdirSync(temporaryRoot).filter((name) => name.endsWith(".tgz"));
    assert.deepEqual(archives, [metadata[0].filename]);

    const archive = path.join(temporaryRoot, metadata[0].filename);
    const listing = spawnSync("tar", ["-tzf", archive], {
      cwd: temporaryRoot,
      encoding: "utf8",
      shell: false,
      windowsHide: true,
    });
    assert.equal(listing.status, 0, listing.stderr);
    const entries = listing.stdout.split(/\r?\n/).filter(Boolean);
    const forbidden = [
      /^package\/node_modules\//,
      /^package\/\.codex\//,
      /^package\/\.anchor\//,
      /(?:^|\/)__pycache__\//,
      /\.pyc$/,
      /(?:^|\/)[^/]+\.egg-info\//,
      /^package\/(?:cache|\.npm|\.npm-cache)\//,
      /(?:^|\/)(?:tests?|fixtures?)\//,
    ];
    for (const entry of entries) {
      assert.equal(
        forbidden.some((pattern) => pattern.test(entry)),
        false,
        `forbidden release archive entry: ${entry}`,
      );
    }
    for (const required of [
      "package/package.json",
      "package/CHANGELOG.md",
      "package/docs/MIGRATION_0.2.md",
      "package/src/anchorloop/skills/anchorloop/SKILL.md",
      "package/src/anchorloop/skills/anchorloop/references/workflow.md",
    ]) {
      assert(entries.includes(required), `missing release archive entry: ${required}`);
    }
    assert.equal(
      entries.includes("package/package-lock.json"),
      false,
      "published runtime must not depend on checkout-only package-lock.json",
    );

    const extractRoot = path.join(temporaryRoot, "extracted");
    fs.mkdirSync(extractRoot);
    const extract = spawnSync("tar", ["-xzf", archive, "-C", extractRoot], {
      cwd: temporaryRoot,
      encoding: "utf8",
      shell: false,
      windowsHide: true,
    });
    assert.equal(extract.status, 0, extract.stderr);

    const packagedRoot = path.join(extractRoot, "package");
    const packagedVersion = spawnSync(
      process.execPath,
      [path.join(packagedRoot, "npm", "bin", "anchorloop.js"), "--version"],
      {
        cwd: packagedRoot,
        encoding: "utf8",
        shell: false,
        windowsHide: true,
      },
    );
    assert.equal(
      packagedVersion.status,
      0,
      `${packagedVersion.stdout}\n${packagedVersion.stderr}`,
    );
    assert.equal(packagedVersion.stdout.trim(), packageMetadata.version);
  } finally {
    fs.rmSync(temporaryRoot, { recursive: true, force: true });
  }
});
