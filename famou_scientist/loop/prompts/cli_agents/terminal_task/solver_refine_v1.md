# Terminal Task Solver Refine v1

继续当前 Terminal Task Solver session，在同一个 `$worktree` 中修正上一轮实现。

任务要求：

$instruction

评测策略：

$evaluation_policy_note

本轮重点：

- 读取公开上下文中的 SurrogateReport，逐项处理失败检查和证据缺口。
- 保留已经通过的行为，避免无依据地重写整个实现。
- 可以补充针对性测试，但不得寻找或调用官方隐藏 evaluator。
- 严格遵守公开上下文中的 `resource_limits`；进程池/线程池 worker 数不得超过分配的
  CPU 数，避免多进程复制大型数据。
- 不要把大量或高分辨率栅格图像直接加载进模型上下文；先计算数值摘要，必要时只查看
  单张最长边不超过 512 像素的强下采样预览或裁剪，避免在会话中累积图像 payload。
- 当前 refine turn 完成后自然退出；不需要调用 `submit_candidate`。
- 最多使用 $max_turns 个自主回合。

公开运行上下文：

```json
$request_json
```
