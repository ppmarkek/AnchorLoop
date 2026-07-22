# Contributing to AnchorLoop

`anchorloop@0.2.1` is the current published production release. Small,
testable changes that strengthen its local, agent-neutral workflow core are
preferred over broad integrations.

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
`npx --yes anchorloop@0.2.1 install`) requires Node.js 18 or newer and must
remain a thin launcher around the Python core. During development, exercise
the checkout directly. When changing its package, launcher, or skill templates:

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

Production npm releases are signed-tag driven. Configure npm trusted publishing for
the `ppmarkek/AnchorLoop` repository, `.github/workflows/release.yml`, and the
protected `npm-release` GitHub environment. Keep the CI jobs as required checks
on `main`. Do not add a long-lived npm token to the workflow.

Create a signed annotated tag whose name exactly matches the canonical version
(for example, `git tag -s v0.2.1 -m "AnchorLoop 0.2.1"`) and ensure the
signing key is associated with the maintainer's GitHub account before pushing
the tag. After the full Python, wheel, npm, OS, and Node 18/20/22 matrix passes,
a disposable publish job validates the packaged documentation using the tagged
commit date. It rejects staged changes, non-ignored untracked paths, and
tracked mutations outside the documentation allowlist before a dry-run of
package assembly. Both the dry-run and staging disable lifecycle scripts so
the checked payload cannot mutate afterward. The job then passes the finalized
Git checkout directory to `npm stage publish` under `next` with provenance
through stage-only OIDC, preserving npm's internal directory-derived `gitHead`;
it never calls `npm publish` or promotes `latest`.

This produces deterministic packaged documentation and one reviewed tarball
from the signed source and commit date, but it is not a bit-for-bit binary
reproducibility claim. Hosted runner images and Python build tooling still
receive upstream updates; do not claim binary reproducibility without a
separately pinned toolchain and runner-image policy.

`anchorloop@0.2.1` is the published production baseline. npm versions are
immutable: verify that the exact next version does not exist before creating a
release tag. The signed-tag workflow runs exact-tag CI, validates the
documentation and package boundary, stages the tarball under `next` with
stage-only OIDC, and records npm `gitHead`. A maintainer downloads and inspects
the exact staged tarball, approves it with 2FA, dispatches the tag-bound exact
registry smoke, verifies npm `gitHead`, and only then promotes the version to
`latest` manually with 2FA. Never publish an existing version directly, move a
signed tag, or overwrite a failed release. Fix pre-stage failures in a new
commit; after approval, deprecate a defective version and release a new patch.
Do not weaken `release.yml` or add a long-lived token.

## Pull requests

Describe the user-visible behavior, the state transition or invariant affected,
and the checks you ran. Keep unrelated formatting or refactoring out of the
same change when possible.
