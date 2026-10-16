---
description: 启动 FM 深度演化
agent: famou-evolution
---

进入 FM 演化模式，对当前已交付方案进行多轮自动优化 $ARGUMENTS 轮。

**预算（budget）契约**： `$ARGUMENTS` 如果是整数，这个整数**就是本次演化的 budget，必须原样传给 init_evolution 的 budget 参数**。没有数字时使用工具默认值 5。

## 你已有的信息

你能看到完整的对话历史，包括：
- 用户的原始需求和澄清过程
- 生成的 PLAN.md（含目标、约束、数据说明）
- famou-build 的执行产出（代码、结果文件、可视化等）

当前工作目录下的文件也都可以直接读取（data/、PLAN.md、产出文件等）。

## 初始化

每次启动演化都按下面的步骤走，**不要跳步骤**。即便工作空间下已存在历史 `.evolution/run_*/`，本次也按全新一轮处理——`init_evolution` 工具会自动给新 run 编号（不覆盖旧的）。**跳过 `init_evolution` 会让自动评估、归档、续轮机制全部失效**——你产出的解不会被打分、不会归档到 candidates/vNNN/，下一轮也不会自动启动。

1. 基于对话历史和当前目录中的文件，理解问题全貌：用户需求、数据结构、约束条件、已有方案的质量

2. 编写两个文件：

   **objective.md** — 提炼问题描述，evo-builder 每轮全新上下文靠此理解问题：
   - 用户需求、数据结构、约束条件、优化目标（从 PLAN.md 和对话历史中提取）
   - **逐条列出**所有约束，每条标注对应的数据字段名。遍历数据中的每个限制性字段，确保不遗漏
   - solution 是什么形式的代码文件（如 `*.py`）
   - 代码的输入输出约定（读什么数据、输出什么结果）
   - 数据文件的位置和格式说明
   - **产物契约**（必写）：solution 跑完时必须把完整决策变量序列化到 sibling `<stem>.result.json`（JSON 格式），schema 要能让 evaluator 仅凭 result.json 重新校验所有硬约束 + 重算目标值（不能只存 summary）。明确列出 result.json 的字段定义

   **evaluator.py** — 评估器，接受代码文件作为输入，按需执行代码并评分：
   - 调用方式：`python evaluator.py <code_file_path>`
   - 职责：根据 sibling `<stem>.result.json` 决定是否执行代码 → 校验产出 → 评分
   - 输出文件：在代码文件同目录写 `<stem>.score.json`（如 `solve_v2.py` → `solve_v2.score.json`）
   - 输出格式：JSON，至少含 `{"score": <float>}`，可包含其他诊断字段
   - exit code：0 = 评估成功（包括 solution 失败但 evaluator 正常打分的情况，分数写在 score.json 里），非 0 = evaluator 自身出错
   - 数据路径：用相对于 evaluator.py 所在目录的路径(运行时在 `{evolution_dir}/.harness/` 下)
   - 独立运行：不依赖对话上下文，只依赖传入的代码文件和同目录下的数据
   - **顶部 module docstring 必须包含"约束验证表"**（与设计原则 2 对齐，作为 evaluator 实现的契约），示例如下：

     ```
     | 约束名 | 数据来源 | 验证方式 | result.json 涉及字段 |
     |---|---|---|---|
     | 容量上界 | data/problem.json[machines.capacity] | 独立计算 | schedule[].load |
     | 换模换色 | data/problem.json[mold.change_time] | 独立 lookup + 重算 | schedule[].machine, .mold |
     ```

     "验证方式" 只能填三种之一：
     - **独立计算**：从 data 重算，不读 solver 自报值
     - **部分独立**：从 data 取 reference 对比 solver 自报值，差异超阈值违规
     - **信任 solver**：直接读 solver 自报值；仅限"solver 内置数值求解器输出"等数值精度场景，**必须给物理依据**

   **产物 + 缓存契约**（关键，solution 和 evaluator 都要遵守）：

   - **solution 必须**在执行结束时把**完整决策变量**序列化到 sibling `<stem>.result.json`（JSON 格式）。
     - "完整"= 足以重新校验所有硬约束 + 重新计算目标值，不能只存 summary。
     - 例：`sol_v5.py` 跑完写 `sol_v5.result.json`。
     - stdout 仅作为人类可读的进度日志，**不作为评估输入**。

   - **evaluator 必须**在入口实现产物缓存（result.json 命中就跳过执行）。入口逻辑（伪代码）：

     ```python
     # code_path 是命令行传入的代码文件
     result_path = code_path 同目录下 <stem>.result.json
     score_path  = code_path 同目录下 <stem>.score.json

     # 产物缓存：result.json 比 code 新就跳过执行
     if result_path 存在 and mtime(result_path) >= mtime(code_path):
         result = load(result_path)
     else:
         subprocess 跑 code（设超时，cwd=code 同目录）
         如果 solver 失败 或 result_path 不存在:
             score_path 写 {"score": None, "validity": 0, "error": "..."}
             exit 0
         result = load(result_path)

     # 下面是你的评估逻辑（见原则 1-6）
     output = 你的评估(result)   # 字典，至少含 score 和 validity 字段
     score_path 写 output（JSON）
     ```

     **核心契约**：cache 用 mtime 比较；cold path 必须捕获 solver 失败和 result 缺失，并写 `score.json`（含 `validity=0`）；评估输出必含 `score` 和 `validity` 字段。怎么实现自由发挥。

   **evaluator 设计原则**：
   1. **validity/quality 分离**：先检查所有硬约束（容量、覆盖、物理限制等），任一违反 → validity=0。只有 validity=1 时才计算 quality score。不要用 penalty 混在一起——违规方案和合法方案必须能清晰区分
   2. **物理一致性 → 与约束验证表对齐**：表格中标"独立计算"或"部分独立"的约束，evaluator 必须从 data 重算，不能从 result.json 读 solver 自报值。"信任 solver" 标记的约束必须有物理依据注释
   3. **评分依赖独立**：评分公式里的常数（权重、惩罚、基准）和监督信号（ground truth、参考分布）必须 hardcode 或从 data 独立计算，禁止从 result.json 读或由 pred 派生。每项标注来源（instruction X 段 / data/xxx[k]）
   4. **边界条件完整**：损耗、容差、极端 case 都要处理。**容差必须有明确来源**——要么是数值精度（浮点累积、求解器精度），要么是用户给定显式声明的业务容差，不能凭自己的直觉给。所有未声明的容差都是 optimizer 的 exploit 入口
   5. **诊断信息丰富**：score.json 含分项指标（validity、violation_count、各维度子分数等），方便 evo-builder 理解分数构成并针对性优化
   6. **评分透明**：evaluator.py 注释清楚评分公式和各项权重，让 evo-builder 读 evaluator 源码就能理解"什么最影响分数"
   7. **产物自洽**：result.json schema 足够丰富，不需回头跑 solver / 不需看 stdout 就能判 validity 和算 quality

