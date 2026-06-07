# 动态模式

`workflow.mode: dynamic` 时，主 Agent 逐轮生成单步 DSL，解释器单步 Eval，循环直到完成。

## DSL 文件结构

```yaml
workflow:
  name: research-task
  mode: dynamic
  max_steps: 30                # 默认 30，最大 200
  description: 动态研究任务

variables:
  target: "用户行为分析"

nodes: []    # 初始无节点，由主 Agent 动态生成
```

## 循环架构

```
主 Agent (循环控制器)      解释器 (单步执行器)      SubAgent (任务执行器)
     │                        │                        │
     ├─ 观察状态 ─────────┐   │                        │
     │  (state.md)        │   │                        │
     │                    │   │                        │
     ├─ 生成单步 DSL ─────→   执行 program/text 节点   │
     │   (1~3 个节点)     │    ├─ 展开 {{ }}           │
     │                    │    ├─ 写 node results       │
     │                    │    └─ 写 build_plan.json    │
     │                    │                        │
     ├─ 读 build_plan ←───┘                        │
     │                                            │
     ├─ 如果是 agent 节点:                         │
     │   ├─ 读 agent_params                        │
     │   ├─ 调 Agent tool ─────────────────────────→ 执行任务
     │   └─ 写回 result.md   ←────────────────────┘
     │
     ├─ 更新 state.md
     ├─ step_count++
     └─ 继续或结束
```

## 循环流程

### 0. 初始化

1. 读入 DSL 文件，确认 `mode: dynamic`
2. 检查 `workflow.variables`
3. 确认 `max_steps`
4. 创建 session
5. 创建初始 `state.md`

### 1. 观察状态

读 `<session>/state.md` 和 `<session>/build_plan.json`。如果已完成，跳到结果确认。

### 2. 生成下一步

生成包含 1~3 个节点的 DSL JSON：

```json
{
  "workflow": { "name": "research-task", "mode": "dynamic" },
  "nodes": [
    {
      "id": "step-3",
      "type": "program",
      "command": "echo {{ nodes.step-2.result }}",
      "capture": "search_output"
    }
  ]
}
```

规则：
- 节点 ID 必须全局唯一（建议 `step-<N>` 前缀）
- 可引用之前所有步的结果：`{{ nodes.step-1.result }}`
- 每步不超过 3 个节点
- 不要包含已执行的节点（解释器自动跳过）
- **program 节点的复杂逻辑必须使用独立脚本文件**：行内命令（`python -c "..."`、含中文的长管道等）难以调试和维护。如果命令超过 2-3 个操作、包含中文参数、或需要条件/循环，应生成或引用已有的 `.py`/`.sh` 脚本文件，command 里只写脚本调用

### 3. 调用解释器

```bash
python interpreter/task_compiler.py <temp.json> --session <session-name>
```

校验失败 → 修复 JSON 重试；执行失败 → 按 `on_failure` 策略处理。

### 4. 处理 Agent 节点

读 `build_plan.json`，对每个 `type: "agent"` 且 `status: "pending"` 的节点启动 SubAgent。

### 5. 更新状态

写 `state.md`：

```markdown
# State — step-3/30

## 目标
分析用户行为数据并生成报告

## 已完成
- step-1: 查询数据库 → 1000 条记录
- step-2: 数据清洗 → 980 条有效记录

## 最后节点结果
- step-3 (program): 完成，capture → `stats_result`

## 下一步方向
- step-4: 生成可视化图表 (program)
```
### 6. 检查完成条件

- `step_count >= max_steps` → 结束
- 节点全部完成且目标达成 → 结束
- 每 5 步询问用户是否继续
- 其他 → 回到步骤 1

## 状态文件格式

`state.md` 是循环中维持状态的唯一持久化文件，**不依赖对话上下文**。

必需字段：
- `# State — step-N/M`：当前步数 / 最大步数
- `## 已完成`：已完成步骤摘要
- `## 最后节点结果`：最近一步执行结果
- `## 下一步方向`：候选方向

## 积累模式

动态模式默认只关注"当前步 → 下一步"的转换。**积累模式**在此基础上将所有节点持久化到一个 DSL 文件中，使整个工作流程可以被保存、review 和复用。

### 与动态模式的唯一区别

```
动态模式：  生成单步 DSL → 执行 → 丢 → 重复
积累模式：  生成单步 DSL → 执行 → 追加到积累 YAML → 重复 → 产物是可复用 DSL
```

解释器和执行流程完全相同，差别只在主 Agent 的循环行为。

### 文件约定

在 session 目录下维护三个文件：

| 文件 | 职责 | 谁维护 |
|------|------|--------|
| `state.md` | 当前进展（同动态模式） | 主 Agent 每轮更新 |
| `context.md` | 全局约束、规则、待办 | 主 Agent 初始化时建，按需更新 |
| `workflow.accumulating.yaml` | 积累的 DSL 节点 | 主 Agent 每轮追加/回写 |

