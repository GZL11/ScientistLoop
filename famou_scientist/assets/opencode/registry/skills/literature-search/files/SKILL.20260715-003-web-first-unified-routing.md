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

### Intent Matrix
0. Classify the user's request before searching:
   - **Specific Paper Lookup**: the user names one paper, acronym, versioned title, DOI, arXiv ID, or URL.
   - **Fuzzy Paper Lookup**: the user gives an approximate title or may have misspelled the paper name.
   - **Topic Literature Search**: the user asks for related work, a direction, a benchmark landscape, or several relevant papers.
   - **Systematic Review**: the user asks for a systematic review, PRISMA-like survey, meta-analysis, or reproducible search protocol.
   - **Corpus Reading**: the user provides papers/PDFs/URLs and asks to read them; do not expand the corpus without confirmation.

### Paper Lookup and Fuzzy Lookup
1. For **Specific Paper Lookup** or **Fuzzy Paper Lookup**, use the native web tools first:
   - First run native websearch with the user's original phrase. Preserve the original wording; do not rewrite it into a broad topic.
   - If unclear, run at most two focused variants such as `"<query>" arxiv`, `"<query>" paper`, or punctuation-normalized variants. Do not add broad topic words unless the user gave them.
   - When websearch finds arXiv, OpenReview, ACL Anthology, PMLR, DOI, publisher, official project page, or GitHub evidence for the paper, use webfetch to verify title, authors, abstract, and identifier.
   - Use `arc_search_literature` only as metadata enrichment or academic-source cross-check after the web-first attempt, passing `user_query` when available.
   - Do not use disabled custom paper-lookup exports.
   - Only show candidates whose title/core terms match the user's query, or whose page clearly explains a likely spelling/acronym variant. Never list candidates that match only versions, years, numbers, or generic words.
   - If the likely match is a spelling or naming variant, state the uncertainty and ask for confirmation before deep reading unless the evidence is clearly decisive.
   - If no high-confidence paper is found after the short lookup, ask the user for an arXiv ID, DOI, author, institution, or topic clue instead of expanding into a broad literature review.

### Topic Search and Systematic Search
2. For **Topic Literature Search**, use `arc_search_literature` for multi-source academic retrieval, split broad topics into sub-directions, and screen by relevance and quality.
3. For **Systematic Review**, define the search protocol first: research question, scope, databases, Boolean queries, date range, inclusion/exclusion criteria, deduplication, and screening plan.
4. For **Corpus Reading**, read and triage the provided corpus first. New candidate papers require user confirmation before being added.

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
