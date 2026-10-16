# NatureBench Judge Invalid 案例、原因与解决措施

本文汇总当前已经观察到的 NatureBench Validity Judge Invalid 案例，记录候选的数值结果、
判定原因、结果处置和合规重做方向，并定义 IdeaAgent、ImplementAgent 共同遵守的新合规边界。

表中的 `g` 是数值 evaluator 返回的 `aggregate_improvement`：`g < 0` 为未 Match，
`0 <= g <= 0.1` 为数值 Match，`g > 0.1` 为数值 Surpass。Invalid 候选的 `g` 只用于审计，
不能作为可信成绩或正式 SOTA 结果。

## 一、范围和当前结论

当前案例分为三类：

1. 正式结果复核后排除：原本数值 Match/Surpass，但重判发现明确违规行为；
2. 新实验候选未采纳：数值有提升，但 Judge Invalid，因此不覆盖旧正式结果；
3. 判定边界：不同 Judge 调用存在分歧，需要按更严格边界重做或人工复核。

2026-08-19 的 GPT-5.5 全量重判在 38 个原 Match/Surpass case 中得到 32 Valid、6 Invalid。
其中 5 个在第二次 GPT-5.5 判定中仍为 Invalid；`s42256-024-00815-9` 为 2 次 Invalid、
1 次 Valid，按「判定分歧取 Valid」的约定采用 Valid 结论。另有此前 Claude Judge Invalid
和后续实验 Invalid 案例，统一列在下表。

2026-08-20 的全量补判把有正式 Run 的 88 个 case 统一到 GPT-5.5 口径，得到 73 Valid、
15 Invalid。随后 2026-08-20 提交的 `invalid-v3` 批次对这 15 个 case 做合规重做，
2026-08-21 补判结果为 11 个转 Valid、2 个仍 Invalid、2 个重跑未完成，当前 Judge Invalid
降至 4 个。下表中已由合规重做转为 Valid 的案例，其「当前处置」列已相应更新，但
「Invalid 原因」和「合规重做措施」保留作为边界定义的依据，不因个案转正而删除。

## 二、Invalid 案例与逐项解决措施

