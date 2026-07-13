# AnchorLoop

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

Основной flow:

~~~text
start → brief → plan → approve → implement → review → precommit → verify → close
~~~

Команда `precommit` проверяет синтаксис Python и Git whitespace; поиск возможных секретов включается только для одобренного инженером правила security. Она не делает commit. Основной английский README содержит полную документацию, ограничения текущей pre-alpha версии и план развития.
