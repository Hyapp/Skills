# Windows 限制

program 节点的 Python 脚本在 Windows 上的已知问题和约束。

## 禁止行内 Python

`python -c "..."` 行内代码不可行，原因是：

1. **多层转义断裂**：YAML → JSON → cmd.exe → Python，每层转义规则不同
2. **中文编码问题**：`subprocess.run(text=True)` 用 gbk 解码 stdout，非 ASCII 字符导致 `UnicodeDecodeError`

```yaml
# ❌ 禁止
command: |
  python -c "..."

# ✅ 正确 — 独立脚本
command: python workflows/scripts/my_script.py
```

## 独立 Python 脚本防坑清单

| # | 规则 | 原因 |
|---|------|------|
| 1 | `shell=True` + 字符串命令调 `.cmd` | Windows 上 lark-cli.cmd 需要 cmd.exe 解析 |
| 2 | 内层 subprocess 加 `encoding='utf-8'` | lark-cli 输出 UTF-8，`text=True` 默认用 gbk 解码会崩 |
| 3 | stdout 输出纯 ASCII：`ensure_ascii=True` | 解释器用 gbk 捕获 stdout |
| 4 | 写 .bat 用 `locale.getpreferredencoding()` | cmd.exe 用系统编码（gbk）读 .bat |
| 5 | 大入参走 stdin，不用 `@file` | `@file` 在 Windows 上触发 Go symlink bug |

## lark-cli 已知问题

| 问题 | 表现 | 解决方案 |
|------|------|----------|
| `.cmd` 后缀 | `FileNotFoundError` | `lc = 'lark-cli.cmd' if os.name == 'nt' else 'lark-cli'` |
| `@file` 绝对路径 | `cannot resolve symlinks` | 改用命令行内联传参或 stdin 管道 |
| `@file` 相对路径 | 同上 | `... --flag - < tempfile` |
| Batch 文件中文乱码 | lark-cli 收到乱码参数 | `locale.getpreferredencoding()` 写 .bat |
| `docs +create --markdown` | v2 API 不接受 | 始终用 XML 传给 `--content` |
| `<sheet>` 自闭合 | 创建空白表格失败 | `<sheet ...></sheet>`（必须闭合标签） |
| `<sheet>` 属性顺序不固定 | token 和 sheet-id 值互换 | 两种顺序各写一个 regex |
