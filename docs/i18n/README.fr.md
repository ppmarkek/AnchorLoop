# AnchorLoop

> **Production publiée :** `anchorloop@0.2.0`

**Workflow agent-neutre, contrôlé par l’ingénieur, pour le développement
logiciel assisté par IA.**

[English](../../README.md) · [Русский](README.ru.md) · [Español](README.es.md) · [Português](README.pt-BR.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

AnchorLoop permet à un agent IA d’écrire du code sans retirer à l’ingénieur le
contrôle des objectifs, décisions, règles, changements de structure et de
l’acceptation finale.

## Statut

**Production publiée :** `anchorloop@0.2.0`

La version `0.2.0` inclut la récupération après incident, la validation, les
modes d’ownership, les releases sécurisées et l’installation de skills pour
plusieurs agents. Utilisez toujours la version exacte dans l’automatisation et
les skills installés.

## Idée centrale

> L’agent peut écrire le code. L’ingénieur décide pourquoi il existe, quel
> compromis est accepté, quelles règles s’appliquent et comment le résultat est
> vérifié.

AnchorLoop conserve l’objectif et les contraintes de la tâche, l’approbation du
plan, les règles de qualité et de sécurité, le choix des skills, la vérification
et les incertitudes restantes.

Chaque tâche utilise `AUTO`, `FAST`, `STANDARD` ou `CAREFUL`. `AUTO` choisit
`FAST` pour la documentation et les petites tâches, `STANDARD` pour le travail
courant et `CAREFUL` pour l’authentification, les paiements, migrations,
concurrence, infrastructure, changements destructifs, APIs publiques et
nouvelles dépendances. `STANDARD` et `CAREFUL` exigent un artefact de
l’ingénieur, les compromis, une stratégie de vérification et une preuve de
compréhension. `CAREFUL` programme un recall **24 heures après la fermeture**.

## Cycle de livraison

<img src="../../docs/assets/anchorloop-delivery-loop.svg" alt="Cycle de livraison AnchorLoop" width="100%">

L’implémentation suit un plan approuvé par l’ingénieur. Une vérification
échouée revient explicitement par `revise` au lieu de rouvrir le travail en
silence.

## Limite de confiance

AnchorLoop fournit des gates auditables, mais ne remplace ni l’authentification
ni le contrôle d’accès. Les approvals contiennent une provenance :

- `audit` enregistre la personne déclarée comme approbatrice ;
- `interactive-tty` exige un terminal interactif et la saisie `APPROVE` ;
- un adaptateur de host de confiance ou un canal d’approbation séparé peut lier
  l’identité.

`--by` et une confirmation terminal ne prouvent pas l’identité sans ce canal.
Le skill ne remplace ni le CLI ni l’état `.anchor/`.

## Conception agent-neutre

La source de vérité est le CLI local `anchor` et `.anchor/`, pas un modèle,
provider, IDE ou format de slash-command particulier.

| Capacité du host | Fonctionnement |
|---|---|
| Terminal | Exécuter directement `anchor`. |
| Instructions ou skills | Un adaptateur lit l’état et affiche la prochaine action. |
| Commands, hooks, MCP | Des adaptateurs fins ajoutent confort et guardrails. |
| Sans terminal | L’ingénieur ou un bridge local lance le CLI ; l’agent lit next action. |

Tous les hosts utilisent les mêmes états de tâche et règles d’approval.

## Fonctions incluses dans 0.2.0

- Skills pour Agent Skills, Codex, Cursor, Gemini CLI, Claude Code et OpenCode.
- Protection des symlinks et Windows reparse points, chemins sûrs et écritures
  atomiques.
- Cross-platform lock, redo journal, event outbox et recovery idempotent.
- Journals durables séparés pour l’installation et la suppression des skills.
- `anchor doctor`, `doctor --strict` et `doctor --repair` explicite.
- Fingerprints déterministes du workspace et du snapshot Git.
- Contrôle du diff depuis la baseline avant `review` et `precommit`.
- `init`, `add` et installations avec preview puis `--apply`.
- État `.anchor/`, règles proposées, metadata Graphify et protocole portable.
- Workflow strict :
  `start → brief → plan → approve → implement → review → precommit → verify → close`.

Graphify, les tests spécifiques du projet, la recherche externe et les
adaptateurs natifs ne sont pas installés automatiquement.

## Installer le paquet npm publié

Prérequis : Node.js 18+ et Python 3.11+.

~~~sh
npx --yes anchorloop@0.2.0 install --project --platform codex --apply
npx --yes anchorloop@0.2.0 install --interactive
~~~

Le wizard propose le projet ou le profil utilisateur et permet de choisir
Codex, Cursor, Gemini CLI, Claude Code, OpenCode, le standard Agent Skills ou
toutes les destinations natives. Il ne crée pas `.anchor/`, `node_modules` ni
de cache dans le projet.

Pour les scripts et la CI :

~~~sh
anchor install --project --platform codex --apply
anchor install --global --platform gemini --apply
anchor install --global --all --apply
anchor install --global --all
~~~

## Installer le CLI standalone

~~~sh
pipx install git+https://github.com/ppmarkek/AnchorLoop.git
python -m pip install "git+https://github.com/ppmarkek/AnchorLoop.git"
~~~

Il s’agit d’une installation Git, pas d’une release PyPI. Exécutez ensuite
`anchor install` pour ajouter le skill portable.

## Migrer de 0.1.0 vers 0.2.0

Ne supprimez pas `.anchor/` : il contient le workflow du projet. La migration
met à jour les fichiers de protocole/support et les assets du skill tout en
conservant tâches, règles, approvals et audit.

Terminez d’abord le recovery de l’ancienne version :

~~~sh
npx --yes anchorloop@0.1.0 doctor --strict
npx --yes anchorloop@0.1.0 doctor --repair
npx --yes anchorloop@0.1.0 doctor --strict
~~~

Puis utilisez la version exacte :

~~~sh
npx --yes anchorloop@0.2.0 install --project --platform codex --apply
npx --yes anchorloop@0.2.0 add --apply
npx --yes anchorloop@0.2.0 doctor --strict
~~~

Voir le [guide de migration](../MIGRATION_0.2.md).

## Développer depuis un checkout

~~~sh
git clone https://github.com/ppmarkek/AnchorLoop.git
cd AnchorLoop
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
~~~

Sous Windows, activez `.venv\Scripts\Activate.ps1`.

## Installer le skill portable avec le CLI

Le CLI reste standalone et agent-neutre ; le skill indique seulement comment
consulter le CLI et l’état Anchor.

~~~powershell
anchor install --project --platform agents
anchor install --project --platform agents --apply
anchor install --project --platform codex --apply
anchor uninstall --project --platform agents --apply
~~~

Les fichiers modifiés localement ne sont pas écrasés ou supprimés sans
`--force` explicite.

## Premier projet

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

`anchor add` affiche le plan ; seul `--apply` crée l’état. L’ingénieur fournit
lui-même outcome, scope, constraints, invariant et uncertainty.

~~~sh
anchor plan --summary "Use bounded exponential backoff and preserve delivery idempotency." --mode AUTO --task-type feature --approach "Retry only transient responses with a bounded idempotent schedule." --alternative "Immediate unlimited retries were rejected because they amplify outages." --risk "A retry can duplicate delivery." --verification "Exercise a transient failure and assert one final delivery." --human-artifact "Ada's acceptance case: two transient failures then one successful delivery with the same id." --comprehension "Prediction: the idempotency key prevents duplicate side effects across attempts." --by "Ada Engineer"
anchor approve --by "Ada Engineer"
anchor implement
anchor review
anchor precommit
anchor verify --by "Ada Engineer" --result pass --reason "The documented manual scenario passed." --recall "The bounded schedule controls load; the stable key controls duplicate effects."
anchor close
~~~

Pour `CAREFUL`, ajoutez `--rollback-mitigation`. En cas d’échec :

~~~sh
anchor verify --by "Ada Engineer" --result fail --reason "The retry still loses the delivery id." --recall "The key is regenerated on each attempt, so the invariant does not hold."
anchor revise --target implement --reason "Fix the observed behavior within the approved scope."
~~~

Utilisez `--target plan` si la solution ou le périmètre doit changer.

## Les règles appartiennent à l’ingénieur

Les règles commencent comme propositions et deviennent actives seulement après
approval humain :

~~~sh
anchor rules list
anchor rules propose structure "Features may import only public module entry points."
anchor rules approve rule-structure-<id> --by "Ada Engineer"
~~~

L’agent peut proposer une règle, mais ne peut pas l’activer, la modifier ou la
contourner.

## Pre-commit et evidence

~~~sh
anchor precommit
~~~

La baseline vérifie la syntaxe Python, les credentials/private keys si la règle
security approuvée est active et les whitespace errors de `git diff --check`.
Elle ne crée pas de commit. Elle conserve aussi les fingerprints SHA-256, HEAD,
index et diff state ; une modification impose un nouveau review et precommit.

Verification peut enregistrer turns, tokens, minutes, provider/model, recall et
outcomes. Ce sont des données d’audit locales, pas une télémétrie vérifiée.
`anchor report --format json|csv` produit un rapport model-by-mode local.

## État du projet

~~~text
.anchor/
  config.json                 Configuration
  next-action.md              Action suivante autorisée
  protocol/                   Contrat portable
  tasks/                      Tâches actives et fermées
  rules/                      Propositions et règles approuvées
  architecture/              Propositions de structure
  graphify/                   Metadata d’intégration
  agents/                     Capabilities et adaptateurs
  project.lock                Lock interprocess
  transactions/ et outbox/  Recovery et delivery state
  cache/ et logs/            Artefacts locaux
~~~

Après une migration, relancez `anchor add --apply` pour ajouter les entrées
cache/recovery aux Gitignore sans supprimer les lignes personnalisées.

## Documentation

- [Plan produit](../PROJECT_PLAN.md)
- [Carte des décisions](../ANCHOR_DECISION_MAP.md)
- [Domain glossary](../../CONTEXT.md)
- [Portable skill](../PORTABLE_SKILL.md)
- [Migration 0.1.0 → 0.2.0](../MIGRATION_0.2.md)
- [Changelog](../../CHANGELOG.md)
- [Contributing](../../CONTRIBUTING.md)
- [Security](../../SECURITY.md)

## Développement et tests

~~~sh
PYTHONPATH=src python3 -m unittest discover -s tests
npm run test:npm
npm run pack:check
~~~

## Licence

MIT. Voir [LICENSE](../../LICENSE).
