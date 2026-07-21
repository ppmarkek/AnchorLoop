# AnchorLoop

> **公開済み production:** `anchorloop@0.2.0`

**エンジニアが意思決定を管理する、AI 支援ソフトウェア開発のための
エージェント中立ワークフロー。**

[English](../../README.md) · [Русский](README.ru.md) · [Español](README.es.md) · [Português](README.pt-BR.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

AnchorLoop は AI エージェントがコードを書けるようにしながら、目的、
判断、ルール、構造変更、最終受け入れをエンジニアの管理下に置きます。

## ステータス

**公開済み production:** `anchorloop@0.2.0`

`0.2.0` には recovery、検証、ownership モード、安全な release、複数の
エージェント向け skill インストールが含まれます。自動化とインストール
済み skill では常に正確なバージョンを使用してください。

## 基本理念

> エージェントはコードを書けます。なぜ必要なのか、どのトレードオフを
> 採用したのか、どのルールを適用するのか、結果をどう検証するのかは
> エンジニアが決めます。

AnchorLoop はタスクの outcome と制約、plan approval、quality/security
rule、skill の選択、検証、残った不確実性を記録します。

タスクは `AUTO`、`FAST`、`STANDARD`、`CAREFUL` のモードで動きます。
`AUTO` は簡単なドキュメント作業に `FAST`、通常の開発に `STANDARD`、
認証、決済、migration、concurrency、infrastructure、破壊的変更、公開
API、新しい依存関係に `CAREFUL` を選びます。`STANDARD` と `CAREFUL` では
エンジニアの成果物、トレードオフ、検証戦略、理解の説明が必要です。
`CAREFUL` は close の **24 時間後** に recall を予定します。

## Delivery loop

<img src="../../docs/assets/anchorloop-delivery-loop.svg" alt="AnchorLoop の delivery loop" width="100%">

実装はエンジニアが承認した plan に従います。検証に失敗した場合は、
隠れて再開するのではなく `revise` で明示的に戻ります。

## Trust boundary

AnchorLoop は監査可能な workflow gate ですが、認証や access control では
ありません。approval には provenance が含まれます。

- `audit` は承認したと申告された人物を記録します。
- `interactive-tty` は対話端末と `APPROVE` の入力を要求します。
- trusted host adapter や別の approval channel で本人確認を追加できます。

`--by` や端末確認だけでは本人性を証明できません。skill は CLI と
`.anchor/` state の代替ではありません。

## エージェント中立設計

source of truth はローカルの `anchor` CLI と `.anchor/` です。特定の
model、provider、IDE、slash-command 形式には依存しません。

| Host の機能 | AnchorLoop の動作 |
|---|---|
| Terminal | `anchor` CLI を直接実行します。 |
| Instructions / skills | adapter が state を読み、次の許可された操作を表示します。 |
| Commands / hooks / MCP | thin adapter が便利さと guardrails を追加できます。 |
| Terminal なし | engineer または local bridge が CLI を実行し、agent が next action を読みます。 |

すべての host は同じ task state と approval rule を使用します。

## 0.2.0 に含まれる機能

- Agent Skills、Codex、Cursor、Gemini CLI、Claude Code、OpenCode 向け skill。
- symlink と Windows reparse point の拒否、安全な path、atomic write。
- cross-platform lock、redo journal、event outbox、idempotent recovery。
- skill 操作専用の durable journal。
- `anchor doctor`、`doctor --strict`、明示的な `doctor --repair`。
- workspace と Git snapshot の deterministic fingerprint。
- `review` と `precommit` 前の task baseline からの diff 検査。
- `init`、`add`、install の preview と `--apply`。
- `.anchor/`、proposed rules、Graphify metadata、portable protocol、
  next-action file。
- 厳密なフロー:
  `start → brief → plan → approve → implement → review → precommit → verify → close`。

Graphify、プロジェクト固有の test、外部 research、native host adapter は
自動インストールされません。

## 公開 npm パッケージのインストール

必要条件: Node.js 18 以上、Python 3.11 以上。

~~~sh
npx --yes anchorloop@0.2.0 install --project --platform codex --apply
npx --yes anchorloop@0.2.0 install --interactive
~~~

wizard では current project または user profile を選べます。Codex、
Cursor、Gemini CLI、Claude Code、OpenCode、Agent Skills standard、すべての
native destination を選択できます。`.anchor/`、`node_modules`、project
cache は作成されません。

Scripts と CI では明示的なコマンドを使います。

~~~sh
anchor install --project --platform codex --apply
anchor install --global --platform gemini --apply
anchor install --global --all --apply
anchor install --global --all
~~~

## standalone CLI のインストール

~~~sh
pipx install git+https://github.com/ppmarkek/AnchorLoop.git
python -m pip install "git+https://github.com/ppmarkek/AnchorLoop.git"
~~~

これは PyPI release ではなく Git からのインストールです。その後、
`anchor install` で portable skill を追加します。

## 0.1.0 から 0.2.0 への migration

`.anchor/` は削除しないでください。workflow record として、task、rule、
approval、audit を保持します。migration は protocol/support file と skill
asset を更新します。

旧バージョンの recovery を先に完了します。

~~~sh
npx --yes anchorloop@0.1.0 doctor --strict
npx --yes anchorloop@0.1.0 doctor --repair
npx --yes anchorloop@0.1.0 doctor --strict
~~~

次に正確なバージョンで更新します。

~~~sh
npx --yes anchorloop@0.2.0 install --project --platform codex --apply
npx --yes anchorloop@0.2.0 add --apply
npx --yes anchorloop@0.2.0 doctor --strict
~~~

[migration guide](../MIGRATION_0.2.md) も参照してください。

## checkout からの開発

~~~sh
git clone https://github.com/ppmarkek/AnchorLoop.git
cd AnchorLoop
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
~~~

Windows では `.venv\Scripts\Activate.ps1` を実行します。

## standalone CLI から portable skill をインストール

CLI は standalone かつ agent-neutral のままです。skill は CLI と Anchor
state の参照方法だけを提供します。

~~~powershell
anchor install --project --platform agents
anchor install --project --platform agents --apply
anchor install --project --platform codex --apply
anchor uninstall --project --platform agents --apply
~~~

ローカル変更された installer-owned file は、明示的な `--force` なしには
上書きも削除もされません。

## 最初のプロジェクト

~~~sh
anchor add
anchor add --apply
anchor rules list
anchor rules approve baseline-code-quality-v1 --by "Ada Engineer"
anchor rules approve baseline-security-v1 --by "Ada Engineer"
anchor rules approve baseline-structure-v1 --by "Ada Engineer"
anchor start "Retry temporary webhook failures"
anchor brief --by "Ada Engineer" --outcome "Retry temporary failures" --scope "Webhook delivery only" --constraints "Keep the API compatible" --invariant "A transient failure retries safely" --uncertainty "Provider retry limits"
~~~

最初の `anchor add` は plan を表示し、`--apply` が state を作成します。
Outcome、scope、constraints、invariant、uncertainty は engineer 自身が
用意します。

~~~sh
anchor plan --summary "Use bounded exponential backoff and preserve delivery idempotency." --mode AUTO --task-type feature --approach "Retry only transient responses with a bounded idempotent schedule." --alternative "Immediate unlimited retries were rejected because they amplify outages." --risk "A retry can duplicate delivery." --verification "Exercise a transient failure and assert one final delivery." --human-artifact "Ada's acceptance case: two transient failures then one successful delivery with the same id." --comprehension "Prediction: the idempotency key prevents duplicate side effects across attempts." --by "Ada Engineer"
anchor approve --by "Ada Engineer"
anchor implement
anchor review
anchor precommit
anchor verify --by "Ada Engineer" --result pass --reason "The documented manual scenario passed." --recall "The bounded schedule controls load; the stable key controls duplicate effects."
anchor close
~~~

`CAREFUL` では `--rollback-mitigation` も指定します。検証失敗時:

~~~sh
anchor verify --by "Ada Engineer" --result fail --reason "The retry still loses the delivery id." --recall "The key is regenerated on each attempt, so the invariant does not hold."
anchor revise --target implement --reason "Fix the observed behavior within the approved scope."
~~~

解決方法や scope を変更する場合は `--target plan` を使用します。

## Rule は engineer が管理

Rule は最初は proposal で、engineer の approval 後に active になります。

~~~sh
anchor rules list
anchor rules propose structure "Features may import only public module entry points."
anchor rules approve rule-structure-<id> --by "Ada Engineer"
~~~

Agent は rule を提案できますが、active 化、変更、retire、回避はできません。

## Pre-commit と evidence

~~~sh
anchor precommit
~~~

Baseline は Python syntax、active security rule がある場合の credentials /
private keys、`git diff --check` の whitespace を検査します。commit は作成
しません。SHA-256 fingerprint、HEAD、index、diff state も保存されるため、
対象コードが変われば review と precommit をやり直します。

Verification には turns、tokens、active minutes、provider/model、recall、
outcomes を記録できます。これは local audit data であり、検証済み
telemetry ではありません。`anchor report --format json|csv` は model-by-mode
の local report を作成します。

## プロジェクト状態

~~~text
.anchor/
  config.json                 project configuration
  next-action.md              次に許可された action
  protocol/                   portable workflow contract
  tasks/                      active / closed task records
  rules/                      proposed / approved / active rules
  architecture/              structure policy
  graphify/                   integration metadata
  agents/                     detected capabilities and adapters
  project.lock                interprocess lock
  transactions/ and outbox/  recovery and delivery state
  cache/ and logs/            local artifacts
~~~

Migration 後は `anchor add --apply` を再実行し、custom line を保ったまま
cache と recovery の Gitignore entry を追加します。

## ドキュメント

- [Product plan](../PROJECT_PLAN.md)
- [Decision map](../ANCHOR_DECISION_MAP.md)
- [Domain glossary](../../CONTEXT.md)
- [Portable skill](../PORTABLE_SKILL.md)
- [0.1.0 → 0.2.0 migration](../MIGRATION_0.2.md)
- [Changelog](../../CHANGELOG.md)
- [Contributing](../../CONTRIBUTING.md)
- [Security](../../SECURITY.md)

## 開発とテスト

~~~sh
PYTHONPATH=src python3 -m unittest discover -s tests
npm run test:npm
npm run pack:check
~~~

## License

MIT。[LICENSE](../../LICENSE) を参照してください。
