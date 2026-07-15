"use strict";

const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const zlib = require("node:zlib");

const repositoryRoot = path.resolve(__dirname, "..", "..");
const {
  SUPPORTED_VERSION,
  assertReleaseArtifactDocs,
  finalizeReleaseDocs,
  releaseDocumentSpecs,
} = require("../scripts/finalize-release-docs.js");

const RELEASE_DATE = "2026-07-15";

function fixtureRoot() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "anchorloop-release-docs-"));
  for (const spec of releaseDocumentSpecs(SUPPORTED_VERSION, RELEASE_DATE)) {
    const source = path.join(repositoryRoot, ...spec.path.split("/"));
    const destination = path.join(root, ...spec.path.split("/"));
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.copyFileSync(source, destination);
  }
  const runtimeSource = path.join(repositoryRoot, "src", "anchorloop", "version.py");
  const runtimeDestination = path.join(root, "src", "anchorloop", "version.py");
  fs.mkdirSync(path.dirname(runtimeDestination), { recursive: true });
  fs.copyFileSync(runtimeSource, runtimeDestination);
  return root;
}

function readDocuments(root) {
  return new Map(
    releaseDocumentSpecs(SUPPORTED_VERSION, RELEASE_DATE).map((spec) => [
      spec.path,
      fs.readFileSync(path.join(root, ...spec.path.split("/")), "utf8"),
    ]),
  );
}

function copyPackageFixture(root) {
  fs.mkdirSync(root, { recursive: true });
  const packageMetadata = JSON.parse(
    fs.readFileSync(path.join(repositoryRoot, "package.json"), "utf8"),
  );
  const fixturePaths = new Set([
    "package.json",
    "package-lock.json",
    "npm/scripts/finalize-release-docs.js",
    ...packageMetadata.files.map((relativePath) => relativePath.replace(/\/$/, "")),
  ]);
  for (const relativePath of [...fixturePaths].sort()) {
    const source = path.join(repositoryRoot, ...relativePath.split("/"));
    const destination = path.join(root, ...relativePath.split("/"));
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    if (fs.statSync(source).isDirectory()) {
      fs.cpSync(source, destination, { recursive: true });
    } else {
      fs.copyFileSync(source, destination);
    }
  }
}

function snapshotFiles(root) {
  const snapshot = new Map();
  function visit(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const absolutePath = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        visit(absolutePath);
      } else {
        assert.equal(entry.isFile(), true, `fixture contains a non-file entry: ${absolutePath}`);
        const relativePath = path.relative(root, absolutePath).split(path.sep).join("/");
        snapshot.set(relativePath, fs.readFileSync(absolutePath));
      }
    }
  }
  visit(root);
  return snapshot;
}

function runNpmPack(root, outputDirectory, cacheDirectory) {
  const npmArguments = [
    "pack",
    "--pack-destination",
    outputDirectory,
    "--json",
    "--ignore-scripts",
  ];
  const environment = {
    ...process.env,
    ANCHORLOOP_RELEASE_TAG: `v${SUPPORTED_VERSION}`,
    npm_config_audit: "false",
    npm_config_cache: cacheDirectory,
    npm_config_fund: "false",
    npm_config_offline: "true",
    npm_config_update_notifier: "false",
  };
  const npmExecutable = process.env.npm_execpath;
  return npmExecutable
    ? spawnSync(process.execPath, [npmExecutable, ...npmArguments], {
        cwd: root,
        encoding: "utf8",
        env: environment,
        shell: false,
        timeout: 60_000,
        windowsHide: true,
      })
    : spawnSync(process.platform === "win32" ? "npm.cmd" : "npm", npmArguments, {
        cwd: root,
        encoding: "utf8",
        env: environment,
        shell: process.platform === "win32",
        timeout: 60_000,
        windowsHide: true,
      });
}

function tarString(buffer, start, length) {
  const field = buffer.subarray(start, start + length);
  const nul = field.indexOf(0);
  return field.subarray(0, nul === -1 ? field.length : nul).toString("utf8");
}

function tarOctal(buffer, start, length) {
  const value = tarString(buffer, start, length).trim();
  if (value === "") {
    return 0;
  }
  assert.match(value, /^[0-7]+$/, `invalid tar octal field: ${JSON.stringify(value)}`);
  return Number.parseInt(value, 8);
}

