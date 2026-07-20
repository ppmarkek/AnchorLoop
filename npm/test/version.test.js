"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const repositoryRoot = path.resolve(__dirname, "..", "..");
const { assertPackageName, assertVersionConsistency, readCanonicalVersion } = require("../scripts/version.js");
const { parseArguments } = require("../scripts/registry-smoke.js");

function writeReleaseFixture(root, { packageMetadata, packageLock } = {}) {
  fs.mkdirSync(path.join(root, "src", "anchorloop"), { recursive: true });
  fs.writeFileSync(path.join(root, "src", "anchorloop", "version.py"), 'VERSION = "1.2.3"\n', "utf8");
  fs.writeFileSync(
    path.join(root, "package.json"),
    `${JSON.stringify(packageMetadata || { name: "anchorloop", version: "1.2.3" })}\n`,
    "utf8",
  );
  fs.writeFileSync(
    path.join(root, "package-lock.json"),
    `${JSON.stringify(packageLock || {
      name: "anchorloop",
      version: "1.2.3",
      lockfileVersion: 3,
      packages: { "": { name: "anchorloop", version: "1.2.3" } },
    })}\n`,
    "utf8",
  );
  fs.writeFileSync(
    path.join(root, "pyproject.toml"),
    '[project]\ndynamic = ["version"]\n[tool.setuptools.dynamic]\nversion = { attr = "anchorloop.version.VERSION" }\n',
    "utf8",
  );
}

test("the canonical version drives both package formats and the release tag", () => {
  const version = readCanonicalVersion(repositoryRoot);
  assert.deepEqual(
    assertVersionConsistency({ root: repositoryRoot, releaseTag: `v${version}` }),
    { packageName: "anchorloop", version },
  );
  assert.throws(
    () => assertVersionConsistency({ root: repositoryRoot, releaseTag: "v999.0.0" }),
    /does not match canonical version/,
  );
});

test("a stale npm manifest cannot pass the release version gate", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "anchorloop-version-"));
  try {
    writeReleaseFixture(root, { packageMetadata: { name: "anchorloop", version: "1.2.4" } });
    assert.throws(() => assertVersionConsistency({ root }), /does not match canonical version/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("release metadata cannot depend on AnchorLoop itself", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "anchorloop-version-"));
  try {
    writeReleaseFixture(root, {
      packageMetadata: {
        name: "anchorloop",
        version: "1.2.3",
        dependencies: { anchorloop: "^1.2.0" },
      },
    });
    assert.throws(() => assertVersionConsistency({ root }), /must not depend on itself/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("release lockfile cannot contain a recursive AnchorLoop package", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "anchorloop-version-"));
  try {
    writeReleaseFixture(root, {
      packageLock: {
        name: "anchorloop",
        version: "1.2.3",
        lockfileVersion: 3,
        packages: {
          "": { name: "anchorloop", version: "1.2.3" },
          "node_modules/anchorloop": { version: "1.2.2" },
        },
      },
    });
    assert.throws(() => assertVersionConsistency({ root }), /recursive AnchorLoop dependency/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("a stale lockfile version cannot pass the release gate", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "anchorloop-version-"));
  try {
    writeReleaseFixture(root, {
      packageLock: {
        name: "anchorloop",
        version: "1.2.2",
        lockfileVersion: 3,
        packages: { "": { name: "anchorloop", version: "1.2.2" } },
      },
    });
    assert.throws(() => assertVersionConsistency({ root }), /lock.json version/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("release checkout rejects a generated local skill installation", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "anchorloop-version-"));
  try {
    writeReleaseFixture(root);
    const marker = path.join(root, ".codex", "skills", "anchorloop", ".anchorloop-skill.json");
    fs.mkdirSync(path.dirname(marker), { recursive: true });
    fs.writeFileSync(marker, "{}\n", "utf8");
    assert.throws(() => assertVersionConsistency({ root }), /generated local AnchorLoop skill/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("ambiguous canonical version assignments are rejected", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "anchorloop-version-"));
  try {
    fs.mkdirSync(path.join(root, "src", "anchorloop"), { recursive: true });
    fs.writeFileSync(
      path.join(root, "src", "anchorloop", "version.py"),
      'VERSION = "1.2.3"\nVERSION = "1.2.4"\n',
      "utf8",
    );
    assert.throws(() => readCanonicalVersion(root), /exactly one VERSION/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("registry smoke defaults to the canonical package release", () => {
  const release = assertVersionConsistency({ root: repositoryRoot });
  assert.deepEqual(parseArguments([]), release);
  assert.equal(parseArguments(["--help"]), null);
  assert.equal(assertPackageName("@ppmarkek/anchorloop"), "@ppmarkek/anchorloop");
  assert.throws(() => parseArguments(["--package", "anchorloop\nforged-output"]), /safe public npm package name/);
});
