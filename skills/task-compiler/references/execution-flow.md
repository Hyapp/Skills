# 执行流程

主 Agent 按四个阶段调度 workflow。

## 阶段 1：初始节点准备

1. 读入 DSL 文件
2. 检查 `workflow.variables`：
   - 有默认值的变量直接确认
   - 没有默认值的变量向用户询问补全
3. **扫描 `requires` 依赖**：遍历所有节点，收集 `requires` 并集：
   - `skills`：检查当前环境中是否已加载对应 skill
   - `tools`：检查对应可执行文件是否在 PATH 中。在 Windows 上应使用 `where`（cmd）、`Get-Command`（PowerShell）或 `shutil.which()`（Python），而非 `which`；参见 [Windows 限制](windows-limitations.md)
   - 缺少任一依赖 → 向用户报告缺失项并中止

   > **两层校验模型**：解释器负责 `requires` 的结构校验（字段类型、格式是否正确），本阶段主 Agent 负责环境可用性校验（skill 是否已加载、tool 是否在 PATH）。格式通过的 requires 仍可能因运行环境缺少依赖而在此步骤失败。

4. 如有必要，运行初始环境检查命令
5. 向用户报告准备就绪

## 阶段 2：规划调度 — 运行解释器

1. YAML → 转为 JSON（解释器只接受 JSON）
2. 调用解释器：

```bash
python ./interpreter/task_compiler.py <workflow.json> \
  [--output-dir <dir>] [--session <name>] [--debug] [--clean]
```

3. 读 `build_plan.json`，检查：
   - 是否有校验/执行错误 → 向用户报告并中止
   - 已完成的 program/text 节点的结果

## 阶段 3：执行 Agent 节点（按 Wave 并行）

`build_plan.json` 包含 `waves`（wave 分组列表）和 `workflow.parallel_n`（并发数）。主 Agent 按 wave 逐批执行，逻辑如下：

```
wave 0: [node-a, node-b]    → 发 parallel_n 个并行 Agent
    全成功 or skip 失败 → 继续
    manual 失败 → 记录副产物，暂停，等用户确认

wave 1: [node-c, node-d, node-e] → 同上

wave 2: ...
```

### 决策表

| 条件 | 行为 |
|------|------|
| 批内全成功 | 继续下一批（下一 wave） |
| 批内有失败 + `on_failure: abort` + `recovery: auto` | 等正在跑的完成，停止，汇总错误 |
| 批内有失败 + `on_failure: skip` | 标记失败，继续下一批 |
| 批内有失败 + `recovery: manual` | 等正在跑的完成，停止，展示 manifest + 执行副产物，等用户确认后决定是否继续 |

### 执行步骤

1. 读取 `build_plan.json` 中的 `waves`、`parallel_n`、`execution_order`
2. 按 wave 逐批处理，每批最多同时派发 `parallel_n` 个 SubAgent（使用 `Agent(run_in_background=true)`）
3. 每个 SubAgent 执行后，将结果写入 `<output_dir>/agents/<node-id>/result.md`
4. 一批完成后，检查结果：
   - 全成功 → 下一 wave
   - 有 `manual` 失败 → 汇总所有已执行节点的副产物，展示给用户，请求确认
   - 其他失败 → 按 `on_failure` + `recovery` 组合处理
5. 全部 wave 完成后进入阶段 4

## 阶段 4：结果确认

1. 汇总所有 Agent 节点的输出
2. 向用户报告整体执行结果（成功数 / 失败数 / 每个 Agent 摘要 / 输出位置）
3. 询问用户是否需要进一步操作