function paxAttributes(data) {
  const attributes = {};
  let offset = 0;
  while (offset < data.length) {
    const separator = data.indexOf(0x20, offset);
    assert(separator > offset, "invalid PAX record length");
    const recordLength = Number.parseInt(data.subarray(offset, separator).toString("ascii"), 10);
    assert(Number.isSafeInteger(recordLength) && recordLength > 0, "invalid PAX record size");
    const recordEnd = offset + recordLength;
    assert(recordEnd <= data.length, "truncated PAX record");
    const record = data.subarray(separator + 1, recordEnd - 1).toString("utf8");
    const equals = record.indexOf("=");
    assert(equals > 0, "invalid PAX attribute");
    attributes[record.slice(0, equals)] = record.slice(equals + 1);
    offset = recordEnd;
  }
  return attributes;
}

function readTarGz(archivePath) {
  const archive = zlib.gunzipSync(fs.readFileSync(archivePath));
  const entries = new Map();
  let offset = 0;
  let pendingLongPath = null;
  let pendingPax = null;
  while (offset + 512 <= archive.length) {
    const header = archive.subarray(offset, offset + 512);
    if (header.every((byte) => byte === 0)) {
      break;
    }
    const size = tarOctal(header, 124, 12);
    const type = String.fromCharCode(header[156] || 0);
    const dataStart = offset + 512;
    const dataEnd = dataStart + size;
    assert(dataEnd <= archive.length, "truncated tar entry");
    const data = archive.subarray(dataStart, dataEnd);
    const prefix = tarString(header, 345, 155);
    const headerPath = [prefix, tarString(header, 0, 100)].filter(Boolean).join("/");

    if (type === "x") {
      pendingPax = paxAttributes(data);
    } else if (type === "g") {
      // Global PAX metadata does not name a package payload entry.
    } else if (type === "L") {
      pendingLongPath = tarString(data, 0, data.length);
    } else {
      const entryPath = pendingPax?.path || pendingLongPath || headerPath;
      assert(entryPath, "tar payload entry has no path");
      entries.set(entryPath, {
        content: type === "0" || type === "\0" ? Buffer.from(data) : null,
        type,
      });
      pendingLongPath = null;
      pendingPax = null;
    }
    offset = dataStart + Math.ceil(size / 512) * 512;
  }
  return entries;
}

