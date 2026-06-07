# Skills — 可复用的 AI Agent 技能

面向 **Claude Code**、**Codex**、**Trae** 等 AI 编程助手的可复用技能集合。

[English](./README.md)

---

## task-compiler — DSL 模式

Plan 模式的搭档。当你需要 Agent 执行一个长程、多步骤、高稳定性的任务时，启用 **DSL 模式**。与 Agent 逐步交互推理不同，你将整个任务描述为声明式流水线，Agent 将其编译为有序的执行计划，自动解析依赖、并行调度、处理错误并从失败点恢复。

适用场景：从数据生成结构化文档、多阶段代码生成流水线、构建与部署编排，或者任何你希望可预测、可重复执行而无需人工盯守的工作流。

用 YAML 声明工作流，执行 `/task-compile`，然后就可以离开 — 引擎负责调度、重试、缓存，并通过 `--session` 支持增量重跑。

实现原理：工作流是有类型节点（`program`、`agent`、`plugin`、`expand`、`text`）组成的 DAG，引擎对其做拓扑排序、按 wave 并行、隐式依赖注入，并具备插件自动发现能力。

详见 [wiki/task-compiler.zh.md](./wiki/task-compiler.zh.md)。

---

> 更多 Skill 持续添加中。
