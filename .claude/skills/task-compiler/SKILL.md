---
description: 运行 vDSL 工作流 — 解析 DSL 文件，调度 SubAgent，确认结果
---

# Task Compiler

运行一个 vDSL 工作流定义，按 DAG 顺序调度 SubAgent 并汇总结果。

```
/task-compile <workflow.yaml> [--output-dir ./output] [--session <name>] [--debug] [--clean]
```

**你（主 Agent）只做三件事：**
1. **初始节点准备** — 确认变量，确保环境就绪
2. **规划调度** — 调用解释器，按 plan 启动 SubAgent（支持按 wave 并行）
3. **结果确认** — 汇总结果，向用户报告

## 快速查阅

| 场景 | 看这个 |
|------|--------|
| 只想跑一次已有的 workflow | [快速执行](references/quick-execution.md) |
| 编写或修改 DSL 文件 | [DSL 格式](references/dsl-format.md) |
| 配置并行度 (`parallel: n`) | [DSL 格式](references/dsl-format.md) |
| 理解 Wave 分组的执行阶段 | [执行流程](references/execution-flow.md) |
| 动态模式（逐轮生成 DSL） | [动态模式](references/dynamic-mode.md) |
| 积累模式（动态→可复用 DSL） | [积累模式](references/dynamic-mode.md#积累模式) |
| 节点依赖声明（`requires`） | [DSL 格式](references/dsl-format.md#agent-节点) |
| 错误处理和 recovery 模式 | [错误处理](references/error-handling.md) |
| Windows 编码/CLI 兼容性 | [Windows 限制](references/windows-limitations.md) |
