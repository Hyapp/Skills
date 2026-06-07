# Skills — Reusable Agent Skills

A collection of reusable skills for AI coding agents including **Claude Code**, **Codex**, and **Trae**.

[中文文档](./README.zh.md)

---

## task-compiler

Execute **vDSL workflows** — define a DAG in YAML and let the agent schedule and run nodes in dependency order.

Workflows are defined declaratively. Node types include `program` (shell commands), `agent` (sub-agent tasks), `plugin` (registered plugin invocations), `expand` (dynamic template expansion), and `text` (template string interpolation). The engine handles topological sort with wave-based parallel grouping, implicit dependency injection via `{{ nodes.X.result }}`, and a plugin system with auto-discovery.

Error handling supports abort/retry/pause/skip strategies with per-node retry limits. Content hash caching avoids redundant re-execution, and `--session <name>` enables incremental runs that reuse previous outputs.

See full docs at [wiki/task-compiler.md](./wiki/task-compiler.md).

---

> More skills coming soon.
