# Terminal-Bench Science Task-Specific Verifier 设计说明

> 状态：第一版已接入 verifier source 的静态检查、VerifierAgent 自测记录、Controller 同环境运行时探针、最多五次同 Session 编译修复、bundle 冻结和执行入口；
> 旧 `VerifierPlan + diagnose` 仍作为兼容路径保留，尚未完全移除。
>
> 目标：让 VerifierAgent 只负责生成一个经过测试、可冻结的 task-specific verifier；后续每轮由系统执行这个 verifier，为 Solve/ImplementAgent 提供确定性反馈。正式成绩仍由 Terminal-Bench Science 官方 verifier 在最终 `FinalAudit` 阶段给出。

## 1. 设计目标

Terminal-Bench Science 的正式验收是任务作者预先定义的程序化规则、数值检查、仿真或 ground-truth 对比，不是 Agent Judge。我们的 TerminalTask loop 需要在 Agent 运行期间尽可能模拟这些验收条件，提前暴露候选的失败项。

因此目标不是再增加一个负责“看结果并判断”的 LLM，而是：

```text
VerifierAgent
  -> 生成 task-specific verifier
  -> Controller 校验、测试并冻结

SolveAgent
  -> 修改 workspace
  -> 系统执行冻结 verifier
  -> 返回逐项结果和修复信息
  -> 必要时 resume/refine

Agent loop 结束
  -> 冻结 workspace
  -> 官方 Harbor/TBS verifier（FinalAudit）
```

非目标：

- 不让 VerifierAgent 在每轮重新判断候选；
- 不用 LLM Judge 替代官方 verifier；
- 不把官方 hidden GT 或官方私有测试暴露给 Agent；
- 不新增一个与统一 Infra 平行的 Terminal-Bench 专用 Runner；
- 不要求 VerifierAgent 手写最终 JSON 字符串。

## 2. 角色和边界

| 角色 | 职责 | 是否参与每轮候选判定 |
|---|---|---:|
| `VerifierAgent` | 根据公开 task 说明编写 verifier 源码、检查描述和测试 fixture | 否，仅初始化/有限修复阶段 |
| `Controller` | 校验 verifier、计算 hash、冻结版本、调度执行、保存报告 | 是，负责系统编排，不解释结果 |
| `GeneratedVerifier` | 对候选 workspace/artifact 执行确定性检查并返回结构化对象 | 是，唯一的 surrogate 判定来源 |
| `SolveAgent` | 完成任务并根据 verifier 反馈修复 | 是，读取反馈但不修改 verifier |
| 官方 TBS/Harbor verifier | 对冻结 workspace 做正式 FinalAudit | 仅最终阶段 |

当前实现中的 `phase=diagnose` 和 `_diagnoser()` 属于需要移除的旧路径：它们会在每轮把证据再次交给 VerifierAgent/LLM，让 LLM 决定 `passed` 或 `repair_required`。新设计中每轮不再调用这个 LLM diagnose。

## 3. VerifierAgent 产物

VerifierAgent 不直接输出一大段 JSON。它在指定的 verifier source workspace 中写入文件：

```text
controller/verifier/source/
  verifier.py             # 必需：可执行 verifier
  verifier_spec.md        # 检查项、依据和覆盖边界
  tests/
    test_verifier.py      # 必需：verifier 自测
  fixtures/               # 可选：正例、负例和边界样例
```

`verifier.py` 提供受控接口。推荐接口形状：

```python
def describe() -> list[CheckSpec]:
    """返回固定检查项及其公开说明。"""

def verify(candidate_root: Path, task_root: Path, output_dir: Path) -> VerifierResult:
    """只读检查候选，结果由 runner 序列化。"""
```

这些类型和字段契约由系统提供的 verifier SDK/本地 helper 定义，不由 Agent 自由改变。VerifierAgent 在 `verifier.py` 中描述检查项并实现检查逻辑：

- `describe()` 返回检查项内容；Controller 校验和规范化后形成最终 `CheckSpec`；
- `verify()` 运行时为每个检查生成单项结果（`CheckResult`）；
- Controller 的 verifier runner 校验这些结果，并汇总计算整轮 `VerifierResult` 及其 `passed`/`repair_required` 状态。

