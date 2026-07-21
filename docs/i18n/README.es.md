# AnchorLoop

> **Producción publicada:** `anchorloop@0.2.0`

**Workflow controlado por ingeniería y neutral para agentes de desarrollo con
IA.**

[English](../../README.md) · [Русский](README.ru.md) · [Español](README.es.md) · [Português](README.pt-BR.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

AnchorLoop permite que un agente de IA escriba código sin quitar al ingeniero
el control sobre objetivos, decisiones, reglas, cambios estructurales y
aceptación final.

## Estado

**Producción publicada:** `anchorloop@0.2.0`

La versión `0.2.0` incluye recuperación, validación, modos de ownership,
releases seguros e instalación de skills para varios agentes. En automatización
y skills instalados usa siempre la versión exacta.

## Idea principal

> El agente puede escribir código. El ingeniero decide por qué existe, qué
> alternativa se eligió, qué reglas aplican y cómo se verifica el resultado.

AnchorLoop registra el objetivo y las restricciones, la aprobación del plan,
las reglas de calidad y seguridad, la selección de skills, la verificación y
las incertidumbres pendientes.

Cada tarea usa `AUTO`, `FAST`, `STANDARD` o `CAREFUL`. `AUTO` elige `FAST` para
documentación y tareas pequeñas, `STANDARD` para desarrollo normal y `CAREFUL`
para autenticación, pagos, migraciones, concurrencia, infraestructura, cambios
destructivos, APIs públicas y nuevas dependencias. `STANDARD` y `CAREFUL`
requieren artefacto del ingeniero, razonamiento de alternativas, estrategia de
verificación y explicación de comprensión. `CAREFUL` programa recall **24 horas
después del cierre**.

## Ciclo de entrega

<img src="../../docs/assets/anchorloop-delivery-loop.svg" alt="Ciclo de entrega de AnchorLoop" width="100%">

La implementación sigue un plan aprobado por el ingeniero. Una verificación
fallida usa `revise` de forma explícita en vez de reabrir trabajo en silencio.

## Límite de confianza

AnchorLoop proporciona gates auditables, pero no es autenticación ni control de
acceso. Los approvals guardan provenance:

- `audit` registra quién declara haber aprobado una acción;
- `interactive-tty` exige terminal interactivo e introducir `APPROVE`;
- un adaptador de host confiable o un canal separado puede vincular identidad.

`--by` y una confirmación de terminal no prueban identidad sin ese canal. El
skill no reemplaza al CLI ni al estado `.anchor/`.

## Diseño neutral para agentes

La fuente de verdad es el CLI local `anchor` y `.anchor/`, no un modelo,
proveedor, IDE o formato de slash-comandos concreto.

| Capacidad del host | Funcionamiento |
|---|---|
| Terminal | Ejecuta directamente `anchor`. |
| Instrucciones o skills | Un adaptador lee el estado y muestra la siguiente acción. |
| Commands, hooks, MCP | Adaptadores finos añaden comodidad y guardrails. |
| Sin terminal | El ingeniero o un bridge local ejecuta CLI; el agente lee next action. |

Todos los hosts usan los mismos estados y reglas de approval.

## Funciones incluidas en 0.2.0

- Skills para Agent Skills, Codex, Cursor, Gemini CLI, Claude Code y OpenCode.
- Protección contra symlinks y Windows reparse points, writes atómicos y paths
  seguros.
- Cross-platform lock, redo journal, event outbox y recovery idempotente.
- Journals durables separados para instalar, actualizar y eliminar skills.
- `anchor doctor`, `doctor --strict` y `doctor --repair` explícito.
- Fingerprints deterministas del workspace y del snapshot Git.
- Revisión del diff desde el task baseline antes de `review` y `precommit`.
- `init`, `add` e instalaciones con preview y `--apply`.
- `.anchor/`, reglas propuestas, metadata Graphify, protocolo portable y
  next-action file.
- Flujo estricto:
  `start → brief → plan → approve → implement → review → precommit → verify → close`.

Graphify, tests específicos del proyecto, investigación externa y adaptadores
native no se instalan automáticamente.

## Instalar el paquete npm publicado

Requisitos: Node.js 18+ y Python 3.11+.

~~~sh
npx --yes anchorloop@0.2.0 install --project --platform codex --apply
npx --yes anchorloop@0.2.0 install --interactive
~~~

El wizard permite elegir el proyecto o el perfil del usuario y ofrece Codex,
Cursor, Gemini CLI, Claude Code, OpenCode, Agent Skills standard o todos los
destinos nativos. No crea `.anchor/`, `node_modules` ni cache del proyecto.

Para scripts y CI:

~~~sh
anchor install --project --platform codex --apply
anchor install --global --platform gemini --apply
anchor install --global --all --apply
anchor install --global --all
~~~

## Instalar el CLI standalone

~~~sh
pipx install git+https://github.com/ppmarkek/AnchorLoop.git
python -m pip install "git+https://github.com/ppmarkek/AnchorLoop.git"
~~~

Es una instalación desde Git, no un release de PyPI. Después usa `anchor
install` para añadir el skill portable.

## Migrar de 0.1.0 a 0.2.0

No borres `.anchor/`: es el registro del workflow. La migración actualiza
protocol/support files y assets del skill, conservando tareas, reglas,
approvals y auditoría.

Primero termina el recovery de la versión anterior:

~~~sh
npx --yes anchorloop@0.1.0 doctor --strict
npx --yes anchorloop@0.1.0 doctor --repair
npx --yes anchorloop@0.1.0 doctor --strict
~~~

Después actualiza con versión exacta:

~~~sh
npx --yes anchorloop@0.2.0 install --project --platform codex --apply
npx --yes anchorloop@0.2.0 add --apply
npx --yes anchorloop@0.2.0 doctor --strict
~~~

Consulta la [guía de migración](../MIGRATION_0.2.md).

## Desarrollo desde un checkout

~~~sh
git clone https://github.com/ppmarkek/AnchorLoop.git
cd AnchorLoop
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
~~~

En Windows activa `.venv\Scripts\Activate.ps1`.

## Instalar el skill portable desde el CLI

El CLI sigue siendo standalone y neutral; el skill solo ayuda a consultar CLI y
estado Anchor.

~~~powershell
anchor install --project --platform agents
anchor install --project --platform agents --apply
anchor install --project --platform codex --apply
anchor uninstall --project --platform agents --apply
~~~

Los archivos modificados localmente no se sobrescriben ni eliminan sin
`--force` explícito.

## Primer proyecto

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

`anchor add` muestra el plan; solo `--apply` crea el estado. El ingeniero debe
proporcionar outcome, scope, constraints, invariant y uncertainty.

~~~sh
anchor plan --summary "Use bounded exponential backoff and preserve delivery idempotency." --mode AUTO --task-type feature --approach "Retry only transient responses with a bounded idempotent schedule." --alternative "Immediate unlimited retries were rejected because they amplify outages." --risk "A retry can duplicate delivery." --verification "Exercise a transient failure and assert one final delivery." --human-artifact "Ada's acceptance case: two transient failures then one successful delivery with the same id." --comprehension "Prediction: the idempotency key prevents duplicate side effects across attempts." --by "Ada Engineer"
anchor approve --by "Ada Engineer"
anchor implement
anchor review
anchor precommit
anchor verify --by "Ada Engineer" --result pass --reason "The documented manual scenario passed." --recall "The bounded schedule controls load; the stable key controls duplicate effects."
anchor close
~~~

Para `CAREFUL`, añade `--rollback-mitigation`. Si falla la verificación:

~~~sh
anchor verify --by "Ada Engineer" --result fail --reason "The retry still loses the delivery id." --recall "The key is regenerated on each attempt, so the invariant does not hold."
anchor revise --target implement --reason "Fix the observed behavior within the approved scope."
~~~

Usa `--target plan` cuando cambien solución o alcance.

## Las reglas pertenecen al ingeniero

Las reglas empiezan como propuestas y se activan solo con approval humano:

~~~sh
anchor rules list
anchor rules propose structure "Features may import only public module entry points."
anchor rules approve rule-structure-<id> --by "Ada Engineer"
~~~

El agente puede proponer reglas, pero no activarlas, modificarlas o saltárselas.

## Pre-commit y evidence

~~~sh
anchor precommit
~~~

La baseline comprueba sintaxis Python, credenciales/private keys cuando la regla
de security está activa y whitespace de `git diff --check`. No crea commits.
También guarda fingerprints SHA-256, HEAD, index y diff state. Un cambio exige
nuevo review y precommit.

Verification puede registrar turns, tokens, minutos, provider/model, recall y
outcomes. Son datos de auditoría local, no telemetry verificada. `anchor report
--format json|csv` genera informes model-by-mode sin subir datos.

## Estado del proyecto

~~~text
.anchor/
  config.json                 Configuración
  next-action.md              Siguiente acción permitida
  protocol/                   Contrato portable
  tasks/                      Tareas abiertas y cerradas
  rules/                      Propuestas y reglas aprobadas
  architecture/              Propuestas de estructura
  graphify/                   Metadata de integración
  agents/                     Capabilities y adapters
  project.lock                Lock entre procesos
  transactions/ y outbox/    Recovery y delivery state
  cache/ y logs/              Artefactos locales
~~~

Después de migrar, repite `anchor add --apply` para añadir entradas de cache y
recovery a los Gitignore sin perder líneas propias.

## Documentación

- [Plan del producto](../PROJECT_PLAN.md)
- [Mapa de decisiones](../ANCHOR_DECISION_MAP.md)
- [Domain glossary](../../CONTEXT.md)
- [Portable skill](../PORTABLE_SKILL.md)
- [Migración 0.1.0 → 0.2.0](../MIGRATION_0.2.md)
- [Changelog](../../CHANGELOG.md)
- [Contributing](../../CONTRIBUTING.md)
- [Security](../../SECURITY.md)

## Desarrollo y tests

~~~sh
PYTHONPATH=src python3 -m unittest discover -s tests
npm run test:npm
npm run pack:check
~~~

## Licencia

MIT. Consulta [LICENSE](../../LICENSE).
