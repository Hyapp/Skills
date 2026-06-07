# task-compiler

Execute **vDSL workflows** — define a DAG in YAML, schedule and run nodes in dependency order.

Compatible with **Claude Code**, **Codex**, and **Trae**.

## Quick Start

```yaml
# workflow.yaml
workflow:
  name: example
  nodes:
    - id: step-1
      type: program
      command: echo "hello"
    - id: step-2
      type: agent
      depends_on: [step-1]
      prompt: |
        Continue based on step-1 output.
```

```bash
/task-compile workflows/example/workflow.yaml
```

## Node Types

| Type | Description |
|------|-------------|
| `program` | Execute a shell command |
| `agent` | Spawn a SubAgent for complex tasks |
| `plugin` | Invoke a registered plugin (e.g. render to Feishu doc) |
| `expand` | Dynamically expand template nodes |
| `text` | Expand `{{ }}` templates into text |

## Features

- **DAG scheduling** — topological sort with wave-based grouping. Implicit dependency injection (`{{ nodes.X.result }}` auto-adds `depends_on`)
- **Plugin system** — `plugins/<name>/plugin.yaml` declares IR schema + execute entry point. Auto-discovered at startup
- **Feishu rendering** — `render-feishu` plugin converts IR → Feishu cloud doc. Supports heading, paragraph, sheet blocks with lazy-loaded handlers
- **Error handling** — abort / retry / pause / skip strategies, per-node retry limits, content hash cache
- **Session management** — `--session <name>` reuses previous outputs for incremental execution

## Project Structure

```
.claude/skills/task-compiler/
├── SKILL.md                     # Skill entry point
├── interpreter/                  # vDSL interpreter
│   ├── task_compiler.py          # Main entry
│   ├── validate.py               # Validation + plugin discovery
│   ├── eval.py                   # Node evaluation (program/agent/expand)
│   └── dag.py                    # Topological sort
├── plugins/
│   └── render-feishu/            # Feishu document render plugin
│       ├── plugin.yaml           # IR schema + execute declaration
│       ├── render.py             # CLI: IR → Feishu doc
│       ├── utils.py              # lark-cli wrapper
│       └── blocks/               # Block type handlers (lazy-loaded)
├── references/                   # Documentation
└── workflows/
    └── feishu-sales-report/      # Example: sales report generation
```

## How to Use

Place in your agent's skills directory, or:

```bash
# Claude Code
/claude-code load-skill .claude/skills/task-compiler

# Codex / Trae
# Copy under the configured skills directory and the agent will auto-discover it
```

Run a workflow:

```bash
/task-compile workflows/feishu-sales-report/workflow.yaml --session report-1
```