VerifierAgent 不需要手写 JSON，也不能自行修改结果 schema 或直接指定整轮状态。Verifier runner 负责把最终对象序列化为稳定的 `round_N.json`。

最终 `CheckSpec` 包含：

- `id`：由 Controller 在编译阶段稳定分配，VerifierAgent 不填写；同一个冻结 bundle
  内保持不变，用于关联检查定义、运行结果和证据；
- `requirement_ref`：VerifierAgent 填写，引用公开 task instruction 中对应的验收要求；
- `severity`：VerifierAgent 根据公开要求标注，值为 `critical|major|minor`。
  `critical` 表示明确的硬性验收条件，`major` 表示会显著影响验收的代理检查，
  二者失败会触发 `repair_required`；`minor` 仅作诊断提示，不阻断本轮；
- `checker_kind`：可选的审计标签，例如 `file`、`schema`、`numeric` 或
  `simulation`，用于说明检查实现类型；它不参与判定、评分或权限配置。MVP 可以不提供，
  runner 不依赖它；
- `pass_criteria`：VerifierAgent 根据公开要求填写的、可重放的通过条件。

不按 `checker_kind` 切换多套执行 profile。为保证与不同 task 和公开 evaluator
兼容，Controller 使用一套统一 runner：

- 将候选 workspace snapshot 挂载为只读，将本轮专用 output/evidence 目录作为唯一可写目录；
- 提供隔离的临时目录供公开 evaluator 写缓存或中间文件，任务结束后随本轮清理；
- 复用 task 当前的运行环境和公开 evaluator，不改变其依赖、环境变量或调用方式；
- 对整个 verifier run 使用统一、可配置的 wall-time、CPU、内存和磁盘上限；
- 保留最基本的路径边界和结果 schema 校验，禁止访问 Controller 私有目录、hidden GT
  和任务目录之外的未授权路径；
- verifier 执行失败时返回 `verifier_error`，不把它误判为候选失败。

这样 `checker_kind` 只是帮助阅读和审计的标签，不会因为标签错误导致 verifier
无法运行，也不会引入额外的权限、资源或调度复杂度。若将来确实出现资源隔离需求，
再单独增加 runner profile，不改变 verifier 接口。

证据脱敏规则由 Controller 全局控制，不作为单项 `CheckSpec` 的
`evidence_policy`。失败报告也不预置 `repair_template`；verifier 只需返回明确的
失败原因、实际值、期望值和可访问证据，由 SolveAgent 自行决定如何修复。

## 4. 第一版：生成后校验和冻结

第一版做三类校验：VerifierAgent 在 verifier workspace 内自测，Controller 做静态和
接口检查，并在冻结前用之后实际执行 Proxy 的同一个 Python 运行时做公开数据探针。
这里不加入第二个 Agent Judge，也不接触 hidden GT。

### 4.1 静态和接口检查

- Python 语法编译和导入；
- `describe()`、`verify()` 和结果类型存在；
- Controller 能为所有检查稳定分配无冲突 ID；
- critical requirement 都有对应检查；
- 输出字段和状态值符合固定 schema；
- verifier 代码不修改候选 workspace；
- 禁止访问 hidden GT、官方测试私有路径、Controller 私有目录和未授权网络；
- 禁止任意 shell 注入、动态下载和读写任务外路径。

静态检查本身不执行 verifier 的 task-specific 测试，也不判断测试样例的语义正确性；
它只确认源码、接口、依赖、路径边界和结果 schema 满足系统契约。运行时兼容性由
4.3 的 Controller 探针补充检查。

### 4.2 VerifierAgent 自测

自测发生在 SolveAgent 运行之前，此时还没有真实候选产物。VerifierAgent 负责在
verifier source workspace 内准备测试 fixture，并实际运行自己的 `tests/`：

