# AnchorLoop

[English](../../README.md) · [Русский](README.ru.md) · [Español](README.es.md) · [Português](README.pt-BR.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

AnchorLoop est un workflow local pour les agents de programmation assistés par IA. L’ingénieur garde le contrôle des tâches, des règles, de la structure et de la validation finale.

Principe : l’IA peut écrire du code, mais elle ne peut pas approuver son propre plan, activer de nouvelles règles, choisir des skills ou fermer une tâche.

Python 3.11 ou plus récent est nécessaire :

~~~sh
python3 -m pip install -e .
~~~

Dans le dépôt cible :

~~~sh
anchor add
anchor add --apply
anchor rules list
anchor start "Titre court de la tâche"
~~~

Flux principal :

~~~text
start → brief → plan → approve → implement → review → precommit → verify → close
~~~

`precommit` vérifie la syntaxe Python et les espaces Git ; la recherche de secrets possibles n’est activée que par une règle de sécurité approuvée par l’ingénieur. Il ne crée pas de commit. Consultez le README anglais pour la spécification complète.
