# AnchorLoop

[English](../../README.md) · [Русский](README.ru.md) · [Español](README.es.md) · [Português](README.pt-BR.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

> - **Producción publicada:** `anchorloop@0.1.0`
> - **Candidato de versión sin publicar:** `0.2.0`
> - Hasta publicar `0.2.0`, usa `npx --yes anchorloop@0.1.0 ...` en producción.
>   [Guía de migración](../MIGRATION_0.2.md).

AnchorLoop es un workflow local para agentes de programación con IA. El ingeniero conserva el control de las tareas, las reglas, la estructura y la aceptación final.

Principio: la IA puede escribir código, pero no puede aprobar su propio plan, activar reglas nuevas, elegir skills ni cerrar una tarea.

Requiere Python 3.11 o posterior:

~~~sh
python3 -m pip install -e .
~~~

En el repositorio objetivo:

~~~sh
anchor add
anchor add --apply
anchor rules list
anchor start "Título corto de la tarea"
~~~

Flujo principal:

~~~text
start → brief → plan → approve → implement → review → precommit → verify → close
~~~

`precommit` valida sintaxis de Python y espacios de Git; la búsqueda de posibles secretos solo se activa con una regla de seguridad aprobada por el ingeniero. No crea commits. Consulta el README en inglés para la especificación completa.
