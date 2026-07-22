# AnchorLoop

> **Produção publicada:** `anchorloop@0.2.1`

**Workflow controlado por engenharia e neutro para agentes de desenvolvimento
de software assistido por IA.**

[English](../../README.md) · [Русский](README.ru.md) · [Español](README.es.md) · [Português](README.pt-BR.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

O AnchorLoop permite que um agente de IA escreva código sem retirar do
engenheiro o controle sobre objetivos, decisões, regras, mudanças estruturais
e aceitação final.

## Status

**Produção publicada:** `anchorloop@0.2.1`

A versão `0.2.1` inclui recovery, validação, modos de ownership, releases
seguros e instalação de skills para vários agentes. Use sempre a versão exata
na automação e nos skills instalados.

## Ideia principal

> O agente pode escrever código. O engenheiro decide por que ele existe, qual
> trade-off foi escolhido, quais regras se aplicam e como o resultado será
> verificado.

O AnchorLoop registra o outcome e as restrições da tarefa, aprovação do plano,
regras de qualidade e segurança, seleção de skills, verificação e incertezas.

Cada tarefa usa `AUTO`, `FAST`, `STANDARD` ou `CAREFUL`. `AUTO` escolhe `FAST`
para documentação e tarefas simples, `STANDARD` para desenvolvimento normal e
`CAREFUL` para autenticação, pagamentos, migrations, concorrência,
infraestrutura, mudanças destrutivas, APIs públicas e novas dependências.
`STANDARD` e `CAREFUL` exigem artefato do engenheiro, trade-offs, estratégia de
verificação e explicação de compreensão. `CAREFUL` agenda recall **24 horas
depois do fechamento**.

## Ciclo de entrega

<img src="../../docs/assets/anchorloop-delivery-loop.svg" alt="Ciclo de entrega do AnchorLoop" width="100%">

A implementação segue um plano aprovado pelo engenheiro. Quando a verificação
falha, `revise` retorna explicitamente ao trabalho em vez de reabri-lo em
silêncio.

## Limite de confiança

AnchorLoop fornece gates auditáveis, mas não substitui autenticação ou controle
de acesso. Os approvals guardam provenance:

- `audit` registra quem declara ter aprovado uma ação;
- `interactive-tty` exige terminal interativo e a entrada `APPROVE`;
- um host adapter confiável ou canal separado pode vincular a identidade.

`--by` e uma confirmação no terminal não provam identidade sem esse canal. O
skill não substitui o CLI nem o estado `.anchor/`.

## Design neutro para agentes

A fonte de verdade é o CLI local `anchor` e `.anchor/`, não um model, provider,
IDE ou formato de slash-command específico.

| Capacidade do host | Como funciona |
|---|---|
| Terminal | Executa o CLI `anchor` diretamente. |
| Instructions ou skills | Um adapter lê o estado e exibe a próxima ação. |
| Commands, hooks, MCP | Adapters finos adicionam conveniência e guardrails. |
| Sem terminal | O engenheiro ou um bridge local executa CLI; o agente lê next action. |

Todos os hosts usam os mesmos estados de tarefa e regras de approval.

## Funcionalidades do 0.2.1

- Skills para Agent Skills, Codex, Cursor, Gemini CLI, Claude Code e OpenCode.
- Proteção contra symlinks e Windows reparse points, paths seguros e writes
  atômicos.
- Cross-platform lock, redo journal, event outbox e recovery idempotente.
- Journals duráveis separados para as operações de skill.
- `anchor doctor`, `doctor --strict` e `doctor --repair` explícito.
- Fingerprints determinísticos do workspace e snapshot Git.
- Verificação do diff desde o task baseline antes de `review` e `precommit`.
- `init`, `add` e instalações com preview e `--apply`.
- `.anchor/`, rules propostas, metadata Graphify e protocolo portable.
- Fluxo estrito:
  `start → brief → plan → approve → implement → review → precommit → verify → close`.

Graphify, testes específicos do projeto, pesquisa externa e adaptadores nativos
não são instalados automaticamente.

## Instalar o pacote npm publicado

Requisitos: Node.js 18+ e Python 3.11+.

~~~sh
npx --yes anchorloop@0.2.1 install --project --platform codex --apply
npx --yes anchorloop@0.2.1 install --interactive
~~~

O wizard oferece o projeto atual ou o perfil do usuário e permite escolher
Codex, Cursor, Gemini CLI, Claude Code, OpenCode, Agent Skills standard ou
todos os destinos nativos. Não cria `.anchor/`, `node_modules` nem cache no
projeto.

Para scripts e CI:

~~~sh
anchor install --project --platform codex --apply
anchor install --global --platform gemini --apply
anchor install --global --all --apply
anchor install --global --all
~~~

## Instalar o CLI standalone

~~~sh
pipx install git+https://github.com/ppmarkek/AnchorLoop.git
python -m pip install "git+https://github.com/ppmarkek/AnchorLoop.git"
~~~

É uma instalação Git, não um release PyPI. Depois execute `anchor install` para
adicionar o skill portable.

## Migrar de 0.1.0 para 0.2.1

Não apague `.anchor/`: ele é o registro do workflow do projeto. A migração
atualiza arquivos de protocolo/suporte e assets do skill, preservando tasks,
rules, approvals e audit records.

Primeiro finalize o recovery da versão anterior:

~~~sh
npx --yes anchorloop@0.1.0 doctor --strict
npx --yes anchorloop@0.1.0 doctor --repair
npx --yes anchorloop@0.1.0 doctor --strict
~~~

Depois atualize usando a versão exata:

~~~sh
npx --yes anchorloop@0.2.1 install --project --platform codex --apply
npx --yes anchorloop@0.2.1 add --apply
npx --yes anchorloop@0.2.1 doctor --strict
~~~

Veja o [guia de migração](../MIGRATION_0.2.md).

## Desenvolvimento a partir de um checkout

~~~sh
git clone https://github.com/ppmarkek/AnchorLoop.git
cd AnchorLoop
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
~~~

No Windows, ative `.venv\Scripts\Activate.ps1`.

## Instalar o skill portable pelo CLI

O CLI continua standalone e neutro; o skill apenas explica como consultar CLI
e o estado Anchor.

~~~powershell
anchor install --project --platform agents
anchor install --project --platform agents --apply
anchor install --project --platform codex --apply
anchor uninstall --project --platform agents --apply
~~~

Arquivos alterados localmente não são sobrescritos nem removidos sem `--force`
explícito.

## Primeiro projeto

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

`anchor add` apenas mostra o plano; `--apply` cria o estado. O engenheiro deve
fornecer outcome, scope, constraints, invariant e uncertainty.

~~~sh
anchor plan --summary "Use bounded exponential backoff and preserve delivery idempotency." --mode AUTO --task-type feature --approach "Retry only transient responses with a bounded idempotent schedule." --alternative "Immediate unlimited retries were rejected because they amplify outages." --risk "A retry can duplicate delivery." --verification "Exercise a transient failure and assert one final delivery." --human-artifact "Ada's acceptance case: two transient failures then one successful delivery with the same id." --comprehension "Prediction: the idempotency key prevents duplicate side effects across attempts." --by "Ada Engineer"
anchor approve --by "Ada Engineer"
anchor implement
anchor review
anchor precommit
anchor verify --by "Ada Engineer" --result pass --reason "The documented manual scenario passed." --recall "The bounded schedule controls load; the stable key controls duplicate effects."
anchor close
~~~

Para `CAREFUL`, adicione `--rollback-mitigation`. Em caso de falha:

~~~sh
anchor verify --by "Ada Engineer" --result fail --reason "The retry still loses the delivery id." --recall "The key is regenerated on each attempt, so the invariant does not hold."
anchor revise --target implement --reason "Fix the observed behavior within the approved scope."
~~~

Use `--target plan` quando a solução ou o escopo precisar mudar.

## As regras pertencem ao engenheiro

Rules começam como propostas e só ficam ativas após approval do engenheiro:

~~~sh
anchor rules list
anchor rules propose structure "Features may import only public module entry points."
anchor rules approve rule-structure-<id> --by "Ada Engineer"
~~~

O agente pode propor uma rule, mas não pode ativá-la, alterá-la ou ignorá-la.

## Pre-commit e evidence

~~~sh
anchor precommit
~~~

A baseline verifica sintaxe Python, credentials/private keys quando a security
rule está ativa e whitespace de `git diff --check`. Não cria commit. Também
salva fingerprints SHA-256, HEAD, index e diff state; alterações exigem novo
review e precommit.

Verification pode registrar turns, tokens, minutos, provider/model, recall e
outcomes. São dados locais de auditoria, não telemetry verificada. `anchor
report --format json|csv` gera relatório local model-by-mode.

## Estado do projeto

~~~text
.anchor/
  config.json                 Configuração
  next-action.md              Próxima ação permitida
  protocol/                   Contrato portable
  tasks/                      Tasks ativas e fechadas
  rules/                      Propostas e rules aprovadas
  architecture/              Política de estrutura
  graphify/                   Metadata de integração
  agents/                     Capabilities e adapters
  project.lock                Lock entre processos
  transactions/ e outbox/   Recovery e delivery state
  cache/ e logs/             Artefatos locais
~~~

Após a migração, execute novamente `anchor add --apply` para adicionar entradas
de cache e recovery aos Gitignore, preservando linhas personalizadas.

## Documentação

- [Plano do produto](../PROJECT_PLAN.md)
- [Mapa de decisões](../ANCHOR_DECISION_MAP.md)
- [Domain glossary](../../CONTEXT.md)
- [Portable skill](../PORTABLE_SKILL.md)
- [Migração 0.1.0 → 0.2.1](../MIGRATION_0.2.md)
- [Changelog](../../CHANGELOG.md)
- [Contributing](../../CONTRIBUTING.md)
- [Security](../../SECURITY.md)

## Desenvolvimento e testes

~~~sh
PYTHONPATH=src python3 -m unittest discover -s tests
npm run test:npm
npm run pack:check
~~~

## Licença

MIT. Veja [LICENSE](../../LICENSE).
