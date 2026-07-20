# AnchorLoop

[English](../../README.md) · [Русский](README.ru.md) · [Español](README.es.md) · [Português](README.pt-BR.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

> - **Veröffentlichte Produktion:** `anchorloop@0.1.0`
> - **Unveröffentlichter Release Candidate:** `0.2.0`
> - Bis zur Veröffentlichung von `0.2.0` Produktionsbefehle mit
>   `npx --yes anchorloop@0.1.0 ...` ausführen. [Migrationsanleitung](../MIGRATION_0.2.md).

AnchorLoop ist ein lokaler Workflow für KI-Coding-Agents. Der Engineer behält die Kontrolle über Aufgaben, Regeln, Projektstruktur und die finale Abnahme.

Grundsatz: Die KI darf Code schreiben, aber ihren Plan nicht selbst freigeben, keine neuen Regeln aktivieren, keine Skills auswählen und keine Aufgabe schließen.

Python 3.11 oder neuer wird benötigt:

~~~sh
python3 -m pip install -e .
~~~

Im Ziel-Repository:

~~~sh
anchor add
anchor add --apply
anchor rules list
anchor start "Kurzer Aufgabentitel"
~~~

Hauptablauf:

~~~text
start → brief → plan → approve → implement → review → precommit → verify → close
~~~

`precommit` prüft Python-Syntax und Git-Whitespace; die Suche nach möglichen Secrets wird nur durch eine vom Engineer genehmigte Sicherheitsregel aktiviert. Es erzeugt keinen Commit. Die vollständige Spezifikation steht im englischen README.
