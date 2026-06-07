# Skills

[English](./README.md)

---

## task-compiler — DSL 模式
更严格的 Plan 模式。当 Agent 执行长程、多步骤、高稳定性的任务时，启用 **DSL 模式**。与 Agent 逐步交互推理不同，整个任务被描述为声明式流水线，Agent 将其解释为有序的执行计划，自动解析依赖、并行调度、处理错误并从失败点恢复。

Plugin 支持: 添加自定义操作

适用场景：
1. CI/CD 工作流
2. 数据搬运工: 读数据 -> 分析数据 -> 报告产生 -> 数据同步 一条龙
3. 可预测，严格控制，执行流程记录与重复执行的长程工作流

支持: **Claude Code**、**Codex**、**Trae**.

[task-compiler](./wiki/task-compiler.zh.md)

---