```text
临时 self-test workspace
  ├── valid_minimal/       # 已知应通过的最小候选
  ├── invalid_missing/     # 从正例删除必需产物
  ├── invalid_malformed/   # 类型、维度或格式错误
  └── boundary_*/          # 阈值两侧的候选
       ↓
VerifierAgent 运行 tests/test_verifier.py
       ↓
保存测试命令、退出码、日志和 fixture 清单
```

VerifierAgent 应尽量覆盖：

- 一个应通过的正例；
- 每个 critical 检查至少一个应失败的负例；
- 边界样例，例如阈值刚好通过和刚好失败；
- 同一个候选重复执行两次，结果和指标一致；
- 空候选、缺 artifact、格式错误候选的错误处理。

task-specific 的正例、负例和边界 fixture 由 VerifierAgent 放入 `fixtures/`。这些是
测试用候选产物，不是 SolveAgent 的真实结果。第一版只记录 Agent 自测的命令、退出码、
日志和覆盖清单，不由 Controller 独立判断 fixture 的语义是否正确。因此自测通过
表示“VerifierAgent 提供的测试命令成功”，不等于系统已经证明 verifier 与官方验收
一致；这项能力留到后续版本。

如果 task 无法构造已知正例，VerifierAgent 应明确标记自测覆盖不足；Controller 仍可
冻结通过静态检查的 bundle，但在质量评估中将其记录为 `self_test=partial`，且暂不让
它驱动自动 `passed`/`repair_required` 闭环。自测命令失败或未运行时，bundle 不进入
候选循环，需先由 VerifierAgent 修复。

### 4.3 Controller 同环境运行时探针

VerifierAgent 的自测可能运行在 Agent worker 的依赖环境中，而冻结后的 Proxy verifier
由 Controller Python 进程加载和执行。两者的 Python 包或 codec 版本不同，即使 Agent
自测通过，真实执行仍可能失败。因此 bundle 冻结前增加一道 Controller 探针：

```text
VerifierAgent 产出源码并自测
  -> Controller 静态检查
  -> Controller 当前 Python 运行时加载 verifier
  -> 使用公开 task 数据执行最小真实读取/解码
  -> 通过后才允许 freeze
```

当前实现对包含 `verifier_study.py` 和公开 `study/` 目录的医学影像任务执行真实 DICOM
探针：实例化生成的 `Study` helper，并对每个 diagnostic series 的首个实例调用
`pixels()`。这会实际经过 Controller 所安装的 NumPy、pydicom 和像素 codec，而不是
只检查 import。其他不适用的任务明确记录为 `skipped`，保持原有行为。

探针失败属于 verifier 运行时不兼容，不属于 Solver 候选失败。Controller 将异常类型、
完整错误消息作为 `compile_errors`，以 `phase=repair_compile` 恢复同一个 VerifierAgent
Session；修复后的源码必须重新经过静态检查和运行时探针。探针结果及 Controller 的
NumPy/pydicom 版本写入 manifest，便于区分 verifier 逻辑问题和依赖环境问题。

### 4.4 冻结

Controller 静态检查和运行时探针通过（不适用的任务为 `skipped`），且 VerifierAgent
自测命令成功（或明确标记为 `partial`）后，生成并写入：

```text
controller/verifier/
  manifest.json
  verifier.py
  verifier_spec.md
  tests/
  fixtures/
```

`manifest.json` 由系统生成，至少包含：

```json
{
  "schema_version": 2,
  "task_id": "...",
  "task_input_hash": "sha256:...",
  "verifier_bundle_hash": "sha256:...",
  "verifier_agent_session_ref": "...",
  "checks": ["artifact_exists", "schema", "metric_gate"],
  "self_test": {
    "status": "agent_reported_passed|agent_reported_failed|partial|not_run",
    "case_count": 6,
    "runner": "verifier_agent",
    "exit_code": 0,
    "log_ref": "controller/verifier/self_test.log"
  },
  "controller_runtime_check": {
    "status": "passed|skipped",
    "diagnostic_series": 3,
    "decoded_instances": 3,
    "numpy_version": "...",
    "pydicom_version": "..."
  },
  "frozen": true
}
```

冻结后：

