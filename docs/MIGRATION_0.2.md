# Migrating AnchorLoop from 0.1.0 to 0.2.0

## Release status

- Previous production: `anchorloop@0.1.0`
- Current production: `anchorloop@0.2.0`

The exact `0.2.0` package is available in the public registry. Use exact
versions throughout the migration, do not replace `.anchor/`, and do not skip
the `0.1.0` recovery preflight.

## Compatibility contract

Keep the project's `.anchor/` directory. It contains tasks, rules, approvals,
events, outcomes, and recovery state; neither package upgrade nor skill
installation should replace it.

The `0.2.0` setup path:

- appends missing managed ignore entries without removing custom lines;
- refreshes missing protocol and support files;
- preserves existing task, rule, approval, and audit records;
- continues to read legacy CAREFUL recall records;
- requires an explicit `rules supersede` action for legacy approved rules that
  lack approval-time integrity evidence;
- refuses to overwrite a locally modified installed skill unless `--force` is
  explicitly selected after reviewing the diff.

## Before upgrading: finish any 0.1.0 recovery

From each existing AnchorLoop project, first verify the old installation while
`0.1.0` still owns its recovery format:

~~~sh
npx --yes anchorloop@0.1.0 doctor --strict
~~~

If strict inspection reports pending recovery, repair it with `0.1.0` and then
repeat the strict check:

~~~sh
npx --yes anchorloop@0.1.0 doctor --repair
npx --yes anchorloop@0.1.0 doctor --strict
~~~

Only continue after the final `0.1.0 doctor --strict` succeeds. Preserve its
output if recovery cannot complete; do not ask `0.2.0` to replay a partially
applied legacy journal.

## Upgrade with the exact npm version

From each existing AnchorLoop project:

~~~sh
npx --yes anchorloop@0.2.0 install --project --platform codex --apply
npx --yes anchorloop@0.2.0 add --apply
npx --yes anchorloop@0.2.0 doctor --strict
~~~

Keep commands pinned to `@0.2.0` in automation and installed skill metadata.
The pin makes upgrades deliberate and avoids relying on mutable npm dist-tags.

## Locally modified skill files

If installation reports modified owned assets:

1. inspect the existing skill directory and save its diff outside the managed
   installation;
2. run installation again without `--force` to confirm the conflict;
3. merge any intentional instruction changes into project-owned documentation;
4. only then rerun the exact install command with `--force`.

`--force` applies only to installer-owned skill assets. It does not authorize
deleting or replacing `.anchor/` workflow state.

## Legacy approved rules

A legacy approved rule without its approval-time document digest is not
silently trusted. Propose and approve a replacement in the same category, then
record the migration explicitly:

~~~sh
npx --yes anchorloop@0.2.0 rules supersede <old-rule-id> <new-rule-id> \
  --by "Engineer name" \
  --reason "Migrate the legacy rule to an integrity-protected document."
~~~

## If validation fails

Do not delete `.anchor/`, edit its JSON by hand, or downgrade state in place.
Preserve the checkout and the failing `doctor --strict` output, inspect
transaction/recovery guidance with `status` and the exact installed `doctor`,
and resolve the conflict before retrying. npm versions and published tags must
never be overwritten.
