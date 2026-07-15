# AnchorLoop

[English](../../README.md) · [Русский](README.ru.md) · [Español](README.es.md) · [Português](README.pt-BR.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

> - **Produção publicada:** `anchorloop@0.1.0`
> - **main não publicado:** release candidate `0.2.0`
> - Até a publicação de `0.2.0`, use `npx --yes anchorloop@0.1.0 ...` em
>   produção. [Guia de migração](../MIGRATION_0.2.md).

AnchorLoop é um workflow local para agentes de programação com IA. A pessoa engenheira mantém o controle das tarefas, das regras, da estrutura e da aceitação final.

Princípio: a IA pode escrever código, mas não pode aprovar seu próprio plano, ativar novas regras, escolher skills ou fechar uma tarefa.

Requer Python 3.11 ou superior:

~~~sh
python3 -m pip install -e .
~~~

No repositório alvo:

~~~sh
anchor add
anchor add --apply
anchor rules list
anchor start "Título curto da tarefa"
~~~

Fluxo principal:

~~~text
start → brief → plan → approve → implement → review → precommit → verify → close
~~~

`precommit` verifica sintaxe Python e espaços do Git; a busca por possíveis segredos só é ativada por uma regra de segurança aprovada pela pessoa engenheira. Ele não cria commits. Consulte o README em inglês para a especificação completa.
