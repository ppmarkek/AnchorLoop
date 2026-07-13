# AnchorLoop

> Статус: версия 0.1 подготовлена как release candidate для публичной alpha.
> Пакет `anchorloop` ещё не опубликован в npm, поэтому `npx anchorloop install`
> начнёт работать только после резервирования имени отдельной нижней
> bootstrap-версией, tagged-релиза `0.1.0` и registry smoke test.

[English](../../README.md) · [Русский](README.ru.md) · [Español](README.es.md) · [Português](README.pt-BR.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

AnchorLoop — локальный workflow для работы с AI coding agents, в котором инженер сохраняет контроль над задачами, правилами, структурой и финальной проверкой.

Главный принцип: AI может писать код, но не может сам утверждать план, включать новые правила, выбирать скиллы или закрывать задачу.

Установка требует Python 3.11+:

~~~sh
python3 -m pip install -e .
~~~

В целевом репозитории:

~~~sh
anchor add
anchor add --apply
anchor rules list
anchor start "Краткое название задачи"
~~~

`anchor add --apply` сохраняет существующие правила и дописывает в корневой
`.gitignore` и `.anchor/.gitignore` недостающие пути для cache, npm-cache,
Graphify output, lock, transaction и outbox; эти локальные артефакты нельзя
добавлять в Git.

Основной flow:

~~~text
start → brief → plan → approve → implement → review → precommit → verify → close
~~~

Команда `precommit` проверяет синтаксис Python и Git whitespace; поиск возможных секретов включается только для одобренного инженером правила security. Она не делает commit. Основной английский README содержит актуальную полную документацию, режимы FAST/STANDARD/CAREFUL, безопасную установку skill, транзакционное восстановление и ограничения release candidate.
