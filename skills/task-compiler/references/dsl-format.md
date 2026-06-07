# DSL 格式

## 顶层结构

```yaml
workflow:
  name: my-workflow
  description: 做什么的
  mode: static               # static（默认）| dynamic
  on_failure: abort          # abort | retry | pause
  max_retries: 3
  parallel: 1                # 并发数（默认 1 = 串行），控制同一 wave 内的 agent 节点并行度
  agent_runtime: codex # codex（默认）| trae | claude，指定 SubAgent 使用的模型运行时
  variables:                 # 可选，有默认值直接确认，无默认值向用户询问
    target: "默认值"
    search_query:
  nodes:
    - id: step-1
      type: program
      description: 第一步
      command: echo hello
    - id: step-2
      type: agent
      description: 第二步
      depends_on:
        - step-1
      agent_params:
        prompt_file: ...
        context_file: ...
```

## 节点类型

| 类型 | 说明 |
|------|------|
| `program` | 执行 shell 命令，capture stdout |
| `text` | 展开 `{{ }}` 模板，输出文本 |
| `agent` | 启动 SubAgent 执行复杂任务 |
| `plugin` | 引用已注册 plugin（如 render-feishu），在 Phase 3 执行。解释器在 Phase 2 验证 plugin 存在并准备参数，状态置为 pending |

## workflow 级别字段说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | string | - | **必填**。workflow 名称 |
| `description` | string | - | 可选描述 |
| `mode` | string | `static` | `static` 或 `dynamic` |
| `on_failure` | string | `abort` | `abort`、`retry`、`pause` |
| `max_retries` | int | `3` | 重试次数 |
| `parallel` | int | `1` | 并发数，控制同一 wave 内的 agent 节点并行度 |
| `agent_runtime` | string | `codex` | SubAgent 使用的模型运行时：`codex`（默认）、`trae`、`claude` |
| `variables` | dict | - | 工作流变量定义 |

### 通用字段（所有节点类型共用）

所有节点均可使用以下字段：

```yaml
- id: my-script
  type: program                # 或 text / agent
  description: 可选的说明文字
  on_failure: abort            # abort | skip | retry | pause（节点级，覆盖 workflow 级）
  capture: output_var          # 可选，命名捕获 stdout/result，供后续 {{ variables.xxx }} 引用
  idempotent: true             # 可选，标记节点为幂等。回退时已完成的幂等节点跳过重跑
  requires:                    # 可选，声明运行时环境依赖（所有节点类型均支持）
    skills:
      - lark-doc
    tools:
      - lark-cli
  depends_on:
    - prev-node-id
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `requires` | dict | 运行时环境依赖。`skills` 为需要的子技能名称（如 `lark-doc`），`tools` 为需要的可执行文件（如 `lark-cli`）。所有节点类型均可声明。解释器做结构校验，主 Agent 在 Phase 1 做环境可用性校验 |
| `capture` | string | 将节点的 stdout/result 命名为变量，后续节点通过 `{{ variables.xxx }}` 引用 |
| `idempotent` | bool | 可选，默认 false。标记节点为幂等——相同输入始终产生相同输出。回退时已完成的幂等节点保留其 completed 状态，不重新执行。适用于固定种子的数据生成、纯计算等无副作用的节点 |

### program 节点

```yaml
- id: my-script
  type: program
  command: python scripts/generate.py
  capture: output_var   # 可选，命名捕获结果供后续 {{ }} 引用
```

> **Windows 注意**：禁止 `python -c "..."` 行内代码，详见 [Windows 限制](windows-limitations.md)。

### text 节点

```yaml
- id: welcome
  type: text
  content: |
    # {{ workflow.name }}
    上一步结果：{{ nodes.my-script.result }}
```

### plugin 节点

```yaml
- id: render-doc
  type: plugin
  plugin: render-feishu              # plugin 名称，对应 plugins/<name>/plugin.yaml
  depends_on:
    - build-ir
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `plugin` | string | **必填**。plugin 名称，task-compiler 验证它在 `plugins/` 中存在 |

Plugin 节点在 Phase 2 被**发现并验证**（检查 plugin.yaml 存在、execute.command 完整），状态设为 `pending`。
主 Agent 在 Phase 3 读取 `plugin_params.command` 执行。

#### plugin.yaml 格式

Plugin 目录下必须包含 `plugin.yaml`：

