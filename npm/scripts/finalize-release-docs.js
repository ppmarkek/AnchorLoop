"use strict";

const fs = require("node:fs");
const path = require("node:path");

const SUPPORTED_VERSION = "0.2.0";
const PREVIOUS_PRODUCTION_VERSION = "0.1.0";

function lines(...values) {
  return values.join("\n");
}

function normalizeNewlines(value) {
  return value.replace(/\r\n/g, "\n");
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

function countOccurrences(value, needle) {
  if (!needle) {
    throw new Error("Release documentation replacement cannot use an empty source fragment.");
  }
  return value.split(needle).length - 1;
}

function replaceExactlyOnce(value, source, replacement, relativePath) {
  const count = countOccurrences(value, source);
  if (count !== 1) {
    throw new Error(
      `${relativePath}: expected the release-candidate source fragment exactly once, found ${count}.`,
    );
  }
  return value.replace(source, replacement);
}

function translationSpecs(version, releaseDate) {
  assertReleaseDate(releaseDate);
  const exactPackage = `anchorloop@${version}`;
  return {
    "docs/i18n/README.de.md": {
      source: lines(
        "> - **Veröffentlichte Produktion:** `anchorloop@0.1.0`",
        "> - **Unveröffentlichter Release Candidate:** `0.2.0`",
        "> - Bis zur Veröffentlichung von `0.2.0` Produktionsbefehle mit",
        ">   `npx --yes anchorloop@0.1.0 ...` ausführen. [Migrationsanleitung](../MIGRATION_0.2.md).",
      ),
      artifact: lines(
        `> - **Release-Artefakt:** \`${exactPackage}\``,
        `> - **Artefaktdatum:** \`${releaseDate}\``,
        "> - **Registry-/Dist-Tag-Status:** wird von diesem unveränderlichen Artefakt nicht festgelegt.",
        "> - Verwenden Sie die exakte Version erst nach externer Registry-Prüfung. [Migrationsanleitung](../MIGRATION_0.2.md).",
      ),
    },
    "docs/i18n/README.es.md": {
      source: lines(
        "> - **Producción publicada:** `anchorloop@0.1.0`",
        "> - **Candidato de versión sin publicar:** `0.2.0`",
        "> - Hasta publicar `0.2.0`, usa `npx --yes anchorloop@0.1.0 ...` en producción.",
        ">   [Guía de migración](../MIGRATION_0.2.md).",
      ),
      artifact: lines(
        `> - **Artefacto de versión:** \`${exactPackage}\``,
        `> - **Fecha del artefacto:** \`${releaseDate}\``,
        "> - **Estado del registro/dist-tag:** este artefacto inmutable no lo declara.",
        "> - Usa la versión exacta solo después de verificar el registro externamente. [Guía de migración](../MIGRATION_0.2.md).",
      ),
    },
    "docs/i18n/README.fr.md": {
      source: lines(
        "> - **Production publiée :** `anchorloop@0.1.0`",
        "> - **Release candidate non publié :** `0.2.0`",
        "> - Jusqu'à la publication de `0.2.0`, utilisez",
        ">   `npx --yes anchorloop@0.1.0 ...` en production. [Guide de migration](../MIGRATION_0.2.md).",
      ),
      artifact: lines(
        `> - **Artefact de version :** \`${exactPackage}\``,
        `> - **Date de l'artefact :** \`${releaseDate}\``,
        "> - **État du registre/dist-tag :** cet artefact immuable ne l'affirme pas.",
        "> - Utilisez la version exacte uniquement après vérification externe du registre. [Guide de migration](../MIGRATION_0.2.md).",
      ),
    },
    "docs/i18n/README.ja.md": {
      source: lines(
        "> - **公開済み production:** `anchorloop@0.1.0`",
        "> - **未公開の release candidate:** `0.2.0`",
        "> - `0.2.0` が公開されるまでは production で",
        ">   `npx --yes anchorloop@0.1.0 ...` を使用してください。[移行ガイド](../MIGRATION_0.2.md)。",
      ),
      artifact: lines(
        `> - **リリース成果物:** \`${exactPackage}\``,
        `> - **成果物の日付:** \`${releaseDate}\``,
        "> - **レジストリ/dist-tag の状態:** この不変の成果物では表明しません。",
        "> - 外部でレジストリを確認した後にのみ正確なバージョンを使用してください。[移行ガイド](../MIGRATION_0.2.md)。",
      ),
    },
    "docs/i18n/README.pt-BR.md": {
      source: lines(
        "> - **Produção publicada:** `anchorloop@0.1.0`",
        "> - **Release candidate não publicado:** `0.2.0`",
        "> - Até a publicação de `0.2.0`, use `npx --yes anchorloop@0.1.0 ...` em",
        ">   produção. [Guia de migração](../MIGRATION_0.2.md).",
      ),
      artifact: lines(
        `> - **Artefato de release:** \`${exactPackage}\``,
        `> - **Data do artefato:** \`${releaseDate}\``,
        "> - **Estado do registry/dist-tag:** este artefato imutável não o declara.",
        "> - Use a versão exata somente após verificar o registry externamente. [Guia de migração](../MIGRATION_0.2.md).",
      ),
    },
    "docs/i18n/README.ru.md": {
      source: lines(
        "> - **Опубликованный production:** `anchorloop@0.1.0`",
        "> - **Неопубликованный release candidate:** `0.2.0`",
        "> - До публикации `0.2.0` используйте в production точную команду",
        ">   `npx --yes anchorloop@0.1.0 ...`. [Инструкция по миграции](../MIGRATION_0.2.md).",
      ),
      artifact: lines(
        `> - **Артефакт релиза:** \`${exactPackage}\``,
        `> - **Дата артефакта:** \`${releaseDate}\``,
        "> - **Состояние registry/dist-tag:** этот неизменяемый артефакт его не утверждает.",
        "> - Используйте точную версию только после внешней проверки registry. [Инструкция по миграции](../MIGRATION_0.2.md).",
      ),
      extraReplacements: [
        {
          source: "Основной английский README содержит актуальную полную документацию, режимы FAST/STANDARD/CAREFUL, безопасную установку skill, транзакционное восстановление и ограничения release candidate.",
          artifact: "Основной английский README содержит актуальную полную документацию, режимы FAST/STANDARD/CAREFUL, безопасную установку skill, транзакционное восстановление и границы артефакта релиза.",
        },
      ],
    },
    "docs/i18n/README.zh-CN.md": {
      source: lines(
        "> - **已发布的 production：** `anchorloop@0.1.0`",
        "> - **尚未发布的 release candidate：** `0.2.0`",
        "> - 在 `0.2.0` 发布前，production 请使用",
        ">   `npx --yes anchorloop@0.1.0 ...`。[迁移指南](../MIGRATION_0.2.md)。",
      ),
      artifact: lines(
        `> - **发布制品：** \`${exactPackage}\``,
        `> - **制品日期：** \`${releaseDate}\``,
        "> - **Registry/dist-tag 状态：** 此不可变制品不对此作出声明。",
        "> - 仅在外部验证 registry 后使用精确版本。[迁移指南](../MIGRATION_0.2.md)。",
      ),
    },
  };
}

function releaseDocumentSpecs(version, releaseDate) {
  assertReleaseDate(releaseDate);
  if (version !== SUPPORTED_VERSION) {
    throw new Error(
      `Release documentation finalizer supports ${SUPPORTED_VERSION}; update its exact transformations before releasing ${version}.`,
    );
  }
  const exactPackage = `anchorloop@${version}`;
  const previousPackage = `anchorloop@${PREVIOUS_PRODUCTION_VERSION}`;
  const specs = [
    {
      path: "README.md",
      replacements: [
        {
          source: lines(
            `**Published production:** \`${previousPackage}\``,
            "",
            `**Unreleased main:** \`${version}\` release candidate`,
            "",
            `The published \`${PREVIOUS_PRODUCTION_VERSION}\` package remains the production version. The current`,
            "release branch contains the unreleased recovery, validation, ownership,",
            `release-safety, and multi-agent installer work planned for \`${version}\`. Until the`,
            `signed \`v${version}\` tag passes staging, maintainer approval, exact-version registry`,
            "smoke, and interactive `latest` promotion, do not describe those additions as",
            "available from npm `latest`.",
          ),
          artifact: lines(
            `**Release artifact:** \`${exactPackage}\``,
            "",
            `**Artifact date:** \`${releaseDate}\``,
            "",
            "**Registry state:** verify the exact version and active dist-tags externally.",
            "",
            `This immutable artifact contains the recovery, validation, ownership, release-safety,`,
            `and multi-agent installer work for \`${version}\`. It does not assert registry`,
            "availability or which dist-tag points to the version. Verify registry state before",
            "installation and keep automation pinned to the exact version.",
          ),
        },
        {
          source: `## What is implemented in the unreleased ${version} candidate`,
          artifact: `## What is included in the ${version} release artifact`,
        },
        {
          source: "docs/assets/anchorloop-delivery-loop.svg",
          artifact: `https://raw.githubusercontent.com/ppmarkek/AnchorLoop/v${version}/docs/assets/anchorloop-delivery-loop.svg`,
        },
        {
          source: "docs/assets/anchorloop-evidence-integrity.svg",
          artifact: `https://raw.githubusercontent.com/ppmarkek/AnchorLoop/v${version}/docs/assets/anchorloop-evidence-integrity.svg`,
        },
        {
          source: lines(
            `## Install the published ${PREVIOUS_PRODUCTION_VERSION} package`,
            "",
            "Requirements: Node.js 18 or newer and Python 3.11 or newer.",
            "",
            "Use the exact published production version:",
            "",
            "~~~sh",
            `npx --yes ${previousPackage} install --project --platform codex --apply`,
            "~~~",
            "",
            "Do not use an unversioned `npx anchorloop install` command to test the features",
            "documented below: npm `latest` continues to resolve to `0.1.0` until the",
            `\`${version}\` release flow completes.`,
            "",
            `## Unreleased ${version} guided setup`,
            "",
            "From a development checkout, install the current Python CLI in editable mode:",
            "",
            "~~~sh",
            "python -m pip install -e .",
            "anchor install --interactive",
            "~~~",
          ),
          artifact: lines(
            `## Install the exact ${version} release artifact`,
            "",
            "Requirements: Node.js 18 or newer and Python 3.11 or newer.",
            "",
            "Use the exact artifact version only after external registry verification:",
            "",
            "~~~sh",
            `npx --yes ${exactPackage} install --project --platform codex --apply`,
            "~~~",
            "",
            "Do not use an unversioned `npx anchorloop install` command in automation; keep the",
            "exact version in commands and installed skill metadata.",
            "",
            `## ${version} guided setup`,
            "",
            "Run the compact setup wizard from the exact version after registry verification:",
            "",
            "~~~sh",
            `npx --yes ${exactPackage} install --interactive`,
            "~~~",
          ),
        },
        {
          source: "pipx install git+https://github.com/ppmarkek/AnchorLoop.git",
          artifact: `pipx install "git+https://github.com/ppmarkek/AnchorLoop.git@v${version}"`,
        },
        {
          source: 'python -m pip install "git+https://github.com/ppmarkek/AnchorLoop.git"',
          artifact: `python -m pip install "git+https://github.com/ppmarkek/AnchorLoop.git@v${version}"`,
        },
        {
          source: lines(
            `See the [${PREVIOUS_PRODUCTION_VERSION} to ${version} migration guide](docs/MIGRATION_0.2.md) for the required`,
            `\`${PREVIOUS_PRODUCTION_VERSION}\` recovery preflight, release-candidate procedure, and exact commands to`,
            "use after publication.",
          ),
          artifact: lines(
            `See the [${PREVIOUS_PRODUCTION_VERSION} to ${version} migration guide](docs/MIGRATION_0.2.md) for the required`,
            `\`${PREVIOUS_PRODUCTION_VERSION}\` recovery preflight and the exact-version upgrade procedure.`,
          ),
        },
      ],
    },
    {
      path: "CHANGELOG.md",
      replacements: [
        {
          source: lines(
            "All notable AnchorLoop changes are documented here. npm releases are immutable;",
            "an entry marked **Unreleased** describes repository state, not production npm",
            "availability.",
            "",
            `## ${version} - Unreleased`,
            "",
            `Published production remains \`${previousPackage}\` until the signed \`v${version}\` tag`,
            "is contained in `main` and passes staging, maintainer approval, exact-version",
            "registry smoke, and interactive `latest` promotion.",
          ),
          artifact: lines(
            "All notable AnchorLoop changes are documented here. This immutable package",
            `artifact records the changes included in version \`${version}\`; registry availability`,
            "and active dist-tags are external state and must be verified separately.",
            "",
            `## ${version} - ${releaseDate}`,
          ),
        },
      ],
    },
    {
      path: "SECURITY.md",
      replacements: [
        {
          source: lines(
            "| Version | Supported |",
            "|---|---|",
            "| `0.2.x` | Unreleased release candidate |",
            "| `0.1.x` | Security fixes only |",
            "",
            `Published production remains \`${previousPackage}\`. Version \`${version}\` is an`,
            "unreleased release candidate until the complete signed-tag and staged registry",
            "workflow succeeds. New security work is developed on the current `0.2.x`",
            "candidate; the published `0.1.x` line receives security fixes only.",
          ),
          artifact: lines(
            "| Version | Artifact relationship |",
            "|---|---|",
            "| `0.2.x` | Line represented by this artifact |",
            "| `0.1.x` | Previous artifact line |",
            "",
            `This immutable document describes the security scope of the \`${exactPackage}\` release`,
            `artifact dated \`${releaseDate}\`. Registry availability, active dist-tags, and live support policy are`,
            "external state; consult the repository security policy before deployment.",
          ),
        },
      ],
    },
    {
      path: "CONTRIBUTING.md",
      replacements: [
        {
          source: lines(
            `\`${previousPackage}\` is the published public-alpha baseline; current \`main\` is`,
            `the unreleased \`${version}\` release candidate. Small, testable changes that`,
            "strengthen its local, agent-neutral workflow core are preferred over broad",
            "integrations.",
          ),
          artifact: lines(
            `\`${exactPackage}\` is the exact release artifact dated \`${releaseDate}\` represented by this source snapshot.`,
            "Small, testable changes that strengthen its local, agent-neutral workflow core are",
            "preferred over broad integrations.",
          ),
        },
        {
          source: lines(
            "The optional exact-version npm route (for example,",
            `\`npx --yes ${exactPackage} install\` after publication) requires Node.js 18 or`,
            "newer and must remain a thin launcher around the Python core. During candidate",
            "development exercise the checkout directly. When changing its package,",
            "launcher, or skill templates:",
          ),
          artifact: lines(
            "The optional exact-version npm route (for example,",
            `\`npx --yes ${exactPackage} install\`) requires Node.js 18 or newer and must remain`,
            "a thin launcher around the Python core. Exercise development changes from a checkout.",
            "When changing its package, launcher, or skill templates:",
          ),
        },
        {
          source: lines(
            `\`${previousPackage}\` remains the published production baseline while \`${version}\` is`,
            `an unreleased candidate. npm versions are immutable: before creating \`v${version}\`,`,
            `verify that \`${exactPackage}\` does not exist. The signed-tag workflow runs`,
            "exact-tag CI against the truthful repository docs, then changes only packaged",
            "documentation in its disposable job using the tagged commit date. It dry-runs",
            "package assembly with lifecycle scripts disabled, then stages the finalized Git",
            "checkout directory under `next` with lifecycle scripts disabled through",
            "stage-only OIDC so npm records `gitHead`. A maintainer downloads and inspects",
            "the exact staged tarball, approves it with 2FA, dispatches the",
            "tag-bound exact registry smoke, verifies npm `gitHead`, and only then promotes",
            "the version to `latest` manually with 2FA. After",
            "`npm view anchorloop@latest version` returns",
            `\`${version}\`, open a post-promotion documentation PR against \`main\`. That PR must`,
            `move every source status surface and its release-document tests from \`${PREVIOUS_PRODUCTION_VERSION}\``,
            `production / \`${version}\` candidate to \`${version}\` production. It must also update or`,
            `retire the \`${version}\`-specific finalizer source fragments and source-RC assertions`,
            `before preparing the next release cycle. Leave the signed \`v${version}\` artifact`,
            `unchanged. Never publish \`${version}\` directly, move a signed tag, or overwrite a`,
            "failed release. Fix pre-stage failures in a new commit; after approval,",
            "deprecate a defective version and release `0.2.1`. Do not weaken `release.yml`",
            "or add a long-lived token.",
          ),
          artifact: lines(
            `This source snapshot represents the immutable \`${exactPackage}\` artifact dated`,
            `\`${releaseDate}\`; registry availability and active dist-tags are external state. npm`,
            "versions are immutable. The release workflow runs exact-tag CI on the truthful",
            "repository docs, prepares only packaged documentation in a disposable job using",
            "the tagged commit date, dry-runs package assembly with lifecycle scripts disabled,",
            "and stages the finalized Git checkout directory under `next` with lifecycle scripts",
            "disabled through stage-only OIDC so npm records `gitHead`.",
            "A maintainer downloads, inspects, and approves the exact staged artifact with 2FA,",
            "then dispatches tag-bound exact",
            "registry smoke, verifies npm `gitHead`, and promotes the exact version manually.",
            "After external `latest` promotion is verified, a maintainer opens a",
            "post-promotion documentation PR against `main`, updates or retires the",
            "release-specific finalizer fragments and source-RC assertions, and leaves the",
            "signed artifact unchanged.",
            "Never bypass the staged flow, move a signed tag, or overwrite a failed release.",
            "After approval, deprecate a defective version and release a new patch. Do not",
            "weaken `release.yml` or add a long-lived token.",
          ),
        },
      ],
    },
    {
      path: "docs/MIGRATION_0.2.md",
      replacements: [
        {
          source: lines(
            "## Release status",
            "",
            `- Published production: \`${previousPackage}\``,
            `- Current release branch: unreleased \`${version}\` release candidate`,
            "",
            `Do not run the \`${version}\` registry commands in this guide until that exact version`,
            "exists publicly and its registry smoke has passed. Use exact versions",
            "throughout the migration, do not replace `.anchor/`, and do not skip the",
            `\`${PREVIOUS_PRODUCTION_VERSION}\` recovery preflight.`,
          ),
          artifact: lines(
            "## Release artifact",
            "",
            `- Exact release artifact: \`${exactPackage}\``,
            `- Artifact date: \`${releaseDate}\``,
            "- Registry and dist-tag status: verify externally",
            "",
            `Run the \`${version}\` registry commands only after that exact version is externally`,
            "available and its registry smoke has passed. Use exact versions throughout the",
            "migration, do not replace `.anchor/`, and do not skip the",
            `\`${PREVIOUS_PRODUCTION_VERSION}\` recovery preflight.`,
          ),
        },
        {
          source: "## After publication: upgrade with the exact npm version",
          artifact: "## Upgrade with the exact npm version",
        },
        {
          source: lines(
            `Keep commands pinned to \`@${version}\` in automation and installed skill metadata.`,
            "The pin makes upgrades deliberate and avoids relying on npm `latest` during",
            "the rollout. Before publication, test the candidate only from a development",
            "checkout.",
          ),
          artifact: lines(
            `Keep commands pinned to \`@${version}\` in automation and installed skill metadata.`,
            "The pin makes upgrades deliberate and avoids relying on mutable dist-tags. Use these",
            "commands only after the exact registry version and its smoke test are verified;",
            "otherwise exercise a development checkout.",
          ),
        },
      ],
    },
    {
      path: "docs/ANCHOR_DECISION_MAP.md",
      replacements: [
        {
          source: lines(
            `\`${previousPackage}\` remains published production. The current release branch is`,
            `the unreleased \`${version}\` release candidate. The release flow requires the signed`,
            "annotated tag commit to be contained in `origin/main` and to pass exact-tag CI",
            "before the exact tarball is staged under `next` through a Trusted Publisher",
            "configured for stage-only `npm stage publish`. A maintainer must download and",
            "inspect the staged artifact, approve it with 2FA, then dispatch the read-only",
            "exact-version registry lifecycle, verify that `next` points to that version,",
            "and check npm `gitHead`. Only after those checks pass may a maintainer",
            `interactively run \`npm dist-tag add ${exactPackage} latest\` with 2FA. The`,
            "workflow stores no npm token and never promotes `latest` automatically. Until",
            `that sequence completes, no document may claim that \`${version}\` is published or`,
            "available from npm `latest`.",
          ),
          artifact: lines(
            `This document describes the immutable \`${exactPackage}\` release artifact dated`,
            `\`${releaseDate}\`. Registry`,
            "availability and active dist-tags are intentionally external state. The release flow",
            "requires the signed annotated tag commit to be contained in `origin/main` and to",
            "pass exact-tag CI before the exact tarball is staged under `next` through a Trusted",
            "Publisher configured for stage-only `npm stage publish`. A maintainer must download",
            "and inspect the staged artifact, approve it with 2FA, then dispatch the read-only",
            "exact-version registry lifecycle, verify that `next` points to that version, and",
            "check npm `gitHead`. Only after those checks pass may a maintainer promote the exact",
            "version interactively with 2FA. The workflow stores no npm token and never promotes",
            "a dist-tag automatically; consumers must verify registry state externally.",
          ),
        },
      ],
    },
    {
      path: "docs/PORTABLE_SKILL.md",
      replacements: [
        {
          source: lines(
            `Published production is \`${previousPackage}\`. The current release branch is the`,
            `unreleased \`${version}\` release candidate; its guided multi-agent installer is not`,
            "available from npm `latest` until the signed tag, staging, approval, registry",
            "smoke, and interactive promotion sequence succeeds.",
            "",
            "For production use, pin the published package explicitly:",
            "",
            "~~~powershell",
            `npx --yes ${previousPackage} install --project --platform codex --apply`,
            "~~~",
            "",
            `To exercise the \`${version}\` candidate from a checkout, install the current source`,
            "and open the guided installer locally:",
            "",
            "~~~powershell",
            "python -m pip install -e .",
            "anchor install --interactive",
            "~~~",
          ),
          artifact: lines(
            `This document is packaged with the exact \`${exactPackage}\` release artifact dated`,
            `\`${releaseDate}\`. It`,
            "does not assert registry availability or active dist-tags; verify both externally.",
            "",
            "Use the exact package version only after registry verification:",
            "",
            "~~~powershell",
            `npx --yes ${exactPackage} install --project --platform codex --apply`,
            "~~~",
            "",
            "Open the guided installer from the exact version:",
            "",
            "~~~powershell",
            `npx --yes ${exactPackage} install --interactive`,
            "~~~",
          ),
        },
        {
          source: `These remain separate opt-in integrations and are not part of the \`${version}\` release-candidate scope.`,
          artifact: `These remain separate opt-in integrations and are not part of the \`${version}\` release-artifact scope.`,
        },
        {
          source: lines(
            `After \`${version}\` is published and its registry smoke passes, automation may use`,
            `the exact-version runner \`npx --yes ${exactPackage} ...\`. Keep release and`,
            "automation commands pinned even after npm `latest` moves.",
          ),
          artifact: lines(
            "When the exact registry version is available and its smoke test passes, automation",
            `may use the runner \`npx --yes ${exactPackage} ...\`. Keep release and automation`,
            "commands pinned instead of relying on mutable dist-tags.",
          ),
        },
      ],
    },
    {
      path: "docs/PROJECT_PLAN.md",
      replacements: [
        {
          source: `Status: \`${version}\` release candidate; \`${PREVIOUS_PRODUCTION_VERSION}\` is published production`,
          artifact: `Status: immutable \`${version}\` release artifact dated \`${releaseDate}\`; registry and dist-tag state is external`,
        },
        {
          source: "## What the 0.2 candidate implements",
          artifact: "## What the 0.2 release artifact implements",
        },
        {
          source: lines(
            "After publication and registry smoke, the npm form will run the same surface",
            `through the pinned \`npx --yes ${exactPackage}\` command. During release-candidate`,
            `development use the editable Python checkout and \`anchor\`; \`${previousPackage}\``,
            "remains the production npm package. README and the bundled skill contain the",
            "full structured plan/verification examples.",
          ),
          artifact: lines(
            "When the exact registry version is externally available and its smoke test passes,",
            `the npm form runs the same surface through the pinned \`npx --yes ${exactPackage}\``,
            "command. Development checkouts may use the editable Python installation and `anchor`.",
            "README and the bundled skill contain the full structured plan/verification examples.",
          ),
        },
      ],
    },
  ];

  for (const [relativePath, translation] of Object.entries(translationSpecs(version, releaseDate))) {
    specs.push({
      path: relativePath,
      replacements: [
        { source: translation.source, artifact: translation.artifact },
        ...(translation.extraReplacements || []),
      ],
    });
  }
  return specs;
}

function discoverTranslationPaths(root) {
  const directory = path.join(root, "docs", "i18n");
  return fs
    .readdirSync(directory, { withFileTypes: true })
    .filter((entry) => entry.isFile() && /^README\..+\.md$/.test(entry.name))
    .map((entry) => `docs/i18n/${entry.name}`)
    .sort();
}

function assertTranslationCoverage(root, version, releaseDate) {
  const expected = Object.keys(translationSpecs(version, releaseDate)).sort();
  const discovered = discoverTranslationPaths(root);
  if (JSON.stringify(discovered) !== JSON.stringify(expected)) {
    throw new Error(
      `Release documentation finalizer translation set is stale. Expected ${expected.join(", ")}; found ${discovered.join(", ")}.`,
    );
  }
}

function buildArtifactContents(root, version, releaseDate) {
  assertTranslationCoverage(root, version, releaseDate);
  const outputs = new Map();
  for (const spec of releaseDocumentSpecs(version, releaseDate)) {
    const absolutePath = path.join(root, ...spec.path.split("/"));
    let content = normalizeNewlines(fs.readFileSync(absolutePath, "utf8"));
    for (const replacement of spec.replacements) {
      content = replaceExactlyOnce(content, replacement.source, replacement.artifact, spec.path);
    }
    outputs.set(spec.path, content);
  }
  assertArtifactContents(outputs, version, releaseDate);
  return outputs;
}

function readArtifactContents(root, version, releaseDate) {
  assertTranslationCoverage(root, version, releaseDate);
  const outputs = new Map();
  for (const spec of releaseDocumentSpecs(version, releaseDate)) {
    const absolutePath = path.join(root, ...spec.path.split("/"));
    outputs.set(spec.path, normalizeNewlines(fs.readFileSync(absolutePath, "utf8")));
  }
  return outputs;
}

function assertIncludes(contents, relativePath, marker) {
  const content = contents.get(relativePath);
  if (!content || !content.includes(marker)) {
    throw new Error(`${relativePath}: release artifact marker is missing: ${marker}`);
  }
}

function assertArtifactContents(contents, version, releaseDate) {
  assertReleaseDate(releaseDate);
  const exactPackage = `anchorloop@${version}`;
  const required = new Map([
    ["README.md", `**Release artifact:** \`${exactPackage}\``],
    ["CHANGELOG.md", `## ${version} - ${releaseDate}\n`],
    ["SECURITY.md", `security scope of the \`${exactPackage}\` release`],
    ["CONTRIBUTING.md", `\`${exactPackage}\` is the exact release artifact dated \`${releaseDate}\``],
    ["docs/MIGRATION_0.2.md", `- Exact release artifact: \`${exactPackage}\``],
    ["docs/ANCHOR_DECISION_MAP.md", `immutable \`${exactPackage}\` release artifact`],
    ["docs/PORTABLE_SKILL.md", `exact \`${exactPackage}\` release artifact`],
    ["docs/PROJECT_PLAN.md", `Status: immutable \`${version}\` release artifact`],
  ]);
  for (const [relativePath, marker] of required) {
    assertIncludes(contents, relativePath, marker);
    assertIncludes(contents, relativePath, releaseDate);
  }

  const forbidden = [
    /unreleased/i,
    /release[- ]candidate/i,
    /published production/i,
    /latest stable/i,
    /current release branch/i,
    /npm `latest` (?:continues to resolve|resolves)/i,
    /available from npm `latest`/i,
    /publishes it with npm provenance through OIDC/i,
    /exact-source/i,
  ];
  for (const [relativePath, content] of contents) {
    for (const pattern of forbidden) {
      if (pattern.test(content)) {
        throw new Error(`${relativePath}: release artifact retains forbidden status marker ${pattern}.`);
      }
    }
  }

  const readme = contents.get("README.md");
  if (readme.includes(`npx --yes anchorloop@${PREVIOUS_PRODUCTION_VERSION} install`)) {
    throw new Error("README.md: release artifact still installs the previous production version.");
  }
  if (readme.includes("raw.githubusercontent.com/ppmarkek/AnchorLoop/main/")) {
    throw new Error("README.md: release artifact retains a mutable main-branch image URL.");
  }
  for (const asset of ["anchorloop-delivery-loop.svg", "anchorloop-evidence-integrity.svg"]) {
    const pinned = `https://raw.githubusercontent.com/ppmarkek/AnchorLoop/v${version}/docs/assets/${asset}`;
    if (!readme.includes(pinned)) {
      throw new Error(`README.md: release artifact lacks pinned image URL ${pinned}.`);
    }
  }
  const changelog = contents.get("CHANGELOG.md");
  if (!changelog.includes(`## ${version} - ${releaseDate}`)) {
    throw new Error("CHANGELOG.md: release artifact heading must use the tagged commit date.");
  }

  for (const relativePath of Object.keys(translationSpecs(version, releaseDate))) {
    const banner = contents.get(relativePath).split("\n").slice(0, 10).join("\n");
    if (!banner.includes(`\`${exactPackage}\``)) {
      throw new Error(`${relativePath}: release artifact banner lacks ${exactPackage}.`);
    }
    if (banner.includes(`anchorloop@${PREVIOUS_PRODUCTION_VERSION}`)) {
      throw new Error(`${relativePath}: release artifact banner retains the previous version.`);
    }
    if (!banner.includes(`\`${releaseDate}\``)) {
      throw new Error(`${relativePath}: release artifact banner lacks the tagged commit date.`);
    }
    const dates = banner.match(/\b[0-9]{4}-[0-9]{2}-[0-9]{2}\b/g) || [];
    if (dates.length !== 1 || dates[0] !== releaseDate) {
      throw new Error(`${relativePath}: release artifact banner contains an unexpected release date.`);
    }
  }
}

function finalizeReleaseDocs(root, version, releaseDate) {
  const outputs = buildArtifactContents(root, version, releaseDate);
  for (const [relativePath, content] of outputs) {
    const absolutePath = path.join(root, ...relativePath.split("/"));
    fs.writeFileSync(absolutePath, content, "utf8");
  }
  return [...outputs.keys()];
}

function assertReleaseArtifactDocs(root, version, releaseDate) {
  const contents = readArtifactContents(root, version, releaseDate);
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
      `${options.check ? "Verified" : "Prepared"} ${files.length} release artifact documents for ${options.version}.\n`,
    );
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}

module.exports = {
  SUPPORTED_VERSION,
  assertReleaseArtifactDocs,
  buildArtifactContents,
  finalizeReleaseDocs,
  parseArguments,
  releaseDocumentSpecs,
};
