# AnchorLoop

[English](../../README.md) · [Русский](README.ru.md) · [Español](README.es.md) · [Português](README.pt-BR.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

> - **已发布的 production：** `anchorloop@0.1.0`
> - **尚未发布的 release candidate：** `0.2.0`
> - 在 `0.2.0` 发布前，production 请使用
>   `npx --yes anchorloop@0.1.0 ...`。[迁移指南](../MIGRATION_0.2.md)。

AnchorLoop 是面向 AI 编程代理的本地 workflow。工程师始终掌控任务、规则、项目结构和最终验收。

核心原则：AI 可以编写代码，但不能自行批准计划、启用新规则、选择技能或关闭任务。

需要 Python 3.11 或更高版本：

~~~sh
python3 -m pip install -e .
~~~

在目标仓库中运行：

~~~sh
anchor add
anchor add --apply
anchor rules list
anchor start "简短任务标题"
~~~

主要流程：

~~~text
start → brief → plan → approve → implement → review → precommit → verify → close
~~~

`precommit` 会检查 Python 语法和 Git 空白问题；只有工程师批准 security 规则后，才会检查可能的密钥。它不会创建 commit。完整说明请查看英文 README。