| Case | 数值结果 | Judge 结论 | Invalid 原因 | 当前处置 | 合规重做措施 |
|---|---:|---|---|---|---|
| `s41592-023-01940-w` | `g=+0.599386`，数值 Surpass | GPT-5.5 重复判 Invalid | 直接加载两个历史 certified-anchor 预测 CSV，根据历史 MAE、评分公式和归一化 cliff 手工限制 test-row delta；SCORE_ATTEMPT 没有拟合最终预测器 | 不采纳该 Surpass；保留旧正式结果 | 删除 anchor CSV 和 cliff/L1 手工门控；从训练矩阵训练可复现的稀疏/流式模型，只用训练/验证划分做校准；evaluator 分数只能选择或触发重训模型 |
| `s41592-023-02148-8` | `g=+0.255722`，数值 Surpass | GPT-5.5 2/2 Invalid | 直接调用提供的 Rfam CM，并用固定 consensus/mutation fallback 生成输出，没有从 family FASTA 拟合关键预测行为 | invalid-v3 合规重做后 GPT-5.5 Valid，`g=+0.279872` 已计入正式结果 | 在提供的 family FASTA 上拟合或校准序列模型、CM 参数或判别头；固定 fallback 只能处理工程异常，不能承担主要预测 |
| `s41592-025-02926-6` | `g=+0.337544`，数值 Surpass | GPT-5.5 2/2 Invalid | 从另一 slice/panel 文件逐字复制目标 panel，属于跨 split/instance 目标提取 | invalid-v3 合规重做后 GPT-5.5 Valid，但分数回落至 `g=-0.716138`（未 Match），已计入正式结果 | 使用训练数据构造 masked-panel/paired-panel 验证，训练跨 panel 表达预测或生成模型；禁止从其他可用文件复制目标矩阵 |
| `s42256-022-00518-z` | `g=+0.261313`，数值 Surpass | GPT-5.5 2/2 Invalid | 使用人工调节的 marker 阈值和固定 `CD8_MAP` 覆盖部分 query 标签 | invalid-v3 合规重做后 GPT-5.5 Valid，`g=+0.201018` 已计入正式结果 | 用训练集学习 marker 权重、分类边界和 label mapping；marker 可作为特征或先验，但不能用手工阈值直接覆盖测试预测 |
| `s42256-022-00556-7` | `g=+0.161643`，数值 Surpass | GPT-5.5 2/2 Invalid | 对 `bit_stream_xor` 硬编码 closed-form XOR parity 规则，未从提供数据学习 | invalid-v3 重做仍 Judge Invalid（改为融合 `frozen/` 下的预计算 `.npy` 产物），继续排除 | 使用训练样本学习关系结构或执行可审计的程序归纳/模型选择；最终规则必须由训练数据优化并在公开验证划分上选择，不能预写任务答案公式 |
| `s42256-023-00636-2` | `g=+0.020453`，数值 Match | GPT-5.5 2/2 Invalid | 主要输出由手工化学模板、固定规则和 isotope-label 技巧构造，真实训练模型只作为 fallback | invalid-v3 重做仍 Judge Invalid（tanimoto 输出由随机等价 SMILES 填充），继续排除 | 训练分子生成器/打分器并由其生成候选；化学有效性规则仅作约束和过滤，禁止用 isotope label 或模板编码方式迎合评分器 |
| `s42256-024-00815-9` | `g=+0.023436`，数值 Match | GPT-5.5 为 2 Invalid/1 Valid，边界不稳定 | 从 validation target 建 linker/template 检索索引，并把检索到的目标 linker 直接复制到候选 | 按「判定分歧取 Valid」采用，`g=+0.023436` 已计入正式结果 | 只能基于输入特征检索；使用训练数据拟合 linker 生成器或 learned ranker，检索结果不能直接作为 target，validation target 不能成为答案库 |
| `s43588-024-00757-7` | `g=-0.301818`，未 Match | Claude Judge Invalid | 根据多轮 evaluator 分数反解固定预测模式 `[1,0,1,1,0,1,1,1]`，对 1033 个测试样本输出同一模式；没有使用分子特征和训练标签生成主预测 | invalid-v3 合规重做后 GPT-5.5 Valid，`g=-0.299699`（未 Match），已计入正式结果 | 从分子图、光谱或结构特征和训练标签拟合 per-sample 模型；禁止通过历史分数反解固定输出向量 |
| `s41592-024-02372-w` | `g=+0.369267`，数值 Surpass | Claude Judge Invalid | 从测试文件名解析 PWM ID，再用该 ID 查找训练文件中的目标 PWM，115/130 样本接近直接恢复答案 | 不采纳新 Surpass；保留旧正式 `g=-3.072213` | 只使用蛋白质序列、DNA 序列和结构特征训练位置敏感 PWM 预测模型；提交前检查是否从文件名、目录名或测试元数据提取目标标识 |
| `s41592-025-02854-5` | `g=-0.265813`，相对旧值提升 | GPT-5.5 Invalid；Claude 曾判 Valid，存在分歧 | 从公开 pseudobulk BigWig 和 eQTL summary statistics 通过求和/查询直接重建题目要求的输出，而非训练预测器 | invalid-v3 合规重做后 GPT-5.5 Valid，`g=-0.583355`（未 Match），已覆盖旧正式结果 | 训练调控序列/细胞状态/variant-effect 模型；外部公开数据只有在题面允许且作为输入特征时才能使用，不能查询与 target 一一对应的 beta、轨迹或汇总结果 |

对应运行证据：

