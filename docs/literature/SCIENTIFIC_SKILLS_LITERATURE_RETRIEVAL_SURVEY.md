# 科研 Skills 文献检索调研

调研日期：2026-07-14

本文整理 11 个 GitHub 科研类 skills / skill 套件对“第一步文献检索”的设计。重点不是评价写作能力，而是抽取可复用的检索启动、候选筛选、引用验证和用户确认机制。

## 总体结论

这 10 个项目并不都是“文献检索 skill”。可以分成三类：

| 类型 | 项目 | 对文献检索的关系 |
|---|---|---|
| 检索/综述主流程 | `academic-research-skills-codex`, `literature-survey-skill`, `claude-scientific-writer`, `claude-scholar`, `latex-paper-skills` | 明确定义从研究主题 / 研究问题到检索、筛选、验证、综述的流程 |
| 写作前研究阶段 | `PaperSpine`, `Nature-Paper-Skills` | 文献检索服务于写作、贡献定位和引用支持库，不是独立搜索工具 |
| 写作/引用质量控制 | `Research-Paper-Writing-Skills`, `citation-check-skill`, `nature-skills` | 主要做写作、引用校验或 Nature 风格；检索只作为前置依赖或验证手段 |

对我们最重要的启发：

1. 先做意图路由，不要所有请求都进入完整科研流程。
2. 模糊研究方向应先收敛成研究问题，而不是直接搜大量论文。
3. 检索应是并行召回 + 验证，而不是单一工具返回候选。
4. 候选必须有相关性理由、来源、验证状态，不合格候选不应进入“备选论文集合”。
5. 扩展论文集合要有用户确认，特别是新增论文、扩大范围、进入深度综述之前。
6. 检索结果需要可追溯：检索词、数据库、日期、结果数、筛选理由、排除理由。

## 逐项整理

### 1. academic-research-skills-codex

