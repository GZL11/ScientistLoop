# Search-v2 搜索策略设计与运行结果

本文记录 Famou Scientist 在 NatureBench 中使用的 Search-v2 策略：ImplementAgent
在已有方案和 IdeaSpark 新 Idea 之间进行动态选择，并在必要时融合两者。本文同时记录
2026-08-11 Search-v2 批次的实际决策证据和结果，便于复盘策略是否真正生效。

本文的结果来源包括：

- [Search-v2 运行目录](../../../.famou/naturebench-runs/)，每个 Run 保存完整 Agent、候选、评测和日志产物；
- 各 Run 下 `actors/implement_actor_*/search_decisions.jsonl`，记录 ImplementAgent 的结构化选择；
- 各 Run 下 `expbank/*/record.json`，记录 attempt 级父子关系、动作和评测结果；
- [Search-v2 配对结果](RERUN_COMPARISON_20260811.csv)，记录 Search-v2 与前一批结果的官方分数对比；
- [Search-v2 汇总证据](SEARCH_V2_EVIDENCE_20260812.json)，记录批次级统计。

## 1. 为什么需要 Search Policy

自主算法创新不是单纯地不断生成新 Idea，也不是在一个方案上无限调参。一个有效的
ImplementAgent 需要根据最近一次评测、过往实验和剩余时间判断搜索方向：

1. 当前方法仍有明确的、低风险的改进空间时，继续 `refine`；
2. 当前方法的核心假设已经被证伪，或者新 Idea 有更高的上限时，切换到新 Idea；
3. 当前方法的主体已经被验证，而新 Idea 只解决一个明确的瓶颈时，将两者 `fuse`。

Search Policy 是独立的策略模块，不负责写代码、不负责执行实验、不负责评测，也不
负责替代 ImplementAgent 做科研判断。它只负责把当前方案与一个候选新 Idea 配对、
提供决策上下文、校验决策并完成队列状态变更。

## 2. 三种动作

### 2.1 `refine`：继续当前方案

`refine` 表示保留当前 Idea 的方法主线，在现有代码和证据上继续进行以下一种或多种
工作：

- 修复工程错误、数据格式错误或评测失败；
- 修改算法中的一个机制或参数化方式；
- 做消融实验或受控变体；
- 根据子任务分数和诊断，针对最主要的失败模式改进。

如果本回合已经把一个新 Idea 放入 Improve 上下文，选择 `refine` 时不会消费该 Idea，
而是把它重新放到 IdeaSpark 队尾，等待后续 ImplementAgent 使用。这对应“放回去重放”，
不等于删除 Idea。

### 2.2 `switch`：使用新 Idea

`switch` 表示当前方法的关键瓶颈已经比较明确，继续修补的预期收益低于新 Idea，因而
消费当前提供的 Idea，并以它作为下一次实现的主线。当前方案不再作为本回合的主要
方法，但它的代码、评测、失败诊断和 ExpBank 记录仍然保留。

`switch` 是代码中的动作名，本文将它解释为“使用新 Idea”，而不是终止整个研究 Loop。

### 2.3 `fuse`：融合当前方案与新 Idea

`fuse` 表示当前方案已经包含可复用的有效基础，而新 Idea 提供了能够对应当前瓶颈的
独立机制。ImplementAgent 应保留当前方案中已经验证的部分，同时实现新 Idea 中可验证
的机制；不能把两个方案的全部组件无条件堆叠。

一个合格的 fusion 应在提交记录中说明：

- 当前方案中保留了什么，以及对应哪次评测证据；
- 新 Idea 解决哪个具体瓶颈；
- 两者为何机制上互补；
- 哪些组件被明确舍弃，以及舍弃原因；
- 如何通过消融或分阶段实验判断收益来自哪一部分。

## 3. 一轮 Improve 的流程

```text
有效评测结果 / 工程反馈
          |
          v
  读取当前 best、ExpBank 和 IdeaSpark
          |
          v
  提供当前方案 + 一个候选新 Idea
          |
          v
       ImplementAgent
          |
          v
  输出结构化 search_decision
      /          |          \\
 refine       switch       fuse
    /             |            \\
 当前方案       消费新 Idea       保留当前方案
  继续改进      作为主线实现       并融合新 Idea
      \\          |            /
       提交候选 -> Evaluator -> ExpBank
```

