#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");

// The 0.2.0 artifact has already been promoted. Release documentation is now
// kept truthful in the source tree; this script validates the tagged checkout
// instead of rewriting pre-release documentation into the npm payload.
const SUPPORTED_VERSION = "0.2.0";
const RELEASE_DOCUMENT_PATHS = [
  "README.md",
  "CHANGELOG.md",
  "SECURITY.md",
  "CONTRIBUTING.md",
  "docs/MIGRATION_0.2.md",
  "docs/ANCHOR_DECISION_MAP.md",
  "docs/PORTABLE_SKILL.md",
  "docs/PROJECT_PLAN.md",
  "docs/i18n/README.de.md",
  "docs/i18n/README.es.md",
  "docs/i18n/README.fr.md",
  "docs/i18n/README.ja.md",
  "docs/i18n/README.pt-BR.md",
  "docs/i18n/README.ru.md",
  "docs/i18n/README.zh-CN.md",
];

function normalizeNewlines(value) {
  return value.replace(/\r\n/g, "\n");
}

function preserveNewlines(value, original) {
  const newline = original.includes("\r\n") ? "\r\n" : "\n";
  return value.replace(/\n/g, newline);
}

function assertReleaseDate(releaseDate) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(releaseDate || "")) {
    throw new Error("Release artifact date must use YYYY-MM-DD from the tagged commit.");
  }
  const parsed = new Date(`${releaseDate}T00:00:00Z`);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== releaseDate) {
    throw new Error(`Release artifact date is invalid: ${releaseDate}.`);
  }
}

function releaseDocumentSpecs(version, releaseDate) {
  assertReleaseDate(releaseDate);
  if (version !== SUPPORTED_VERSION) {
    throw new Error(
      `Release documentation validator supports ${SUPPORTED_VERSION}; update its supported version before releasing ${version}.`,
    );
  }
  return RELEASE_DOCUMENT_PATHS.map((relativePath) => ({
    path: relativePath,
    replacements: [],
  }));
}

function discoverTranslationPaths(root) {
  const directory = path.join(root, "docs", "i18n");
  return fs
    .readdirSync(directory, { withFileTypes: true })
    .filter((entry) => entry.isFile() && /^README\..+\.md$/.test(entry.name))
    .map((entry) => `docs/i18n/${entry.name}`)
    .sort();
}

function assertTranslationCoverage(root) {
  const expected = RELEASE_DOCUMENT_PATHS
    .filter((relativePath) => relativePath.startsWith("docs/i18n/"))
    .sort();
  const discovered = discoverTranslationPaths(root);
  if (JSON.stringify(discovered) !== JSON.stringify(expected)) {
    throw new Error(
      `Release documentation validator translation set is stale. Expected ${expected.join(", ")}; found ${discovered.join(", ")}.`,
    );
  }
}

function readDocuments(root, version, releaseDate) {
  assertTranslationCoverage(root);
  return new Map(
    releaseDocumentSpecs(version, releaseDate).map((spec) => {
      const absolutePath = path.join(root, ...spec.path.split("/"));
      return [spec.path, normalizeNewlines(fs.readFileSync(absolutePath, "utf8"))];
    }),
  );
}

function assertIncludes(contents, relativePath, marker) {
  const content = contents.get(relativePath);
  if (!content || !content.includes(marker)) {
    throw new Error(`${relativePath}: release document marker is missing: ${marker}`);
  }
}