#### context.md — 全局上下文注入

```markdown
# Context — feishu-sales-report

## 全局规则
- 发现已有节点有缺陷时，直接回写修正，不留 TODO
- 所有节点必须带 description
- 幂等节点加 capture，后续节点通过 {{ variables.xxx }} 引用

## 修正记录
- step-3: 方向错了，已标记废弃，最终清理时移除
- step-5 的 depends_on 缺少 step-2，已补上

## 最终产物说明
- 只保留从 generate-data 到 create-doc 这条主线
- 所有中间试错节点（step-3, step-4 的备选方案）在清理时删除
```

主 Agent 在发现错误或回写时，同步更新 `context.md` 的"修正记录"部分。这是它**不会忘记的机制**——每轮循环读 context.md 是固定步骤，修正记录就在那里。

#### workflow.accumulating.yaml

```yaml
workflow:
  name: research-task
  mode: static              # 积累完成后转为 static
  description: 动态研究任务-2026-06-07

variables:
  target: "用户行为分析"
  search_query: "user behavior analysis 2025"

nodes:
  - id: step-1
    type: program
    description: 数据查询
    capture: raw_data
    command: python search.py --query "{{ variables.search_query }}"

  - id: step-2
    type: agent
    description: 分析数据
    requires:
      skills:
        - web-search
      tools:
        - python
    depends_on:
      - step-1
    prompt: "分析原始数据，提取关键模式..."
```

#### 主 Agent 循环

每次循环（观察 → 生成 → 执行 → 更新状态），**多做三件事**：

1. **读 `context.md`** — 加载全局规则和修正记录
2. **生成节点时标注 `requires`** — 主 Agent 根据自身能力自省：如果生成 agent 节点调用了某个 skill 或外部工具，在该节点上标注对应的 `requires` 字段。这样积累的 DSL 对其他人也是可用的。

   > **注意**：主 Agent 必须自觉标注 `requires`，解释器不会强制要求。若主 Agent 忘记标注，Phase 1 的依赖扫描会跳过该节点，SubAgent 可能在运行中途因缺工具而失败。积累模式产出的 DSL 若缺少 `requires`，其他环境无法直接复用。

3. **写/更新积累文件**：
   - 追加当前步新生成的节点定义
   - 如果发现之前节点的缺陷，立即回写修正（受 context.md 约束驱动）
   - 如果修正了某节点，在 `context.md` 修正记录中追加条目
4. 保持 YAML 语法有效、结构完整

#### 发现错误时的处理流程

1. 意识到某节点有缺陷
2. 直接编辑 `workflow.accumulating.yaml` 修正该节点
3. 在 `context.md` 修正记录中追加一条（"step-X: 修正了 YY 问题"）
4. 继续循环

如果错误导致后续节点都不可用：
1. 在 `context.md` 中标记该节点废弃
2. 从 `workflow.accumulating.yaml` 中删除该节点和依赖它的下游节点
3. 重新生成替代方案

### 收尾清理 — 只保留正确路径

积累模式结束后，`workflow.accumulating.yaml` 中可能包含试错节点、被废弃的分支。清理的目标是**只保留一条可执行的正确路径**。

清理标准：**只保留在最终 `context["nodes"]` 中有成功结果且未被废弃的节点**。具体流程：

1. **读 `build_plan.json`** — `node_results` 包含所有被执行过的节点及其状态
2. **读 `context.md`** — 修正记录标记了哪些节点废弃、哪个分支是正确路径
3. **剪枝**：
   - 移除标记为废弃的节点
   - 移除 `execution_order` 中状态不为 `completed` 的节点
   - 修复残留的 `depends_on` 引用（剪掉指向被删节点的边）
4. **验证**：检查清理后的 DAG 无悬挂依赖、无循环
5. **输出**：写入 `workflows/<name>.yaml`，同时移除 `mode: static`（积累完后就是静态）

#### 剪枝示例

```yaml
# 清理前
nodes:
  - id: step-1          # 主线
  - id: step-2          # 主线
  - id: step-3-try-a    # 废弃分支
  - id: step-3-try-b    # 废弃分支
  - id: step-3          # 主线（纠正后的）
  - id: step-4          # 主线

# 清理后（只保留主线）
nodes:
  - id: step-1
  - id: step-2
  - id: step-3          # depends_on 自动修正为 [step-2]
  - id: step-4          # depends_on 自动修正为 [step-3]
```

### 适用场景

| 场景 | 建议 |
|------|------|
| 一次性的探索性分析 | 动态模式，不需要积累 |
| 探索后发现流程有价值，想保存 | 中途切换到积累模式 |
| 明确想做可复用的工作流 | 开始时就用积累模式 |
| 多轮迭代，需要人工 review 流程 | 积累模式 + 每 5 步展示进度给用户 |