- verifier bundle 只读；
- 每轮必须使用同一个 `verifier_bundle_hash`；
- SolverAgent 不能看到或修改 verifier source；
- VerifierAgent 不再恢复 session 参与候选判定；
- bundle 改变必须创建新的 attempt，不能覆盖当前 run。

如果编译或自测失败，Controller 会把精确错误通过 `phase=repair_compile` 发回同一个
`terminal_verifier` Session，默认允许最多五次受控修复并重新校验、冻结；编译尝试和修复次数
写入 Graph state。五次仍失败则当前 Graph 在 FinalAudit 前明确失败，不能使用未经测试的
verifier，也不能让 LLM 充当 fallback judge。该上限独立于 Solver 的 refine 预算，可通过
`TerminalTaskHarnessConfig.max_verifier_compile_repairs` 调整。

## 5. 每轮执行和结果报告

每轮 Solver turn 结束后，Controller 创建不可变候选 snapshot，并调用冻结的 `verify()`：

```text
solver workspace
  -> candidate snapshot
  -> GeneratedVerifier.verify(...)
  -> controller/surrogate/round_N.json
  -> solver workspace/.famou/surrogate/round_N.json
```

Verifier runner 自动生成以下报告：

```json
{
  "schema_version": 2,
  "round": 0,
  "verifier_bundle_hash": "sha256:...",
  "status": "passed|repair_required|verifier_error",
  "checks": [
    {
      "id": "artifact_exists",
      "status": "passed|failed",
      "actual": true,
      "expected": true,
      "reason": "design.npy 存在且可读取",
      "metrics": {},
      "evidence_refs": [".famou/surrogate/round_0/evidence/artifact.json"]
    }
  ],
  "metrics": {}
}
```

约束：

- `status` 由 verifier runner 根据检查结果计算，不能由 LLM 改写；
- `verifier_error` 只表示 verifier 执行或 schema 故障，不表示候选失败；
- `repair_required` 至少包含一个 failed critical/major 检查；
- 每项结果都应带可重放证据或明确说明没有证据；
- 给 Agent 的报告只保留公开、相对 workspace 可访问的路径和数据；
- Controller 私有路径、官方 GT、隐藏结果和完整 artifact storage path 不得进入 Agent view。

## 6. `partial-reflector` 示例

对官方 `partial-reflector`，VerifierAgent 应生成尽量接近官方验收的 task-specific verifier，覆盖：

- `/app/design.npy` 存在；
- `float64`、二维、尺寸、值域；
- 至少 `98%` 二值化；
- `0.35 μm` 最小线宽/间隙；
- 长直角矩形槽接口比例；
- 公开可执行的 FDTD 或低成本代理检查；
- 11 个波长上的 `T`、`R`、loss 及逐项阈值。

如果完整 FDTD 在每轮运行成本过高，可先使用公开、确定性的低成本检查或代理指标，但报告必须明确：

```json
{
  "check_kind": "surrogate",
  "official_final_audit_required": true
}
```

不能把 surrogate 通过当成官方 reward，也不能把未执行的 FDTD 检查报告为 passed。

## 7. 状态机调整

现有状态：

```text
VerifierPlan
  -> Solve
  -> SurrogateVerify
  -> LLM diagnose
  -> Repair
```

目标状态：

```text
VerifierCompile
  -> VerifierSelfTest
  -> VerifierFreeze
  -> Solve
  -> ExecuteFrozenVerifier
  -> Repair（失败且预算足够）
  -> ExecuteFrozenVerifier
  -> FreezeWorkspace
  -> FinalAudit（官方 TBS verifier）
```

建议的 Graph state 字段：

```text
verifier_bundle_ref
verifier_bundle_hash
verifier_compile_status
verifier_self_test_status
last_verifier_report_ref
last_verifier_status
```

这里的 `Graph state` 是 Controller 持久化的 **DAG 内部状态快照**，用于决定下一步唤醒哪个节点、在进程中断后从哪里恢复，以及保证节点调用幂等。它不是发给 Agent 的输入，也不是由 Agent 编辑的配置文件。Agent 只读取经过筛选的任务文件和 `.famou/surrogate/round_N.json`；Controller 私有的 state、bundle 路径和完整运行目录不进入 Agent view。

