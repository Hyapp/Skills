# 执行流程

主 Agent 按五个阶段调度 workflow。

## 阶段 0：上下文恢复

**每次被调用时最先执行的步骤。** 在开始任何新工作流之前，先检查是否有未完成的 session：

1. 运行恢复检查：
   ```bash
   python ./interpreter/state_index.py recover
   ```

2. 如果输出 `recoverable_sessions` 非空，取第一个 in_progress 的 session：
   - 恢复命令给出 `session`、`current_wave`、`pending_nodes`、`next_action`
   - 直接按 `next_action` 执行（dispatch 或 wave-complete）
   - 从 [阶段 3](#阶段-3执行节点按-wave-并行) 继续，**跳过阶段 1-2**

3. 如果有一个以上 in_progress session，向用户报告所有可恢复 session，请用户选择

4. 如果无 in_progress session，正常进入阶段 1

### 压缩后的自动恢复

当主 Agent 遭遇上下文压缩后重新加载 skill 时，阶段 0 自动触发。检查流程同上：`recover` → 发现 in_progress → 直接接续执行。

这意味着主 Agent **不需要记住当前执行到哪个 session**——每次被调用都从检查开始，有未完成的工作就继续，没有才新建。

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

3. 初始化执行状态：

```bash
python ./interpreter/state_index.py <output_dir> init
```

4. 读 `build_plan.json`，检查：
   - 是否有校验/执行错误 → 向用户报告并中止
   - 已完成的 program/text 节点的结果

## 阶段 3：执行节点（按 Wave 并行）

`build_plan.json` 包含 `waves`（wave 分组列表）和 `workflow.parallel_n`（并发数）。主 Agent 按 wave 逐批执行，逻辑如下：

```
wave 0: [node-a, node-b]    → 发 parallel_n 个并行 SubAgent
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

### Agent 节点执行步骤

每批节点启动前先标记已派发：

```bash
python ./interpreter/state_index.py <output_dir> dispatch <node-id-1> <node-id-2>
```

然后按 wave 逐批执行：

1. 按 wave 逐批处理，每批最多同时派发 `parallel_n` 个 SubAgent（使用 `Agent(run_in_background=true)`）
2. 每个 SubAgent 执行后，将结果写入 `<output_dir>/agents/<node-id>/result.md`
3. 一批完成后，检查结果：
   - 全成功 → 调用 state hook 推进到下一批：

     ```bash
     python ./interpreter/state_index.py <output_dir> wave-complete
     ```
     hook 输出当前 wave、pending 节点、下一步操作。主 Agent 接续执行。
   - 有 `manual` 失败 → 汇总所有已执行节点的副产物，展示给用户，请求确认
   - 其他失败 → 按 `on_failure` + `recovery` 组合处理。必要时使用 rollback：

     ```bash
     python ./interpreter/state_index.py <output_dir> rollback 1
     ```
     rollback 输出受影响的节点列表，主 Agent 按列表重跑。
4. 全部 wave 完成后进入阶段 4

### Plugin 节点执行步骤

Plugin 节点在 `execution_order` 中 `type: plugin`，状态为 `pending`。主 Agent 对每个 plugin 节点按以下流程执行：

1. **静态校验**：读取 `plugin.yaml` 声明的 IR schema，与生成的 IR 对比：
   - 检查 `sections` 中每个 block type 是否在 `block_types` 中有定义
   - 检查 `ir.context.sheets` 是否满足每个 `sheet_ref` 的引用需求
   - 检查 `render-order` 的 `path` 是否指向存在的文件
   - 如有不合规 → 主 Agent 诊断问题后中止，可修改 DSL 后重试
2. **Runtime 校验**：如果 `plugin_params.validate_command` 存在，执行它：
   ```bash
   python <plugin>/validate.py <session_dir>
   ```
   - exit 0 → 继续
   - exit ≠ 0 → 按 `on_failure` 策略处理（默认 abort）
3. **执行**：运行 `plugin_params.command`（含已解析的 `{input_ir}` 路径）
4. 结果写入对应节点文件

> 两层校验分工：静态校验保证 IR 语义正确、符合 plugin 声明，由主 Agent 推理完成，失败时可修复 DSL 重跑。Runtime 校验保证环境条件就绪，由 plugin 自带的 validate.py 完成，是执行前的最后一道防线。

### 上下文恢复

当主 Agent 遭遇上下文压缩后，通过 state hook 快速恢复位置：

```bash
# 快速定位：当前 wave、pending 节点、下一步
python ./interpreter/state_index.py <output_dir> status
```

输出：

```yaml
session: feishu-report-8
workflow: feishu-sales-report
status: in_progress
current_wave: 2
completed: 4
total: 7
pending_nodes:
- summary-3-2
next_action: "dispatch: summary-3-2 (wave 2)"
```

主 Agent 直接读 `next_action` 执行——dispatch summary-3-2。

完整索引：

```bash
# wave 进度、所有节点状态、生成物路径
python ./interpreter/state_index.py <output_dir>
```

输出示例：

```yaml
summary:
  session: feishu-report-8
  workflow: feishu-sales-report
  status: in_progress
  wave_count: 5
  current_wave: 2
  completed: 4
  total: 7
  pending_nodes:
  - summary-3-2
waves:
- wave: 0
  status: completed
  nodes:
  - {id: generate-data-1, type: program, status: completed, ...}
  - {id: generate-data-2, type: program, status: completed, ...}
- wave: 1
  status: completed
  nodes:
  - {id: build-ir, type: program, status: completed, ...}
- wave: 2
  status: in_progress
  nodes:
  - {id: summary-2-2, type: agent, status: completed, ...}
  - {id: summary-3-2, type: agent, status: pending, ...}
artifacts:
  ir: output/feishu-report-8/_ir.yaml
  agent_outputs:
    summary-2-2: output/feishu-report-8/agents/summary-2-2/result.md
```

查看特定节点详情：

```bash
python ./interpreter/state_index.py <output_dir> --node summary-2-2
```

### 回退工作流

当执行到 wave N 发现问题时：

每层 wave 只依赖上一层（马尔可夫过程），默认退一层即可：

```bash
# 默认退一层
python ./interpreter/state_index.py <output_dir> rollback

# 或指定目标 wave
python ./interpreter/state_index.py <output_dir> rollback 1
```

输出：

```yaml
action: rollback
target_wave: 1
affected_nodes:
- summary-2-2
- summary-3-2
- summary-1
- render-doc
skipped_idempotent:
- generate-data-1
- generate-data-2
- build-ir
next_action: "re-dispatch wave 1: summary-2-2, summary-3-2, summary-1, render-doc"
note: "3 idempotent node(s) skipped: generate-data-1, generate-data-2, build-ir"
```

主 Agent 按 `affected_nodes` 列表重跑，`skipped_idempotent` 的节点结果直接复用：

```bash
# 重新派发受影响节点
python ./interpreter/state_index.py <output_dir> dispatch summary-2-2 summary-3-2
# 派发 SubAgent 执行...
python ./interpreter/state_index.py <output_dir> wave-complete  # 推进
```

## 阶段 4：结果确认

1. 汇总所有 Agent 节点的输出
2. 向用户报告整体执行结果（成功数 / 失败数 / 每个 Agent 摘要 / 输出位置）
3. 询问用户是否需要进一步操作