function assertArtifactContents(contents, version, releaseDate) {
  assertReleaseDate(releaseDate);
  const exactPackage = `anchorloop@${version}`;
  const required = new Map([
    ["README.md", `**Published production:** \`${exactPackage}\``],
    ["CHANGELOG.md", `## ${version} - Published`],
    ["SECURITY.md", `Published production is \`${exactPackage}\``],
    ["CONTRIBUTING.md", `\`${exactPackage}\` is the current published production release`],
    ["docs/MIGRATION_0.2.md", `- Current production: \`${exactPackage}\``],
    ["docs/ANCHOR_DECISION_MAP.md", `\`${exactPackage}\` is published production`],
    ["docs/PORTABLE_SKILL.md", `Published production is \`${exactPackage}\``],
    ["docs/PROJECT_PLAN.md", `Status: \`${version}\` is the current production release`],
  ]);
  for (const [relativePath, marker] of required) {
    assertIncludes(contents, relativePath, marker);
  }

  const forbidden = [
    /unreleased/i,
    /release[- ]candidate/i,
    /current release branch/i,
    /available from npm `latest`/i,
    /npm `latest` (?:continues to resolve|resolves)/i,
  ];
  for (const [relativePath, content] of contents) {
    for (const pattern of forbidden) {
      if (pattern.test(content)) {
        throw new Error(`${relativePath}: release document retains obsolete status marker ${pattern}.`);
      }
    }
  }

  const readme = contents.get("README.md");
  assertIncludes(contents, "README.md", `npx --yes ${exactPackage} install`);
  if (readme.includes("raw.githubusercontent.com/ppmarkek/AnchorLoop/main/")) {
    throw new Error("README.md: release document retains a mutable main-branch image URL.");
  }

  for (const relativePath of RELEASE_DOCUMENT_PATHS.filter((candidate) => candidate.startsWith("docs/i18n/"))) {
    const banner = contents.get(relativePath).split("\n").slice(0, 10).join("\n");
    if (!banner.includes(`\`${exactPackage}\``)) {
      throw new Error(`${relativePath}: release document banner lacks ${exactPackage}.`);
    }
    if (banner.includes("anchorloop@0.1.0")) {
      throw new Error(`${relativePath}: release document banner retains the previous version.`);
    }
  }
}

function buildArtifactContents(root, version, releaseDate) {
  const outputs = readDocuments(root, version, releaseDate);
  assertArtifactContents(outputs, version, releaseDate);
  return outputs;
}

function finalizeReleaseDocs(root, version, releaseDate) {
  const outputs = buildArtifactContents(root, version, releaseDate);
  for (const [relativePath, content] of outputs) {
    const absolutePath = path.join(root, ...relativePath.split("/"));
    const original = fs.readFileSync(absolutePath, "utf8");
    const finalized = preserveNewlines(content, original);
    if (original !== finalized) {
      fs.writeFileSync(absolutePath, finalized, "utf8");
    }
  }
  return [...outputs.keys()];
}

function assertReleaseArtifactDocs(root, version, releaseDate) {
  const contents = readDocuments(root, version, releaseDate);
  assertArtifactContents(contents, version, releaseDate);
  return [...contents.keys()];
}

function parseArguments(argv) {
  const result = { check: false, releaseDate: null, root: process.cwd(), version: null };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--check") {
      result.check = true;
    } else if (argument === "--root" || argument === "--version" || argument === "--release-date") {
      const value = argv[index + 1];
      if (!value) {
        throw new Error(`${argument} requires a value.`);
      }
      const key = argument === "--release-date" ? "releaseDate" : argument.slice(2);
      result[key] = value;
      index += 1;
    } else {
      throw new Error(`Unknown argument: ${argument}`);
    }
  }
  result.root = path.resolve(result.root);
  if (!result.version) {
    const packageMetadata = JSON.parse(fs.readFileSync(path.join(result.root, "package.json"), "utf8"));
    result.version = packageMetadata.version;
  }
  assertReleaseDate(result.releaseDate);
  return result;
}

if (require.main === module) {
  try {
    const options = parseArguments(process.argv.slice(2));
    const files = options.check
      ? assertReleaseArtifactDocs(options.root, options.version, options.releaseDate)
      : finalizeReleaseDocs(options.root, options.version, options.releaseDate);
    process.stdout.write(
      `${options.check ? "Verified" : "Validated"} ${files.length} release documents for ${options.version}.\n`,
    );
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}

module.exports = {
  SUPPORTED_VERSION,
  assertReleaseArtifactDocs,
  assertArtifactContents,
  buildArtifactContents,
  finalizeReleaseDocs,
  parseArguments,
  releaseDocumentSpecs,
};