字段含义如下：

| 字段 | 作用 | Agent 是否直接可见 |
|---|---|---:|
| `verifier_bundle_ref` | 当前冻结 verifier bundle 的系统引用（路径或对象 ID），供 Controller 执行 | 否 |
| `verifier_bundle_hash` | bundle 内容的不可变版本指纹，确保所有轮次使用同一个 verifier | 通常否；必要时只在报告中作为版本标识 |
| `verifier_compile_status` | VerifierAgent 产物的语法、接口和静态检查状态 | 否 |
| `verifier_self_test_status` | 正例、负例、边界例、重复执行等自测状态 | 否 |
| `last_verifier_report_ref` | 最近一轮报告的系统存储引用；Agent 获得的是对应的脱敏报告 | 否；Agent 读脱敏报告 |
| `last_verifier_status` | 最近一轮的 `passed`、`repair_required` 或 `verifier_error` | 间接可见，通过脱敏报告中的 `status` |

除了这些 verifier 字段，通用 `GraphState` 还会保存 `phase`、`status`、`revision`、`data` 和 `completed_nodes`：

- `phase` 决定当前处于编译、自测、Solve、verifier 执行、Repair、冻结还是 FinalAudit 前等待阶段；
- `status` 表示整个 Graph 是否仍在运行或已经 `completed`、`failed`、`stopped`、`timed_out`；
- `revision` 是单调递增的状态版本，用于检测并发提交或恢复时的状态回退；
- `data` 保存任务 ID、session 引用、轮次、预算和产物引用等业务状态；
- `completed_nodes` 记录已经成功提交的节点调用，防止恢复时重复执行同一个幂等节点。

因此，Graph state 的职责是“**记住系统现在走到哪一步以及下一步该做什么**”；Verifier report 的职责才是“**说明这一轮候选哪些检查通过、哪些需要修复**”。

`verifier_session_ref` 只用于记录编译阶段的 VerifierAgent session，不再代表每轮诊断 session。

## 8. 现有代码迁移

| 当前实现 | 目标实现 |
|---|---|
| `VerifierPlanRunner` | `VerifierCompilerRunner` |
| `VerifierPlanStore` | `VerifierBundleStore`，负责 bundle 校验、hash、冻结 |
| `SurrogateVerifyRunner(..., diagnose=...)` | `FrozenVerifierRunner`，直接执行 bundle |
| `TerminalTaskHarness._diagnoser()` | 删除 |
| `phase="diagnose"` | 删除 |
| `DeterministicRubricExecutor` | 作为 bundle 内部 checker/helper，不能承担 LLM fallback |
| `verifier_plan_ref` | `verifier_bundle_ref` |
| `surrogate_report` | `verifier_report` / `surrogate_report` |

当前阶段不设计旧 Terminal-Bench checkpoint 的兼容迁移：仓库虽然有通用
`GraphStateStore`，但尚无需要按旧 verifier 逻辑恢复的已部署 run。迁移完成后，
新 run 必须生成并冻结 verifier bundle；如果恢复时发现 `graph_version` 或
`verifier_bundle_hash` 不匹配，Controller 应停止该 run 并要求创建新的 attempt，
而不是把旧 JSON plan 转换成新 bundle 或混用两套判定逻辑。待确实出现历史 run
需要延续时，再单独增加有测试覆盖的迁移方案。

## 9. 安全和可信边界

我们的 verifier 是模拟官方 GT 的 surrogate，不是官方 verifier，因此：

- 可以使用公开 task environment 和公开 evaluator；
- 不得访问官方隐藏测试、私有 GT 或 FinalAudit 结果；
- verifier 的输入是 Agent turn 结束时由 Controller 创建的 workspace snapshot
  及其中的候选产物；Agent 的退出只负责触发 verifier，不决定通过或失败；
- `passed`、`repair_required` 等状态只能由冻结 verifier 执行检查后、由 runner
  根据检查结果计算，不能由候选 workspace 中的说明文件或其他自定义状态字段决定；