仓库：[Imbad0202/academic-research-skills-codex](https://github.com/Imbad0202/academic-research-skills-codex)

定位：Codex 版本的 Academic Research Skills 套件，包含深度研究、学术论文、论文审稿、研究流水线等工作流。

相关文件：

- `skills/academic-research-suite/SKILL.md`
- `skills/academic-research-suite/ars/deep-research/WORKFLOW.md`

文献检索相关设计：

- 先做工作流路由：只有深度研究、文献综述、系统综述、元分析、事实核查、研究问题细化等任务才进入 `deep-research`。
- 明确提出“论文主题范围收敛”的覆盖规则：用户只有宽泛主题、暂定标题、研究兴趣，且没有可回答的研究问题时，进入 `deep-research` 的 Socratic mode。
- Socratic mode 只问收敛问题，不直接产出大纲、草稿、文献综述或完整流程看板。
- 调查阶段才做系统性文献检索 + 来源验证。
- 对论断、引用、参考文献、统计数字、期刊政策等要求一手来源 / 权威来源验证。
- 文献和引用存在性检查优先 DOI / 官方元数据查询，再使用权威网页搜索；Semantic Scholar、OpenAlex、Crossref 是程序化验证选项。

可借鉴点：

- 强制区分“研究问题尚未明确”和“开始检索/综述”。
- 当用户只是“想了解/想做某方向”时，agent 应先问 3-5 个收敛问题，而不是自动搜索和整理。
- 检索阶段必须有来源验证，而不是只返回搜索命中。

### 2. Research-Paper-Writing-Skills

仓库：[Master-cai/Research-Paper-Writing-Skills](https://github.com/Master-cai/Research-Paper-Writing-Skills)

定位：ML/CV/NLP 论文写作与修改 skill，主要关注摘要、引言、相关工作、方法、实验、结论等章节的写作质量。

相关文件：

- `research-paper-writing/SKILL.md`

文献检索相关设计：

- 不是检索 skill。
- 默认已有论文主线、实验结果、主要证据。
- 工作流强调“论断-证据对齐”：摘要 / 引言中的主要论断必须能被实验或证据支持。
- 相关工作是写作章节之一，但不定义从零搜索策略。

可借鉴点：

- 检索不应脱离后续论断支撑。每篇候选论文应该标注它支持什么论断、对比点或背景信息。
- 如果用户只是让改写论文，不应自动扩展文献检索，除非明确出现引用缺口。

### 3. PaperSpine

仓库：[WUBING2023/PaperSpine](https://github.com/WUBING2023/PaperSpine)

定位：贡献优先、面向审稿人的论文写作系统。不是单纯润色，而是先学习目标场景、优秀样例和参考资料，再确认贡献点 / 研究动机。

相关文件：

- `src/skill/SKILL.md`
- `src/skill/references/research.md`
- `src/skill/references/citation.md`

文献检索相关设计：

- 第 1 阶段输入整理：先读取或生成 `paper_spine_config.json`。
- `reference_mode` 支持 `local_first`、`specified_paths`、`web`。
- 第 2 阶段研究：必须先索引本地参考资料 / 指定参考资料，再做网页收集。
- 研究阶段要求输出：
  - `reference_materials/source_index.md`
  - `research_dossier.md`
  - `exemplar_learning_dossier.md`
  - `style_profile.md`
  - `sota_gap_map.md`
  - `motivation_options_after_research.md`
- 第 3 阶段引用支持库：构建论断级别的引用支持库，候选数量至少 `citation_target_count * 3`，默认 60，约 80% 为近期论文。
- 第 4 阶段研究动机确认是阻塞状态：必须等用户确认研究动机，不能自动选择。

可借鉴点：

- 本地优先：用户给了论文、PDF、目录时，必须先用用户材料，不应上来就网页搜索。
- 检索产物应该结构化，区分来源索引、SOTA 缺口、引用支持。
- 关键动机/方向必须用户确认，不允许 agent 自动推进。

### 4. literature-survey-skill

仓库：[SNL-UCSB/literature-survey-skill](https://github.com/SNL-UCSB/literature-survey-skill)

定位：从一堆论文到领域理解的文献综述 skill，强调“明确意图 -> 初筛 -> 深入阅读 -> 综合归纳”。

相关文件：

- `SKILL.md`

文献检索相关设计：

- 先建立综述意图：用户为什么做这个综述、范围、时间预算、角色类型。
- 初筛阶段先快速读论文集合，构建领域图景。
- 深入阶段按 Keshav three-pass 等方法进行深读。
- 综合阶段产出“领域已知内容 / 尚不清楚的问题 / 下一步值得推进的方向”。
- 新候选论文出现时，不直接加入，而是在 transition points 批量提出：
  - Paper
  - 发现来源
  - 加入理由
  - 与综述意图的相关性
  - 建议阅读轮次
  - 时间成本
- 用户可选择加入 / 收藏 / 跳过；跳过也要记录理由。
- 如果论文集合超出预算，提示用户调整范围或更严格筛选。

可借鉴点：

- 候选扩展要经过用户确认。
- 每个新增候选必须说明发现来源、加入理由、相关性和阅读成本。
- 对“读论文 session”尤其适合：用户只说读某篇论文时，不应该自动扩展成多论文深度对比。

### 5. citation-check-skill

仓库：[serenakeyitan/citation-check-skill](https://github.com/serenakeyitan/citation-check-skill)

定位：引用和事实验证关口，用网页搜索或仅文档模式验证论断、引用、图表和表格。

相关文件：

- `SKILL.md`

文献检索相关设计：

- 不是发现式文献检索，而是引用 / 论断验证。
- 两遍式结构：
  - 第 1 遍：抽取论断。
  - 第 2 遍：按 `claim_id` 顺序验证，不能重新抽取。
- 搜索验证模式：搜索权威来源。
- 仅文档模式：只允许使用用户提供文档，任何外部知识都要标记。
- 学术引用强制多检索词，不允许搜到一个结果就停：
  - 第一作者 + 年份 + 标题开头词
  - 完整论文标题 + site:semanticscholar.org / site:arxiv.org
  - 第一作者 + 年份 + 发表场所
  - DOI
  - arXiv ID
- 来源权威性层级：一手来源 > 政府/机构来源 > 同行评议出版物 > 行业报告 > 可信新闻 > 二手汇编。
- 只有二手来源时，状态应是未验证。

可借鉴点：

- 我们的论文检索需要“多检索词验证模板”，特别适合解决 InterAgent-1.5 这类标题模糊/拼写近似问题。
- 搜到不相关结果时，不能列为候选；应标记为“没有精确匹配 / 低置信度”。
- 候选应该有已验证 / 未验证 / 不匹配 / 需要用户确认等状态。

### 6. nature-skills

仓库：[Yuan1z0825/nature-skills](https://github.com/Yuan1z0825/nature-skills)

定位：Nature 论文学术表达和科研绘图相关 skills。

相关文件：

- 根 README / skill 套件内容

文献检索相关设计：

- 不是文献检索主流程。
- 更偏 Nature 风格表达、图表、写作规范。

可借鉴点：

- 对第一步检索帮助有限。
- 可在后续论文润色 / Nature 风格写作阶段参考，不应纳入检索路由核心。

### 7. Nature-Paper-Skills

仓库：[Boom5426/Nature-Paper-Skills](https://github.com/Boom5426/Nature-Paper-Skills)

定位：Nature 风格论文起草、修改、审计、重投的 skill 套件。

相关文件：

- `skills/research/academic-researcher/SKILL.md`
- `skills/core/citation-verifier/SKILL.md`

文献检索相关设计：

- `academic-researcher` 支持文献综述、论文总结、方法比较、研究缺口识别。
- 主要提供论文分析框架和文献综述结构。
- `citation-verifier` 明确说明：不用于从零开始的通用文献发现。
- 引用验证器的流程：
  - 本地引用扫描
  - 删除 / 标记占位引用
  - 检查 BibTeX key / DOI / arXiv / PMID
  - 验证论文是否存在于可信来源
  - 如果论断依赖某个结果，确认被引用论文是否真的支持该论断
- 可信验证来源：出版社页面 / DOI 解析器、PubMed、arXiv、Crossref / Semantic Scholar，Google Scholar 只作为兜底发现工具。

可借鉴点：

- 区分文献发现和引用验证。
- 本地引用扫描应先于在线验证。
- 对从用户文档中抽出来的引用，不能盲目信任 BibTeX / Scholar 元数据。

### 8. latex-paper-skills

仓库：[yunshenwuchuxun/latex-paper-skills](https://github.com/yunshenwuchuxun/latex-paper-skills)

定位：LaTeX 论文写作、综述论文、实证论文和从零写论文的工作流。

相关文件：

- `.codex/skills/paper-from-zero/SKILL.md`
- `.codex/skills/arxiv-paper-writer/SKILL.md`
- `.codex/skills/arxiv-paper-writer/references/research-workflow.md`

文献检索相关设计：

- `paper-from-zero` 是前门：主题 -> 创新表述 -> 证据计划 -> 下游写作器。
- 第 2 步：主动搜索文献，构建紧凑的文献图谱。
- 第 3 步：产出 3-5 个候选创新点 / 贡献表述。
- 弱表述要尽早淘汰：没有清晰缺口、证据路径或可证伪论断的直接淘汰。
- `arxiv-paper-writer` 第 0 关口：
  - 确认约束。
  - 把主题翻译成检索关键词。
  - 轻量发现轮次：10-20 篇关键论文。
  - 产出研究快照 + 大纲 + 澄清问题 + 草稿计划。
- 文献补充关口：
  - 收集 50-80 个候选条目。
  - 每个相关工作小节至少 5 篇被引用论文。
  - 每条主要研究脉络至少 1 篇奠基性 / 经典论文。
  - 用 `arxiv_registry.py`、`source_ranker.py`、`citation_policy.py` 验证和过滤。
  - `ref.bib` 至少有 30 个已验证条目后才能开始写。
- 研究工作流强调：
  - 不过度收集，不偏题。
  - 先找近期综述和高引用锚点论文。
  - arXiv 候选用 registry cache 避免重复。
  - 拒绝不相关、无法验证、重复、低质量候选。
  - 验证协议：精确标题 + 第一作者 + 年份，打开来源页面确认标题/作者/年份/发表场所后才能加入。

可借鉴点：

- 适合我们的综述论文检索：轻量发现 -> 文献补充关口 -> 已验证数量门槛。
- 不能边搜边写；先产出研究快照 / 计划 / 澄清问题。
- 对候选加入 `ref.bib` 或长期库之前必须验证。

### 9. claude-scientific-writer

仓库：[K-Dense-AI/claude-scientific-writer](https://github.com/K-Dense-AI/claude-scientific-writer)

定位：通用科学写作套件，其中 `literature-review` 是完整的系统性文献综述 skill。

相关文件：

- `skills/literature-review/SKILL.md`

文献检索相关设计：

- 第 1 阶段规划与范围界定：
  - 定义研究问题
  - 确定范围
  - 制定检索策略
  - 识别 2-4 个主要概念
  - 列出同义词 / 缩写 / 相关术语
  - 规划布尔检索表达式
  - 至少选择 3 个互补数据库
  - 设置纳入 / 排除标准
- 第 2 阶段系统性文献检索：
  - 生物医学：PubMed / PMC / bioRxiv / medRxiv
  - 通用科学：arXiv、Semantic Scholar、Google Scholar
  - 根据领域选择专门数据库
  - 记录检索参数：检索日期、时间范围、检索式、数据库
  - 导出并聚合结果
- 第 3 阶段筛选与选择：
  - 优先按 DOI 去重，标题作为兜底
  - 标题筛选
  - 摘要筛选
  - 全文筛选
  - PRISMA 流程图
- 第 4 阶段数据抽取与质量评估：
  - 元数据、研究设计、方法、结果、局限、资助/利益冲突
  - 质量评级
- 第 6 阶段引用验证：
  - 通过 CrossRef 做 DOI 验证
  - 修复并反复运行，直到通过
- 最佳实践：
  - 至少 3 个数据库
  - 包含预印本服务器
  - 记录所有过程
  - 测试并优化检索式
  - 可用时按引用量排序
  - 标题 -> 摘要 -> 全文的系统性筛选

可借鉴点：

- 系统综述类任务应该有严格检索方案，而不是普通网页搜索。
- 检索本身要生成可复现实验记录。
- 对不同领域要切换数据库组合。

### 10. claude-scholar

仓库：[Galaxy-Dawn/claude-scholar](https://github.com/Galaxy-Dawn/claude-scholar)

定位：半自动科研助手，覆盖想法生成、文献、论文笔记、知识库、实验、写作、发表。

相关文件：

- `README.md`
- `skills/research-ideation/SKILL.md`
- `skills/research-ideation/references/literature-search-strategies.md`

文献检索相关设计：

- 研究构思支持从模糊主题到研究合约：
  - 研究问题
  - 假设
  - 证据需求
  - 证伪标准
  - 方法选择
  - 下一步动作
- 文献综述：
  - 构建有效检索关键词
  - 通过 WebSearch 跨学术数据库检索
  - 筛选并评估论文质量
  - 识别趋势和缺口
  - 生成带证据标签的文献综述
- Zotero 集成：
  - WebSearch 发现相关论文
  - 抽取 DOI / arXiv ID / 落地页 URL
  - `zotero_add_items_by_identifier`：在退回网页来源前，先按标识符导入论文/预印本
  - 创建按主题组织的文献集合
  - 通过 PDF 级联策略附加开放访问 PDF
  - `zotero_get_item_fulltext` 用于全文阅读
  - `zotero_search_items` / `zotero_get_collection_items` 避免重复
- 默认近期范围：最近 3 年，可配置。
- 文献集合组织：
  - 核心论文
  - 方法
  - 应用
  - 基线
  - 待读
- DOI / arXiv 处理：
  - arXiv 可表示为 `10.48550/arXiv.{id}`
  - 只有 DOI / arXiv / 引用元数据失败后，才退回网页来源

可借鉴点：

- 长期科研工作流需要和文献库/知识库对接，而不是每个会话临时搜。
- 检索结果应有去重和文献集合组织。
- “用户知道但 agent 没搜到”的问题，可以通过已有文献库搜索 + 网页搜索 + DOI/arXiv 抽取缓解。

### 11. spark-to-paper-skills

仓库：[Albus-White/spark-to-paper-skills](https://github.com/Albus-White/spark-to-paper-skills)

定位：从一个灵感直接生成整篇论文的 Claude Code skill 套件。它不是单点检索技能，而是“检索 + 写作 + 作图 + 审稿 + LaTeX 编译”的全链路流程。

相关文件：

- `skills/ts-paper/SKILL.md`
- `skills/ts-paper-plan/SKILL.md`
- `skills/ts-paper-cite/SKILL.md`
- `skills/ts-paper-write/SKILL.md`
- `skills/ts-paper-review/SKILL.md`
- `skills/ts-paper-figure/SKILL.md`

文献检索相关设计：

- `ts-paper-cite` 明确要求先做广泛检索，再做筛选，不是找到几篇就停。
- 每篇候选论文必须读摘要后再决定保留与否。
- 所有引用必须真实存在，并通过 DOI / Crossref / arXiv 等方式验证。
- `claims_map.json` 把“哪篇论文支持哪条论断”做成可审计结构。
- 它强调 coverage，而不是只追求最小可用结果。

可借鉴点：

- 对我们的调研特别有价值的是它的“检索 -> 归类 -> 证据映射 -> 继续补缺”思路。
- 它非常强调引用真实性和论断绑定，适合参考我们后续的文献汇总层设计。
- 它更像“论文生成工作流”，不是单独的第一步检索 skill。

### 补充候选

下面这些仓库也值得继续看，但我先只做简表登记，不展开成完整章节：

| 仓库 | 类型 | 主要特点 |
|---|---|---|
| `lingzhi227/agent-research-skills` | 科研综述 skill | 系统性文献综述，偏 deep-research |
| `WenyuChiou/ai-research-skills` | 研究工作流目录 | 覆盖文献综述、研究设计、写作、跨 agent 协作 |
| `keemanxp/slr-prisma` | 系统综述 skill | 按 PRISMA 2020 做系统综述 |
| `saidsurucu/literature-review-skills` | 多源检索 skill | 21 个来源并行检索，偏广覆盖 |
| `bchao1/paper-finder` | 论文查找 skill | 偏具体论文检索 |
| `917Dhj/DeepPaperNote` | 单篇精读 skill | 深读单篇论文并生成笔记 |
| `ShZhao27208/Aut_Sci_Write` | 论文写作套件 | 文献检索、下载、PDF 提取、写作、Zotero 同步 |
| `zLanqing/codex-claude-academic-skills` | 学术技能套件 | 阅读、写作、科学计算一体化 |

## 可复用的第一步检索框架

结合以上项目，建议我们的第一步文献检索抽象成 4 层：

### 第 0 层：意图与范围收敛

输入先分类：

| 用户意图 | 应进入的模式 |
|---|---|
| 指定论文名 / arXiv / DOI / URL | 具体论文查找 |
| 模糊论文名 / 记不清标题 | 模糊论文查找 + 用户确认 |
| 宽泛研究方向 | Socratic 式范围收敛 |
| 要系统综述 / 综述 / 相关工作 | 文献检索方案 |
| 给了一堆论文让读 | 论文集合初筛 / 阅读 |
| 要写论文或改稿 | 写作支持，只有引用缺口时检索 |

原则：没有明确研究问题或用户未要求综述时，不自动进入大规模检索。

### 第 1 层：并行召回

候选来源应并行，而不是只依赖一个工具：

- 原生 WebSearch / WebFetch
- 学术搜索工具
- arXiv 精确 / 模糊检索
- Semantic Scholar / OpenAlex / Crossref
- 本地文献库 / 已验证历史库
- 用户提供材料

对具体论文查找，至少尝试：

- 精确标题检索
- 去掉标点 / 版本后缀后的标题检索
- 第一作者 + 年份 + 标题片段
- 如果有 arXiv ID / DOI，直接使用
- 网页搜索时不要强行追加 `arxiv paper`

### 第 2 层：候选验证

每个候选进入列表前必须有结构化判断：

```text
title: 标题
authors: 作者
year: 年份
venue/source: 发表场所/来源
url: 链接
matched_by: 匹配方式
match_confidence: 匹配置信度
relevance_reason: 相关性理由
mismatch_reason: 不匹配理由
verification_status: 验证状态
```

不相关候选不能作为“备选论文”列给用户，只能放在已拒绝 / 不匹配里。

最低规则：

- 标题 / 作者 / 年份至少两个维度匹配。
- 如果检索词是具体标题，候选只匹配数字、版本号、泛词，必须拒绝。
- 如果置信度不是高置信，应该问用户确认，而不是继续阅读或整理。

### 第 3 层：用户确认 / 证据关口

以下情况需要停下来问用户：

- 找到多个相近候选。
- 只有中 / 低置信度。
- 要扩大论文集合。
- 要从读单篇论文升级到多篇比较。
- 要从检索升级到综述/写作/研究计划。

候选扩展时应给出：

| 论文 | 来源 | 理由 | 相关性 | 建议阅读轮次 | 时间成本 |
|---|---|---|---|---|---|

用户选择加入 / 收藏 / 跳过。

## 对当前问题的直接启发

之前出现的问题可以对应到这些规则：

- Agent 读论文时自作主张做多论文对比：应由意图与范围收敛阻止，读单篇就是读单篇，扩展必须问。
- InterAgent-1.5 检索不到：应使用并行召回，不能只走学术工具；并用标题/作者/年份验证拒绝 LongCat 等明显不相关结果。
- 搜回来很多但不相关：候选验证需要把不匹配候选过滤掉。
- 用户知道的相关论文没被搜到：需要引用链扩展、多数据库、本地文献库 / 已验证历史库和检索词优化。
- prompt 里写工具描述太重：检索策略应在 skill / tool schema / 管理平台中版本化，AGENTS.md 只保留高层路由原则。

## 推荐后续落地

建议新增或改造一个 `literature-search` skill 版本，而不是直接改 AGENTS：

1. 定义意图矩阵。
2. 定义具体 / 模糊论文查找流程。
3. 定义候选结构和拒绝规则。
4. 定义并行召回的工具使用策略。
5. 定义用户确认关口。
6. 将这些策略和 tool schema 解耦，放入管理平台版本库。

## 来源

- [Imbad0202/academic-research-skills-codex](https://github.com/Imbad0202/academic-research-skills-codex)
- [Master-cai/Research-Paper-Writing-Skills](https://github.com/Master-cai/Research-Paper-Writing-Skills)
- [WUBING2023/PaperSpine](https://github.com/WUBING2023/PaperSpine)
- [SNL-UCSB/literature-survey-skill](https://github.com/SNL-UCSB/literature-survey-skill)
- [serenakeyitan/citation-check-skill](https://github.com/serenakeyitan/citation-check-skill)
- [Yuan1z0825/nature-skills](https://github.com/Yuan1z0825/nature-skills)
- [Boom5426/Nature-Paper-Skills](https://github.com/Boom5426/Nature-Paper-Skills)
- [yunshenwuchuxun/latex-paper-skills](https://github.com/yunshenwuchuxun/latex-paper-skills)
- [K-Dense-AI/claude-scientific-writer](https://github.com/K-Dense-AI/claude-scientific-writer)
- [Galaxy-Dawn/claude-scholar](https://github.com/Galaxy-Dawn/claude-scholar)