function extractRegularFiles(entries, destinationRoot) {
  fs.mkdirSync(destinationRoot, { recursive: true });
  const resolvedRoot = path.resolve(destinationRoot);
  for (const [entryPath, entry] of entries) {
    if (entry.content === null) {
      continue;
    }
    assert.match(entryPath, /^package\//, `unexpected tar root: ${entryPath}`);
    const destination = path.resolve(destinationRoot, ...entryPath.split("/"));
    assert(
      destination.startsWith(`${resolvedRoot}${path.sep}`),
      `tar path escapes extraction root: ${entryPath}`,
    );
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.writeFileSync(destination, entry.content);
  }
}

test("release documentation is finalized deterministically without touching runtime", () => {
  const first = fixtureRoot();
  const second = fixtureRoot();
  const sourceReadme = fs.readFileSync(path.join(repositoryRoot, "README.md"), "utf8");
  const runtimeBefore = fs.readFileSync(path.join(first, "src", "anchorloop", "version.py"), "utf8");
  try {
    const firstPaths = finalizeReleaseDocs(first, SUPPORTED_VERSION, RELEASE_DATE);
    const secondPaths = finalizeReleaseDocs(second, SUPPORTED_VERSION, RELEASE_DATE);
    assert.deepEqual(firstPaths, secondPaths);
    assert.equal(firstPaths.length, 15);
    assert.doesNotThrow(() => assertReleaseArtifactDocs(first, SUPPORTED_VERSION, RELEASE_DATE));
    assert.doesNotThrow(() => assertReleaseArtifactDocs(second, SUPPORTED_VERSION, RELEASE_DATE));

    const firstDocuments = readDocuments(first);
    const secondDocuments = readDocuments(second);
    assert.deepEqual(firstDocuments, secondDocuments);
    for (const [relativePath, content] of firstDocuments) {
      assert.doesNotMatch(content, /unreleased|release[- ]candidate|published production/i, relativePath);
    }
    assert.match(firstDocuments.get("README.md"), /\*\*Release artifact:\*\* `anchorloop@0\.2\.0`/);
    assert.match(firstDocuments.get("README.md"), /\*\*Artifact date:\*\* `2026-07-15`/);
    assert.doesNotMatch(firstDocuments.get("README.md"), /raw\.githubusercontent\.com\/ppmarkek\/AnchorLoop\/main\//);
    assert.match(firstDocuments.get("README.md"), /raw\.githubusercontent\.com\/ppmarkek\/AnchorLoop\/v0\.2\.0\//);
    assert.match(firstDocuments.get("CONTRIBUTING.md"), /exact release artifact/);
    assert.equal(
      fs.readFileSync(path.join(first, "src", "anchorloop", "version.py"), "utf8"),
      runtimeBefore,
    );
    assert.equal(fs.readFileSync(path.join(repositoryRoot, "README.md"), "utf8"), sourceReadme);
  } finally {
    fs.rmSync(first, { recursive: true, force: true });
    fs.rmSync(second, { recursive: true, force: true });
  }
});

test(
  "a clean finalized fixture produces an actual neutral npm tarball",
  { timeout: 120_000 },
  () => {
    const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), "anchorloop-release-pack-"));
    const fixture = path.join(sandbox, "fixture");
    const packOutput = path.join(sandbox, "pack-output");
    const npmCache = path.join(sandbox, "npm-cache");
    const extracted = path.join(sandbox, "extracted");
    try {
      copyPackageFixture(fixture);
      const before = snapshotFiles(fixture);
      const finalizer = spawnSync(
        process.execPath,
        [
          path.join(fixture, "npm", "scripts", "finalize-release-docs.js"),
          "--root",
          fixture,
          "--version",
          SUPPORTED_VERSION,
          "--release-date",
          RELEASE_DATE,
        ],
        {
          cwd: fixture,
          encoding: "utf8",
          shell: false,
          timeout: 30_000,
          windowsHide: true,
        },
      );
      assert.equal(finalizer.status, 0, `${finalizer.stdout}\n${finalizer.stderr}`);
      assert.match(finalizer.stdout, /Prepared 15 release artifact documents/);
      assert.doesNotThrow(() =>
        assertReleaseArtifactDocs(fixture, SUPPORTED_VERSION, RELEASE_DATE),
      );

      const after = snapshotFiles(fixture);
      assert.deepEqual(
        [...after.keys()].sort(),
        [...before.keys()].sort(),
        "the finalizer must not create untracked fixture files",
      );
      const changedPaths = [...after]
        .filter(([relativePath, content]) => !content.equals(before.get(relativePath)))
        .map(([relativePath]) => relativePath)
        .sort();
      const expectedChanges = releaseDocumentSpecs(SUPPORTED_VERSION, RELEASE_DATE)
        .map((spec) => spec.path)
        .sort();
      assert.deepEqual(
        changedPaths,
        expectedChanges,
        "the finalizer may mutate only the declared documentation set",
      );

      fs.mkdirSync(packOutput);
      const pack = runNpmPack(fixture, packOutput, npmCache);
      assert.equal(pack.status, 0, `${pack.error || ""}\n${pack.stdout}\n${pack.stderr}`);
      const archives = fs.readdirSync(packOutput).filter((name) => name.endsWith(".tgz"));
      assert.equal(archives.length, 1, `expected one npm tarball, found ${archives.join(", ")}`);

      const entries = readTarGz(path.join(packOutput, archives[0]));
      const entryPaths = [...entries.keys()].sort();
      const forbiddenPayload = [
        /^package\/npm\/scripts\/finalize-release-docs\.js$/,
        /^package\/npm\/test\//,
        /^package\/(?:tests?|fixtures?)\//,
        /^package\/(?:node_modules|\.anchor|\.codex|\.git)\//,
        /(?:^|\/)__pycache__\//,
        /\.pyc$/,
        /(?:^|\/)[^/]+\.egg-info\//,
        /^package\/(?:dist-npm|npm-cache|\.npm-cache)\//,
        /^package\/package-lock\.json$/,
      ];
      for (const entryPath of entryPaths) {
        assert.equal(
          forbiddenPayload.some((pattern) => pattern.test(entryPath)),
          false,
          `forbidden finalized tarball entry: ${entryPath}`,
        );
      }
      for (const requiredPath of [
        "package/package.json",
        "package/README.md",
        "package/CONTRIBUTING.md",
        "package/src/anchorloop/version.py",
        ...expectedChanges.map((relativePath) => `package/${relativePath}`),
      ]) {
        assert(entries.has(requiredPath), `missing finalized tarball entry: ${requiredPath}`);
      }

      extractRegularFiles(entries, extracted);
      const packagedRoot = path.join(extracted, "package");
      for (const spec of releaseDocumentSpecs(SUPPORTED_VERSION, RELEASE_DATE)) {
        const fixtureDocument = fs.readFileSync(
          path.join(fixture, ...spec.path.split("/")),
          "utf8",
        );
        const packagedDocument = fs.readFileSync(
          path.join(packagedRoot, ...spec.path.split("/")),
          "utf8",
        );
        assert.equal(packagedDocument, fixtureDocument, `${spec.path} changed during npm pack`);
        assert.doesNotMatch(
          packagedDocument,
          /unreleased|release[- ]candidate|published production/i,
          `${spec.path} retained source-only release status`,
        );
      }

      const packagedReadme = fs.readFileSync(path.join(packagedRoot, "README.md"), "utf8");
      assert.match(packagedReadme, /\*\*Release artifact:\*\* `anchorloop@0\.2\.0`/);
      assert.match(packagedReadme, /\*\*Artifact date:\*\* `2026-07-15`/);
      assert.doesNotMatch(packagedReadme, /raw\.githubusercontent\.com\/ppmarkek\/AnchorLoop\/main\//);
      assert.match(packagedReadme, /raw\.githubusercontent\.com\/ppmarkek\/AnchorLoop\/v0\.2\.0\/docs\/assets\/anchorloop-delivery-loop\.svg/);
      assert.match(packagedReadme, /raw\.githubusercontent\.com\/ppmarkek\/AnchorLoop\/v0\.2\.0\/docs\/assets\/anchorloop-evidence-integrity\.svg/);

      const packagedContributing = fs.readFileSync(
        path.join(packagedRoot, "CONTRIBUTING.md"),
        "utf8",
      );
      assert.match(packagedContributing, /stages the finalized Git\s+checkout directory/);
      assert.match(packagedContributing, /post-promotion documentation PR against `main`/);
      assert.doesNotMatch(packagedContributing, /publishes it with npm provenance through OIDC/i);
      assert.doesNotMatch(packagedContributing, /exact-source/i);
    } finally {
      fs.rmSync(sandbox, { recursive: true, force: true });
    }
  },
);

test("release documentation finalization fails closed and does not partially write", () => {
  const root = fixtureRoot();
  try {
    const readmePath = path.join(root, "README.md");
    fs.writeFileSync(
      readmePath,
      fs.readFileSync(readmePath, "utf8").replace(
        "**Published production:** `anchorloop@0.1.0`",
        "**Production marker changed unexpectedly:** `anchorloop@0.1.0`",
      ),
      "utf8",
    );
    const before = readDocuments(root);
    assert.throws(
      () => finalizeReleaseDocs(root, SUPPORTED_VERSION, RELEASE_DATE),
      /README\.md: expected the release-candidate source fragment exactly once, found 0/,
    );
    assert.deepEqual(readDocuments(root), before);
    assert.throws(
      () => assertReleaseArtifactDocs(root, SUPPORTED_VERSION, RELEASE_DATE),
      /README\.md: release artifact marker is missing/,
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("a new release version requires an explicit documentation transformation update", () => {
  const root = fixtureRoot();
  try {
    assert.throws(
      () => finalizeReleaseDocs(root, "0.3.0", RELEASE_DATE),
      /update its exact transformations before releasing 0\.3\.0/,
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("release artifact date must be supplied explicitly and be calendar-valid", () => {
  const root = fixtureRoot();
  try {
    assert.throws(
      () => finalizeReleaseDocs(root, SUPPORTED_VERSION, null),
      /must use YYYY-MM-DD from the tagged commit/,
    );
    assert.throws(
      () => finalizeReleaseDocs(root, SUPPORTED_VERSION, "2026-02-30"),
      /date is invalid/,
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
