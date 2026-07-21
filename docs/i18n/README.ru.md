# AnchorLoop

> **Опубликованная production-версия:** `anchorloop@0.2.0`

**Workflow для AI-разработки, в котором инженер сохраняет контроль над
решениями.**

[English](../../README.md) · [Русский](README.ru.md) · [Español](README.es.md) · [Português](README.pt-BR.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

AnchorLoop позволяет AI-агенту писать код, не забирая у инженера контроль над
целью, решениями, правилами, изменениями структуры и финальной проверкой.

## Статус

**Опубликованная production-версия:** `anchorloop@0.2.0`

Релиз `0.2.0` включает восстановление после сбоев, валидацию, режимы
владения, безопасный release-процесс и установку skill для нескольких агентов.
В автоматизации и установленных skill используйте точную версию.

## Основная идея

> Агент может писать код. Инженер определяет, зачем он нужен, какие компромиссы
> приняты, какие правила действуют и как проверяется результат.

AnchorLoop фиксирует работу, которая сохраняет инженерный контроль:

- цель и ограничения задачи;
- утверждение плана до реализации;
- утверждение новых quality, security и structure rules;
- выбор skill и внешних решений;
- проверку готового поведения;
- разбор непонятных концепций и решений.

Каждая задача работает в режиме `AUTO`, `FAST`, `STANDARD` или `CAREFUL`.
`AUTO` выбирает `FAST` для простых документационных задач, `STANDARD` для
обычной разработки и `CAREFUL` для authentication, payments, migrations,
concurrency, infrastructure, destructive changes, public APIs и новых
зависимостей. Для `STANDARD` и `CAREFUL` нужны артефакт инженера, объяснение
компромиссов, стратегия проверки и подтверждение понимания. `CAREFUL` добавляет
отложенное recall через **24 часа после закрытия**.

## Цикл поставки

<img src="../../docs/assets/anchorloop-delivery-loop.svg" alt="Цикл AnchorLoop от задачи до проверки и закрытия" width="100%">

Реализация начинается после утвержденного инженером плана. Если проверка не
пройдена, задача возвращается через явный `revise`, а не переоткрывается
скрытым образом.

## Граница доверия

AnchorLoop создает проверяемые workflow-gates, но не является authentication или
access control. Агент с доступом к тому же терминалу может вызвать CLI и
передать имя инженера. Поэтому approval хранит provenance:

- `audit` записывает заявленного согласовавшего;
- `interactive-tty` требует интерактивный терминал и ввод `APPROVE`;
- отдельный trusted host adapter или approval channel может добавить проверку
  личности позже.

`--by` и подтверждение в терминале нельзя считать доказательством личности без
такого доверенного канала. Skill не заменяет CLI и состояние `.anchor/`.

## Agent-neutral по дизайну

Источником истины являются локальный `anchor` CLI и `.anchor/`, а не конкретная
модель, provider, IDE или формат slash-команд.

| Возможность среды | Как работает AnchorLoop |
|---|---|
| Терминал | Запускается CLI `anchor`. |
| Инструкции или skill | Адаптер читает состояние и показывает следующий разрешенный шаг. |
| Native commands, hooks, MCP | Адаптер может добавить удобство или guardrails. |
| Нет интеграции с терминалом | Инженер или локальный bridge запускает CLI, агент читает next action. |

Все среды получают одинаковые состояния задач и правила approval. Native
integrations остаются тонкими адаптерами и не владеют workflow-state.

## Что входит в релиз 0.2.0

- `anchor install` и `anchor uninstall` управляют skill для Agent Skills,
  Codex, Cursor, Gemini CLI, Claude Code и OpenCode.
- Управляемые пути отклоняют symlink и Windows reparse points; запись идет через
  уникальный временный файл и atomic replacement.
- Project mutations защищены cross-platform lock, durable redo journal,
  ordered event outbox и безопасным recovery.
- Установка, обновление и удаление skill используют отдельный durable journal.
- `anchor doctor` только проверяет состояние, `doctor --strict` делает findings
  ошибкой, а `doctor --repair` восстанавливает прерванную операцию.
- Ошибка verification сохраняется и может привести к `anchor revise`.
- Quality gate хранит fingerprints workspace и Git snapshot.
- До `review` и `precommit` проверяется реальный diff от task baseline; пути
  CAREFUL требуют явного review инженера.
- `anchor init` и `anchor add` сначала показывают план и требуют `--apply`.
- Setup создает `.anchor/`, предложенные baseline rules, Graphify metadata,
  portable protocol и next-action file.
- Переходы задачи строго следуют цепочке:
  `start → brief → plan → approve → implement → review → precommit → verify → close`.
- Agent не может сам создать human artifact, comprehension, approval,
  verification, close или delayed recall.

Graphify installation, project-specific test commands, external research,
skill discovery и native host adapters не устанавливаются автоматически.

## Установка опубликованного npm-пакета

Требования: Node.js 18+ и Python 3.11+.

Точная production-команда:

~~~sh
npx --yes anchorloop@0.2.0 install --project --platform codex --apply
~~~

Интерактивная установка:

~~~sh
npx --yes anchorloop@0.2.0 install --interactive
~~~

Wizard предлагает текущий проект или профиль пользователя. В профиле можно
выбрать Codex, Cursor, Gemini CLI, Claude Code, OpenCode, общий Agent Skills
standard или все native locations. Skill не создает `.anchor/`, не изменяет
application code, не добавляет `node_modules` и не создает cache в проекте.

Для scripts и CI используйте явные команды:

~~~sh
anchor install --project --platform codex --apply
anchor install --global --platform gemini --apply
anchor install --global --all --apply
anchor install --global --all
~~~

## Установка standalone CLI

Установка из Git без клонирования:

~~~sh
pipx install git+https://github.com/ppmarkek/AnchorLoop.git
~~~

Или в активное окружение Python:

~~~sh
python -m pip install "git+https://github.com/ppmarkek/AnchorLoop.git"
~~~

Это Git-установка, не релиз PyPI. После установки запускайте `anchor install`
для добавления portable skill.

## Миграция с 0.1.0 на 0.2.0

Не удаляйте `.anchor/`: это workflow record проекта. Миграция обновляет
управляемые protocol/support files и skill assets, сохраняя tasks, rules,
approvals и audit records. Локально измененный skill сначала проверьте, затем
используйте `--force` только осознанно.

Перед обновлением завершите recovery старой версии:

~~~sh
npx --yes anchorloop@0.1.0 doctor --strict
npx --yes anchorloop@0.1.0 doctor --repair
npx --yes anchorloop@0.1.0 doctor --strict
~~~

Затем обновите проект точной версией:

~~~sh
npx --yes anchorloop@0.2.0 install --project --platform codex --apply
npx --yes anchorloop@0.2.0 add --apply
npx --yes anchorloop@0.2.0 doctor --strict
~~~

Подробности: [руководство миграции](../MIGRATION_0.2.md).

## Разработка из checkout

~~~sh
git clone https://github.com/ppmarkek/AnchorLoop.git
cd AnchorLoop
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
~~~

Windows:

~~~powershell
.venv\Scripts\Activate.ps1
~~~

## Установка portable skill через standalone CLI

CLI остается standalone и agent-neutral. Skill только подсказывает агенту, как
прочитать CLI и текущее состояние Anchor.

~~~powershell
anchor install --project --platform agents
anchor install --project --platform agents --apply
anchor install --project --platform codex --apply
~~~

Для удаления только неизмененных файлов:

~~~powershell
anchor uninstall --project --platform agents --apply
~~~

Installer не изменяет `.anchor/`, application code, `AGENTS.md`, hooks или
Graphify configuration. Измененные локально skill assets не перезаписываются
без явного `--force`.

## Первый проект

В целевом проекте:

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

Первая команда только показывает setup plan. `--apply` создает state. Никакие
файлы не индексируются и не изменяются без явного действия.

Инженер должен самостоятельно предоставить:

~~~text
Outcome:
Scope / non-goals:
Constraints:
Invariant or acceptance case:
Main uncertainty:
~~~

Затем выполните workflow:

~~~sh
anchor plan --summary "Use bounded exponential backoff and preserve delivery idempotency." --mode AUTO --task-type feature --approach "Retry only transient responses with a bounded idempotent schedule." --alternative "Immediate unlimited retries were rejected because they amplify outages." --risk "A retry can duplicate delivery." --verification "Exercise a transient failure and assert one final delivery." --human-artifact "Ada's acceptance case: two transient failures then one successful delivery with the same id." --comprehension "Prediction: the idempotency key prevents duplicate side effects across attempts." --by "Ada Engineer"
anchor approve --by "Ada Engineer"
anchor implement
anchor review
anchor precommit
anchor verify --by "Ada Engineer" --result pass --reason "The documented manual scenario passed." --recall "The bounded schedule controls load; the stable key controls duplicate effects."
anchor close
~~~

Для `CAREFUL` добавьте `--rollback-mitigation`. После закрытия recall доступен
через 24 часа:

~~~sh
anchor recall --task <id> --by "Ada Engineer" --response "..." --score 0..5
~~~

Если verification не прошла, сохраните evidence и явно вернитесь к реализации:

~~~sh
anchor verify --by "Ada Engineer" --result fail --reason "The retry still loses the delivery id." --recall "The key is regenerated on each attempt, so the invariant does not hold."
anchor revise --target implement --reason "Fix the observed behavior within the approved scope."
~~~

Используйте `--target plan`, если нужно изменить решение или scope.

## Rules принадлежат инженеру

Baseline rules для quality, security и structure сначала являются proposals.
Они становятся active только после approval инженера:

~~~sh
anchor rules list
anchor rules propose structure "Features may import only public module entry points."
anchor rules approve rule-structure-<id> --by "Ada Engineer"
~~~

Ruleset фиксируется в задаче при approval плана. Agent может предложить rule,
но не может сам активировать, изменить, retire или обойти его.

## Pre-commit и evidence

Перед verification выполните:

~~~sh
anchor precommit
~~~

Baseline проверяет invalid Python syntax, возможные credentials/private keys
при active security rule и whitespace errors из `git diff --check`. Команда не
создает commit. Она также сохраняет SHA-256 fingerprint файлов, Git HEAD,
index и diff state. Если код или authoritative Git state изменился, задача
возвращается к review и требует новый precommit.

Verification может записывать turns, tokens, active minutes, provider/model,
recall и outcomes. Это локальные audit inputs, а не подтвержденная telemetry.
`anchor outcome` сохраняет production follow-up, а
`anchor report --format json|csv` строит локальный отчет по model × mode.

## Состояние проекта

~~~text
.anchor/
  config.json
  next-action.md
  protocol/                 portable workflow contract
  tasks/                    active and closed task records
  rules/                    proposals, approved versions, active rules
  architecture/             structure proposals and policy
  graphify/                 integration metadata
  agents/                   detected capabilities and adapter manifests
  project.lock              ignored cross-process lock metadata
  transactions/ and outbox/ ignored recovery journals and delivery state
  cache/ and logs/          ignored local artefacts
~~~

Файлы читаемы человеком. После миграции повторите `anchor add --apply`, чтобы
добавить недостающие cache и recovery entries в `.gitignore` и
`.anchor/.gitignore`, сохранив пользовательские строки.

## Документация

- [План продукта](../PROJECT_PLAN.md)
- [Карта решений](../ANCHOR_DECISION_MAP.md)
- [Domain glossary](../../CONTEXT.md)
- [Portable skill](../PORTABLE_SKILL.md)
- [Миграция 0.1.0 → 0.2.0](../MIGRATION_0.2.md)
- [Changelog](../../CHANGELOG.md)
- [Contributing](../../CONTRIBUTING.md)
- [Security policy](../../SECURITY.md)

## Разработка и тесты

~~~sh
PYTHONPATH=src python3 -m unittest discover -s tests
npm run test:npm
npm run pack:check
~~~

## Лицензия

MIT. См. [LICENSE](../../LICENSE).
