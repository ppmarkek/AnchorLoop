# AnchorLoop

> **Veröffentlichte Production-Version:** `anchorloop@0.2.1`

**Ein ingenieurgeführter, agent-neutraler Workflow für KI-gestützte
Softwareentwicklung.**

[English](../../README.md) · [Русский](README.ru.md) · [Español](README.es.md) · [Português](README.pt-BR.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

AnchorLoop erlaubt einem AI-Agenten, Code zu schreiben, ohne dem Engineer die
Kontrolle über Ziel, Entscheidungen, Regeln, Strukturänderungen und Abnahme zu
entziehen.

## Status

**Veröffentlichte Production-Version:** `anchorloop@0.2.1`

Version `0.2.1` enthält Recovery, Validierung, Ownership-Modi, sichere Releases
und Skill-Installation für mehrere Agents. Verwende in Automatisierung und
installierten Skills immer die exakte Version.

## Grundidee

> Der Agent darf Code schreiben. Der Engineer entscheidet, warum er existiert,
> welche Abwägung gilt, welche Regeln anzuwenden sind und wie das Ergebnis
> geprüft wird.

AnchorLoop hält Outcome und Constraints, Plan-Approval, neue Qualitäts- und
Security-Regeln, Skill-Auswahl, Verifikation und offene Unsicherheiten fest.

Jede Aufgabe nutzt `AUTO`, `FAST`, `STANDARD` oder `CAREFUL`. `AUTO` wählt
`FAST` für einfache Dokumentationsaufgaben, `STANDARD` für normale Entwicklung
und `CAREFUL` für Authentifizierung, Zahlungen, Migrationen, Concurrency,
Infrastruktur, destruktive Änderungen, öffentliche APIs und neue Dependencies.
`STANDARD` und `CAREFUL` erfordern einen Engineer-Artefakt, Abwägungen,
Verifikationsstrategie und eine Verständnis-Erklärung. `CAREFUL` plant Recall
**24 Stunden nach dem Schließen**.

## Lieferzyklus

<img src="../../docs/assets/anchorloop-delivery-loop.svg" alt="AnchorLoop-Lieferzyklus" width="100%">

Die Implementierung folgt einem genehmigten Plan. Bei fehlgeschlagener Prüfung
führt `revise` explizit zurück, statt die Arbeit verborgen neu zu öffnen.

## Vertrauensgrenze

AnchorLoop ist ein auditierbares Workflow-Gate, aber keine Authentifizierung und
kein Access-Control-System. Approval-Daten enthalten Provenance:

- `audit` speichert, wer eine Aktion als genehmigt angibt;
- `interactive-tty` verlangt ein interaktives Terminal und `APPROVE`;
- ein vertrauenswürdiger Host-Adapter oder separater Approval-Kanal kann später
  die Identität binden.

`--by` oder eine Terminal-Bestätigung beweisen ohne solchen Kanal keine
Identität. Der Skill ersetzt weder CLI noch `.anchor/`.

## Agent-neutral

Quelle der Wahrheit sind das lokale `anchor` CLI und `.anchor/`, nicht ein
bestimmtes Modell, ein Provider, eine IDE oder ein Slash-Command-Format.

| Host-Fähigkeit | Verhalten |
|---|---|
| Terminal | `anchor` direkt ausführen. |
| Instructions oder Skills | Ein Adapter liest den Status und zeigt die nächste Aktion. |
| Commands, Hooks, MCP | Ein dünner Adapter kann Komfort und Guardrails hinzufügen. |
| Kein Terminal | Engineer oder lokaler Bridge führt CLI aus; der Agent liest next action. |

Alle Hosts verwenden dieselben Task-Zustände und Approval-Regeln.

## Funktionen von 0.2.1

- Installation, Update und Entfernung eines Skills für Agent Skills, Codex,
  Cursor, Gemini CLI, Claude Code und OpenCode.
- Symlink- und Windows-Reparse-Point-Schutz, atomare Writes und sichere Pfade.
- Cross-platform lock, redo journal, event outbox und idempotentes Recovery.
- Separate durable journals für Skill-Operationen.
- `anchor doctor`, `doctor --strict` und explizites `doctor --repair`.
- Workspace- und Git-Snapshot-Fingerprints als Quality Evidence.
- Diff-Prüfung vom Task-Baseline vor `review` und `precommit`.
- Preview/Apply für `init`, `add` und Installationen.
- Portable `.anchor/`-State, vorgeschlagene Rules, Graphify-Metadata und
  portable Agent-Protokoll.
- Strikter Ablauf:
  `start → brief → plan → approve → implement → review → precommit → verify → close`.

Graphify, projektspezifische Tests, externe Recherche und native Host-Adapter
werden nicht automatisch installiert.

## Installation des veröffentlichten npm-Pakets

Voraussetzungen: Node.js 18+ und Python 3.11+.

~~~sh
npx --yes anchorloop@0.2.1 install --project --platform codex --apply
npx --yes anchorloop@0.2.1 install --interactive
~~~

Der Wizard bietet Projekt- oder Benutzerprofil-Installation für Codex, Cursor,
Gemini CLI, Claude Code, OpenCode, den Agent-Skills-Standard oder alle nativen
Ziele. Er erzeugt weder `.anchor/` noch `node_modules` und schreibt keinen
Projekt-Cache.

Für Scripts und CI:

~~~sh
anchor install --project --platform codex --apply
anchor install --global --platform gemini --apply
anchor install --global --all --apply
anchor install --global --all
~~~

## Standalone CLI installieren

~~~sh
pipx install git+https://github.com/ppmarkek/AnchorLoop.git
python -m pip install "git+https://github.com/ppmarkek/AnchorLoop.git"
~~~

Dies ist ein Git-Weg, kein PyPI-Release. Danach fügt `anchor install` den
optionalen Portable Skill hinzu.

## Migration von 0.1.0 auf 0.2.1

`.anchor/` darf nicht gelöscht werden. Die Migration aktualisiert verwaltete
Protokoll-, Support- und Skill-Dateien und bewahrt Tasks, Rules, Approvals und
Audit Records.

Zuerst altes Recovery abschließen:

~~~sh
npx --yes anchorloop@0.1.0 doctor --strict
npx --yes anchorloop@0.1.0 doctor --repair
npx --yes anchorloop@0.1.0 doctor --strict
~~~

Dann exakt auf `0.2.1` umstellen:

~~~sh
npx --yes anchorloop@0.2.1 install --project --platform codex --apply
npx --yes anchorloop@0.2.1 add --apply
npx --yes anchorloop@0.2.1 doctor --strict
~~~

Siehe [Migrationsanleitung](../MIGRATION_0.2.md).

## Entwicklung aus einem Checkout

~~~sh
git clone https://github.com/ppmarkek/AnchorLoop.git
cd AnchorLoop
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
~~~

Unter Windows: `.venv\Scripts\Activate.ps1`.

## Portable Skill über die CLI installieren

Der Skill bleibt ein dünner, agent-neutraler Adapter um CLI und `.anchor/`:

~~~powershell
anchor install --project --platform agents
anchor install --project --platform agents --apply
anchor install --project --platform codex --apply
anchor uninstall --project --platform agents --apply
~~~

Lokale Änderungen an installer-eigenen Dateien werden ohne bewusstes `--force`
nicht überschrieben oder gelöscht.

## Erstes Projekt

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

`anchor add` zeigt zuerst den Plan; erst `--apply` schreibt State. Der Engineer
liefert Outcome, Scope, Constraints, Invariant und Unsicherheit selbst.

~~~sh
anchor plan --summary "Use bounded exponential backoff and preserve delivery idempotency." --mode AUTO --task-type feature --approach "Retry only transient responses with a bounded idempotent schedule." --alternative "Immediate unlimited retries were rejected because they amplify outages." --risk "A retry can duplicate delivery." --verification "Exercise a transient failure and assert one final delivery." --human-artifact "Ada's acceptance case: two transient failures then one successful delivery with the same id." --comprehension "Prediction: the idempotency key prevents duplicate side effects across attempts." --by "Ada Engineer"
anchor approve --by "Ada Engineer"
anchor implement
anchor review
anchor precommit
anchor verify --by "Ada Engineer" --result pass --reason "The documented manual scenario passed." --recall "The bounded schedule controls load; the stable key controls duplicate effects."
anchor close
~~~

Für `CAREFUL` zusätzlich `--rollback-mitigation` verwenden. Bei einem Fehler:

~~~sh
anchor verify --by "Ada Engineer" --result fail --reason "The retry still loses the delivery id." --recall "The key is regenerated on each attempt, so the invariant does not hold."
anchor revise --target implement --reason "Fix the observed behavior within the approved scope."
~~~

## Regeln gehören dem Engineer

Rules beginnen als Vorschläge und werden erst durch den Engineer aktiv:

~~~sh
anchor rules list
anchor rules propose structure "Features may import only public module entry points."
anchor rules approve rule-structure-<id> --by "Ada Engineer"
~~~

Ein Agent darf Rules vorschlagen, aber nicht selbst aktivieren, ändern oder
umgehen.

## Pre-Commit und Evidence

~~~sh
anchor precommit
~~~

Der Baseline-Check prüft Python-Syntax, Credentials/Private Keys bei aktivierter
Security-Rule und Whitespace über `git diff --check`. Er erstellt keinen Commit.
Er speichert außerdem SHA-256-Fingerprints von Dateien sowie HEAD, Index und
Diff-State. Nach Änderungen ist ein neuer Review- und Precommit-Schritt nötig.

Verification kann Turns, Tokens, active minutes, Provider/Model, Recall und
Outcomes speichern. Das sind lokale Audit-Daten, keine verifizierte Telemetrie.
`anchor report --format json|csv` erstellt lokale Model-by-Mode-Auswertungen.

## Projektzustand

~~~text
.anchor/
  config.json                 Projektkonfiguration
  next-action.md              Nächste erlaubte Aktion
  protocol/                   Workflow-Vertrag
  tasks/                      Aktive und geschlossene Tasks
  rules/                      Vorschläge, genehmigte und aktive Rules
  architecture/               Strukturvorschläge und Policy
  graphify/                   Integrationsmetadaten
  agents/                     Erkannte Fähigkeiten und Adapter
  project.lock                Cross-process lock
  transactions/ und outbox/  Recovery und Delivery State
  cache/ und logs/            Lokale Artefakte
~~~

Nach einer Migration `anchor add --apply` erneut ausführen, damit fehlende
Cache- und Recovery-Einträge in Gitignore-Dateien ergänzt werden.

## Dokumentation

- [Produktplan](../PROJECT_PLAN.md)
- [Entscheidungskarte](../ANCHOR_DECISION_MAP.md)
- [Domain glossary](../../CONTEXT.md)
- [Portable Skill](../PORTABLE_SKILL.md)
- [Migration 0.1.0 → 0.2.1](../MIGRATION_0.2.md)
- [Changelog](../../CHANGELOG.md)
- [Contributing](../../CONTRIBUTING.md)
- [Security](../../SECURITY.md)

## Entwicklung und Tests

~~~sh
PYTHONPATH=src python3 -m unittest discover -s tests
npm run test:npm
npm run pack:check
~~~

## Lizenz

MIT. Siehe [LICENSE](../../LICENSE).
