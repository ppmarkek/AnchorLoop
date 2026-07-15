# AnchorLoop

[English](../../README.md) · [Русский](README.ru.md) · [Español](README.es.md) · [Português](README.pt-BR.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

> - **公開済み production:** `anchorloop@0.1.0`
> - **未公開の main:** `0.2.0` release candidate
> - `0.2.0` が公開されるまでは production で
>   `npx --yes anchorloop@0.1.0 ...` を使用してください。[移行ガイド](../MIGRATION_0.2.md)。

AnchorLoop は、AI コーディングエージェントのためのローカル workflow です。エンジニアはタスク、ルール、プロジェクト構造、最終受け入れの管理を維持します。

原則: AI はコードを書けますが、自分の計画を承認したり、新しいルールを有効化したり、スキルを選択したり、タスクを完了したりできません。

Python 3.11 以降が必要です。

~~~sh
python3 -m pip install -e .
~~~

対象リポジトリで実行します。

~~~sh
anchor add
anchor add --apply
anchor rules list
anchor start "短いタスク名"
~~~

基本フロー:

~~~text
start → brief → plan → approve → implement → review → precommit → verify → close
~~~

`precommit` は Python 構文と Git の空白を確認します。秘密情報の可能性の検索は、エンジニアが承認した security ルールがある場合にだけ有効です。commit は作成しません。詳細は英語版 README を参照してください。