- 不得执行候选提供的任意命令，除非该命令属于预先批准的 checker；
- 不得修改候选 workspace；
- verifier source、manifest 和每轮报告都要保留 hash；
- 最终是否完成仍以官方 FinalAudit 为准。

## 10. 校准和验收指标

Verifier 生成后自测只证明“可执行”，不能证明它近似官方 verifier。离线校准需要使用已经完成的官方 run，对比：

```text
surrogate pass  + official pass  = true pass
surrogate pass  + official fail  = false pass（最高优先级）
surrogate fail  + official pass  = false fail
surrogate fail  + official fail  = true fail
```

至少记录：

- critical requirement coverage；
- surrogate/official 一致率；
- false-pass rate；
- false-fail rate；
- 每轮 verifier 时间和资源；
- verifier 反馈后 Agent 的修复提升率。

## 11. 实施顺序

1. 定义 `VerifierResult`、`CheckSpec`、bundle manifest 和 runner schema；
2. 实现 bundle 静态校验、记录 VerifierAgent 自测结果、hash 和冻结；
3. 将 `VerifierPlanRunner` 替换为编译/自测/冻结节点；
4. 将每轮 `diagnose` 替换为冻结 verifier 执行；
5. 保留 `Solve -> Repair -> Freeze -> FinalAudit` 状态机；
6. 为 `partial-reflector` 实现第一个 task-specific verifier；
7. 灰度运行少量真实 task，记录 verifier 反馈与官方结果的差异；
8. 用历史 TBS 结果做 surrogate/official 离线校准；
9. 再决定是否加入 Controller 独立生成 fixture 和动态 contract tests；
10. 默认关闭旧 LLM diagnose 路径，完成迁移后删除旧 prompt 和兼容代码。

## 12. 最终职责图

```text
VerifierAgent
  = 编写 verifier

Controller
  = 校验、测试、冻结、调度和落盘

GeneratedVerifier
  = 确定性检查候选并生成反馈

SolveAgent
  = 根据反馈修复任务实现

Official TBS Verifier
  = FinalAudit 的最终权威验收
```

核心原则：**LLM 可以参与生成 verifier，但不能在 verifier 运行时充当裁判；系统反馈必须来自已测试并冻结的程序化 verifier。**

## 13. Agent 退出与 verifier 唤醒

Verifier 不由 Agent 主动提交，也不依赖 Agent 是否调用某个 `submit` tool。不同 CLI runtime（Claude Code、Codex、OpenCode 等）都使用同一套系统收尾语义：

- Agent 自然退出、当前 turn timeout 或被外部 stop 后，Controller 等待该 turn 的进程完全结束；
- Controller 为当前 workspace 创建不可变 snapshot，并记录 snapshot hash；
- Controller 自动执行已冻结的 verifier bundle；
- verifier 结果写入 Controller 私有报告和 Agent 可访问的脱敏报告；
- `repair_required` 且预算足够时，Controller resume 同一个 SolveAgent session；
- `passed`、达到最大 refine 轮数或达到 Agent 总预算时，Controller 冻结最终 workspace 并进入官方 `FinalAudit`。

因此不为 CC、Codex、OpenCode 分别设计业务层面的提交工具。若未来某个 runtime 为调试需要提供“提前结束”能力，它也只能作为 runtime 层的退出请求，不能直接触发 verifier、跳过 snapshot 或改变 verifier 版本；主流程仍由 Controller 在 Agent turn 结束后自动推进。

### 13.1 任务级容器生命周期

TerminalTask 使用任务级而不是 turn 级的 FMJob 生命周期。任务开始时分别启动一个
Solver worker 和一个（GT 或 proxy）Verifier worker；后续 solve/refine/verify 轮次通过
CFS 上的请求队列驱动同一 worker。Solver 的唯一持久 worktree 和任务声明的绝对产物
目录都位于共享 trial CFS 中，因此下一轮不会因为重新创建容器而丢失上一轮文件。

每轮仍创建不可变候选快照，Verifier 只读取该快照，避免它与 Solver 同时读写同一目录。
任务结束、时间预算耗尽或异常退出时，Controller 在 `finally` 中停止两个 worker 并
释放 FMJob。SOTA loop 和未配置任务级模式的旧调用继续使用一次调用一个 Job 的兼容路径。