3. **验证 evaluator 的正确性**（这一步很关键，评估器是整个演化的信任锚点）：
   - **逐条对照约束验证表**（evaluator.py 顶部 docstring）和 PLAN.md / 数据字段，确认表中无遗漏（漏列的约束等价于漏验）
   - **对每条已列入的硬约束**，构造"仅违反该约束"的反例方案，evaluator 必须 reject (validity=0)
   - **对每条标"信任 solver"的约束额外审视**：物理依据是否站得住、能否被 solver 误报伪装合规——若可能被 solver 撒谎绕过，必须改回"独立计算"
   - 写一个合法方案跑 evaluator，确认能正常输出 score.json，sibling `<stem>.result.json` 已被 solution 写出
   - 验证 score 是否合理：手动估算预期分数，和 evaluator 输出对比
   - 测试边界 case：空方案（应该 validity=0）
   - **缓存生效验证**：对同一份合法方案连跑两次 evaluator，第二次应明显更快（< 1s 量级，不再起 subprocess）。如果不够快，检查 result.json 是否被 solution 写出、mtime 比较是否走对分支
   - 如果发现问题，修复 evaluator 再重新验证

4. 调用 `init_evolution` 工具初始化演化环境：
   - 传入 evaluator 和 objective 的路径、budget、solution_pattern、direction
   - 工具自动创建 `.evolution/run_NNN/` 目录，复制文件，激活演化循环
   - 返回 JSON 含 `evolution_dir` 路径

5. 写 `{evolution_dir}/status.md` 的初始 Diagnosis

6. 然后按照你的每轮流程执行第一轮（派 evo-builder → 诊断 → 报告）
