import json
import pathlib
import re
import tomllib
import unittest

from anchorloop.version import VERSION


def _workflow_job(workflow: str, job_name: str) -> str:
    lines = workflow.splitlines()
    marker = f"  {job_name}:"
    try:
        start = lines.index(marker)
    except ValueError as error:
        raise AssertionError(f"Workflow job {job_name!r} is missing") from error
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.fullmatch(r"  [A-Za-z0-9_-]+:", lines[index]):
            end = index
            break
    return "\n".join(lines[start:end])


def _workflow_step(job: str, step_name: str) -> str:
    lines = job.splitlines()
    marker = f"      - name: {step_name}"
    try:
        start = lines.index(marker)
    except ValueError as error:
        raise AssertionError(f"Workflow step {step_name!r} is missing") from error
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("      - "):
            end = index
            break
    return "\n".join(lines[start:end])


class ReleaseVersionTests(unittest.TestCase):
    def test_python_and_npm_packaging_use_the_canonical_version(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1]
        pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        package = json.loads((root / "package.json").read_text(encoding="utf-8"))

        self.assertNotIn("version", pyproject["project"])
        self.assertIn("version", pyproject["project"]["dynamic"])
        self.assertEqual(
            pyproject["tool"]["setuptools"]["dynamic"]["version"]["attr"],
            "anchorloop.version.VERSION",
        )
        self.assertEqual(package["version"], VERSION)
        self.assertIn("src/anchorloop/version.py", package["files"])

    def test_release_workflow_stages_with_oidc_and_keeps_promotion_human_owned(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        finalizer = (root / "npm" / "scripts" / "finalize-release-docs.js").read_text(
            encoding="utf-8"
        )

        exact_tag_ci = _workflow_job(workflow, "exact-tag-ci")
        publish = _workflow_job(workflow, "publish-npm")
        verify = _workflow_job(workflow, "verify-public-registry")

        self.assertIn("    if: github.event_name == 'push'", exact_tag_ci)
        self.assertIn("    uses: ./.github/workflows/ci.yml", exact_tag_ci)
        self.assertIn("    if: github.event_name == 'push'", publish)
        self.assertIn("    needs: exact-tag-ci", publish)
        self.assertIn("    environment: npm-release", publish)
        self.assertIn(
            "    permissions:\n      contents: read\n      id-token: write",
            publish,
        )
        self.assertIn("    if: github.event_name == 'workflow_dispatch'", verify)
        self.assertIn("    permissions:\n      contents: read", verify)
        self.assertNotIn("id-token: write", verify)

        signed_tag = _workflow_step(
            publish,
            "Require a GitHub-verified signed annotated tag",
        )
        ancestry = _workflow_step(
            publish,
            "Require tagged commit to be merged into main",
        )
        prepare_docs = _workflow_step(
            publish,
            "Prepare time-invariant release artifact documentation",
        )
        verify_docs = _workflow_step(
            publish,
            "Verify release artifact documentation and mutation boundary",
        )
        package_preview = _workflow_step(
            publish,
            "Dry-run package assembly from the finalized checkout",
        )
        stage = _workflow_step(
            publish,
            "Stage candidate with npm provenance through trusted publishing",
        )
        handoff = _workflow_step(publish, "Record the human approval handoff")

        self.assertIn(".verification.verified", signed_tag)
        self.assertIn('test "$target_sha" = "$(git rev-parse HEAD)"', signed_tag)
        self.assertIn(
            'git merge-base --is-ancestor "$tagged_commit" refs/remotes/origin/main',
            ancestry,
        )
        for required_file in (
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
        ):
            self.assertIn(required_file, finalizer)
        self.assertIn("git show -s --format=%cs HEAD", prepare_docs)
        self.assertIn("npm/scripts/finalize-release-docs.js", prepare_docs)
        self.assertIn('--release-date "$release_date"', prepare_docs)
        self.assertIn("npm/scripts/finalize-release-docs.js", verify_docs)
        self.assertIn("--check", verify_docs)
        self.assertIn("CONTRIBUTING.md", verify_docs)
        self.assertIn("git diff --cached --quiet --", verify_docs)
        self.assertIn("git diff --cached --name-only --", verify_docs)
        self.assertIn("git ls-files --others --exclude-standard -z", verify_docs)
        self.assertIn("Unexpected untracked release path", verify_docs)
        for protected_path in (
            "src npm package.json package-lock.json pyproject.toml",
            "Unexpected release artifact mutation",
        ):
            self.assertIn(protected_path, " ".join(verify_docs.split()))
        self.assertLess(
            verify_docs.index("git diff --cached --quiet --"),
            verify_docs.index("git ls-files --others --exclude-standard -z"),
        )
        self.assertLess(
            verify_docs.index("git ls-files --others --exclude-standard -z"),
            verify_docs.index("git diff --exit-code --"),
        )
        self.assertNotIn("Require final release documentation", publish)
        self.assertNotIn("release-candidate", finalizer)
        self.assertIn("published production", finalizer)
        self.assertIn("validates the tagged checkout", finalizer)
        self.assertNotIn("raw.githubusercontent.com/ppmarkek/AnchorLoop/v${version}/", finalizer)
        self.assertIn("npm pack --dry-run --ignore-scripts", package_preview)
        self.assertIn("npm stage publish .", " ".join(stage.split()))
        self.assertIn("--ignore-scripts", stage)
        self.assertNotIn("steps.archive.outputs.path", stage)
        self.assertNotRegex(stage, r"npm stage publish\s+.*\.tgz")
        self.assertIn("--tag next", stage)
        self.assertIn("exact staged artifact", handoff)
        self.assertIn("npm stage approve <stage-id>", handoff)
        self.assertIn(
            "gh workflow run release.yml --ref v${VERSION} -f version=${VERSION}",
            handoff,
        )
        self.assertLess(publish.index(signed_tag), publish.index(ancestry))
        self.assertLess(publish.index(ancestry), publish.index(prepare_docs))
        self.assertLess(publish.index(prepare_docs), publish.index(verify_docs))
        self.assertLess(publish.index(verify_docs), publish.index(package_preview))
        self.assertLess(publish.index(package_preview), publish.index(stage))
        self.assertLess(publish.index(stage), publish.index(handoff))

        requested_version = _workflow_step(
            verify,
            "Verify requested version and exact release tag",
        )
        revalidated_tag = _workflow_step(
            verify,
            "Revalidate GitHub-verified signed annotated tag",
        )
        verify_ancestry = _workflow_step(
            verify,
            "Require tagged commit to remain in main",
        )
        approved_candidate = _workflow_step(
            verify,
            "Require exact version to be the approved next candidate",
        )
        registry_smoke = _workflow_step(
            verify,
            "Smoke-test the exact public registry release",
        )
        commit_identity = _workflow_step(verify, "Verify published commit identity")
        promotion = _workflow_step(verify, "Record the human-owned promotion command")

        self.assertIn(".verification.verified", revalidated_tag)
        self.assertIn('expected_ref="refs/tags/v${REQUESTED_VERSION}"', requested_version)
        self.assertIn('test "$GITHUB_REF" = "$expected_ref"', requested_version)
        self.assertIn(
            "gh workflow run release.yml --ref v${REQUESTED_VERSION} -f version=${REQUESTED_VERSION}",
            requested_version,
        )
        self.assertIn('test "$object_type" = "tag"', revalidated_tag)
        self.assertIn('test "$target_type" = "commit"', revalidated_tag)
        self.assertIn('test "$target_sha" = "$(git rev-parse HEAD)"', revalidated_tag)
        self.assertIn("git merge-base --is-ancestor", verify_ancestry)
        self.assertIn('npm view "${PACKAGE_NAME}@next" version', approved_candidate)
        self.assertIn("node npm/scripts/registry-smoke.js", registry_smoke)
        self.assertIn('npm view "${PACKAGE_NAME}@${VERSION}" gitHead', commit_identity)
        self.assertIn("npm dist-tag add ${PACKAGE_NAME}@${VERSION} latest", promotion)
        self.assertIn("Promotion remains an interactive maintainer action with 2FA", promotion)
        self.assertIn("Follow-up documentation", promotion)
        self.assertIn("must not republish", promotion)
        self.assertIn("v${VERSION} artifact unchanged", promotion)
        self.assertLess(verify.index(requested_version), verify.index(revalidated_tag))
        self.assertLess(verify.index(revalidated_tag), verify.index(verify_ancestry))
        self.assertLess(verify.index(verify_ancestry), verify.index(approved_candidate))
        self.assertLess(verify.index(approved_candidate), verify.index(registry_smoke))
        self.assertLess(verify.index(registry_smoke), verify.index(commit_identity))
        self.assertLess(verify.index(commit_identity), verify.index(promotion))

        self.assertNotRegex(workflow, r"(?m)^\s+npm publish(?:\s|$)")
        self.assertNotRegex(workflow, r"(?m)^\s+npm dist-tag add(?:\s|$)")
        self.assertNotIn("NODE_AUTH_TOKEN", workflow)
        self.assertNotIn("secrets.", workflow)

    def test_release_documentation_describes_published_0_2(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        security = (root / "SECURITY.md").read_text(encoding="utf-8")
        contributing = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
        migration = (root / "docs" / "MIGRATION_0.2.md").read_text(encoding="utf-8")
        decision_map = (root / "docs" / "ANCHOR_DECISION_MAP.md").read_text(
            encoding="utf-8"
        )
        project_plan = (root / "docs" / "PROJECT_PLAN.md").read_text(encoding="utf-8")
        normalized_decision_map = " ".join(decision_map.split())
        translations = sorted((root / "docs" / "i18n").glob("README.*.md"))

        self.assertIn("**Published production:** `anchorloop@0.2.0`", readme)
        self.assertNotIn("**Unreleased candidate:** `0.2.0` release candidate", readme)
        self.assertIn('src="docs/assets/anchorloop-delivery-loop.svg"', readme)
        self.assertIn('src="docs/assets/anchorloop-evidence-integrity.svg"', readme)
        self.assertNotIn("raw.githubusercontent.com/ppmarkek/AnchorLoop/main/", readme)
        self.assertIn("deterministic materialized-file fallback", readme)
        self.assertIn("## 0.2.0 - Published", changelog)
        self.assertIn("Published production is `anchorloop@0.2.0`", security)
        self.assertIn("Current production release", security)
        self.assertNotIn("unreleased release", security.lower())
        self.assertIn("anchorloop@0.2.0` is the published production baseline", contributing)
        self.assertIn("stage-only OIDC", contributing)
        self.assertIn("approves it with 2FA", contributing)
        self.assertIn("tag-bound exact registry smoke", " ".join(contributing.split()))
        self.assertIn("`latest` manually with 2FA", contributing)
        self.assertIn("validates the packaged documentation", contributing)
        self.assertIn("exact staged tarball", contributing)
        self.assertIn("directory-derived `gitHead`", " ".join(contributing.split()))
        self.assertIn("Both the dry-run and staging disable lifecycle", contributing)
        self.assertIn("disable lifecycle scripts", contributing)
        self.assertNotIn("publishes it with npm provenance through OIDC", contributing)
        self.assertNotIn("exact-source", contributing)
        self.assertIn("- Current production: `anchorloop@0.2.0`", migration)
        self.assertNotIn("Current release branch", migration)
        old_strict = "npx --yes anchorloop@0.1.0 doctor --strict"
        old_repair = "npx --yes anchorloop@0.1.0 doctor --repair"
        new_install = "npx --yes anchorloop@0.2.0 install"
        self.assertLess(migration.index(old_strict), migration.index(old_repair))
        self.assertLess(migration.index(old_repair), migration.index(new_install))
        self.assertIn("staged npm publishing", normalized_decision_map)
        self.assertIn("stores no npm token", normalized_decision_map)
        self.assertIn("`anchorloop@0.2.0` is published production", decision_map)
        self.assertIn("deterministic materialized-file fallback", project_plan)
        for translation in translations:
            banner = "\n".join(translation.read_text(encoding="utf-8").splitlines()[:10])
            self.assertIn("anchorloop@0.2.0", banner, translation.name)
            self.assertNotIn("anchorloop@0.1.0", banner, translation.name)
            self.assertNotRegex(banner, r"\b[0-9]{4}-[0-9]{2}-[0-9]{2}\b", translation.name)


if __name__ == "__main__":
    unittest.main()