## 14. 端到端流程图

```text
                         ┌──────────────────────────────┐
                         │ 公开 task instruction / view │
                         └──────────────┬───────────────┘
                                        │
                                        v
                         ┌──────────────────────────────┐
                         │ VerifierAgent                 │
                         │ 编写 verifier.py + tests     │
                         │ 只在初始化阶段运行            │
                         └──────────────┬───────────────┘
                                        │
                                        v
                         ┌──────────────────────────────┐
                         │ Controller                    │
                         │ 编译/静态检查                 │
                         │ 记录 Agent 自测结果           │
                         │ 同环境公开数据运行时探针       │
                         │ hash + freeze verifier bundle│
                         └──────────────┬───────────────┘
                                        │ 失败：有限次修复
                         ┌──────────────┴───────────────┐
                         │                              │
                         v                              │
              ┌──────────────────────┐                  │
              │ SolveAgent turn      │                  │
              │ solve / refine       │                  │
              └──────────┬───────────┘                  │
                         │ Agent 自然退出/timeout/stop  │
                         v                              │
              ┌──────────────────────┐                  │
              │ Controller 收尾      │                  │
              │ snapshot + hash      │                  │
              └──────────┬───────────┘                  │
                         v                              │
              ┌──────────────────────┐                  │
              │ Frozen Generated     │                  │
              │ Verifier             │                  │
              │ 确定性执行检查       │                  │
              └──────────┬───────────┘                  │
                         v                              │
              ┌──────────────────────┐                  │
              │ round_N.json         │                  │
              │ passed / repair      │                  │
              │ metrics + evidence  │                  │
              └───────┬──────────────┘                  │
                      │                                  │
          repair_required 且有预算                        │
                      │                                  │
                      └──────────────> resume 同一       │
                                       SolveAgent session │
                                       (回到 turn)         │
                                                         │
          passed / 预算耗尽 / 达到最大轮数               │
                      │                                  │
                      v                                  │
              ┌──────────────────────┐                  │
              │ Freeze final         │                  │
              │ workspace            │                  │
              └──────────┬───────────┘                  │
                         v                              │
              ┌──────────────────────┐                  │
              │ Official TBS/Harbor  │                  │
              │ FinalAudit           │                  │
              │ 最终权威 reward      │                  │
              └──────────────────────┘                  │
```

图中只有初始化阶段调用 `VerifierAgent`；候选循环中的反馈全部来自冻结的 Generated Verifier。Agent runtime 的退出方式不改变这条路径，官方 `FinalAudit` 也不会把结果回写到已冻结的 workspace。

## 15. 候选 verifier 模式切换

默认的候选校验模式是 `proxy`，必须继续作为兼容默认值保留。为了测试“直接使用官方
GT verifier 反馈”以及量化 proxy 与 GT 的差异，TerminalTaskGraph 增加配置
`candidate_verifier_mode`：

`gt_final_only` 用于“零次中途 GT”对照实验（有限次 GT 曲线的 K=0 端点）：Solver 的公开
上下文会明确标注 `final_only_once` 和剩余次数 `1`，并说明运行期间没有 GT 分数/失败反馈；
Controller 不创建 VerifierAgent，不执行候选级评测，只在 Solver 结束后调用一次官方
`FinalAudit`。该模式不提供 GT 反馈驱动的 refine。

`gt_budget` 用于“有限次 GT”实验（K=1、2、3…）：Solver 在运行期间可以**主动申请**官方 GT，
总次数由 `official_gt_budget`（CLI `--official-gt-budget`，默认 1）限制；`FinalAudit`
单独执行一次，不占用该额度，结果也不反馈给 Solver。触发方式是 Agent 驱动的：

1. Solver 的公开上下文携带 `evaluation_policy=on_request_budget`、
   `official_gt_evaluations_allowed/used/remaining` 和 `gt_request_file`
   （即 worktree 内的 `famou_terminal_solver_result.json`，wrapper 在每个 turn 开始前清空）。
