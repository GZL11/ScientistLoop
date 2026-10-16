---
name: literature-search
description: Systematic literature review methodology including search strategy, screening, and synthesis. Use when conducting literature reviews or writing background sections.
metadata:
  category: experiment
  trigger-keywords: "literature,review,systematic,PRISMA,search,database,PubMed,arXiv,citation"
  applicable-stages: "3,4,5,6"
  priority: "2"
  version: "1.0"
  author: researchclaw
  references: "adapted from K-Dense-AI/claude-scientific-skills"
---

## Literature Search Best Practice

### Paper Lookup vs Topic Search
0. If the user appears to ask for one specific paper by title, acronym, versioned name, DOI, or arXiv ID, do **Paper Lookup first**:
   - Call `arc_lookup_paper(query, limit=5)` with the user's original phrase.
   - Do not append `arxiv paper` or broaden into a topic query on the first attempt.
   - If `needs_confirmation=true`, show the top candidates and ask the user which one they meant before reading or summarizing a paper.
   - Only switch to topic search after the target paper is confirmed or the user says they want broader related work.

### Search Strategy Design
1. Define research question using PICO framework (Population, Intervention, Comparison, Outcome)
2. Identify 2-4 core concepts from the research question
3. List synonyms, abbreviations, and related terms for each concept
4. Combine terms with Boolean operators: AND (between concepts), OR (within synonyms)
5. Select at least 3 complementary databases relevant to the domain:
   - Biomedical: PubMed, Scopus, Web of Science
   - Computer science: arXiv, Semantic Scholar, DBLP, ACL Anthology
   - Interdisciplinary: Google Scholar, OpenAlex
6. Document exact search strings for reproducibility

> **按子方向分多次检索（搭配 `arc_search_literature`）**：把主题拆成几个细分方向，
> 每个方向**单独发一次检索**，而不是一个宽泛大词一次搜完。例如 SSVEP →
> 「刺激范式设计 / 分类·解码算法 / 跨被试·跨会话迁移 / 数据集·基准」分别检索。
> 这样既覆盖更全（每个方向召回各自的核心工作），web 端文献面板也会**按每次检索词
> 聚类成小领域**、类内按年份倒序展示，综述脉络一目了然。检索词用英文（召回更好）。

### Inclusion and Exclusion Criteria
1. Define date range (e.g., last 5-10 years for rapidly evolving fields)
2. Specify language restrictions (typically English)
3. Specify publication types (peer-reviewed, preprints, conference papers)
4. Define study design requirements (RCTs, observational, computational)
5. Set domain-specific filters (species, methodology, sample size)
6. Document all criteria BEFORE screening begins

### PRISMA Methodology
1. Record total hits from each database before deduplication
2. Remove duplicates and record count
3. Screen titles and abstracts against inclusion criteria (record excluded count)
4. Full-text review of remaining papers (record excluded with reasons)
5. Report final included studies with PRISMA flow diagram
6. For scoping reviews, use PRISMA-ScR extension

### Screening and Quality Assessment
1. Use two-pass screening: title/abstract first, then full text
2. Apply quality assessment tools appropriate to study type:
   - RCTs: Cochrane Risk of Bias tool
   - Observational: Newcastle-Ottawa Scale
   - ML papers: check reproducibility, dataset validity, statistical rigor
3. Extract data systematically using a predefined extraction form

### Synthesis Approaches
1. **Narrative synthesis**: Organize findings thematically, identify patterns and contradictions
2. **Meta-analysis**: Pool quantitative results when studies are sufficiently homogeneous
3. **Gap analysis**: Explicitly identify what is NOT covered in the literature
4. Summarize key findings per theme with supporting citation counts
5. Highlight conflicting results and possible explanations
6. End with clear statement of research gaps that motivate your study
