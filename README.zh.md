# Skills — Claude Code 技能集合

为 [Claude Code](https://claude.ai/code) 设计的可复用 Skill 集合。

[English](./README.md)

---

## task-compiler

运行 **vDSL 工作流** — 通过 YAML 定义 DAG，按依赖顺序调度节点执行。

### 快速开始

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
        基于 step-1 的输出继续处理。
```

```bash
/task-compile workflows/example/workflow.yaml
```

### 节点类型

| 类型 | 说明 |
|------|------|
| `program` | 执行 shell 命令 |
| `agent` | 启动 SubAgent 处理复杂任务 |
| `plugin` | 调用插件（如渲染飞书文档） |
| `expand` | 动态展开模板节点 |
| `text` | 展开 `{{ }}` 模板输出文本 |

### 特性

- **DAG 调度** — 自动拓扑排序，按 wave 分组并行。隐式依赖注入（`{{ nodes.X.result }}` 自动添加 depends_on）
- **插件系统** — `plugins/<name>/plugin.yaml` 声明 IR schema + 执行入口。task-compiler 启动时自动发现
- **飞书渲染** — `render-feishu` 插件：IR → 飞书云文档，支持 heading/paragraph/sheet 等块类型，render-order pragma 异步注入 AI 摘要
- **错误处理** — 支持 abort / retry / pause / skip 策略，节点级重试，内容哈希缓存
- **会话管理** — `--session <name>` 复用已有输出，增量执行

### 项目结构

```
.claude/skills/task-compiler/
├── SKILL.md                     # Skill 入口（Claude Code 加载点）
├── interpreter/                  # vDSL 解释器
│   ├── task_compiler.py          # 主入口
│   ├── validate.py               # 校验 + plugin 发现
│   ├── eval.py                   # 节点执行（program/agent/expand）
│   └── dag.py                    # 拓扑排序
├── plugins/
│   └── render-feishu/            # 飞书文档渲染插件
│       ├── plugin.yaml           # IR schema + execute 声明
│       ├── render.py             # CLI：IR → 飞书文档
│       ├── utils.py              # lark-cli 封装
│       └── blocks/               # 块类型 handler（渐近加载）
├── references/                   # 文档参考
└── workflows/
    └── feishu-sales-report/      # 示例工作流：销售报告生成
```

### 使用方式

在 Claude Code 中加载此 Skill：

```bash
# 放在 Claude Code 配置的 skills 目录中，或
/claude-code load-skill .claude/skills/task-compiler
```

运行工作流：

```bash
/task-compile workflows/feishu-sales-report/workflow.yaml --session report-1
```

---

> 更多 Skill 持续添加中。