```yaml
name: render-feishu
version: 1
description: IR → 飞书云文档渲染器

requires:               # 可选。声明运行时依赖，引用该 plugin 的节点自动继承
  tools:
    - lark-cli

execute:
  command: python {plugin_dir}/render.py {input_ir}

validate:                     # 可选。执行前校验，主 Agent 在 Phase 3 调用
  command: python {plugin_dir}/validate.py {session_dir}

ir:                           # 可选。声明 IR schema，供主 Agent 静态校验
  media_type: application/vnd.feishu-doc-ir
  format: yaml
  context: ...
  block_types: ...
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `requires` | 否 | 运行时环境依赖，格式同节点级 `requires`。声明后，DSL 中引用本 plugin 的节点自动继承此依赖，Phase 1 统一检查 |
| `execute.command` | 是 | 执行命令。支持模板变量：`{plugin_dir}`（plugin 目录）、`{input_ir}`（IR 文件路径，由主 Agent 在 Phase 3 解析） |
| `validate.command` | 否 | 前置校验命令。支持模板变量：`{plugin_dir}`、`{session_dir}`（会话输出目录）。exit 0 继续，exit ≠ 0 阻断执行 |
| `ir` | 否 | IR schema 声明，主 Agent 在 Phase 3 做静态校验时参考 |

解释器在启动时自动扫描 `plugins/*/plugin.yaml` 发现所有可用 plugin。

**依赖继承规则：** 节点级 `requires` 与 plugin 级 `requires` 合并（并集），节点级可以补充额外的依赖但不能减少 plugin 声明的依赖。

### agent 节点

```yaml
- id: create-doc
  type: agent
  recovery: auto             # auto（默认）| manual
  manifest:                  # 可选，标明副作用供错误恢复参考
    - 飞书文档（含内嵌画板）
    - 电子表格数据
  requires:                  # 可选，声明运行时依赖
    skills:
      - lark-doc
    tools:
      - lark-cli
  depends_on:
    - data-prep
  output:                    # 可选，声明输出文件（用于校验）
    files:
      - result.md
  agent_params:
    prompt_file: agents/my-agent/prompt.md     # prompt 模板（{{ }} 已展开）
    context_file: agents/my-agent/context.json  # 文件清单和输入源
    files_dir: agents/my-agent/files/           # 依赖文件目录
```

| 字段 | 说明 |
|------|------|
| `recovery` | `auto`（默认）：无副作用或幂等，失败可直接重跑；`manual`：有不可逆副作用，失败时主 Agent 汇总副产物清单供用户确认 |
| `manifest` | 人类可读的副作用清单，仅 `recovery: manual` 时生效。失败时展示给用户"预期有哪些东西，部分可能已创建" |
| `output.files` | 输出文件列表（相对于 agent 节点目录）。声明后解释器自动注入校验步骤到 prompt，SubAgent 执行完毕后用 task-compiler 内置的 `interpreter/validate_output.py` 校验所有文件存在且非空。不声明则根据 workflow.mode 决定：dynamic 模式默认开启（校验 `result.md`），static 模式默认关闭。可通过 `--output-validate` / `--no-output-validate` CLI 标志强制开关 |

#### 输出校验流程

output 校验使用 task-compiler 内置的固定校验脚本 (`interpreter/validate_output.py`)，幂等且不可定制：

1. 解释器将输出文件列表和校验命令注入到 SubAgent 的 prompt 尾部
2. SubAgent 执行任务，将结果写入声明的输出文件
3. SubAgent 运行 `python validate_output.py <file1> <file2> ...`
4. 校验通过（exit 0）→ 返回结果
5. 校验失败（exit 1）→ SubAgent 读取 stdout 中的错误描述（"文件不存在"或"文件为空"），自行修复后回到步骤 3
6. 重试耗尽 → 标记 failed 返回

解释器不参与重试循环。校验脚本是 task-compiler 自带的固定脚本，不依赖自定义校验逻辑。

## `{{ }}` 表达式

在 `command`、`content`、prompt 等字段中引用运行时值：

| 表达式 | 说明 |
|--------|------|
| `{{ workflow.name }}` | workflow 名称 |
| `{{ workflow.description }}` | workflow 描述 |
| `{{ variables.xxx }}` | variables 中定义的值 |
| `{{ nodes.step-1.result }}` | 前序节点的 stdout 捕获结果 |
| `{{ nodes.step-1.exit_code }}` | 前序节点的退出码 |

表达式在解释器阶段完成展开，agent 节点的 prompt 读到的是已展开的纯文本。

**隐式依赖注入：** 解释器会自动检测 `command`/`content`/`prompt` 中的 `{{ nodes.X.result }}` 引用，自动将节点 X 注入到本节点的 `depends_on` 中（不需要手动写）。这保证了 wave 分组的正确性——B 引用了 A 的数据，B 一定在 A 之后执行。

## 依赖关系

`depends_on` 定义 DAG 依赖，解释器按拓扑排序执行：

```yaml
- id: step-b
  depends_on:
    - step-a     # step-b 在 step-a 完成后才执行
```

没有 `depends_on` 的节点可并行（当前仍是串行，后续支持）。
