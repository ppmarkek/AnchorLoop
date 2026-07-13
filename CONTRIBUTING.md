# Contributing to AnchorLoop

AnchorLoop is pre-alpha. Small, testable changes that strengthen its local,
agent-neutral workflow core are preferred over broad integrations.

## Local development

Requirements: Python 3.11 or newer.

~~~powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests
python -m compileall src
~~~

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

The optional `npx anchorloop install` route requires Node.js 18 or newer and
must remain a thin launcher around the Python core. When changing its package,
launcher, or skill templates:

~~~powershell
npm test
npm run pack:check
~~~

Keep `package.json` and `pyproject.toml` on the same version: the installed
skill pins its npx runner to that exact version. The npm archive must include
only the launcher, required Python source, skill assets, and documentation—no
`node_modules`, `__pycache__`, `*.pyc`, `.egg-info`, or project-local cache.

Keep all Anchor-managed reads, writes, appends, removals, and skill-install
paths behind `SafeProjectFS`. Do not add direct `Path.write_text`, fixed-name
temporary files, or symlink-following state access outside that boundary.

## Pull requests

Describe the user-visible behavior, the state transition or invariant affected,
and the checks you ran. Keep unrelated formatting or refactoring out of the
same change when possible.
