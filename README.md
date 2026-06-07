# Skills — Reusable Agent Skills

A collection of reusable skills for AI coding agents including **Claude Code**, **Codex**, and **Trae**.

[中文文档](./README.zh.md)

---

## task-compiler — DSL Mode

A companion to Plan mode. Activate **DSL mode** when you need the agent to execute a long-running, multi-step workflow with high reliability. Instead of the agent reasoning step-by-step interactively, you describe the entire task as a declarative pipeline, and the agent compiles it into an ordered execution plan with dependency resolution, automatic parallelism, error recovery, and resume-from-failure support.

Use it for tasks like: generating structured documents from data, running multi-stage code generation pipelines, orchestrating build-and-deploy sequences, or any workflow where you want predictable, repeatable execution without babysitting.

Declare your workflow in YAML, run `/task-compile`, and walk away — the engine handles scheduling, retries, caching, and incremental re-runs via `--session`.

Under the hood: workflows are DAGs of typed nodes (`program`, `agent`, `plugin`, `expand`, `text`) with topological sort, wave-based parallelism, implicit dependency injection, and a plugin system with auto-discovery.

See full docs at [wiki/task-compiler.md](./wiki/task-compiler.md).

---

> More skills coming soon.