- [`s41592-023-01940-w`](../../../.famou/naturebench-runs/rerun-v3-claude-opus-01940-w-20260820/)
- [`s41592-023-02148-8`](../../../.famou/naturebench-runs/code-refresh-s41592-023-02148-8-20260810-1955/)（Invalid 证据）、[合规重做 Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s41592-023-02148-8-20260820/)
- [`s41592-025-02926-6`](../../../.famou/naturebench-runs/rerun-final-v15-claude-deepseek-s02926-20260817/)（Invalid 证据）、[合规重做 Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s41592-025-02926-6-20260820/)
- [`s42256-022-00518-z`](../../../.famou/naturebench-runs/rerun-v2c-claude-deepseek-00518-20260818/)（Invalid 证据）、[合规重做 Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s42256-022-00518-z-20260820/)
- [`s42256-022-00556-7`](../../../.famou/naturebench-runs/nb-rerun-v5-s42256-022-00556-7-glm52-20260807-202616/)（Invalid 证据）、[重做后仍 Invalid](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s42256-022-00556-7-20260820/)
- [`s42256-023-00636-2`](../../../.famou/naturebench-runs/code-refresh-s42256-023-00636-2-20260810-1955/)（Invalid 证据）、[重做后仍 Invalid](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s42256-023-00636-2-20260820/)
- [`s42256-024-00815-9`](../../../.famou/naturebench-runs/20260811-search-v2-s42256-024-00815-9/)
- [`s43588-024-00757-7`](../../../.famou/naturebench-runs/configfix-s43588-024-00757-7-20260810-2120/)（Invalid 证据）、[合规重做 Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s43588-024-00757-7-20260820/)
- [`s41592-024-02372-w`](../../../.famou/naturebench-runs/rerun-v2b-claude-deepseek-02372-20260817/)
- [`s41592-025-02854-5`](../../../.famou/naturebench-runs/rerun-v2g-claude-deepseek-02854-5-20260819/)（Invalid 证据）、[合规重做 Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s41592-025-02854-5-20260820/)

## 三、判定分歧案例

### `s43588-025-00920-8`

- 数值结果：`g=+0.013787`，数值 Match；
- 首次 GPT-5.5：Invalid，认为历史预测和测试集 R2/RMSE 反馈被用于优化 blend；
- GPT-5.5 retry：Valid，确认 `aho_main` 在 train/validation 上真实拟合了 OOF target
  encoding 和 LightGBM，其他输出是已拟合模型的补充融合；
- 当前结论：不能把“模型融合”整体列为违规。只要基础预测由真实训练路径产生，evaluator
  反馈只用于选择或调参，而不是直接计算测试答案，融合可以是合规的；
- 采用结论：2026-08-21 按「判定分歧取 Valid」的约定采用该 Run，正式 `g` 由
  `-0.186163` 更新为 `+0.013787`，新增一个 Match。

运行证据：
[`s43588-025-00920-8`](../../../.famou/naturebench-runs/rerun-v3-claude-opus-00920-8-20260820/)。

### 分歧案例的处理原则

对同一候选出现 Valid/Invalid 分歧时，采用多次独立 Judge 投票：

1. 使用同一个 Judge 模型、同一套 Judge policy、同一个 SCORE_ATTEMPT、同一份候选代码和
   等价的证据上下文，避免把输入变化误当成模型随机性；
2. 至少取得 3 次有效 verdict，只统计明确的 `is_valid=true` 或 `is_valid=false`；
3. 网络错误、HTTP 502、无 API key、超时、输出不可解析和 `is_valid=null` 都是基础设施错误，
   不计入票数，需要补跑到 3 次有效票。

取得 3 次有效票后直接按简单多数决定最终结果，例如 `Valid 2 / Invalid 1`。系统仍保存每次
verdict、模型、输入策略和 evidence manifest，不覆盖历史判定。

## 四、新合规边界

采用最小覆盖原则：不增加泛化的行为限制，只加入下面三条能够直接对应已发生 Invalid case
的边界。IdeaAgent 和 ImplementAgent 使用完全相同的三条规则，不增加额外 schema、证明材料
或强制流程。

