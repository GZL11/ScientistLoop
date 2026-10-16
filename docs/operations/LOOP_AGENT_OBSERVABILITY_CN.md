# Loop Agent 轨迹与成本观测

## 1. 定位

这是 Loop Infra 的通用能力，不属于 NatureBench、Harbor 或任何具体 Benchmark。

```text
Agent Adapter
  -> 本次激活的增量 telemetry + 原生轨迹引用
  -> Loop Observability Store
       |- artifacts/agent_usage.jsonl
       |- artifacts/agent_trajectory.jsonl
       `- controller/agent_usage_summary.json
  -> Benchmark Trajectory Adapter
       `- 按官方格式投影，不反向侵入 Infra
```

Agent、Benchmark、Evaluator 的边界如下：

- Agent Adapter 负责理解 Claude Code、Codex、OpenCode 或自定义 Agent 的原生格式；
- Loop Infra 只消费统一 telemetry，不解析某个 Benchmark 的目录；
- Benchmark Adapter 只把统一轨迹投影为官方提交格式；
- Evaluator 不参与 Agent Token 或费用统计。

## 2. 激活级记录

`artifacts/agent_usage.jsonl` 每行对应一次 Agent 激活，主要字段包括：

| 字段 | 含义 |
|---|---|
| `call_id` | 本次激活的全局标识 |
| `role` | `idea`、`implement`、`idea_rank` 或 single-LLM 节点名 |
| `adapter/runtime/model` | Agent Adapter、CLI 运行时和显式模型 |
| `session_id/resumed` | 长生命周期 Session 及本次是否 Resume |
| `started_at_ms/finished_at_ms/duration_ms` | 激活时间和进程活跃时长 |
| `provider_turns` | 供应商明确返回的回合数 |
| `token_usage` | input、cache create、cache read、output 四类 Token |
| `cost` | Agent CLI/Adapter 明确返回的原始费用、币种和来源 |
| `native_trajectory_refs` | 原生 Session 证据引用 |
| `normalized_trajectory_ref` | 本次增量标准轨迹 |

统计约束：

- 不根据模型名和公开价格表隐式猜价；没有 CLI/Adapter 费用字段时，原始费用保持 `null`；
- 只有 Goal/Harness 显式提供价格策略时才生成 `calculated_cost`，且不覆盖原始费用；
- Agent 活跃时长是各激活时长之和，并发激活会重叠，不等于 Run 墙钟时间；
- Resume 前记录原生 Session 文件偏移，Resume 后只导出新增事件；
- Claude 同一响应的 thinking/tool 内容块即使重复携带 usage，也只计一次；
- 统一 ledger 是事实来源，summary 和 CSV 都是可重建的派生产物。

## 3. 统一轨迹

`artifacts/agent_trajectory.jsonl` 使用稳定 envelope：

```json
{
  "schema_version": 1,
  "event_id": "call_x:12",
  "call_id": "call_x",
  "role": "implement",
  "runtime": "claude",
  "session_id": "session_x",
  "sequence": 12,
  "event_type": "assistant",
  "source": {"kind": "native_session", "path": "branches/..."},
  "payload": {}
}
```

`payload` 保留供应商原始事件，envelope 提供跨 Agent 可查询的公共字段。这样既能做统一
查询，也不会为了所谓统一而丢失工具调用、消息、错误和供应商扩展字段。

NatureBench 等官方格式由各自 trajectory adapter 在导出边界解包或转换 `payload`。
新 Run 的 adapter 不需要扫描 `.claude` 或 `.codex` 私有目录；旧 Run 才使用兼容回退。

## 4. 查询与导出

按 Harness Run 目录查询：

```bash
famou-scientist loop telemetry \
  --workspace .famou/naturebench-runs/<run-id>
```

按普通 Loop Goal 查询：

```bash
famou-scientist loop telemetry --goal-id <goal-id> --json
```

生成可提交给外部平台的独立目录：

```bash
famou-scientist loop telemetry \
  --workspace <run-dir> \
  --output <export-dir>
```

导出目录包含：

```text
<export-dir>/
|- agent_usage.jsonl
|- agent_usage.csv
|- agent_trajectory.jsonl
`- agent_usage_summary.json
```

## 5. Adapter 要求

新的 Agent Adapter 应在标准结果的 `telemetry` 字段中返回本次激活的增量信息。
字段不可得时填空，不得伪造；原生轨迹可以保留为引用，也可以同时提供标准增量轨迹。

当前内置 CLI Adapter 已支持：

- Claude Code：解析顶层 `usage`、`num_turns`、`total_cost_usd` 和原生 Session；
- Codex：解析 `turn.completed.usage` 和 thread/session；
- OpenCode：读取顶层标准 usage，缺失字段保持为空；
- 自定义 Agent / single LLM command：支持 `__telemetry__` 或 `__usage__`，否则至少记录
  调用状态、时长和证据路径。

`total_cost_usd` 是 CLI 给出的美元等价成本。使用 Anthropic-compatible 网关连接 GLM 等
模型时，它可能按 CLI 识别到的 canonical Claude 模型价格计算，不能直接视为底层服务的
实际账单；真实账单应由部署方 billing API 或内部计费系统另行接入 Adapter。

## 6. 显式价格重算

普通 Loop 可在 Goal 中配置：

```yaml
infra:
  observability:
    pricing:
      currency: USD
      per_million_tokens:
        input: 1.4
        cache_creation: 1.4
        cache_read: 0.26
        output: 4.4
      source: user_confirmed
      effective_at: "2026-08-11"
```

Harness 使用等价参数：

```bash
famou-scientist agent run \
  ... \
  --pricing-currency USD \
  --input-price-per-million 1.4 \
  --cache-creation-price-per-million 1.4 \
  --cache-read-price-per-million 0.26 \
  --output-price-per-million 4.4 \
  --pricing-source user_confirmed \
  --pricing-effective-at 2026-08-11
```

四类单价必须同时提供。计算公式为：

```text
calculated_cost =
    input_tokens                 * input_price / 1,000,000
  + cache_creation_input_tokens  * cache_creation_price / 1,000,000
  + cache_read_input_tokens      * cache_read_price / 1,000,000
  + output_tokens                * output_price / 1,000,000
```

`controller/agent_usage_summary.json` 同时保留：

- `total.cli_reported_cost`：CLI/Adapter 原始费用；
- `total.calculated_cost`：配置价格重算值；
- `total.calculated_cost_breakdown`：四类 Token 的费用分项；
- `pricing_policy/pricing_source/pricing_effective_at`：完整价格审计口径。

当前 GLM-5.2 价格由用户在 2026-08-11 确认。Cache Creation 暂按未命中输入价格
`$1.40/M` 计算，Cache Read 按 `$0.26/M` 计算。若供应商后续给出独立 Cache Creation
价格，只需更新配置并重建摘要，无需改动原始 usage ledger。
