# 快速执行

已有 DSL 文件时的执行命令。

## 基本用法

```bash
/task-compile <workflow.yaml>
/task-compile <workflow.json> [--output-dir ./output] [--session <name>]
```

示例：
```
/task-compile workflows/feishu-sales-report.yaml
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

## 手动调用解释器

```bash
python interpreter/task_compiler.py <workflow.json> \
  [--output-dir ./output] [--session <name>] [--debug] [--clean]
```

YAML 文件会自动转换为同名的 `.json` 文件后传入解释器。

## 参考 workflow

- `workflows/feishu-sales-report.yaml` — 创建飞书文档（内嵌电子表格 + 假数据 + 总结）
