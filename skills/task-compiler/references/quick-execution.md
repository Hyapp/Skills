# 快速执行

已有 DSL 文件时的执行命令。

## 基本用法

```bash
/task-compile <workflow.yaml>
/task-compile <workflow.json> [--output-dir ./output] [--session <name>]
```

示例：
```
/task-compile ./workflows/feishu-sales-report/workflow.yaml
```

## 标志

| 标志 | 说明 |
|------|------|
| `--output-dir <dir>` | 输出目录（默认 `./output`） |
| `--session <name>` | 指定会话名称以复用执行目录；不指定时自动生成唯一目录 |
| `--debug` | 跳过 hash 校验，接受被用户手动修改过的中间产物 |
| `--clean` | 执行成功后自动删除会话目录 |
| `--on-failure <strategy>` | `abort`（停止）\| `retry`（重试）\| `pause`（暂停） |
| `--max-retries N` | 重试次数（默认 3），仅 `retry` 策略有效 |
| `--output-validate` | 强制启用 agent 节点输出校验（dynamic 模式默认启用，static 默认关闭） |
| `--no-output-validate` | 强制禁用 agent 节点输出校验 |

## 手动调用解释器

```bash
python ./interpreter/task_compiler.py <workflow.json> \
  [--output-dir ./output] [--session <name>] [--debug] [--clean]
```

YAML 文件会自动转换为同名的 `.json` 文件后传入解释器。

## 执行后状态管理

解释器运行后使用 state hook 初始化执行状态：

```bash
python ./interpreter/execution_state.py ./output/<session> init
```

## 上下文恢复

压缩后快速恢复：

```bash
# 当前 wave 和下一步
python ./interpreter/execution_state.py ./output/<session> status

# 完整的 session 索引（wave 进度、节点状态、生成物）
python ./interpreter/state_index.py ./output/<session>

# 查看特定节点
python ./interpreter/state_index.py ./output/<session> --node summary-2-2
```

## 参考 workflow

- `./workflows/feishu-sales-report/workflow.yaml` — 创建飞书文档（内嵌电子表格 + 假数据 + 总结）