| 新增边界 | 对应 Invalid case |
|---|---|
| **1. 不直接复制或恢复题目要求的 target。** 不从文件名/ID、其他 split 或 instance、validation target、公开 target table、pseudobulk/eQTL 轨迹或 retrieved template 直接取得答案。 | 文件名 PWM lookup：`s41592-024-02372-w`；跨 panel 复制：`s41592-025-02926-6`；公开 target 重建：`s41592-025-02854-5`；linker target retrieval：`s42256-024-00815-9`。 |
| **2. 不用 evaluator 反馈反解或直接构造测试输出。** 不根据分数反推固定 test pattern、逐行 delta、评分公式或 normalization cliff。 | certified-anchor + cliff delta：`s41592-023-01940-w`；分数反解固定预测模式：`s43588-024-00757-7`。 |
| **3. 不让未拟合的固定规则替代数据拟合路径。** 手写阈值、固定 map/vector、domain template、isotope trick 或 supplied fallback 不能成为主预测器或覆盖主预测。 | marker gate/CD8 map：`s42256-022-00518-z`；硬编码 XOR：`s42256-022-00556-7`；化学模板/isotope trick：`s42256-023-00636-2`；固定 Rfam fallback：`s41592-023-02148-8`。 |

以上三条之外不新增限制。完整 evaluator 反馈、历史有效模型或输出复用、预训练组件、把 retrieval
作为输入特征、模型融合、物理/化学/统计约束仍然允许，只要没有触发上述三类已证实问题。

V3 prompt 在三条规则后只放三个最小 few-shot 对照：文件名 PWM lookup、evaluator cliff 上的
anchor delta、marker threshold/固定 map 覆盖。每个示例同时给出违规操作和合规替代操作；其余
案例只在本文档中维护，避免 prompt 过长或让 Agent 把示例误当成穷尽列表。

## 五、我们已经完成的系统措施

1. **新增版本化 Prompt V3**：IdeaAgent 和 ImplementAgent 共享完全相同的三条、且逐条有案例
   依据的合规边界；仅在各自原有工作阶段自然提醒，不增加额外流程或证明材料。
2. **保留 V1/V2**：没有覆盖旧 prompt，允许实验按版本切换和复现。
3. **支持 V3 运行时选择**：CLI Agent 与 benchmark-managed worker 均支持 V3。
4. **Validity Verifier 可配置**：系统已有 new-best 晋升前的校验 Agent，默认关闭；开启后
   Invalid verdict、原因和证据会落盘并反馈给同一个 ImplementActor，促使其 refine，而不是
   把违规候选晋升为 best。
5. **Judge 错误与 Invalid 分离**：502、无 key、超时和不可解析响应保持 `is_valid=null`，
   不伪装成 Invalid。
6. **保留审计证据**：每次 Judge 的 verdict、SCORE_ATTEMPT、输入 manifest 和模型信息均
   单独保存，不覆盖历史判定。

Prompt 文件：

- `famou_scientist/loop/prompts/cli_agents/idea_agent_v3.md`
- `famou_scientist/loop/prompts/cli_agents/implement_agent_v3.md`
- `famou_scientist/loop/prompts/benchmark_managed/idea_agent_v3.md`
- `famou_scientist/loop/prompts/benchmark_managed/implement_agent_v3.md`

启用 V3：

```bash
IDEA_PROMPT_VERSION=v3
IMPLEMENT_PROMPT_VERSION=v3
```

对应容器内环境变量为 `FAMOU_IDEA_PROMPT_VERSION=v3` 和
`FAMOU_IMPLEMENT_PROMPT_VERSION=v3`。默认值仍为 V1，已有 V1/V2 运行不会被静默改变。

## 六、建议的后续执行顺序

1. 对所有 Judge Invalid case 使用 V3 prompt 重新设计并重跑，不直接修补原违规输出；
2. 重跑时开启 Validity Verifier，对每个 new best 在正式 Judge 前做一次约束解释和证据检查；
3. 对 `s42256-024-00815-9`、`s41592-025-02854-5` 等分歧案例优先做无 retrieval、无外部
   target source 的干净对照；
4. 对 evaluator 的归一化错误单独修 evaluator，不能让 Agent 通过控制预测误差停在 cliff
   上来规避问题；
5. 只有实例完整、数值有效且最终 Judge Valid 的结果才能更新正式结果文档和提交包。
