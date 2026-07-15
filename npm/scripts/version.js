#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");

const repositoryRoot = path.resolve(__dirname, "..", "..");
const commonVersionPattern = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;
const packageNamePattern = /^(?:@[a-z0-9][a-z0-9._~-]*\/)?[a-z0-9][a-z0-9._~-]*$/;

function assertPackageName(packageName) {
  if (
    typeof packageName !== "string"
    || packageName.length === 0
    || packageName.length > 214
    || !packageNamePattern.test(packageName)
  ) {
    throw new Error(`${JSON.stringify(packageName)} is not a safe public npm package name.`);
  }
  return packageName;
}

function readCanonicalVersion(root = repositoryRoot) {
  const versionPath = path.join(root, "src", "anchorloop", "version.py");
  const source = fs.readFileSync(versionPath, "utf8");
  const assignments = source.split(/\r?\n/).filter((line) => /^VERSION\b/.test(line));
  const match = assignments.length === 1 ? /^VERSION = "([^"]+)"$/.exec(assignments[0]) : null;
  if (!match) {
    throw new Error(`${versionPath} must contain exactly one VERSION = "..." assignment.`);
  }
  if (!commonVersionPattern.test(match[1])) {
    throw new Error(`${match[1]} is not a supported Python/npm release version.`);
  }
  return match[1];
}

function assertBundledVersionConsistency(options = {}) {
  const root = options.root || repositoryRoot;
  const version = readCanonicalVersion(root);
  const packagePath = path.join(root, "package.json");
  const packageMetadata = JSON.parse(fs.readFileSync(packagePath, "utf8"));
  const packageName = assertPackageName(packageMetadata.name);
  if (packageMetadata.version !== version) {
    throw new Error(
      `package.json version ${packageMetadata.version} does not match canonical version ${version}.`,
    );
  }

  if (packageMetadata.dependencies?.[packageName]) {
    throw new Error("AnchorLoop must not depend on itself.");
  }

  return { packageName, version };
}

function assertVersionConsistency(options = {}) {
  const root = options.root || repositoryRoot;
  const releaseTag = options.releaseTag === undefined
    ? process.env.ANCHORLOOP_RELEASE_TAG
    : options.releaseTag;
  const { packageName, version } = assertBundledVersionConsistency({ root });

  const lockPath = path.join(root, "package-lock.json");
  const packageLock = JSON.parse(fs.readFileSync(lockPath, "utf8"));
  if (
    packageLock.version !== version
    || packageLock.packages?.[""]?.version !== version
  ) {
    throw new Error("package-lock.json version does not match the canonical version.");
  }
  if (
    packageLock.packages?.["node_modules/anchorloop"]
    || packageLock.packages?.[""]?.dependencies?.anchorloop
  ) {
    throw new Error("package-lock.json contains a recursive AnchorLoop dependency.");
  }

  const generatedSkillMarker = path.join(
    root,
    ".codex",
    "skills",
    "anchorloop",
    ".anchorloop-skill.json",
  );
  if (fs.existsSync(generatedSkillMarker)) {
    throw new Error("The generated local AnchorLoop skill must not be present in a release checkout.");
  }

  const pyprojectPath = path.join(root, "pyproject.toml");
  const pyproject = fs.readFileSync(pyprojectPath, "utf8");
  if (/^version\s*=\s*"/m.test(pyproject)) {
    throw new Error("pyproject.toml must not duplicate the canonical version as a static project version.");
  }
  if (!/^dynamic\s*=\s*\[\s*"version"\s*\]$/m.test(pyproject)) {
    throw new Error('pyproject.toml must declare dynamic = ["version"].');
  }
  if (!/^version\s*=\s*\{\s*attr\s*=\s*"anchorloop\.version\.VERSION"\s*\}$/m.test(pyproject)) {
    throw new Error("pyproject.toml must resolve its version from anchorloop.version.VERSION.");
  }

  if (releaseTag && releaseTag !== `v${version}`) {
    throw new Error(`Release tag ${releaseTag} does not match canonical version v${version}.`);
  }
  return { packageName, version };
}

function main() {
  try {
    const result = assertVersionConsistency();
    console.log(`${result.packageName}@${result.version}: version sources are consistent.`);
    return 0;
  } catch (error) {
    console.error(`Version check failed: ${error instanceof Error ? error.message : String(error)}`);
    return 1;
  }
}

if (require.main === module) {
  process.exitCode = main();
}

module.exports = {
  assertBundledVersionConsistency,
  assertPackageName,
  assertVersionConsistency,
  readCanonicalVersion,
};