评测仍由统一 Controller / Evaluator Provider 调用；Search Policy 不会让 Agent 直接访问
官方 evaluator，也不会把隐藏测试集暴露给 Agent。

## 4. 队列和状态语义

### 4.1 新 Idea 的租约

Improve 回合只从 IdeaSpark 中选取处于 `queued` 状态、且不是 continuation 的新 Idea。
策略为候选 Idea 创建短期 lease 后，才把它放入 ImplementAgent 的上下文。这样可以
避免两个并发 ImplementAgent 同时消费同一个 Idea。

### 4.2 决策结算

Controller 收到 Agent 的结构化决策后执行确定性结算：

| 决策 | 候选 Idea lease | 当前方案 | 结果 |
|---|---|---|---|
| `refine` | 回放到队尾 | 保留 | 当前方案继续迭代 |
| `switch` | 消费并完成 lease | 切换 | 新 Idea 成为实现主线 |
| `fuse` | 消费并完成 lease | 保留 | 记录双 Idea lineage |

非法动作、缺少候选 Idea、租约归属不匹配等情况会安全回退或忽略结算，不能误消费
Idea。每次决策和结算都保留原始输入、动作、Idea ID、队列项 ID、Actor ID、时间和
证据引用。

### 4.3 失败与 continuation

工程失败、评测失败和有效分数不是同一种状态。工程错误应通过 feedback mailbox 返回
给原 ImplementActor 进行修复；如果 Actor 已释放并发槽，则将其 parked，待资源允许
时 resume。修复回合与普通 Improve 回合使用同一套证据记录，但不能把修复错误误认为
算法 Idea 被证伪。

## 5. Agent 决策协议

ImplementAgent 每次提交或收到评测反馈后，按当前 prompt 读取：

- 当前任务 instruction 和可用资源信封；
- `expbank_dir` 下的 `INDEX.md`、相关 `SUMMARY.md`、代码和失败证据；
- 当前 best 分数、公开 evaluator 返回的总分和分项指标；
- 当前方案的父 attempt、剩余研究时间和剩余提交机会；
- IdeaSpark 提供的新 Idea 及其预期收益、资源需求和验证计划。

然后输出 `search_decision`，至少包含：

```json
{
  "action": "refine | switch | fuse",
  "reason": "基于评测和历史证据的选择理由",
  "current_idea_id": "当前 Idea ID",
  "offered_idea_id": "本回合提供的新 Idea ID",
  "lineage_idea_ids": ["实际采用的 Idea ID"],
  "expected_return": "对 Match-SOTA / Surpass-SOTA 的预期",
  "resource_impact": "CPU、GPU、显存、内存和运行时间影响",
  "validation_plan": "本回合如何验证假设"
}
```

`expected_return` 是决策依据和事后校准数据，不是官方分数。正式结果只能使用
NatureBench evaluator 的公开返回和最终 validity judge。

## 6. 统计口径

本批次有 15 个 Search-v2 Run：

- 13 个 Run 真正进入 Task 并产生结构化 Search 决策；
- `s41592-025-02926-6` 和 `s42256-023-00628-2` 没有进入 Task 入口，因此没有决策
  日志，也不纳入动作比例或配对效果统计；
- 13 个已启动 case 共记录 83 次动作：`refine` 29 次、`switch` 36 次、`fuse` 18 次。

动作次数回答“Agent 在搜索过程中如何选择”。它不是 83 个独立任务，也不能直接等同
于 83 个最终候选；同一方案可能经历多次 refine，且一个 fuse 后还可能继续 refine。

最终结果按 NatureBench 官方 Run 口径：每个独立 Run 取最佳有效 canonical 结果，
不把多个 Run 平均。Search-v2 与前一批可配对的 13 个 case 中：

| 统计项 | 结果 |
|---|---:|
| 分数提升 | 9 / 13（69.23%） |
| 分数回退 | 4 / 13 |
| 增量中位数 | +0.036091 |
| 中位数绝对增量 | 0.040877 |
| 旧版本 Match-SOTA | 0 / 13 |
| Search-v2 Match-SOTA | 4 / 13 |
| Search-v2 Surpass-SOTA | 0 / 13 |
| 单侧符号检验 p 值 | 0.1334 |

均值增量为 `+0.563430`，但受到 `s41592-025-02886-x` 的极端增量影响。当前结论应
表述为“有方向性收益和明显的个案收益，但具有任务依赖性”，不能宣称 Search-v2 已经
普遍有效或达到统计显著。

