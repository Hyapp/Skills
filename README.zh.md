# Skills — 可复用的 AI Agent 技能

面向 **Claude Code**、**Codex**、**Trae** 等 AI 编程助手的可复用技能集合。

[English](./README.md)

---

## task-compiler

运行 **vDSL 工作流** — 通过 YAML 定义 DAG，由 Agent 按依赖顺序调度节点执行。

工作流以声明式 YAML 描述。节点类型包括 `program`（shell 命令）、`agent`（子 Agent 任务）、`plugin`（插件调用）、`expand`（动态模板展开）和 `text`（模板字符串插值）。引擎自动完成拓扑排序并按 wave 分组并行，支持通过 `{{ nodes.X.result }}` 隐式注入依赖，插件系统自动发现。

错误处理支持 abort/retry/pause/skip 策略，节点级别重试。内容哈希缓存避免重复执行，`--session <name>` 实现增量运行，复用已有输出。

详见 [wiki/task-compiler.zh.md](./wiki/task-compiler.zh.md)。

---

> 更多 Skill 持续添加中。
