"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const repositoryRoot = path.resolve(__dirname, "..", "..");
const { assertPackageName, assertVersionConsistency, readCanonicalVersion } = require("../scripts/version.js");
const { parseArguments } = require("../scripts/registry-smoke.js");

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
    fs.mkdirSync(path.join(root, "src", "anchorloop"), { recursive: true });
    fs.writeFileSync(path.join(root, "src", "anchorloop", "version.py"), 'VERSION = "1.2.3"\n', "utf8");
    fs.writeFileSync(path.join(root, "package.json"), '{"name":"anchorloop","version":"1.2.4"}\n', "utf8");
    fs.writeFileSync(
      path.join(root, "pyproject.toml"),
      '[project]\ndynamic = ["version"]\n[tool.setuptools.dynamic]\nversion = { attr = "anchorloop.version.VERSION" }\n',
      "utf8",
    );
    assert.throws(() => assertVersionConsistency({ root }), /does not match canonical version/);
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