## 7. 逐 Case 决策记录

下表的动作序列来自对应 Run 的 `search_decisions.jsonl`，顺序按 `recorded_at` 排列。
`switch` 表示使用新 Idea，`fuse` 表示融合，`refine` 表示继续当前方案。

| Case | 动作序列 | refine | switch | fuse | 官方 Run 结果 |
|---|---|---:|---:|---:|---|
| `s41467-025-64512-w` | fuse -> switch -> fuse -> fuse -> refine -> refine -> refine | 3 | 1 | 3 | 回退，below Match，delta -0.000290 |
| `s41467-025-65557-7` | refine -> fuse -> refine -> fuse -> refine -> refine -> switch | 4 | 1 | 2 | 提升，Match，delta +0.040877 |
| `s41587-024-02428-4` | refine -> switch -> switch -> refine -> fuse -> switch -> switch -> refine | 3 | 4 | 1 | 回退，below Match，delta -0.086120 |
| `s41592-023-02035-2` | switch -> switch -> switch -> switch -> fuse -> switch -> fuse | 0 | 5 | 2 | 提升，below Match，delta +0.044174 |
| `s41592-024-02316-4` | fuse -> switch -> switch -> switch -> switch -> switch -> fuse -> switch -> switch -> switch -> switch -> switch -> refine -> switch -> refine -> switch -> fuse -> switch | 2 | 13 | 3 | 提升，Match，delta +0.040034 |
| `s41592-025-02886-x` | refine | 1 | 0 | 0 | 提升，below Match，delta +6.633859 |
| `s41592-025-02926-6` | 无 | 0 | 0 | 0 | 未启动，不可配对 |
| `s41592-025-02983-x` | refine -> fuse -> fuse | 1 | 0 | 2 | 提升，Match，delta +0.036091 |
| `s42256-022-00534-z` | switch -> refine -> refine -> refine -> refine -> switch -> refine -> switch -> switch | 5 | 4 | 0 | 提升，below Match，delta +0.023946 |
| `s42256-023-00628-2` | 无 | 0 | 0 | 0 | 未启动，不可配对 |
| `s42256-024-00795-w` | fuse -> switch -> switch -> switch | 0 | 3 | 1 | 回退，below Match，delta -0.037459 |
| `s42256-024-00815-9` | refine -> switch | 1 | 1 | 0 | 提升，Match，delta +0.514990 |
| `s42256-025-01003-z` | refine -> fuse | 1 | 0 | 1 | 提升，below Match，delta +0.215335 |
| `s43588-024-00698-1` | refine -> switch -> fuse -> switch -> switch -> refine | 2 | 3 | 1 | 提升，below Match，delta +0.020847 |
| `s43588-024-00716-2` | fuse -> refine -> refine -> refine -> refine -> fuse -> refine -> refine -> switch | 6 | 1 | 2 | 回退，below Match，delta -0.121687 |

## 8. 细粒度案例分析

### 8.1 `s41467-025-65557-7`：融合后继续 refine，最终达到 Match

这个 case 的决策序列是：

```text
refine -> fuse -> refine -> fuse -> refine -> refine -> switch
```

Agent 早期判断当前方法已有可复用基础，因此两次选择 `fuse`，并在理由中保留经过
验证的基线组件，只引入能对应具体子任务瓶颈的机制；中间的 `refine` 用于修正和收敛。
最终官方 Run 分数从 `-0.017470` 提升到 `0.023407`，增量 `+0.040877`，达到
Match-SOTA。这个 case 说明 fusion 并不意味着一次性结束，融合后仍然可以回到 refine。

### 8.2 `s41592-024-02316-4`：大量 switch，最终由融合候选贡献有效提升

这个 case 共 18 次决策，其中 `switch=13`、`fuse=3`、`refine=2`。这说明该任务中
IdeaSpark 新 Idea 的消费非常积极，当前方案被多次判定为上限不足或瓶颈明确。Agent
理由中出现了针对具体 instance、模态分解、聚类和空间标签传播的方案比较，而不是只做
统一超参搜索。

可解析的最佳 attempt 记录为 `0050`，动作是 `fuse`，attempt 分数为 `0.028785`；
这与“只看最后一次动作”不同，最后一次动作是 `switch`。官方 Run 仍以 canonical
最佳结果为准，配对结果从 `-0.011249` 提升到 `0.028785`，达到 Match-SOTA。这个
case 是“搜索过程动作很多，但最终最好候选不一定来自最后动作”的典型例子。

