# AnchorLoop

[English](../../README.md) · [Русский](README.ru.md) · [Español](README.es.md) · [Português](README.pt-BR.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

> - **已发布的 production：** `anchorloop@0.2.0`
> - **当前版本：** `0.2.0`
> - 自动化请使用精确版本：`npx --yes anchorloop@0.2.0 ...`。
> - [迁移指南](../MIGRATION_0.2.md)包含从 `0.1.0` 升级的步骤。

AnchorLoop 是面向 AI 编程代理的本地 workflow。工程师始终掌控任务、规则、项目结构和最终验收。

## 核心理念

AI 可以编写代码，但不能自行批准计划、启用新规则、选择技能或关闭任务。AnchorLoop 将高风险动作分成可检查的阶段：

1. 工程师描述任务并确认范围。
2. AI 生成 brief 和可验证的计划。
3. 工程师批准计划、规则和技能。
4. AI 实现变更并记录证据。
5. 工程师检查结果，然后关闭任务。

四种工作模式：

- `AUTO`：低风险、可逆的本地工作。
- `FAST`：小型、清晰、易于撤销的变更。
- `STANDARD`：默认模式，需要计划和批准。
- `CAREFUL`：高影响、不可逆或涉及敏感信息的工作。

## 交付循环

![AnchorLoop 交付循环](../../docs/assets/anchorloop-delivery-loop.svg)

```text
start → brief → plan → approve → implement → review → precommit → verify → close
```

每个阶段都有明确的输入和输出。`approve` 是授权边界；`verify` 只接受可复现的检查结果；`close` 会把最终状态写入项目记录。

## 信任边界

AnchorLoop 是本地 CLI 和项目内的可移植技能，不会替工程师连接外部服务，也不会隐藏地修改远程仓库。它可以帮助代理：

- 读取项目结构和约束；
- 生成计划、决策记录和变更说明；
- 执行明确授权的本地命令；
- 运行测试、静态检查和安全检查；
- 保存可追溯的 evidence。

它不会：

- 自行批准自己的计划或权限提升；
- 绕过项目规则或删除用户数据；
- 在没有明确授权时发布、推送或发送外部消息；
- 把“命令已执行”当作“结果已验证”。

## 与代理无关的设计

核心流程使用纯文本文件、JSON 和常见 shell 命令，因此可以在不同代理和编辑器中复用：

| 场景 | 主要文件或命令 |
| --- | --- |
| 项目状态 | `AGENTS.md`、`ANCHOR_STATE.json`、`ANCHOR_DECISION_MAP.md` |
| 任务记录 | `anchor start`、`anchor brief`、`anchor plan`、`anchor close` |
| 规则 | `anchor rules list`、`.anchorloop/rules/` |
| 技能 | `anchor skill list`、`.anchorloop/skills/` |
| 证据 | `.anchorloop/evidence/`、`anchor verify` |
| 审查 | `anchor review`、`anchor precommit` |

## 0.2.0 已包含的功能

- 生产版本 `0.2.0` 的 npm 包和独立 Python CLI。
- 适用于主要 AI 编程代理的可移植 skill 安装流程。
- `plan`、`approve`、`implement`、`review`、`precommit`、`verify` 和 `close` 阶段。
- 基于风险的规则选择和显式的权限提升提示。
- 可恢复的 skill 安装，避免部分复制造成损坏。
- 跨平台的 Python smoke test、版本一致性检查和发布文档检查。
- 本地 evidence、决策图和迁移文档。

## 安装已发布的 npm 包

需要 Node.js 18 或更高版本：

```sh
npx --yes anchorloop@0.2.0 --help
npx --yes anchorloop@0.2.0 doctor
```

也可以安装到项目中：

```sh
npm install --save-dev anchorloop@0.2.0
npx anchorloop@0.2.0 init
```

如果项目使用锁文件，请提交 `package-lock.json` 的变化。自动化脚本应固定到 `0.2.0`，不要依赖浮动的版本范围。

## 安装独立 CLI

需要 Python 3.11 或更高版本：

```sh
python3 -m pip install anchorloop==0.2.0
anchor --help
anchor doctor
```

在受管环境中，可以使用虚拟环境：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install anchorloop==0.2.0
```

## 从 0.1.0 迁移到 0.2.0

先在仓库根目录运行诊断：

```sh
npx --yes anchorloop@0.1.0 doctor
```

然后安装当前生产版本并重新生成项目文件：

```sh
npm install --save-dev anchorloop@0.2.0
npx anchorloop@0.2.0 add --apply
npx anchorloop@0.2.0 doctor
```

如果使用 Python CLI：

```sh
python3 -m pip install --upgrade anchorloop==0.2.0
anchor add --apply
anchor doctor
```

检查并提交以下内容（如果它们发生变化）：

- `AGENTS.md`；
- `ANCHOR_STATE.json`；
- `.anchorloop/rules/` 和 `.anchorloop/skills/`；
- CI、pre-commit 或其他自动化脚本中的版本号；
- 项目锁文件。

完整的兼容性说明见[迁移指南](../MIGRATION_0.2.md)。

## 从源码 checkout 开发

```sh
git clone https://github.com/anchorloop/anchorloop.git
cd anchorloop
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
npm install
```

验证环境：

```sh
npm test
PYTHONPATH=src python3 -m unittest discover -s tests
npm run version:check
```

## 安装可移植 skill

将 AnchorLoop 的可移植 skill 安装到代理支持的目录：

```sh
anchor skill install
anchor skill list
```

预览目标位置：

```sh
anchor skill install --dry-run
```

卸载由 AnchorLoop 管理的 skill：

```sh
anchor skill uninstall
```

安装流程会记录目标、版本和结果；如果目标目录不可写，命令会给出修复提示，而不是留下不完整的目录。

## 第一个项目

在要管理的仓库中：

```sh
anchor add
anchor add --apply
anchor rules list
anchor skill list
anchor start "添加用户头像上传"
```

典型流程：

```sh
anchor brief "添加用户头像上传"
anchor plan
anchor approve
anchor implement
anchor review
anchor precommit
anchor verify
anchor close
```

每一步都应检查输出。计划尚未获批时不要进入实现阶段；验证失败时不要关闭任务。

## 规则

规则按风险选择，并且必须能够被项目成员查看：

```sh
anchor rules list
anchor rules show core
anchor rules show security
```

通常始终启用核心规则；只有当任务确实涉及凭据、身份验证、权限、个人数据或外部副作用时，才启用安全规则。规则文件位于 `.anchorloop/rules/`，可以在代码审查中一起修改和讨论。

## Pre-commit 基线

运行：

```sh
anchor precommit
```

默认检查包括 Python 语法和 Git 空白错误。涉及安全规则时，还会检查可能的密钥。该命令不会创建 commit，也不会替工程师决定是否提交。

建议把以下命令放入 CI：

```sh
npm test
PYTHONPATH=src python3 -m unittest discover -s tests
npm run version:check
```

## Evidence 和可追溯性

验证结果应说明运行了什么、结果是什么以及仍有哪些限制。推荐把命令输出和决策记录放在：

```text
.anchorloop/evidence/
ANCHOR_DECISION_MAP.md
ANCHOR_STATE.json
```

不要用“看起来正常”替代测试输出；不要把审查意见、外部发布或人工批准伪装成自动检查结果。

## 项目状态

初始化后的仓库大致包含：

```text
AGENTS.md
ANCHOR_STATE.json
ANCHOR_DECISION_MAP.md
.anchorloop/
├── evidence/
├── rules/
└── skills/
```

请把这些文件视为项目的受版本控制的工作流配置。它们不应包含密码、token 或其他秘密。

## 文档

- [主 README](../../README.md)
- [项目计划](../PROJECT_PLAN.md)
- [迁移指南](../MIGRATION_0.2.md)
- [决策图](../ANCHOR_DECISION_MAP.md)
- [可移植 skill 指南](../PORTABLE_SKILL.md)
- [贡献指南](../../CONTRIBUTING.md)
- [安全策略](../../SECURITY.md)
- [变更记录](../../CHANGELOG.md)

## 开发

运行 JavaScript 测试：

```sh
npm test
```

运行 Python 测试：

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

检查版本、发布包和文档：

```sh
npm run version:check
npm_config_cache=/private/tmp/anchorloop-npm-cache npm run pack:check
node npm/scripts/finalize-release-docs.js --check --version 0.2.0 --release-date 2026-07-20
```

发布流程要求经过审查的版本提交、签名 tag 和可信发布配置。请先阅读[贡献指南](../../CONTRIBUTING.md)，不要直接从本地 shell 发布未经审查的包。

## 许可证

MIT，见 [LICENSE](../../LICENSE)。
