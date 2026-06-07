# Skills

[中文文档](./README.zh.md)

---

## task-compiler — DSL Mode

A stricter companion to Plan mode. Activate **DSL mode** when your agent needs to run long, multi-step, high-reliability tasks. Unlike step-by-step interactive reasoning, the entire task is described as a declarative pipeline — the agent compiles it into an ordered execution plan, automatically resolves dependencies, schedules parallel work, handles errors, and resumes from the point of failure.

Plugin support: add custom operations.

Use cases:
1. CI/CD workflows
2. Data pipelines: read → analyze → report → sync
3. Predictable, strictly controlled, repeatable long-running workflows

Compatible with **Claude Code**, **Codex**, and **Trae**.

[task-compiler](./wiki/task-compiler.md)

---

> More skills coming soon.
