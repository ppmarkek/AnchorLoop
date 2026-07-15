# Contributing to AnchorLoop

`anchorloop@0.1.0` is the published public-alpha baseline; current `main` is
the unreleased `0.2.0` release candidate. Small, testable changes that
strengthen its local, agent-neutral workflow core are preferred over broad
integrations.

## Local development

Requirements: Python 3.11 or newer.

~~~powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests
python -m compileall src
~~~

CI exercises Python 3.11-3.14 on Ubuntu and the lock/recovery boundary on
Windows 3.11 and 3.14. Keep platform-specific transaction and installer tests
in the normal suite; do not replace them with Linux-only mocks.

## Change expectations

- Keep the `anchor` CLI and `.anchor/` project state as the source of truth.
- Do not make a host-specific adapter mandatory for another host.
- Do not bypass transitions or engineer-owned gates by editing state JSON
  directly.
- Add regression tests for changed workflow, filesystem, or security behavior.
- Keep setup and installer changes previewable and explicit.
- Treat Graphify, third-party skills, network access, and host configuration as
  opt-in integrations.

## npm launcher

The optional exact-version npm route (for example,
`npx --yes anchorloop@0.2.0 install` after publication) requires Node.js 18 or
newer and must remain a thin launcher around the Python core. During candidate
development exercise the checkout directly. When changing its package,
launcher, or skill templates:

~~~powershell
npm test
npm run pack:check
~~~

Edit `src/anchorloop/version.py` as the canonical release version and mirror
that value in the npm-required `package.json` field. `pyproject.toml` resolves
its dynamic version directly from the canonical module. `npm run
version:check` rejects a stale npm mirror or a mismatched release tag. The
installed skill pins its npx runner to that exact checked version. The npm
archive must include only the launcher, required Python source, skill assets,
and documentation—no `node_modules`, `__pycache__`, `*.pyc`, `.egg-info`, or
project-local cache.

Keep all Anchor-managed reads, writes, appends, removals, and skill-install
paths behind `SafeProjectFS`. Do not add direct `Path.write_text`, fixed-name
temporary files, or symlink-following state access outside that boundary.

## Release safety

Production npm releases are tag-driven. Configure npm trusted publishing for
the `ppmarkek/AnchorLoop` repository, `.github/workflows/release.yml`, and the
protected `npm-release` GitHub environment. Keep the CI jobs as required checks
on `main`. Do not add a long-lived npm token to the workflow.

Create a signed annotated tag whose name exactly matches the canonical version
(for example, `git tag -s v0.2.0 -m "AnchorLoop 0.2.0"`) and ensure the
signing key is associated with the maintainer's GitHub account before pushing
the tag. The release workflow reruns the full Python, wheel, npm, OS, and Node
18/20/22 matrix for the tagged commit; checks the GitHub-verified tag
signature; builds the exact tarball; publishes it with npm provenance through
OIDC; then runs a clean registry-backed install, task lifecycle, uninstall,
and residue check.

This is an exact-source, gated release—not a bit-for-bit reproducible build.
Hosted runner images and Python build tooling still receive upstream updates;
do not claim binary reproducibility without a separately pinned toolchain and
runner-image policy.

`anchorloop@0.1.0` is the published production baseline. npm versions are
immutable: before creating `v0.2.0`, verify that `anchorloop@0.2.0` does not
exist. The release workflow repeats that check, refuses an existing exact
version, and verifies the published `gitHead` after the registry smoke. Never
publish `0.2.0` manually, move a published tag, or attempt to overwrite a
failed release. Fix pre-publish failures in a new commit; for a post-publish
defect, deprecate the affected version and release `0.2.1`. Do not weaken
`release.yml` or add a long-lived token.

## Pull requests

Describe the user-visible behavior, the state transition or invariant affected,
and the checks you ran. Keep unrelated formatting or refactoring out of the
same change when possible.
