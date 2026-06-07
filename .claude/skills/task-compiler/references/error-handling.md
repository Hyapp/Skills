# 错误处理

## 两层错误处理模型

| 层 | 作用范围 | 谁处理 | 字段 |
|---|---------|--------|------|
| on_failure | program/text/agent 节点 | 解释器（program）或主 Agent（agent） | `on_failure` |
| recovery | agent 节点 | 主 Agent | `recovery` |

## 策略优先级

`node.on_failure > workflow.on_failure > --on-failure CLI > 默认 abort`

| 策略 | 静态模式 | 动态模式 |
|------|----------|----------|
| `abort` | 解释器立即退出 / 主 Agent 停止 | 停止循环，向用户报告 |
| `skip` | 标记 failed，继续 | 标记 failed，继续下一步循环 |
| `retry` | 解释器自动重试（program），耗尽后标记 failed | 主 Agent 重新生成修正后的步骤 |
| `pause` | 解释器标记 paused，主 Agent 询问用户 | 主 Agent 询问用户 |

## Recovery 模式（仅 Agent 节点）

| recovery | 适用节点 | 失败时行为 | Resume 行为 |
|----------|---------|-----------|------------|
| `auto`（默认） | 无副作用或幂等 | 按 `on_failure` 处理 | 可直接重跑 wave |
| `manual` | 有不可逆副作用 | 等 wave 内其他节点完成，汇总 manifest + 执行副产物，请求用户确认 | 跳过，用户确认后继续 |

### manual 失败处理流程

recovery: manual 的节点失败时，主 Agent: 等正在跑的SubAgent完成

1. 等待 wave 内当前批次的其他 SubAgent 自然完成
2. 不发起后续批次
3. 收集所有已执行节点的 stdout/stderr，提取 token/URL 等关键信息
4. 读取节点的 `manifest` 清单
5. 向用户呈现：
   - 预期产物（来自 manifest）
   - 已完成的部分（来自 stdout）
   - 失败的部分（来自 stderr）
   - 恢复建议（如"需要删除已创建的文档吗？"）

## 场景对照

| 场景 | 行为 |
|------|------|
| 解释器校验失败 | 修复 JSON 重试，不递增 step_count |
| program 节点 retry 耗尽 | 标记 failed，按 `on_failure` 处理 |
| Agent 节点 + recovery:auto + 失败 | 按 `on_failure` 处理（skip/abort/pause） |
| Agent 节点 + recovery:manual + 失败 | 汇总副产物，等待用户确认 |
| 达到 max_steps | 强制终止，向用户报告进展 |
