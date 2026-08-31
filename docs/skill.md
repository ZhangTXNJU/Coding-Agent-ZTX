# Skill 能力总结

> 分支：`006-skill`　日期：2026-08-31

本文总结 agent 的 skill 能力：内置常用 skill + 自定义 skill，把「专家经验固化成可复用流程」，让常见任务产出更稳定一致。设计仿照 Claude Code / OpenCode 的 skill 机制。

## 一、什么是 skill

一个 Skill = **名称 + 用途说明 + 执行指引**。触发后把「执行指引」注入上下文，引导模型按约定流程执行，产出格式统一的结果。

| 字段 | 作用 |
|------|------|
| `name` | 唯一标识，小写字母/数字/连字符（如 `code-review`） |
| `description` | 用途说明，让模型判断「何时适用」 |
| `instructions` | 执行指引（正文），触发后注入上下文 |

## 二、内置 skill（5 个常见场景）

| 名称 | 用途 |
|------|------|
| `code-review` | 代码审查，产出分级问题清单与建议（🔴/🟡/🟢） |
| `write-tests` | 生成测试，覆盖正常/边界/异常路径并验证通过 |
| `refactor` | 行为不变的等价重构，每步改动后验证 |
| `write-docs` | 编写 README / docstring / API 文档 |
| `explain-code` | 由整体到局部讲解代码 |

## 三、自定义 skill

把描述文件放入约定目录 `~/.coding-agent/skills/`（markdown，frontmatter + 正文），启动时自动发现。

```markdown
---
name: my-skill
description: 一句话说明这个 skill 做什么、何时用
---
（正文即执行指引）
```

- `name` 必填且须合法（小写字母/数字/连字符）。
- `description` 必填。
- 正文（执行指引）必填。
- 缺字段或格式非法：拒绝加载并提示具体缺失，不影响其它 skill。
- 与内置 skill 重名：自定义覆盖内置，并提示。

## 四、触发方式

1. **自然语言**：用户描述匹配某 skill 时，模型自动调用 `use_skill` 加载指引再执行。
2. **显式名称**：模型直接调用 `use_skill(name=...)`。
3. **REPL 命令**：
   - `/skills` —— 列出全部可用 skill（内置 + 自定义）及用途。
   - `/skill <名称>` —— 查看某个 skill 的完整指引。

系统提示会注入可用 skill 列表（名称 + 用途），供模型判断适用性。

## 五、实现要点

- `coding_agent/skills.py`：`Skill` / `SkillRegistry` / 内置定义 / frontmatter 解析 / `load_custom_skills` / `build_skill_registry` / `build_skills_prompt`。
- `coding_agent/tools/skill.py`：`use_skill` 工具，从 `ToolContext.skills` 查表返回执行指引；skill 不存在时报错并列出可用 skill。
- `coding_agent/agent.py`：`build_system_prompt(skills)` 把 skill 列表追加到系统提示；`Agent.system_prompt` 供 REPL `/clear` 复用。
- `coding_agent/cli.py` + `ui.py`：`/skills`、`/skill <名称>` 命令与渲染。

## 六、测试

新增 21 个测试（`tests/test_skills.py`，全仓 126 个全部通过），覆盖内置 skill 数量与字段、自定义解析（缺 name/description/正文、非法 name）、混合加载、同名覆盖、`use_skill` 命中/未命中、系统提示注入。

## 七、后续

- subagent（子 agent 调用）为规格 `specs/002-skills-subagents` 的下一半能力，尚未实现，计划独立分支开发。
- skill 的「自然语言语义匹配」当前依赖模型对 description 的理解，未做本地向量/关键词检索（与 spec 假设一致，显式名称为最优先、最可预测方式）。