### 8.3 `s42256-024-00815-9`：先 refine，再 switch，两个方向都被尝试

动作序列为：

```text
refine -> switch
```

Agent 先判断当前 retrieval 方案已达到 Match-SOTA，选择低风险 refine；随后对比新 Idea
中的 LSTM/大规模检索方向，发现其资源和训练风险较高，又在另一个回合切换到有更直接
证据支持的方案。最终分数从 `-0.491554` 提升到 `0.023436`，达到 Match-SOTA，
是本批次最清晰的“先保守改进、再消费新 Idea”案例之一。

### 8.4 `s41587-024-02428-4`：资源/可行性约束导致新 Idea 被拒绝

该 case 的序列为：

```text
refine -> switch -> switch -> refine -> fuse -> switch -> switch -> refine
```

Agent 的决策理由中明确提到，候选 Idea 依赖下载 ESM-2，而运行环境网络不可用；在
该条件下，候选 Idea 无法按原计划验证，继续切换会引入不可控工程风险，因此回到
`refine`。这体现了 Search Policy 不应只看预期分数，还必须检查资源、依赖和剩余时间。

最终官方分数从 `-0.065649` 回退到 `-0.151769`。这不是“没有尝试新 Idea”，而是说明
多次切换和融合在这个任务上没有转化为更好的最终候选，后续需要进一步分析候选质量、
资源可行性和任务特定的验证策略。

### 8.5 `s41592-025-02886-x`：只有一次 refine，但取得大幅个案收益

该 case 只有一次结构化决策 `refine`。Agent 根据子任务中的假阴性问题判断，复杂的
watershed 和 tracking 方案在剩余时间内风险较高，因此选择围绕当前方案做受控修正。
官方配对分数从 `-67.354972` 提升到 `-60.721113`，增量 `+6.633859`，但仍低于
Match-SOTA。

该增量对批次均值有很大影响，因此汇总统计同时报告中位数；不能因为这个个案提升很大
就认为 Search-v2 的普遍收益同样很大。

## 9. 结果归因和当前结论

### 9.1 能够确认的结论

- `refine`、`switch`、`fuse` 三种动作已经在真实 Search-v2 Run 中被执行；
- ImplementAgent 会读取当前 best、ExpBank 和候选新 Idea，再做动作选择；
- `fuse` 的 lineage 同时包含当前 Idea 和 offered Idea，说明不是仅在文本中提到融合；
- `refine` 不消费 offered Idea，而是把它放回 IdeaSpark 队尾；
- Search-v2 在 13 个可配对 case 中有 9 个提升，并新增 4 个 Match-SOTA case。

### 9.2 不能直接推出的结论

- 不能把所有提升归因于某一个动作；同一 Run 包含多个动作，且动作和候选之间不是
  一一对应的独立对照实验；
- 不能仅凭“最后一次动作”判断最佳方案来源；
- 不能把单次 Run 结果解释成某个 Idea 的统计因果效果；
- 不能称 Search-v2 在所有 NatureBench 任务上普遍有效，当前单侧符号检验
  `p=0.1334`，样本量也有限。

当前最稳妥的结论是：**Search-v2 已经实现了动态的 refine/new Idea/fusion 搜索，
并在当前样本上表现出有条件的方向性收益；下一步需要增加独立重复 Run、记录每次候选
的完整 lineage，并对三种动作做受控消融，才能比较它们各自的增益。**

## 10. 后续改进

1. 为每个 candidate 在结果表中增加 `search_action`、`current_idea_id`、
   `offered_idea_id`、`lineage_idea_ids` 和 `parent_attempt_id` 列。
2. 将“动作选择”和“最佳结果归因”在 Controller 侧分别持久化，避免依赖离线从
   Agent 日志推断。
3. 为 `refine`、`switch`、`fuse` 增加受控 ablation：固定初始 Idea、资源和预算，
   分别关闭新 Idea、关闭 refine 或关闭 fusion。
4. 对 Agent 的 `expected_return` 做事后校准，记录预期等级与实际 evaluator 分数，
   但不把预期收益当作官方指标。
5. 对网络依赖、资源声明和剩余时间做 dispatch 前硬校验；不可行的 Idea 应在进入
   Implement 前标记为不可执行并保留诊断。