2. Solver 把声明的产物写到规定路径后，在 `gt_request_file` 写入
   `{"request_official_gt": true, "reason": "..."}` 并自然退出；不写即视为不申请。
3. Controller 先导出候选快照；若申请有效且额度未用完，就对该快照运行一次官方 GT，
   把完整 `stdout/stderr/CTRF` 作为 `SurrogateReport.gt_evaluation` 注入下一轮 refine，
   并记录 `official_gt_used += 1`。`verifier_error` 属于系统故障，不扣额度。
4. 不申请、或额度已用完（报告中给出 `official_gt_request: skipped`），Controller 直接冻结
   并进入 FinalAudit。
5. `run_summary.json` 记录 `official_gt_budget`、`official_gt_used` 和逐次申请日志
   `official_gt_requests`（轮次、理由、是否批准、GT 状态、报告路径）。

Solver 提示词按“只新增版本、不原地改”的规则新增 `solver_solve_v2.md` /
`solver_refine_v2.md`，仅放宽了“不生成结果 JSON”这一条以允许写申请文件；wrapper 根据
`evaluation_policy == on_request_budget` 自动选择 v2，其余模式继续使用 v1。

| 模式 | 初始化 | 候选轮次判定 | refine 驱动 | 最终验收 |
| --- | --- | --- | --- | --- |
| `proxy` | 启动 VerifierAgent，编译并冻结 bundle | Frozen Generated Verifier | proxy | 官方 GT FinalAudit |
| `gt_primary` | 不启动 VerifierAgent | 官方 TBS/Harbor GT verifier（每轮） | GT | 官方 GT FinalAudit |
| `gt_final_only` | 不启动 VerifierAgent | 仅导出候选快照，无评测 | 无；导出后直接冻结 | 仅一次官方 GT FinalAudit |
| `gt_budget` | 不启动 VerifierAgent | 导出候选快照；Solver 申请且有额度时执行官方 GT | GT（最多 `official_gt_budget` 次） | 官方 GT FinalAudit（不占额度） |
| `dual_shadow` | 启动并冻结 proxy bundle | proxy + GT 各执行一次 | 仅 proxy | 官方 GT FinalAudit |

上述模式共用 SolverAgent、artifact export、snapshot 和 FinalAudit 收尾；`proxy`、
`gt_primary`、`gt_budget` 继续使用 refine 状态机。GT 候选执行不能改变最终 `FinalAudit`
的 exactly-once 语义；`gt_primary`/`gt_budget` 也不能因为候选阶段通过就跳过最终审计。

**候选导出与冻结的分离（2026-09-10 修复）。** Solver 在 FMJob 容器内工作，声明的产物
（如 `/app/submission/`）只存在于容器导出快照 `artifacts/fmjob-agent/round_N/`；宿主机上的
Solver worktree 只有 `instruction.md`。此前 `gt_final_only` 完全跳过 `SurrogateVerify`，
导致 `last_valid_candidate_artifact_ref` 为空，`FreezeWorkspace` 冻结的是空 worktree，
`FinalAudit` 报告 `findings.json missing`（v53 ankle-mri-findings 即因此无效）。现在所有
模式都经过 `SurrogateVerify` 的导出步骤；不评测的模式返回 `status=exported`，Graph 据此
直接冻结，FinalAudit 始终优先消费容器导出的候选快照。

GT verifier image 与 VerifierAgent image 是两个独立配置。CLI 使用
`--gt-verifier-image` 指定 task-specific 官方 verifier image；正式实验应固定 image
digest。GT 不可用、执行超时或 verifier 进程错误分别记录为 `gt_unavailable` 或
`verifier_error`，不得静默回退到 proxy。

候选 GT 结果保存于 Controller 私有的 `controller/candidate_gt_round_N/`，写入 Agent view
前只保留 `verifier`、`status`、`valid`、`reward` 和非敏感错误摘要。官方测试源码、hidden
test、ground truth、容器路径和完整 stderr 均不暴露给 Agent。`dual_shadow` 的 GT 结果只
用于离线比较，不参与候选 refine 决策。
